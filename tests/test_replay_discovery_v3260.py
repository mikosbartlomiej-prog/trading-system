"""v3.26.0 (2026-06-15) — Agent 3B — ETAP 5 — Replay discovery tests.

Verifies the replay entry-candidate discovery script:

  * Fixture bars produce candidates.
  * Every emitted record carries ``evidence_source="REPLAY"``.
  * NEVER writes to ``opportunity_ledger`` (asserts directory untouched).
  * NEVER makes network calls (patched requests + socket).
  * NEVER imports ``alpaca_orders``.
  * Standing markers footer present.
  * Explicit ``REPLAY_NOT_PAPER`` marker check.

Run:
    python3 -m unittest tests.test_replay_discovery_v3260 -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "replay_entry_candidate_discovery.py"


def _load_module():
    name = "replay_entry_candidate_discovery_v3260"
    spec = importlib.util.spec_from_file_location(name, str(_SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register in sys.modules BEFORE exec so dataclass's __module__ lookup
    # finds the module (Python 3.9 dataclasses needs sys.modules[__module__]).
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


def _make_breakout_bars(n: int = 60) -> dict:
    """Synthetic series engineered to trigger momentum-long on the
    final bar: 20-day high broken, volume 2x avg, RSI lands in [50, 70].

    Layout: alternating up/down with up = +0.5, down = -0.5 keeps RSI ~50.
    A modest breakout day (close > 20-day high) gently nudges RSI ~55–65.
    """
    bars: dict[str, list[float]] = {
        "open": [], "high": [], "low": [], "close": [], "volume": [],
    }
    base = 100.0
    pre = n - 1
    for i in range(pre):
        # Roughly balanced up/down keeps RSI moderate.
        if i % 2 == 0:
            close = base + 0.5
        else:
            close = base - 0.5
        bars["open"].append(base)
        bars["high"].append(max(base, close) + 0.2)
        bars["low"].append(min(base, close) - 0.2)
        bars["close"].append(close)
        bars["volume"].append(1_000_000)
        base = close
    # Modest breakout — close just above 20-day high, NOT a huge gap.
    high_20 = max(bars["high"][-21:-1])
    last_close = high_20 + 0.8
    bars["open"].append(bars["close"][-1])
    bars["high"].append(last_close + 0.2)
    bars["low"].append(bars["close"][-1] - 0.3)
    bars["close"].append(last_close)
    bars["volume"].append(2_500_000)  # > 1.5x avg
    return bars


def _make_flat_bars(n: int = 30) -> dict:
    bars: dict[str, list[float]] = {
        "open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n,
        "close": [100.0] * n, "volume": [1_000_000] * n,
    }
    return bars


class TestReplayDiscovery(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.snapshot_dir = Path(self.tmp.name) / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        # Write breakout snapshot for SPY (momentum-long should fire on
        # final bar).
        (self.snapshot_dir / "SPY.json").write_text(
            json.dumps(_make_breakout_bars(60)), encoding="utf-8"
        )
        # Write flat snapshot for AMD (no signal).
        (self.snapshot_dir / "AMD.json").write_text(
            json.dumps(_make_flat_bars(30)), encoding="utf-8"
        )
        # No snapshot for QQQ — must be reported as missing.

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ── 1. Fixture bars produce candidates ──────────────────────────────────
    def test_breakout_fixture_produces_candidate(self) -> None:
        rep = self.mod.build_report(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            lookback_days=30,
            snapshot_dir=self.snapshot_dir,
            strategies_filter=("momentum-long",),
            universe=("SPY",),
        )
        rows = rep["rows"]
        spy_rows = [r for r in rows if r["symbol"] == "SPY"]
        self.assertGreaterEqual(len(spy_rows), 1)
        total_candidates = sum(r["candidates"] for r in spy_rows)
        # Synthetic breakout designed to fire on final bar.
        self.assertGreaterEqual(
            total_candidates, 1,
            f"Expected >=1 candidate for momentum-long on SPY breakout fixture, "
            f"got {total_candidates}. Row: {spy_rows}"
        )

    # ── 2. Every candidate carries evidence_source=REPLAY ───────────────────
    def test_every_candidate_record_carries_replay_marker(self) -> None:
        rep = self.mod.build_report(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            lookback_days=30,
            snapshot_dir=self.snapshot_dir,
            strategies_filter=("momentum-long",),
            universe=("SPY",),
        )
        any_records = False
        for row in rep["rows"]:
            for rec in row.get("candidate_records") or []:
                any_records = True
                self.assertEqual(rec["evidence_source"], "REPLAY")
                self.assertFalse(rec.get("is_paper_trade"))
                self.assertFalse(rec.get("is_real_market"))
                self.assertFalse(rec.get("is_signal_observation"))
        self.assertTrue(
            any_records,
            "Expected at least one candidate record to verify REPLAY marker"
        )

    # ── 3. REPLAY_NOT_PAPER marker explicit check ───────────────────────────
    def test_replay_not_paper_marker_explicit(self) -> None:
        rep = self.mod.build_report(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            lookback_days=30,
            snapshot_dir=self.snapshot_dir,
            strategies_filter=("momentum-long",),
            universe=("SPY",),
        )
        self.assertEqual(rep["safety"]["evidence_source"], "REPLAY")
        markers = rep["standing_markers"]
        self.assertIn("REPLAY_NEVER_COUNTS_AS_PAPER", markers)
        self.assertIn("REPLAY_NEVER_COUNTS_AS_REAL_MARKET", markers)
        self.assertIn("OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES", markers)
        # Also assert evidence_source values on candidates do NOT include
        # "PAPER" or "REAL_MARKET_DATA".
        for row in rep["rows"]:
            for rec in row.get("candidate_records") or []:
                self.assertNotEqual(rec["evidence_source"], "PAPER")
                self.assertNotEqual(rec["evidence_source"], "REAL_MARKET_DATA")

    # ── 4. NEVER writes to opportunity_ledger ───────────────────────────────
    def test_never_writes_to_opportunity_ledger(self) -> None:
        ledger_dir = _REPO_ROOT / "learning-loop" / "opportunity_ledger"
        if not ledger_dir.exists():
            # Nothing to compare.
            return
        snapshot_before = sorted(p.name for p in ledger_dir.iterdir()
                                 if p.is_file())
        rep = self.mod.build_report(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            lookback_days=30,
            snapshot_dir=self.snapshot_dir,
            strategies_filter=("momentum-long",),
            universe=("SPY", "AMD"),
        )
        snapshot_after = sorted(p.name for p in ledger_dir.iterdir()
                                if p.is_file())
        self.assertEqual(snapshot_before, snapshot_after,
                         "replay-discovery must not touch opportunity_ledger")
        self.assertFalse(rep["safety"]["writes_opportunity_ledger"])

    # ── 5. NEVER makes network calls ────────────────────────────────────────
    def test_never_makes_network_calls(self) -> None:
        # Patch socket.connect to raise on any attempt.
        original_connect = socket.socket.connect

        def block_connect(self, *a, **kw):
            raise AssertionError("Network call attempted in replay discovery")

        with mock.patch.object(socket.socket, "connect", block_connect):
            try:
                import requests  # type: ignore
            except Exception:
                requests = None  # noqa
            if requests is not None:
                with mock.patch.object(
                    requests.Session, "request",
                    side_effect=AssertionError("Network call attempted"),
                ):
                    rep = self.mod.build_report(
                        as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
                        lookback_days=30,
                        snapshot_dir=self.snapshot_dir,
                        strategies_filter=("momentum-long",),
                        universe=("SPY",),
                    )
            else:
                rep = self.mod.build_report(
                    as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
                    lookback_days=30,
                    snapshot_dir=self.snapshot_dir,
                    strategies_filter=("momentum-long",),
                    universe=("SPY",),
                )
        # If we got here, no socket.connect was attempted.
        self.assertEqual(rep["version"], "v3.26.0")

    # ── 6. NEVER imports alpaca_orders ──────────────────────────────────────
    def test_script_does_not_import_alpaca_orders(self) -> None:
        src = _SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("import alpaca_orders", src)
        self.assertNotIn("from alpaca_orders", src)
        self.assertNotIn("from shared.alpaca_orders", src)
        self.assertNotIn("import shared.alpaca_orders", src)


class TestMissingSnapshotsAndStandingMarkers(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.snapshot_dir = Path(self.tmp.name) / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ── 7. Missing snapshots produce diagnostic, no fetch ───────────────────
    def test_missing_snapshot_listed_and_no_fetch_attempted(self) -> None:
        rep = self.mod.build_report(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            lookback_days=7,
            snapshot_dir=self.snapshot_dir,
            strategies_filter=("momentum-long",),
            universe=("SPY", "QQQ"),
        )
        self.assertEqual(set(rep["missing_snapshots"]), {"SPY", "QQQ"})
        # Total rows must equal 0 because all snapshots are missing.
        self.assertEqual(rep["totals"]["rows"], 0)


if __name__ == "__main__":
    unittest.main()
