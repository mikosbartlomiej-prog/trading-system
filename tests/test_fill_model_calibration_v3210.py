"""v3.21.0 (2026-06-04) — Tests for shared/fill_model_calibration.py."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _Base(unittest.TestCase):
    def setUp(self):
        for k in list(sys.modules):
            if k == "fill_model_calibration" \
               or k.endswith(".fill_model_calibration"):
                del sys.modules[k]
        import fill_model_calibration as fmc  # noqa: WPS433
        self.fmc = fmc

    def _pair(self, *, sym="AAPL", strategy="momentum",
              ref=100.0, shadow=100.05, broker=100.07,
              shadow_slip_bps=5.0, actual_slip_bps=7.0,
              spread_assumption_bps=1.0, observed_spread_bps=2.0,
              fill_delay=0.4, adverse=0.0) -> dict:
        return {
            "symbol":                              sym,
            "strategy":                            strategy,
            "reference_price":                     ref,
            "shadow_fill_price":                   shadow,
            "broker_paper_fill_price":             broker,
            "expected_slippage_bps":               shadow_slip_bps,
            "actual_paper_slippage_bps":           actual_slip_bps,
            "spread_assumption_bps":               spread_assumption_bps,
            "observed_spread_bps":                 observed_spread_bps,
            "fill_delay_seconds":                  fill_delay,
            "adverse_selection_after_fill_bps":    adverse,
        }


class TestNoBrokerData(_Base):
    """When the paired sample is empty or below threshold we must NOT
    pretend calibration happened."""

    def test_empty_pairs_returns_insufficient(self):
        rep = self.fmc.build_calibration_report([])
        self.assertEqual(rep["aggregate"]["status"],
                         self.fmc.INSUFFICIENT_BROKER_PAPER_DATA)
        self.assertEqual(rep["aggregate"]["n_paired"], 0)
        self.assertFalse(rep["mutates_runtime"])
        self.assertTrue(rep["non_auto_apply"])

    def test_below_threshold_is_insufficient(self):
        n_below = self.fmc.MIN_PAIRED_OBSERVATIONS - 1
        pairs = [self._pair() for _ in range(n_below)]
        rep = self.fmc.build_calibration_report(pairs)
        self.assertEqual(rep["aggregate"]["status"],
                         self.fmc.INSUFFICIENT_BROKER_PAPER_DATA)
        self.assertEqual(rep["aggregate"]["n_paired"], n_below)


class TestShadowVsBrokerDiff(_Base):
    """When data is present we must compute deltas correctly."""

    def test_diff_calculated_when_data_present(self):
        # 20 paired observations where broker fill is +2 bps worse on
        # average than shadow.
        n = self.fmc.MIN_PAIRED_OBSERVATIONS
        pairs = [
            self._pair(
                ref=100.0,
                shadow=100.05,            # +5 bps
                broker=100.07,            # +7 bps
                shadow_slip_bps=5.0,
                actual_slip_bps=7.0,
            )
            for _ in range(n)
        ]
        rep = self.fmc.build_calibration_report(pairs)
        agg = rep["aggregate"]
        self.assertEqual(agg["n_paired"], n)
        # Mean slippage delta should be ~+2 bps.
        self.assertAlmostEqual(agg["mean_slippage_delta_bps"], 2.0,
                                places=2)
        # Within tolerance band of 5 bps.
        self.assertEqual(agg["status"], self.fmc.WITHIN_TOLERANCE)


class TestNoRuntimeMutation(_Base):
    """Calibration must never claim it mutated runtime."""

    def test_calibration_does_not_mutate_runtime_flag(self):
        n = self.fmc.MIN_PAIRED_OBSERVATIONS
        pairs = [self._pair() for _ in range(n)]
        rep = self.fmc.build_calibration_report(pairs)
        self.assertIs(rep["mutates_runtime"], False)
        self.assertIs(rep["non_auto_apply"], True)
        # Spec: evidence source is PAPER (not BACKTEST/REPLAY).
        self.assertEqual(rep["evidence_source"], "PAPER")


class TestHighSlippageWarning(_Base):
    def test_high_slippage_warning_emitted_at_threshold(self):
        n = self.fmc.MIN_PAIRED_OBSERVATIONS
        # Construct pairs whose actual slippage exceeds the shadow
        # estimate by the WARN threshold (15 bps).
        warn_bps = self.fmc.HIGH_SLIPPAGE_WARN_BPS
        pairs = [
            self._pair(
                shadow_slip_bps=5.0,
                actual_slip_bps=5.0 + warn_bps,
            )
            for _ in range(n)
        ]
        rep = self.fmc.build_calibration_report(pairs)
        self.assertEqual(rep["aggregate"]["status"],
                         self.fmc.MODEL_DRIFT_HIGH)
        self.assertTrue(rep["aggregate"]["warning"])

    def test_no_warning_below_threshold(self):
        n = self.fmc.MIN_PAIRED_OBSERVATIONS
        pairs = [self._pair() for _ in range(n)]
        rep = self.fmc.build_calibration_report(pairs)
        self.assertFalse(rep["aggregate"]["warning"])


class TestReportRenderable(_Base):
    def test_calibration_report_generated(self):
        n = self.fmc.MIN_PAIRED_OBSERVATIONS
        pairs = [self._pair() for _ in range(n)]
        rep = self.fmc.build_calibration_report(pairs)
        md = self.fmc.render_report_markdown(rep)
        self.assertIn("Fill model calibration", md)
        self.assertIn("mutates_runtime: False", md)
        self.assertIn("non_auto_apply: True", md)
        # JSON serialisable.
        json.dumps(rep, default=str, sort_keys=True)


class TestPerKeyGroups(_Base):
    def test_by_symbol_breakdown(self):
        n = self.fmc.MIN_PAIRED_OBSERVATIONS
        pairs = [self._pair(sym="AAPL") for _ in range(n)]
        pairs += [self._pair(sym="MSFT") for _ in range(n)]
        rep = self.fmc.build_calibration_report(pairs)
        self.assertIn("AAPL", rep["by_symbol"])
        self.assertIn("MSFT", rep["by_symbol"])

    def test_invalid_pairs_are_silently_dropped(self):
        n = self.fmc.MIN_PAIRED_OBSERVATIONS
        bad = [{"symbol": "X"}] * 5   # missing prices
        good = [self._pair() for _ in range(n)]
        rep = self.fmc.build_calibration_report(bad + good)
        self.assertEqual(rep["n_pairs_in"], n + 5)
        self.assertEqual(rep["n_pairs_valid"], n)


if __name__ == "__main__":
    unittest.main()
