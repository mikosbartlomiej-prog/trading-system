"""v3.20.0 (2026-06-04) — Tests for shared/experiment_scheduler.py.

These tests enforce ETAP 7 invariants:
  - underrepresented regime gets priority
  - weak strategy does not get larger risk (scheduler raises nothing)
  - generate_plan does not mutate runtime state
  - output deterministic for fixed input
  - plan can be written to disk

Run with:
    python3 -m unittest tests.test_experiment_scheduler_v3200
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["EXPERIMENT_PLANS_DIR"] = str(
            Path(self._tmp.name) / "plans")
        os.environ["EXPERIMENT_PLANS_DOCS_DIR"] = str(
            Path(self._tmp.name) / "docs")
        # Also isolate any quarantine reads to a fresh tmp dir,
        # and redirect audit emissions to keep the repo journal clean.
        os.environ["VARIANT_QUARANTINE_DIR"] = str(
            Path(self._tmp.name) / "variants")
        os.environ["AUDIT_TRADING_DIR"] = str(
            Path(self._tmp.name) / "audit")
        # Force fresh import.
        for k in list(sys.modules):
            if k.endswith(".experiment_scheduler") \
               or k == "experiment_scheduler" \
               or k.endswith(".strategy_variant_quarantine") \
               or k == "strategy_variant_quarantine":
                del sys.modules[k]
        import experiment_scheduler as es  # noqa: E402
        self.es = es

    def tearDown(self):
        for var in ("EXPERIMENT_PLANS_DIR", "EXPERIMENT_PLANS_DOCS_DIR",
                    "VARIANT_QUARANTINE_DIR", "AUDIT_TRADING_DIR"):
            os.environ.pop(var, None)

    @staticmethod
    def _now() -> datetime:
        return datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc)


class TestRegimePrioritization(_Base):
    def test_underrepresented_regime_gets_priority(self):
        """The regime with fewest samples below threshold ranks first."""
        bounds = {
            "per_regime": {
                "RISK_ON":   {"n_closed": 50, "min_required": 30},
                "RISK_OFF":  {"n_closed":  2, "min_required": 10},  # under
                "NEUTRAL":   {"n_closed":  8, "min_required": 10},  # under
                "INFLATION_SHOCK": {"n_closed": 0, "min_required": 10},
            },
        }
        plan = self.es.generate_plan(
            evidence_lower_bounds=bounds, now=self._now())
        regimes = plan["underrepresented_regimes"]
        self.assertGreaterEqual(len(regimes), 3)
        # Smallest n first.
        self.assertEqual(regimes[0]["regime"], "INFLATION_SHOCK")
        self.assertEqual(regimes[0]["n_closed"], 0)
        # RISK_ON has enough data → never surfaced.
        labels = [r["regime"] for r in regimes]
        self.assertNotIn("RISK_ON", labels)


class TestWeakStrategyDoesNotRaiseRisk(_Base):
    def test_weak_strategy_does_not_get_larger_risk(self):
        """A poor strategy ranking does NOT escalate into bigger size."""
        ranking = [
            {"strategy": "weak_one",
             "status": "DISABLE_CANDIDATE", "score": 0.05, "rank": 1},
            {"strategy": "needs_data",
             "status": "NEEDS_MORE_DATA", "score": 0.35, "rank": 2},
            {"strategy": "edge_review",
             "status": "EDGE_REVIEW_CANDIDATE", "score": 0.92, "rank": 9},
        ]
        plan = self.es.generate_plan(strategy_ranking=ranking, now=self._now())
        # Plan keys do NOT carry size / risk / leverage instructions.
        for row in plan["strategies_to_observe"]:
            forbidden_risk_keys = {"size_multiplier", "leverage",
                                   "max_position", "kelly", "weight"}
            self.assertFalse(forbidden_risk_keys & set(row.keys()),
                             f"plan row leaks risk knob: {row}")
        # Invariants block trade-side actions.
        self.assertTrue(plan["invariants"]["SCHEDULER_NEVER_RAISES_RISK"])
        self.assertTrue(plan["invariants"]["SCHEDULER_NEVER_PLACES_TRADES"])


class TestRuntimeIsolation(_Base):
    def test_generate_plan_does_not_mutate_runtime(self):
        """Scheduler must not touch shared.runtime_state or state.json."""
        ranking = [{"strategy": "a", "status": "NEEDS_MORE_DATA",
                    "score": 0.1, "rank": 1}]
        # Snapshot env (where runtime_state would persist).
        env_before = dict(os.environ)

        # Capture filesystem mtimes for state.json + runtime_state.json
        # (if present in repo). If absent, this still asserts non-creation.
        state_path = REPO_ROOT / "learning-loop" / "state.json"
        runtime_path = REPO_ROOT / "learning-loop" / "runtime_state.json"
        before_state = state_path.stat().st_mtime_ns if state_path.exists() \
            else None
        before_runtime = runtime_path.stat().st_mtime_ns if runtime_path.exists() \
            else None

        plan = self.es.generate_plan(
            strategy_ranking=ranking, now=self._now())
        self.assertIsInstance(plan, dict)

        # Env untouched.
        self.assertEqual(env_before, dict(os.environ))
        # State files untouched.
        if before_state is not None:
            self.assertEqual(before_state, state_path.stat().st_mtime_ns)
        else:
            self.assertFalse(state_path.exists())
        if before_runtime is not None:
            self.assertEqual(before_runtime, runtime_path.stat().st_mtime_ns)
        else:
            self.assertFalse(runtime_path.exists())


class TestDeterministicOutput(_Base):
    def test_output_deterministic(self):
        """Two runs with identical inputs produce identical plans (modulo ts)."""
        ranking = [
            {"strategy": "b_strat", "status": "NEEDS_MORE_DATA",
             "score": 0.4, "rank": 1},
            {"strategy": "a_strat", "status": "CONTINUE_OBSERVE",
             "score": 0.6, "rank": 2},
            {"strategy": "c_strat", "status": "EDGE_REVIEW_CANDIDATE",
             "score": 0.9, "rank": 3},
        ]
        ledger = {
            "opportunities": [
                {"symbol": "spy", "ts": "2026-06-04T10:00:00Z"},
                {"symbol": "QQQ", "ts": "2026-06-04T11:00:00Z"},
                {"symbol": "spy", "ts": "2026-06-04T12:00:00Z"},
            ],
        }
        now = self._now()
        plan1 = self.es.generate_plan(
            strategy_ranking=ranking, opportunity_ledger=ledger, now=now)
        plan2 = self.es.generate_plan(
            strategy_ranking=ranking, opportunity_ledger=ledger, now=now)

        # ts_iso identical because we passed `now=` to both.
        self.assertEqual(plan1["ts_iso"], plan2["ts_iso"])
        # The full plan structure identical.
        self.assertEqual(
            json.dumps(plan1, sort_keys=True, default=str),
            json.dumps(plan2, sort_keys=True, default=str),
        )

        # Symbol ordering: most-frequent first ("SPY" with 2 occurrences before
        # "QQQ" with 1), then alphabetical for ties.
        syms = [r["symbol"] for r in plan1["symbols_to_observe"]]
        self.assertEqual(syms[0], "SPY")
        self.assertEqual(syms[1], "QQQ")


class TestPlanWriteToDisk(_Base):
    def test_plan_written_to_disk(self):
        """Plan JSON + markdown both land on disk in the expected locations."""
        plan = self.es.generate_plan(
            strategy_ranking=[
                {"strategy": "x", "status": "NEEDS_MORE_DATA",
                 "score": 0.1, "rank": 1},
            ],
            now=self._now(),
        )
        paths = self.es.write_plan_to_disk(plan)
        self.assertEqual(len(paths), 2)
        json_path = Path(os.environ["EXPERIMENT_PLANS_DIR"]) / \
            f"experiment_plan_{plan['plan_date']}.json"
        md_path = Path(os.environ["EXPERIMENT_PLANS_DOCS_DIR"]) / \
            "experiment_plan_LATEST.md"
        self.assertTrue(json_path.exists())
        self.assertTrue(md_path.exists())
        # Round-trip JSON shape.
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["plan_date"], plan["plan_date"])
        self.assertEqual(loaded["invariants"]
                         ["SCHEDULER_NEVER_PLACES_TRADES"], True)
        # Markdown not empty, mentions invariants.
        md = md_path.read_text(encoding="utf-8")
        self.assertIn("Experiment plan", md)
        self.assertIn("SCHEDULER_NEVER_PLACES_TRADES", md)


class TestVariantsFlowThrough(_Base):
    """End-to-end: register a quarantined variant, then ensure the
    scheduler surfaces it (and only QUARANTINED/REPLAY/SHADOW states)."""

    def test_quarantined_variant_surfaces_in_plan(self):
        import strategy_variant_quarantine as svq  # noqa: E402
        v = svq.register_variant(
            "momentum_long_strict",
            "tighten breakout",
            {"threshold": 0.65},
            evidence_source="BACKTEST",
        )
        # set one to REJECTED → should NOT surface.
        rejected = svq.register_variant(
            "momentum_long_strict",
            "weak idea",
            {"cooldown": 999},
            evidence_source="REPLAY",
        )
        svq.set_status(rejected["id"], svq.REJECTED, reason="negative replay")

        plan = self.es.generate_plan(now=self._now())
        ids = {row["id"] for row in plan["variants_to_replay"]}
        self.assertIn(v["id"], ids)
        self.assertNotIn(rejected["id"], ids)


if __name__ == "__main__":
    unittest.main()
