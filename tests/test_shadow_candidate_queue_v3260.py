"""v3.26.0 (2026-06-15) — Agent 3B — ETAP 7 — Shadow candidate queue tests.

  * Synthetic discovery + near-miss → queue rows.
  * mode=SHADOW_ONLY enforced on every row.
  * status=WAITING_FOR_REAL_MARKET_TRIGGER enforced on every row.
  * NEVER imports alpaca_orders.
  * Quarantine variant rows (when present) integrated correctly.

Run:
    python3 -m unittest tests.test_shadow_candidate_queue_v3260 -v
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "build_shadow_candidate_queue.py"


def _load_module():
    import sys
    name = "build_shadow_candidate_queue_v3260"
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


class TestShadowCandidateQueue(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Build a synthetic replay-discovery file.
        self.replay = self.root / "replay_discovery_latest.json"
        self.near = self.root / "near_miss_status_latest.json"
        self.qdir = self.root / "quarantine_variants"
        self.qdir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_replay(self, rows: list[dict]) -> None:
        self.replay.write_text(
            json.dumps({"rows": rows, "totals": {"rows": len(rows)}}),
            encoding="utf-8",
        )

    def _seed_near_miss(self, flagged: list[dict],
                         pairs: list[dict] | None = None) -> None:
        self.near.write_text(
            json.dumps({"flagged": flagged, "pairs": pairs or []}),
            encoding="utf-8",
        )

    # ── 1. Replay rows with candidates produce queue rows ──────────────────
    def test_replay_rows_produce_queue_entries(self) -> None:
        self._seed_replay([
            {"strategy": "momentum-long", "symbol": "SPY",
             "asset_class": "us_equity",
             "candidates": 2, "near_misses": 0},
        ])
        self._seed_near_miss([])
        rep = self.mod.build_queue(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            replay_input=self.replay,
            near_miss_input=self.near,
            quarantine_dir=self.qdir,
            min_near_miss=3,
            min_candidates=1,
        )
        rows = rep["rows"]
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["strategy"], "momentum-long")
        self.assertEqual(r["symbol"], "SPY")
        self.assertEqual(r["source"], "replay_discovery")

    # ── 2. mode=SHADOW_ONLY enforced on every row ─────────────────────────
    def test_every_row_mode_shadow_only(self) -> None:
        self._seed_replay([
            {"strategy": "crypto-momentum", "symbol": "BTC/USD",
             "candidates": 1, "near_misses": 4},
            {"strategy": "momentum-long", "symbol": "QQQ",
             "candidates": 0, "near_misses": 5},
        ])
        self._seed_near_miss([
            {"strategy_id": "overbought-short", "symbol": "AMD",
             "sample_size": 6, "advisory_reason": "needs review"},
        ])
        rep = self.mod.build_queue(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            replay_input=self.replay,
            near_miss_input=self.near,
            quarantine_dir=self.qdir,
            min_near_miss=3,
            min_candidates=1,
        )
        self.assertGreater(len(rep["rows"]), 0)
        for r in rep["rows"]:
            self.assertEqual(r["mode"], "SHADOW_ONLY")
        self.assertTrue(rep["safety"]["all_rows_mode_shadow_only"])

    # ── 3. status=WAITING_FOR_REAL_MARKET_TRIGGER on every row ────────────
    def test_every_row_status_waiting(self) -> None:
        self._seed_replay([
            {"strategy": "momentum-long", "symbol": "SPY",
             "candidates": 1, "near_misses": 0},
        ])
        self._seed_near_miss([])
        rep = self.mod.build_queue(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            replay_input=self.replay,
            near_miss_input=self.near,
            quarantine_dir=self.qdir,
        )
        for r in rep["rows"]:
            self.assertEqual(r["status"], "WAITING_FOR_REAL_MARKET_TRIGGER")
        self.assertTrue(rep["safety"]["all_rows_waiting_for_trigger"])

    # ── 4. Quarantine SHADOW_ONLY variants integrated ─────────────────────
    def test_quarantine_shadow_only_variant_included(self) -> None:
        (self.qdir / "variant.json").write_text(
            json.dumps({
                "variant_id":          "v3-mom-loose-exp",
                "parent_strategy":     "momentum-long",
                "mode":                "SHADOW_ONLY",
                "symbols":             ["NVDA"],
                "asset_class":         "us_equity",
                "rationale":           "loose RSI band candidate variant",
                "trigger_condition":   "RSI(14) in [40, 80] AND breakout",
                "confidence_expectation": "0.45 - 0.70",
                "data_requirements":   "daily bars",
            }),
            encoding="utf-8",
        )
        self._seed_replay([])
        self._seed_near_miss([])
        rep = self.mod.build_queue(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            replay_input=self.replay,
            near_miss_input=self.near,
            quarantine_dir=self.qdir,
        )
        rows = rep["rows"]
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["source"], "quarantine_variant")
        self.assertEqual(r["variant_id"], "v3-mom-loose-exp")
        self.assertEqual(r["mode"], "SHADOW_ONLY")
        self.assertEqual(r["status"], "WAITING_FOR_REAL_MARKET_TRIGGER")

    # ── 5. NEVER imports alpaca_orders; never network ─────────────────────
    def test_script_safety_invariants(self) -> None:
        src = _SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("import alpaca_orders", src)
        self.assertNotIn("from alpaca_orders", src)
        self.assertNotIn("from shared.alpaca_orders", src)
        # No requests import.
        self.assertNotIn("import requests", src)
        self.assertNotIn("from requests", src)
        # Standing markers footer must include SHADOW_CANDIDATE never auto-promoted.
        self._seed_replay([])
        self._seed_near_miss([])
        rep = self.mod.build_queue(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            replay_input=self.replay,
            near_miss_input=self.near,
            quarantine_dir=self.qdir,
        )
        markers = rep["standing_markers"]
        self.assertIn("SHADOW_CANDIDATE_NEVER_AUTO_PROMOTED", markers)
        self.assertIn("SHADOW_CANDIDATE_NEVER_PLACES_ORDERS", markers)
        self.assertIn("QUEUE_NEVER_INFLATES_SHADOW_ELIGIBILITY", markers)
        self.assertFalse(rep["safety"]["places_orders"])
        self.assertFalse(rep["safety"]["writes_opportunity_ledger"])


if __name__ == "__main__":
    unittest.main()
