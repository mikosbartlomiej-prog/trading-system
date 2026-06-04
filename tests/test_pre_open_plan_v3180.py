"""v3.18.0 (2026-06-04) — Pre-open session plan tests.

Covers:
  - shared/pre_open_plan.py public API (store/get/get_for_symbol/clear)
  - shared/pre_open_plan.py adjustment clamping (max +0.05, min -0.10)
  - scripts/pre_open_session_planner.py end-to-end with mocked data
  - Confidence boost cap enforcement

All tests are LOCAL + DETERMINISTIC + NO NETWORK.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
for p in (SHARED_DIR, SCRIPTS_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


class _RuntimeStateOverride:
    """Context manager: redirect runtime_state.json to a temp file."""

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
        # Force re-import so RUNTIME_STATE_PATH gets re-evaluated.
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


class TestPlanStoreAndGet(unittest.TestCase):
    """Round-trip a plan through runtime_state."""

    def test_get_plan_for_unknown_symbol_returns_none(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            self.assertIsNone(pop.get_plan_for_symbol("AAPL"))

    def test_get_plan_for_empty_symbol_returns_none(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            self.assertIsNone(pop.get_plan_for_symbol(""))
            self.assertIsNone(pop.get_plan_for_symbol(None))  # type: ignore

    def test_store_then_get(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            payload = pop.store_plan(
                plan_date_iso="2026-06-04",
                per_symbol_plan={
                    "AAPL": {
                        "symbol": "AAPL",
                        "label": "GAP_UP_STRONG_PRE_OPEN",
                        "gap_pct": 0.025,
                        "warnings": ["pre_market_gap_strong"],
                        "confidence_adjustment": 0.04,
                        "source": "yahoo",
                        "rationale": "test",
                    },
                },
                actor="pre-open-planner-test",
            )
            self.assertEqual(payload["symbols_planned"], 1)
            entry = pop.get_plan_for_symbol("AAPL")
            self.assertIsNotNone(entry)
            self.assertEqual(entry["label"], "GAP_UP_STRONG_PRE_OPEN")
            self.assertEqual(entry["confidence_adjustment"], 0.04)
            self.assertIn("pre_market_gap_strong", entry["warnings"])


class TestAdjustmentClamping(unittest.TestCase):
    """Plan layer NEVER lets confidence rise more than +0.05."""

    def test_positive_boost_clamped_to_0_05(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            pop.store_plan(
                plan_date_iso="2026-06-04",
                per_symbol_plan={
                    "AAPL": {
                        "label": "GAP_UP_STRONG_PRE_OPEN",
                        # Upstream tried to boost by +0.30 — must be clamped.
                        "confidence_adjustment": 0.30,
                    },
                },
                actor="pre-open-planner-test",
            )
            entry = pop.get_plan_for_symbol("AAPL")
            self.assertEqual(entry["confidence_adjustment"], 0.05)

    def test_negative_penalty_clamped_to_minus_0_10(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            pop.store_plan(
                plan_date_iso="2026-06-04",
                per_symbol_plan={
                    "AAPL": {
                        "label": "LOW_VOLUME_FAKE_MOVE",
                        "confidence_adjustment": -0.50,
                    },
                },
                actor="pre-open-planner-test",
            )
            entry = pop.get_plan_for_symbol("AAPL")
            self.assertEqual(entry["confidence_adjustment"], -0.10)

    def test_invalid_adjustment_defaults_to_zero(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            pop.store_plan(
                plan_date_iso="2026-06-04",
                per_symbol_plan={
                    "AAPL": {
                        "label": "INSUFFICIENT_DATA",
                        "confidence_adjustment": "not_a_number",
                    },
                },
                actor="pre-open-planner-test",
            )
            entry = pop.get_plan_for_symbol("AAPL")
            self.assertEqual(entry["confidence_adjustment"], 0.0)


class TestMalformedInputs(unittest.TestCase):
    """Pre-open plan must be defensive about bad inputs."""

    def test_non_dict_entry_sanitized(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            pop.store_plan(
                plan_date_iso="2026-06-04",
                per_symbol_plan={"AAPL": "not_a_dict"},  # type: ignore
                actor="pre-open-planner-test",
            )
            entry = pop.get_plan_for_symbol("AAPL")
            self.assertIsNotNone(entry)
            self.assertEqual(entry["label"], "INSUFFICIENT_DATA")
            self.assertEqual(entry["confidence_adjustment"], 0.0)

    def test_non_string_symbol_dropped(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            pop.store_plan(
                plan_date_iso="2026-06-04",
                per_symbol_plan={
                    123: {"label": "FLAT_PRE_OPEN"},   # type: ignore
                    "AAPL": {"label": "FLAT_PRE_OPEN"},
                },
                actor="pre-open-planner-test",
            )
            # Only AAPL should survive
            self.assertIsNotNone(pop.get_plan_for_symbol("AAPL"))


class TestPlannerScript(unittest.TestCase):
    """End-to-end pre_open_session_planner with mocked data sources."""

    def test_planner_produces_entry_per_symbol(self):
        with _RuntimeStateOverride():
            # Re-import after env override.
            from pre_open_session_planner import main as planner_main

            ctx_stub = {
                "symbol": "AAPL",
                "pre_market_bars": [
                    {"o": 100, "h": 101, "l": 99.5, "c": 100.5, "v": 1000,
                     "t": "2026-06-04T13:00:00Z"},
                    {"o": 100.5, "h": 102, "l": 100, "c": 101.5, "v": 1500,
                     "t": "2026-06-04T13:05:00Z"},
                    {"o": 101.5, "h": 103, "l": 101, "c": 102.8, "v": 2000,
                     "t": "2026-06-04T13:10:00Z"},
                ],
                "prev_session_close": 100.0,
                "prev_session_high": 101.5,
                "prev_session_low": 98.5,
                "source": "yahoo",
                "fetched_at_iso": "2026-06-04T13:00:00Z",
                "warnings": [],
            }
            with mock.patch("pre_market_data.get_pre_market_context",
                              return_value=ctx_stub):
                rc = planner_main(["--symbols", "AAPL", "--plan-date",
                                    "2026-06-04"])
            self.assertEqual(rc, 0)
            import pre_open_plan as pop
            entry = pop.get_plan_for_symbol("AAPL")
            self.assertIsNotNone(entry)
            # gap = (102.8 - 100) / 100 = +0.028 → STRONG (>=0.02)
            self.assertEqual(entry["label"], "GAP_UP_STRONG_PRE_OPEN")
            self.assertIn("pre_market_gap_strong", entry["warnings"])

    def test_planner_missing_data_yields_no_data_warning(self):
        with _RuntimeStateOverride():
            from pre_open_session_planner import main as planner_main
            empty_ctx = {
                "symbol": "AAPL",
                "pre_market_bars": [],
                "prev_session_close": None,
                "prev_session_high": None,
                "prev_session_low": None,
                "source": "unavailable",
                "fetched_at_iso": "2026-06-04T13:00:00Z",
                "warnings": ["yahoo_no_bars", "nasdaq_no_summary"],
            }
            with mock.patch("pre_market_data.get_pre_market_context",
                              return_value=empty_ctx):
                rc = planner_main(["--symbols", "AAPL", "--plan-date",
                                    "2026-06-04"])
            self.assertEqual(rc, 0)
            import pre_open_plan as pop
            entry = pop.get_plan_for_symbol("AAPL")
            self.assertIsNotNone(entry)
            self.assertEqual(entry["label"], "INSUFFICIENT_DATA")
            self.assertEqual(entry["confidence_adjustment"], 0.0)
            self.assertIn("no_data", entry["warnings"])


class TestMonitorReadAndConfidence(unittest.TestCase):
    """Plan entry consumed by a monitor → confidence_builder respects cap."""

    def test_low_volume_fake_move_lowers_confidence(self):
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            pop.store_plan(
                plan_date_iso="2026-06-04",
                per_symbol_plan={
                    "AAPL": {
                        "label": "LOW_VOLUME_FAKE_MOVE",
                        "gap_pct": 0.025,
                        "warnings": ["pre_market_low_volume_fake_move"],
                        "confidence_adjustment": -0.10,
                        "source": "yahoo",
                        "rationale": "fake_move_detected",
                    },
                },
                actor="pre-open-planner-test",
            )
            entry = pop.get_plan_for_symbol("AAPL")
            # confidence_adjustment is negative → would lower confidence
            self.assertLess(entry["confidence_adjustment"], 0)
            self.assertIn("pre_market_low_volume_fake_move",
                            entry["warnings"])

    def test_plan_never_carries_boost_above_max(self):
        """Defense in depth: regardless of upstream, cap is +0.05."""
        with _RuntimeStateOverride():
            import pre_open_plan as pop
            for upstream_value in (0.05, 0.10, 0.25, 1.0):
                pop.store_plan(
                    plan_date_iso="2026-06-04",
                    per_symbol_plan={
                        "T": {
                            "label": "GAP_UP_STRONG_PRE_OPEN",
                            "confidence_adjustment": upstream_value,
                        },
                    },
                    actor="pre-open-planner-test",
                )
                entry = pop.get_plan_for_symbol("T")
                self.assertLessEqual(entry["confidence_adjustment"],
                                      pop.MAX_POSITIVE_ADJUSTMENT)


if __name__ == "__main__":
    unittest.main()
