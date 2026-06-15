"""v3.26.0 (2026-06-15) — Agent 3B — ETAP 8 — Trigger watchlist tests.

  * Synthetic near-miss + replay → watchlist rows ranked by distance.
  * NEVER places orders.
  * NEVER imports alpaca_orders.
  * top_n parameter honored.
  * Every row mode=SHADOW_ONLY, status=WATCHING.

Run:
    python3 -m unittest tests.test_trigger_watchlist_v3260 -v
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "build_trigger_watchlist.py"


def _load_module():
    import sys
    name = "build_trigger_watchlist_v3260"
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


class TestTriggerWatchlist(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.replay = self.root / "replay_discovery_latest.json"
        self.near = self.root / "near_miss_status_latest.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_replay(self, rows: list[dict]) -> None:
        self.replay.write_text(
            json.dumps({"rows": rows}), encoding="utf-8")

    def _seed_near_miss(self, pairs: list[dict]) -> None:
        self.near.write_text(
            json.dumps({"pairs": pairs, "flagged": []}),
            encoding="utf-8")

    # ── 1. Rows ranked by current_distance ascending ───────────────────────
    def test_rows_ranked_by_distance(self) -> None:
        # Replay produces 3 candidates → low distance; replay produces 1
        # candidate → higher distance.
        self._seed_replay([
            {"strategy": "momentum-long", "symbol": "SPY",
             "asset_class": "us_equity",
             "candidates": 3, "near_misses": 2},
            {"strategy": "momentum-long", "symbol": "QQQ",
             "asset_class": "us_equity",
             "candidates": 1, "near_misses": 1},
        ])
        self._seed_near_miss([])
        rep = self.mod.build_watchlist(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            top_n=20,
            replay_input=self.replay,
            near_miss_input=self.near,
        )
        rows = rep["rows"]
        self.assertEqual(len(rows), 2)
        # Lower distance must come first.
        d0, d1 = rows[0]["current_distance"], rows[1]["current_distance"]
        self.assertLess(d0, d1)
        # First row: SPY (more candidates → lower distance).
        self.assertEqual(rows[0]["symbol"], "SPY")

    # ── 2. top_n honored ───────────────────────────────────────────────────
    def test_top_n_honored(self) -> None:
        replay_rows = [
            {"strategy": "momentum-long", "symbol": f"SYM{i}",
             "asset_class": "us_equity", "candidates": 1, "near_misses": 0}
            for i in range(30)
        ]
        self._seed_replay(replay_rows)
        self._seed_near_miss([])
        rep = self.mod.build_watchlist(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            top_n=5,
            replay_input=self.replay,
            near_miss_input=self.near,
        )
        self.assertEqual(rep["rows_total"], 5)
        self.assertEqual(rep["top_n"], 5)

    # ── 3. Every row mode/status correct ───────────────────────────────────
    def test_row_mode_and_status(self) -> None:
        self._seed_replay([
            {"strategy": "crypto-oversold-bounce", "symbol": "BTC/USD",
             "asset_class": "crypto", "candidates": 0, "near_misses": 4},
        ])
        self._seed_near_miss([])
        rep = self.mod.build_watchlist(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            top_n=20,
            replay_input=self.replay,
            near_miss_input=self.near,
        )
        for r in rep["rows"]:
            self.assertEqual(r["expected_evidence_mode"], "SHADOW_ONLY")
            self.assertEqual(r["status"], "WATCHING")
        self.assertTrue(rep["safety"]["all_rows_mode_shadow_only"])
        self.assertTrue(rep["safety"]["all_rows_status_watching"])

    # ── 4. Near-miss aggregate pairs ingested ──────────────────────────────
    def test_near_miss_pairs_ingested(self) -> None:
        self._seed_replay([])
        self._seed_near_miss([
            {"strategy_id": "momentum-long-loose", "symbol": "AMD",
             "metric_name": "rsi_band_distance",
             "sample_size": 10, "abs_distance_ratio": 0.18,
             "advisory_flag": True},
        ])
        rep = self.mod.build_watchlist(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            top_n=20,
            replay_input=self.replay,
            near_miss_input=self.near,
        )
        # One row from near_miss should appear.
        rows = rep["rows"]
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["strategy"], "momentum-long-loose")
        self.assertEqual(r["symbol"], "AMD")
        # current_distance should equal the abs_distance_ratio.
        self.assertAlmostEqual(r["current_distance"], 0.18, places=4)
        self.assertEqual(r["near_miss_history_count"], 10)

    # ── 5. Safety invariants — no broker, no orders, no auto-promote ──────
    def test_script_never_imports_alpaca_orders(self) -> None:
        src = _SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn("import alpaca_orders", src)
        self.assertNotIn("from alpaca_orders", src)
        self.assertNotIn("from shared.alpaca_orders", src)
        self.assertNotIn("import requests", src)
        self._seed_replay([])
        self._seed_near_miss([])
        rep = self.mod.build_watchlist(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            top_n=20,
            replay_input=self.replay,
            near_miss_input=self.near,
        )
        self.assertFalse(rep["safety"]["places_orders"])
        self.assertFalse(rep["safety"]["writes_opportunity_ledger"])
        self.assertFalse(rep["safety"]["modifies_state_json"])
        markers = rep["standing_markers"]
        self.assertIn("WATCHLIST_NEVER_PLACES_ORDERS", markers)
        self.assertIn("WATCHLIST_NEVER_AUTO_PROMOTES", markers)


if __name__ == "__main__":
    unittest.main()
