"""v3.26.0 (2026-06-15) — Agent 3B — ETAP 6 — Universe opportunity review tests.

  * Synthetic universe → distinct recommendation buckets.
  * NEVER auto-adds trade-eligible symbols.
  * NEVER auto-removes a symbol (advisory only).
  * NEVER imports alpaca_orders.
  * NEVER makes network calls.

Run:
    python3 -m unittest tests.test_universe_opportunity_review_v3260 -v
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "universe_opportunity_review.py"


def _load_module():
    name = "universe_opportunity_review_v3260"
    spec = importlib.util.spec_from_file_location(name, str(_SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


def _write_ledger_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as h:
        for r in rows:
            h.write(json.dumps(r) + "\n")


class TestRecommendationBuckets(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ledger = self.root / "opportunity_ledger"
        self.diag = self.root / "monitor_runtime_diag"
        self.near = self.root / "near_miss"
        self.snap = self.root / "backfill_snapshots"
        for d in (self.ledger, self.diag, self.near, self.snap):
            d.mkdir(parents=True, exist_ok=True)
        self.day = "2026-06-15"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ── 1. KEEP — ledger rows + candidates present ──────────────────────────
    def test_keep_when_symbol_has_active_rows(self) -> None:
        _write_ledger_jsonl(
            self.ledger / f"{self.day}.jsonl",
            [
                {"symbol": "SPY", "risk_decision": "ALLOW",
                 "paper_action": "shadow_filled"},
                {"symbol": "SPY", "risk_decision": "ALERT_ONLY",
                 "paper_action": "shadow_observed"},
            ],
        )
        rep = self.mod.build_report(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            days=7,
            universe=("SPY",),
            ledger_dir=self.ledger,
            diag_dir=self.diag,
            near_miss_dir=self.near,
            snapshot_dir=self.snap,
        )
        # SPY should land in KEEP.
        spy_row = next(r for r in rep["rows"] if r["symbol"] == "SPY")
        self.assertEqual(spy_row["recommendation"], "KEEP")
        self.assertFalse(spy_row["modifies_live_universe"])

    # ── 2. OBSERVE_ONLY_ADD — many near-misses, 0 candidates ────────────────
    def test_observe_only_add_when_near_misses_high_no_candidates(self) -> None:
        _write_ledger_jsonl(
            self.near / f"{self.day}.jsonl",
            [{"symbol": "QQQ", "strategy_id": "momentum-long"}] * 6,
        )
        rep = self.mod.build_report(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            days=7,
            universe=("QQQ",),
            ledger_dir=self.ledger,
            diag_dir=self.diag,
            near_miss_dir=self.near,
            snapshot_dir=self.snap,
        )
        qqq = next(r for r in rep["rows"] if r["symbol"] == "QQQ")
        self.assertEqual(qqq["recommendation"], "OBSERVE_ONLY_ADD")
        # Confirm: this is advisory only, doesn't modify live universe.
        self.assertFalse(qqq["modifies_live_universe"])
        self.assertFalse(rep["safety"]["modifies_live_universe"])

    # ── 3. NEEDS_DATA — data failure tokens ─────────────────────────────────
    def test_needs_data_when_data_failure_tokens_dominant(self) -> None:
        _write_ledger_jsonl(
            self.diag / f"{self.day}.jsonl",
            [
                {"monitor": "price-monitor",
                 "token": "MARKET_DATA_STALE",
                 "detail": {"symbol": "GLD"}}
                for _ in range(6)
            ],
        )
        rep = self.mod.build_report(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            days=7,
            universe=("GLD",),
            ledger_dir=self.ledger,
            diag_dir=self.diag,
            near_miss_dir=self.near,
            snapshot_dir=self.snap,
        )
        gld = next(r for r in rep["rows"] if r["symbol"] == "GLD")
        self.assertEqual(gld["recommendation"], "NEEDS_DATA")

    # ── 4. REMOVE_LOW_QUALITY — fully silent ────────────────────────────────
    def test_remove_low_quality_when_fully_silent(self) -> None:
        rep = self.mod.build_report(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            days=7,
            universe=("PANW",),
            ledger_dir=self.ledger,
            diag_dir=self.diag,
            near_miss_dir=self.near,
            snapshot_dir=self.snap,
        )
        panw = next(r for r in rep["rows"] if r["symbol"] == "PANW")
        self.assertEqual(panw["recommendation"], "REMOVE_LOW_QUALITY")
        # Even though we recommend REMOVE_LOW_QUALITY, safety contract
        # asserts no auto-removal.
        self.assertFalse(rep["safety"]["auto_removes_symbols"])

    # ── 5. NEVER auto-adds/removes; NEVER imports alpaca_orders ─────────────
    def test_safety_contract_never_auto_adds_or_removes(self) -> None:
        rep = self.mod.build_report(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            days=7,
            universe=("SPY", "GLD", "PANW"),
            ledger_dir=self.ledger,
            diag_dir=self.diag,
            near_miss_dir=self.near,
            snapshot_dir=self.snap,
        )
        self.assertFalse(rep["safety"]["auto_adds_trade_symbols"])
        self.assertFalse(rep["safety"]["auto_removes_symbols"])
        self.assertFalse(rep["safety"]["modifies_state_json"])
        # Source check.
        src = _SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("import alpaca_orders", src)
        self.assertNotIn("from alpaca_orders", src)
        self.assertNotIn("from shared.alpaca_orders", src)
        # Standing markers preserved.
        markers = rep["standing_markers"]
        self.assertIn("REVIEW_NEVER_AUTO_ADDS_TRADE_ELIGIBLE_SYMBOLS", markers)
        self.assertIn("REVIEW_NEVER_AUTO_REMOVES_SYMBOLS", markers)


class TestNoNetwork(unittest.TestCase):
    def test_no_socket_connect(self) -> None:
        mod = _load_module()

        def block(self, *a, **kw):
            raise AssertionError("Network call attempted")

        with mock.patch.object(socket.socket, "connect", block):
            rep = mod.build_report(
                as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
                days=7,
            )
        self.assertEqual(rep["version"], "v3.26.0")


if __name__ == "__main__":
    unittest.main()
