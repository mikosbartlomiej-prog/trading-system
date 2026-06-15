"""v3.27.0 (2026-06-15) — Agent 3B — ETAP 7 — Trigger watchlist (enhanced).

Test surface — 8 cases:
  * test_P1_rule_close_distance_high_near_miss
  * test_P2_rule_medium_distance
  * test_P3_rule_far_distance_trending_closer
  * test_BLOCKED_rule_missing_data
  * test_BLOCKED_rule_risk_preconditions_failed
  * test_watchlist_sorted_by_priority
  * test_top_N_30_enforced
  * test_no_alpaca_imports

Run:
    python3 -m unittest tests.test_trigger_watchlist_priority_v3270 -v
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "build_trigger_watchlist.py"


def _load_module():
    name = "build_trigger_watchlist_v3270"
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


class TestTriggerWatchlistPriority(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        self.threshold_path = self.root / "threshold_reality.json"
        self.replay_path = self.root / "replay_discovery.json"
        self.near_miss_aggregate_path = self.root / "near_miss_status.json"
        self.near_miss_dir = self.root / "near_miss"
        self.quarantine_path = self.root / "quarantine.json"
        self.shadow_queue_path = self.root / "shadow_queue.json"

        # Empty placeholders so the script doesn't fall back to real
        # files in the repo learning-loop/ directory.
        self.threshold_path.write_text(
            json.dumps({"strategies": []}), encoding="utf-8")
        self.replay_path.write_text(
            json.dumps({"rows": [], "missing_snapshots": []}),
            encoding="utf-8")
        self.near_miss_aggregate_path.write_text(
            json.dumps({"pairs": []}), encoding="utf-8")
        self.quarantine_path.write_text(
            json.dumps({"rows": []}), encoding="utf-8")
        self.shadow_queue_path.write_text(
            json.dumps({"rows": []}), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_replay(self, rows: list[dict]) -> None:
        self.replay_path.write_text(
            json.dumps({"rows": rows, "missing_snapshots": []}),
            encoding="utf-8")

    def _seed_near_miss_aggregate(self, pairs: list[dict]) -> None:
        self.near_miss_aggregate_path.write_text(
            json.dumps({"pairs": pairs, "flagged": []}),
            encoding="utf-8")

    def _seed_near_miss_jsonl(self, as_of: datetime, records: list[dict]) -> None:
        self.near_miss_dir.mkdir(parents=True, exist_ok=True)
        path = self.near_miss_dir / (as_of.strftime("%Y-%m-%d") + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def _build(self, *, top_n: int = 30, **kw) -> dict:
        as_of = datetime(2026, 6, 15, tzinfo=timezone.utc)
        return self.mod.build_watchlist(
            as_of=as_of,
            top_n=top_n,
            threshold_reality_input=self.threshold_path,
            near_miss_dir_input=self.near_miss_dir,
            near_miss_aggregate_input=self.near_miss_aggregate_path,
            replay_input=self.replay_path,
            quarantine_input=self.quarantine_path,
            shadow_queue_input=self.shadow_queue_path,
            **kw,
        )

    # ── 1. P1 rule — close distance + high near-miss count ────────────────
    def test_P1_rule_close_distance_high_near_miss(self) -> None:
        # 30 replay candidates → distance ~ 1/(1+30) ≈ 0.032 < 0.05.
        # Pair JSONL also stamps 5 near-misses.
        self._seed_replay([
            {"strategy": "momentum-long", "symbol": "AAPL",
             "asset_class": "us_equity",
             "candidates": 30, "near_misses": 0},
        ])
        # JSONL: 5 near-misses in last 7 days for (momentum-long, AAPL).
        self._seed_near_miss_jsonl(
            datetime(2026, 6, 15, tzinfo=timezone.utc),
            [{"strategy_id": "momentum-long", "symbol": "AAPL"}] * 5,
        )
        rep = self._build()
        rows = rep["rows"]
        self.assertGreaterEqual(len(rows), 1)
        first = rows[0]
        self.assertEqual(first["priority"], "P1",
                         f"expected P1, got {first['priority']}: {first}")
        self.assertLess(first["distance_to_trigger"], 0.05)
        self.assertGreaterEqual(first["near_miss_count_7d"], 3)
        self.assertTrue(first["replay_candidate_support"])

    # ── 2. P2 rule — medium distance ──────────────────────────────────────
    def test_P2_rule_medium_distance(self) -> None:
        # 8 candidates → distance ≈ 1/(1+8+0.5*0+0.25*1) ≈ 0.108 (within
        # [0.05, 0.15)). 1 near-miss to satisfy near_miss_count_7d >= 1.
        self._seed_replay([
            {"strategy": "momentum-long-loose", "symbol": "AMD",
             "asset_class": "us_equity",
             "candidates": 8, "near_misses": 0},
        ])
        self._seed_near_miss_jsonl(
            datetime(2026, 6, 15, tzinfo=timezone.utc),
            [{"strategy_id": "momentum-long-loose", "symbol": "AMD"}],
        )
        rep = self._build()
        rows = rep["rows"]
        self.assertEqual(len(rows), 1)
        first = rows[0]
        self.assertEqual(first["priority"], "P2",
                         f"expected P2, got {first['priority']}: {first}")
        self.assertGreaterEqual(first["distance_to_trigger"], 0.05)
        self.assertLess(first["distance_to_trigger"], 0.15)

    # ── 3. P3 rule — far distance but trending closer ─────────────────────
    def test_P3_rule_far_distance_trending_closer(self) -> None:
        # 1 candidate → distance ≈ 1/(1+1) = 0.5 >= 0.15 → P3.
        self._seed_replay([
            {"strategy": "overbought-short", "symbol": "NVDA",
             "asset_class": "us_equity",
             "candidates": 1, "near_misses": 0},
        ])
        rep = self._build()
        rows = rep["rows"]
        self.assertEqual(len(rows), 1)
        first = rows[0]
        self.assertEqual(first["priority"], "P3",
                         f"expected P3, got {first['priority']}: {first}")
        self.assertGreaterEqual(first["distance_to_trigger"], 0.15)

    # ── 4. BLOCKED — missing data ─────────────────────────────────────────
    def test_BLOCKED_rule_missing_data(self) -> None:
        # Near-miss aggregate has a pair with NO replay row + no JSONL
        # entries + no abs_distance_ratio (None). distance returned None
        # → BLOCKED.
        self._seed_replay([])
        self._seed_near_miss_aggregate([
            {"strategy_id": "crypto-momentum", "symbol": "SOL/USD",
             "metric_name": "rsi",
             "sample_size": 0, "abs_distance_ratio": None},
        ])
        rep = self._build()
        rows = rep["rows"]
        self.assertEqual(len(rows), 1)
        first = rows[0]
        self.assertEqual(first["priority"], "BLOCKED",
                         f"expected BLOCKED, got {first['priority']}: {first}")
        self.assertIn(first.get("priority_reason"),
                      ("DATA_MISSING", "RISK_PRECONDITIONS_FAILED"))
        self.assertIsNone(first["distance_to_trigger"])

    # ── 5. BLOCKED — risk preconditions failed ────────────────────────────
    def test_BLOCKED_rule_risk_preconditions_failed(self) -> None:
        # Even a P1-quality row becomes BLOCKED when operator marks risk
        # preconditions as failed.
        self._seed_replay([
            {"strategy": "momentum-long", "symbol": "AAPL",
             "asset_class": "us_equity",
             "candidates": 30, "near_misses": 0},
        ])
        self._seed_near_miss_jsonl(
            datetime(2026, 6, 15, tzinfo=timezone.utc),
            [{"strategy_id": "momentum-long", "symbol": "AAPL"}] * 5,
        )
        rep = self._build(risk_clean_default=False)
        rows = rep["rows"]
        self.assertEqual(len(rows), 1)
        first = rows[0]
        self.assertEqual(first["priority"], "BLOCKED")
        self.assertEqual(first["priority_reason"],
                         "RISK_PRECONDITIONS_FAILED")
        # And the risk_preconditions field surfaces the unknown marker.
        self.assertEqual(first["risk_preconditions"], "STATE_NOT_AVAILABLE")

    # ── 6. Watchlist sorted by priority ascending ─────────────────────────
    def test_watchlist_sorted_by_priority(self) -> None:
        # One P1, one P2, one P3, one BLOCKED.
        self._seed_replay([
            {"strategy": "momentum-long", "symbol": "AAPL",
             "asset_class": "us_equity",
             "candidates": 30, "near_misses": 0},
            {"strategy": "momentum-long-loose", "symbol": "AMD",
             "asset_class": "us_equity",
             "candidates": 8, "near_misses": 0},
            {"strategy": "overbought-short", "symbol": "NVDA",
             "asset_class": "us_equity",
             "candidates": 1, "near_misses": 0},
        ])
        self._seed_near_miss_jsonl(
            datetime(2026, 6, 15, tzinfo=timezone.utc),
            [{"strategy_id": "momentum-long", "symbol": "AAPL"}] * 5
            + [{"strategy_id": "momentum-long-loose", "symbol": "AMD"}],
        )
        self._seed_near_miss_aggregate([
            {"strategy_id": "crypto-momentum", "symbol": "SOL/USD",
             "metric_name": "rsi",
             "sample_size": 0, "abs_distance_ratio": None},
        ])
        rep = self._build()
        rows = rep["rows"]
        # Order: P1 → P2 → P3 → BLOCKED.
        priorities = [r["priority"] for r in rows]
        # Validate monotonic non-decreasing PRIORITY_RANK.
        ranks = [self.mod.PRIORITY_RANK[p] for p in priorities]
        self.assertEqual(ranks, sorted(ranks))

    # ── 7. Top-N cap enforced ─────────────────────────────────────────────
    def test_top_N_30_enforced(self) -> None:
        # Seed 50 distinct rows.
        rows_to_seed = [
            {"strategy": "momentum-long", "symbol": f"SYM{i:02d}",
             "asset_class": "us_equity", "candidates": 1, "near_misses": 0}
            for i in range(50)
        ]
        self._seed_replay(rows_to_seed)
        rep = self._build(top_n=30)
        self.assertEqual(rep["rows_total"], 30)
        self.assertEqual(rep["top_n"], 30)
        self.assertLessEqual(len(rep["rows"]), 30)

    # ── 8. No alpaca imports in script ───────────────────────────────────
    def test_no_alpaca_imports(self) -> None:
        src = _SCRIPT_PATH.read_text(encoding="utf-8")
        # Hard safety: never imports alpaca_orders, never imports
        # network / broker libs.
        self.assertNotIn("import alpaca_orders", src)
        self.assertNotIn("from alpaca_orders", src)
        self.assertNotIn("from shared.alpaca_orders", src)
        self.assertNotIn("import requests", src)
        self.assertNotIn("urllib.request", src)
        # Safety markers on the rendered report.
        rep = self._build()
        markers = rep["standing_markers"]
        self.assertIn("WATCHLIST_NEVER_PLACES_ORDERS", markers)
        self.assertIn("WATCHLIST_NEVER_AUTO_PROMOTES", markers)
        self.assertIn("WATCHLIST_NEVER_AUTO_CHANGES_THRESHOLDS", markers)
        self.assertFalse(rep["safety"]["places_orders"])
        self.assertFalse(rep["safety"]["writes_opportunity_ledger"])
        self.assertFalse(rep["safety"]["modifies_state_json"])
        self.assertFalse(rep["safety"]["auto_changes_thresholds"])


if __name__ == "__main__":
    unittest.main()
