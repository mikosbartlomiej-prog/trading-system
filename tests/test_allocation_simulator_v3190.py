"""v3.19.0 (2026-06-04) — Allocation simulator tests.

Covers:
  - All 6 modes produce a valid output shape.
  - Disabled strategies excluded.
  - Top-N selects highest-scored strategies.
  - Drawdown cap respected by drawdown_capped mode.
  - Regime-aware mode shifts weights based on per_regime stats.
  - compare_allocation_modes returns full table.
  - generate_allocation_report writes md + json.
  - NEVER raises on missing inputs (fail-soft).
  - Determinism (same input → same output).
  - NEVER modifies state.json or runtime_state.json.

All tests are LOCAL + DETERMINISTIC + NO NETWORK.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
for _p in (SHARED_DIR, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import allocation_simulator as alloc  # noqa: E402


def _make_metrics(n_closed=10, pf=1.5, dd=0.10,
                   per_regime=None, per_symbol=None):
    return {
        "n_closed": n_closed,
        "win_rate": 0.55,
        "profit_factor": pf,
        "expectancy": 0.01,
        "avg_win": 0.02,
        "avg_loss": -0.01,
        "max_drawdown": dd,
        "longest_losing_streak": 3,
        "net_pnl_after_fees_slippage": 1000.0,
        "gross_pnl": 1200.0,
        "total_costs": 200.0,
        "per_regime": per_regime or {},
        "per_symbol": per_symbol or {},
    }


def _full_metrics_dict():
    return {
        "momentum-long": _make_metrics(n_closed=20, pf=1.8, dd=0.08,
                                        per_regime={
                                            "RISK_ON": _make_metrics(
                                                n_closed=10, pf=2.2, dd=0.05)
                                        },
                                        per_symbol={
                                            "AAPL": _make_metrics(n_closed=10),
                                            "MSFT": _make_metrics(n_closed=10),
                                        }),
        "geo-defense": _make_metrics(n_closed=10, pf=1.3, dd=0.12,
                                      per_regime={
                                          "NEUTRAL": _make_metrics(
                                              n_closed=5, pf=1.4, dd=0.08)
                                      },
                                      per_symbol={
                                          "RTX": _make_metrics(n_closed=5),
                                      }),
        "overbought-short": _make_metrics(n_closed=9, pf=0.7, dd=0.18,
                                           per_regime={},
                                           per_symbol={}),
    }


class TestModesProduceValidShape(unittest.TestCase):
    def setUp(self):
        self.metrics = _full_metrics_dict()

    def test_all_modes_present(self):
        self.assertEqual(set(alloc.ALLOCATION_MODES), {
            "equal_weight", "confidence_weighted", "risk_adjusted",
            "drawdown_capped", "regime_aware", "top_n",
        })

    def test_each_mode_returns_valid_output(self):
        for mode in alloc.ALLOCATION_MODES:
            with self.subTest(mode=mode):
                r = alloc.simulate_allocation(
                    mode,
                    per_strategy_paper_metrics=self.metrics,
                    current_regime="NEUTRAL",
                )
                self.assertEqual(r["mode"], mode)
                self.assertIn("weights", r)
                self.assertIn("total_paper_pnl_usd", r)
                self.assertIn("profit_factor", r)
                self.assertIn("max_paper_drawdown_pct", r)
                self.assertIn("expectancy", r)
                self.assertIn("notes", r)
                self.assertIn("paper_analysis_only", r["notes"])


class TestEqualWeight(unittest.TestCase):
    def test_equal_weight_simple(self):
        metrics = _full_metrics_dict()
        r = alloc.simulate_allocation(
            "equal_weight", per_strategy_paper_metrics=metrics)
        self.assertEqual(len(r["weights"]), 3)
        for w in r["weights"].values():
            self.assertAlmostEqual(w, 1/3, places=4)

    def test_disabled_strategies_excluded(self):
        metrics = _full_metrics_dict()
        r = alloc.simulate_allocation(
            "equal_weight",
            per_strategy_paper_metrics=metrics,
            disabled_strategies=["overbought-short"])
        self.assertEqual(set(r["weights"].keys()),
                          {"momentum-long", "geo-defense"})
        for w in r["weights"].values():
            self.assertAlmostEqual(w, 0.5, places=4)


class TestDrawdownCapped(unittest.TestCase):
    def test_drawdown_cap_excludes_high_dd(self):
        metrics = _full_metrics_dict()
        r = alloc.simulate_allocation(
            "drawdown_capped",
            per_strategy_paper_metrics=metrics,
            drawdown_cap_pct=0.10,
        )
        # Only momentum-long (dd=0.08) qualifies; geo-defense (dd=0.12)
        # and overbought-short (dd=0.18 + PF<1) excluded.
        self.assertEqual(list(r["weights"].keys()), ["momentum-long"])
        self.assertEqual(r["weights"]["momentum-long"], 1.0)

    def test_drawdown_cap_excludes_pf_below_one(self):
        metrics = {
            "good": _make_metrics(n_closed=10, pf=1.5, dd=0.05),
            "bad":  _make_metrics(n_closed=10, pf=0.6, dd=0.05),
        }
        r = alloc.simulate_allocation(
            "drawdown_capped",
            per_strategy_paper_metrics=metrics,
            drawdown_cap_pct=0.20,
        )
        self.assertIn("good", r["weights"])
        self.assertNotIn("bad", r["weights"])


class TestTopN(unittest.TestCase):
    def test_top_n_selects_highest_scored(self):
        metrics = _full_metrics_dict()
        r = alloc.simulate_allocation(
            "top_n", per_strategy_paper_metrics=metrics, top_n=2)
        self.assertEqual(len(r["weights"]), 2)
        # momentum-long has highest PF + n; geo-defense second.
        self.assertIn("momentum-long", r["weights"])
        self.assertNotIn("overbought-short", r["weights"])

    def test_top_n_handles_too_few_strategies(self):
        metrics = _full_metrics_dict()
        r = alloc.simulate_allocation(
            "top_n", per_strategy_paper_metrics=metrics, top_n=10)
        # Should include all 3 eligible strategies.
        self.assertEqual(len(r["weights"]), 3)


class TestRegimeAware(unittest.TestCase):
    def test_regime_aware_shifts_weights(self):
        metrics = _full_metrics_dict()
        # Compare weights under RISK_ON vs NEUTRAL.
        r_risk_on = alloc.simulate_allocation(
            "regime_aware",
            per_strategy_paper_metrics=metrics,
            current_regime="RISK_ON",
        )
        r_neutral = alloc.simulate_allocation(
            "regime_aware",
            per_strategy_paper_metrics=metrics,
            current_regime="NEUTRAL",
        )
        # Under RISK_ON, momentum-long should get heavier weight (has
        # strong RISK_ON regime stats). Under NEUTRAL, weights should differ.
        self.assertNotEqual(r_risk_on["weights"], r_neutral["weights"])
        # momentum-long under RISK_ON should be weighted more than the
        # baseline equal-weight 1/3.
        self.assertGreater(r_risk_on["weights"].get("momentum-long", 0),
                            1/3)


class TestCompareAllModes(unittest.TestCase):
    def test_compare_returns_table(self):
        metrics = _full_metrics_dict()
        out = alloc.compare_allocation_modes(metrics, current_regime="NEUTRAL")
        self.assertEqual(set(out["results"].keys()),
                          set(alloc.ALLOCATION_MODES))
        self.assertIn("best_by_pnl", out)
        self.assertIn("best_by_pf", out)
        self.assertIn("best_by_dd", out)
        self.assertIn("paper_analysis_only", out["notes"])


class TestGenerateReportWritesFiles(unittest.TestCase):
    def test_generate_report_writes_md_and_json(self):
        metrics = _full_metrics_dict()
        with tempfile.TemporaryDirectory() as td:
            md = os.path.join(td, "alloc.md")
            jp = os.path.join(td, "alloc.json")
            with mock.patch.dict(os.environ,
                                  {"AUDIT_TRADING_DIR": td}):
                mdp, jpp = alloc.generate_allocation_report(
                    out_md_path=md,
                    out_json_path=jp,
                    capital_usd=50_000,
                    current_regime="NEUTRAL",
                    per_strategy_paper_metrics=metrics,
                )
            self.assertEqual(mdp, md)
            self.assertEqual(jpp, jp)
            self.assertTrue(os.path.exists(md))
            self.assertTrue(os.path.exists(jp))
            body = open(md).read()
            self.assertIn("Allocation Simulation Report", body)
            self.assertIn("Paper analysis only", body)
            payload = json.loads(open(jp).read())
            self.assertEqual(payload["capital_usd"], 50_000)
            self.assertIn("comparison", payload)


class TestNoStateChanges(unittest.TestCase):
    """Critical safety: simulate must not touch state.json/runtime_state."""

    def test_simulate_does_not_write_state(self):
        metrics = _full_metrics_dict()
        with tempfile.TemporaryDirectory() as td:
            fake_state = os.path.join(td, "state.json")
            fake_runtime = os.path.join(td, "runtime_state.json")
            with open(fake_state, "w") as f:
                f.write("{}")
            with open(fake_runtime, "w") as f:
                f.write("{}")
            with mock.patch.dict(os.environ, {
                "RUNTIME_STATE_PATH": fake_runtime,
            }):
                for mode in alloc.ALLOCATION_MODES:
                    alloc.simulate_allocation(
                        mode, per_strategy_paper_metrics=metrics)
            # State files must be unchanged.
            self.assertEqual(open(fake_state).read(), "{}")
            self.assertEqual(open(fake_runtime).read(), "{}")


class TestFailSoft(unittest.TestCase):
    def test_unknown_mode_returns_empty(self):
        r = alloc.simulate_allocation(
            "DOES_NOT_EXIST",
            per_strategy_paper_metrics=_full_metrics_dict())
        self.assertIn("unknown_mode", r["notes"])
        self.assertEqual(r["weights"], {})

    def test_non_dict_metrics_returns_empty(self):
        r = alloc.simulate_allocation(
            "equal_weight",
            per_strategy_paper_metrics="not a dict")  # type: ignore
        self.assertEqual(r["weights"], {})

    def test_empty_metrics_returns_empty(self):
        r = alloc.simulate_allocation(
            "equal_weight",
            per_strategy_paper_metrics={})
        self.assertEqual(r["weights"], {})

    def test_no_eligible_strategies(self):
        # All n_closed = 0 → no eligible.
        metrics = {"x": _make_metrics(n_closed=0)}
        r = alloc.simulate_allocation(
            "equal_weight",
            per_strategy_paper_metrics=metrics)
        self.assertEqual(r["weights"], {})


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        metrics = _full_metrics_dict()
        for mode in alloc.ALLOCATION_MODES:
            r1 = alloc.simulate_allocation(
                mode, per_strategy_paper_metrics=metrics)
            r2 = alloc.simulate_allocation(
                mode, per_strategy_paper_metrics=metrics)
            self.assertEqual(r1, r2, f"mode {mode} not deterministic")


if __name__ == "__main__":
    unittest.main()
