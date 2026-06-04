"""v3.19.0 (2026-06-04) — Pre-open plan v2 tests.

Covers:
  - store_plan_v2 round-trip (all v2 fields persisted to runtime_state)
  - apply_pre_open_caps NEVER raises confidence
  - do_not_trade_list blocks symbol (hard zero)
  - confidence_caps_per_strategy + per_symbol enforced
  - stale data warning lowers confidence
  - v2 plans remain v1-compatible (backward compat)

All tests are LOCAL + DETERMINISTIC + NO NETWORK.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
for p in (SHARED_DIR, SCRIPTS_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


class _RuntimeStateOverride:
    """Redirect runtime_state.json to a temp file."""

    def __init__(self):
        self.tmp = None
        self.path = None

    def __enter__(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False)
        self.tmp.write("{}")
        self.tmp.close()
        self.path = self.tmp.name
        os.environ["RUNTIME_STATE_PATH"] = self.path
        if "runtime_state" in sys.modules:
            importlib.reload(sys.modules["runtime_state"])
        if "pre_open_plan" in sys.modules:
            importlib.reload(sys.modules["pre_open_plan"])
        return self.path

    def __exit__(self, *exc):
        os.environ.pop("RUNTIME_STATE_PATH", None)
        try:
            os.unlink(self.path)
        except OSError:
            pass
        if "runtime_state" in sys.modules:
            importlib.reload(sys.modules["runtime_state"])
        if "pre_open_plan" in sys.modules:
            importlib.reload(sys.modules["pre_open_plan"])


class TestStorePlanV2RoundTrip(unittest.TestCase):
    def test_v2_fields_persisted(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            payload = pop.store_plan_v2(
                plan_date_iso="2026-06-04",
                per_symbol_plan={
                    "AAPL": {"symbol": "AAPL", "label": "FLAT_PRE_OPEN"},
                },
                expected_regime="RISK_ON",
                high_risk_symbols=["TSLA", "MSTR"],
                do_not_trade_list=["NVDA"],
                observe_only_list=["AAPL"],
                strategy_warnings={"momentum-long": ["regime_mismatch"]},
                confidence_caps_per_strategy={"options-momentum": 0.55},
                confidence_caps_per_symbol={"TSLA": 0.60},
                event_risk_warnings=["FOMC at 18:00 UTC"],
                liquidity_warnings=["GOOGL:low_volume"],
                gap_warnings=["TSLA:GAP_UP_WEAK"],
                stale_data_warnings=["MSFT"],
                daily_experiment_objectives=["verify SPY"],
            )
            self.assertEqual(payload["expected_regime"], "RISK_ON")
            self.assertEqual(payload["high_risk_symbols"], ["TSLA", "MSTR"])
            self.assertEqual(payload["do_not_trade_list"], ["NVDA"])
            self.assertEqual(payload["strategy_warnings"]["momentum-long"],
                              ["regime_mismatch"])
            self.assertEqual(payload["confidence_caps_per_strategy"]
                              ["options-momentum"], 0.55)
            self.assertEqual(payload["confidence_caps_per_symbol"]["TSLA"],
                              0.60)
            # Verify get_plan reads back
            plan = pop.get_plan()
            self.assertEqual(plan["do_not_trade_list"], ["NVDA"])
            self.assertEqual(plan["stale_data_warnings"], ["MSFT"])

    def test_v1_plan_backward_compat(self):
        """A v1-style plan stored via store_plan still reads via get_plan."""
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            pop.store_plan(
                plan_date_iso="2026-06-04",
                per_symbol_plan={"AAPL": {"symbol": "AAPL",
                                            "label": "FLAT_PRE_OPEN"}},
            )
            plan = pop.get_plan()
            # No v2 fields → apply_pre_open_caps must be no-op
            adj = pop.apply_pre_open_caps(plan, strategy="momentum-long",
                                           symbol="AAPL",
                                           current_confidence=0.78)
            self.assertEqual(adj, 0.78)

    def test_caps_clamped_to_unit(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            payload = pop.store_plan_v2(
                plan_date_iso="2026-06-04",
                per_symbol_plan={},
                confidence_caps_per_strategy={"x": 5.0, "y": -1.0},
                confidence_caps_per_symbol={"AAPL": 99.0},
            )
            self.assertEqual(payload["confidence_caps_per_strategy"]["x"], 1.0)
            self.assertEqual(payload["confidence_caps_per_strategy"]["y"], 0.0)
            self.assertEqual(payload["confidence_caps_per_symbol"]["AAPL"], 1.0)


class TestApplyPreOpenCaps(unittest.TestCase):
    """Critical invariant: confidence NEVER goes up."""

    def test_no_plan_no_op(self):
        import pre_open_plan as pop
        adj = pop.apply_pre_open_caps({}, strategy="x", symbol="AAPL",
                                       current_confidence=0.7)
        self.assertEqual(adj, 0.7)

    def test_per_strategy_cap_enforced(self):
        import pre_open_plan as pop
        plan = {"confidence_caps_per_strategy": {"momentum-long": 0.55}}
        adj = pop.apply_pre_open_caps(plan, strategy="momentum-long",
                                       symbol="AAPL",
                                       current_confidence=0.78)
        self.assertAlmostEqual(adj, 0.55)

    def test_per_symbol_cap_enforced(self):
        import pre_open_plan as pop
        plan = {"confidence_caps_per_symbol": {"TSLA": 0.60}}
        adj = pop.apply_pre_open_caps(plan, strategy="momentum-long",
                                       symbol="TSLA",
                                       current_confidence=0.85)
        self.assertAlmostEqual(adj, 0.60)

    def test_strategy_cap_then_symbol_cap_floor_wins(self):
        import pre_open_plan as pop
        plan = {
            "confidence_caps_per_strategy": {"x": 0.70},
            "confidence_caps_per_symbol":   {"AAPL": 0.45},
        }
        adj = pop.apply_pre_open_caps(plan, strategy="x", symbol="AAPL",
                                       current_confidence=0.90)
        self.assertAlmostEqual(adj, 0.45)

    def test_do_not_trade_zeroes_confidence(self):
        import pre_open_plan as pop
        plan = {"do_not_trade_list": ["NVDA"]}
        adj = pop.apply_pre_open_caps(plan, strategy="x", symbol="NVDA",
                                       current_confidence=0.9)
        self.assertEqual(adj, 0.0)

    def test_stale_data_warning_subtracts_penalty(self):
        import pre_open_plan as pop
        plan = {"stale_data_warnings": ["MSFT"]}
        adj = pop.apply_pre_open_caps(plan, strategy="x", symbol="MSFT",
                                       current_confidence=0.80)
        self.assertAlmostEqual(adj, 0.80 - pop.STALE_DATA_PENALTY)

    def test_caps_never_raise(self):
        """Property test: for ANY plan, adjusted <= original."""
        import pre_open_plan as pop
        cases = [
            {},
            {"confidence_caps_per_strategy": {"x": 0.99}},
            {"confidence_caps_per_symbol":   {"AAPL": 0.95}},
            {"confidence_caps_per_strategy": {"x": 0.5},
             "confidence_caps_per_symbol":   {"AAPL": 0.99}},
            {"do_not_trade_list": ["AAPL"]},
            {"stale_data_warnings": ["AAPL"]},
        ]
        for orig in (0.10, 0.50, 0.75, 0.95, 1.00):
            for plan in cases:
                adj = pop.apply_pre_open_caps(plan, strategy="x",
                                               symbol="AAPL",
                                               current_confidence=orig)
                self.assertLessEqual(adj, orig + 1e-9,
                    f"orig={orig} plan={plan} adj={adj}")
                self.assertGreaterEqual(adj, 0.0)

    def test_apply_with_garbage_confidence_returns_zero(self):
        import pre_open_plan as pop
        adj = pop.apply_pre_open_caps({"do_not_trade_list": []},
                                       strategy="x", symbol="A",
                                       current_confidence="bad")  # type: ignore
        self.assertEqual(adj, 0.0)

    def test_garbage_plan_returns_original(self):
        import pre_open_plan as pop
        adj = pop.apply_pre_open_caps("not_a_dict",  # type: ignore
                                       strategy="x", symbol="A",
                                       current_confidence=0.7)
        self.assertEqual(adj, 0.7)


class TestHelpers(unittest.TestCase):
    def test_get_do_not_trade_list_default(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            self.assertEqual(pop.get_do_not_trade_list(), [])

    def test_get_strategy_warnings(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            pop.store_plan_v2(
                plan_date_iso="2026-06-04",
                per_symbol_plan={},
                strategy_warnings={"x": ["a", "b"]},
            )
            self.assertEqual(pop.get_strategy_warnings("x"), ["a", "b"])
            self.assertEqual(pop.get_strategy_warnings("missing"), [])


if __name__ == "__main__":
    unittest.main()
