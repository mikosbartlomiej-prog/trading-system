"""v3.19.0 (2026-06-04) — Tests for shared/strategy_disable_rules.py.

Covers:
  - Each individual rule fires correctly on synthetic input
  - Multiple rules combine to highest severity
  - KEEP returned when no rule triggered
  - MANUAL_REVIEW_REQUIRED beats DEGRADE
  - DISABLE_CANDIDATE beats DEGRADE
  - evaluate_disable_rules NEVER raises
  - All triggered_rules listed in output
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))

# Reload to avoid stale state.
for _mod in ("strategy_disable_rules", "shared.strategy_disable_rules"):
    if _mod in sys.modules:
        del sys.modules[_mod]
import strategy_disable_rules as sdr   # type: ignore  # noqa: E402


class _Base(unittest.TestCase):
    def _eval(self, **kw):
        return sdr.evaluate_disable_rules(
            strategy=kw.pop("strategy", "S1"),
            metrics=kw.pop("metrics", {}),
            recent_violations=kw.pop("recent_violations", 0),
            calibration_quality=kw.pop("calibration_quality", "unknown"),
            instrument_breakdown=kw.pop("instrument_breakdown", None),
            emit_audit=False,
        )


# ─── KEEP on healthy metrics ─────────────────────────────────────────────────

class TestKeep(_Base):

    def test_keep_when_no_rule_triggered(self):
        m = {
            "n_closed":      15,
            "win_rate":      0.55,
            "profit_factor": 1.2,
            "expectancy_after_fees": 5.0,
            "max_drawdown":  0.15,
            "avg_slippage_bps": 5.0,
            "rejected_signals_pct": 0.1,
            "last_20_win_rate": 0.55,
        }
        out = self._eval(metrics=m)
        self.assertEqual(out["recommendation"], sdr.KEEP)
        self.assertEqual(out["triggered_rules"], [])


# ─── Individual rules ────────────────────────────────────────────────────────

class TestIndividualRules(_Base):

    def test_low_win_rate_fires(self):
        m = {"n_closed": 25, "win_rate": 0.20, "profit_factor": 1.5,
             "expectancy_after_fees": 5.0, "max_drawdown": 0.05}
        out = self._eval(metrics=m)
        self.assertIn("low_win_rate", out["triggered_rules"])
        self.assertEqual(out["recommendation"], sdr.DEGRADE)

    def test_low_profit_factor_fires_disable(self):
        m = {"n_closed": 35, "win_rate": 0.45, "profit_factor": 0.60,
             "expectancy_after_fees": 1.0, "max_drawdown": 0.10}
        out = self._eval(metrics=m)
        self.assertIn("low_profit_factor", out["triggered_rules"])
        self.assertEqual(out["recommendation"], sdr.DISABLE_CANDIDATE)

    def test_negative_expectancy_after_fees_fires(self):
        m = {"n_closed": 10, "win_rate": 0.40,
             "profit_factor": 1.05,
             "expectancy_after_fees": -3.0,
             "max_drawdown": 0.10}
        out = self._eval(metrics=m)
        self.assertIn("negative_expectancy_after_fees",
                      out["triggered_rules"])
        self.assertEqual(out["recommendation"], sdr.DEGRADE)

    def test_max_drawdown_fires(self):
        m = {"n_closed": 10, "win_rate": 0.55,
             "profit_factor": 1.10,
             "expectancy_after_fees": 4.0,
             "max_drawdown_pct": 45.0}
        out = self._eval(metrics=m)
        self.assertIn("max_drawdown", out["triggered_rules"])
        self.assertEqual(out["recommendation"], sdr.DEGRADE)

    def test_risk_violations_force_manual_review(self):
        m = {"n_closed": 10, "win_rate": 0.55,
             "profit_factor": 1.10,
             "expectancy_after_fees": 4.0,
             "max_drawdown": 0.10}
        out = self._eval(metrics=m, recent_violations=1)
        self.assertIn("risk_violations", out["triggered_rules"])
        self.assertEqual(out["recommendation"], sdr.MANUAL_REVIEW_REQUIRED)

    def test_uncalibrated_fires_degrade(self):
        m = {"n_closed": 10, "win_rate": 0.55,
             "profit_factor": 1.10,
             "expectancy_after_fees": 4.0,
             "max_drawdown": 0.10}
        out = self._eval(metrics=m, calibration_quality="uncalibrated")
        self.assertIn("calibration_quality", out["triggered_rules"])
        self.assertEqual(out["recommendation"], sdr.DEGRADE)

    def test_single_instr_concentration_manual_review(self):
        m = {"n_closed": 30, "win_rate": 0.55,
             "profit_factor": 1.10,
             "expectancy_after_fees": 4.0,
             "max_drawdown": 0.10}
        out = self._eval(metrics=m,
                          instrument_breakdown={
                              "AAPL": {"n_closed": 28},
                              "MSFT": {"n_closed": 2},
                          })
        self.assertIn("instrument_concentration", out["triggered_rules"])
        self.assertEqual(out["recommendation"], sdr.MANUAL_REVIEW_REQUIRED)

    def test_high_slippage_fires(self):
        m = {"n_closed": 10, "win_rate": 0.55,
             "profit_factor": 1.10,
             "expectancy_after_fees": 4.0,
             "max_drawdown": 0.10,
             "avg_slippage_bps": 75.0}
        out = self._eval(metrics=m)
        self.assertIn("high_slippage", out["triggered_rules"])
        self.assertEqual(out["recommendation"], sdr.DEGRADE)

    def test_rejected_signals_fires(self):
        m = {"n_closed": 10, "win_rate": 0.55,
             "profit_factor": 1.10,
             "expectancy_after_fees": 4.0,
             "max_drawdown": 0.10,
             "rejected_signals_pct": 0.55}
        out = self._eval(metrics=m)
        self.assertIn("rejected_signals", out["triggered_rules"])
        self.assertEqual(out["recommendation"], sdr.DEGRADE)

    def test_recent_degradation_fires(self):
        m = {"n_closed": 25, "win_rate": 0.55,
             "profit_factor": 1.10,
             "expectancy_after_fees": 4.0,
             "max_drawdown": 0.10,
             "last_20_win_rate": 0.15}
        out = self._eval(metrics=m)
        self.assertIn("recent_degradation", out["triggered_rules"])
        self.assertEqual(out["recommendation"], sdr.DEGRADE)


# ─── Combined severity ─────────────────────────────────────────────────────

class TestCombinedSeverity(_Base):

    def test_manual_review_beats_degrade(self):
        m = {"n_closed": 25, "win_rate": 0.25,  # → low_win_rate (DEGRADE)
             "profit_factor": 1.10,
             "expectancy_after_fees": 4.0,
             "max_drawdown": 0.10}
        out = self._eval(metrics=m, recent_violations=2)
        # MANUAL_REVIEW_REQUIRED should win.
        self.assertEqual(out["recommendation"], sdr.MANUAL_REVIEW_REQUIRED)
        self.assertIn("risk_violations", out["triggered_rules"])
        self.assertIn("low_win_rate", out["triggered_rules"])

    def test_disable_beats_degrade(self):
        m = {"n_closed": 35, "win_rate": 0.25,
             "profit_factor": 0.50,           # → DISABLE_CANDIDATE
             "expectancy_after_fees": -10.0,  # → DEGRADE
             "max_drawdown": 0.10}
        out = self._eval(metrics=m)
        self.assertEqual(out["recommendation"], sdr.DISABLE_CANDIDATE)
        self.assertIn("low_profit_factor", out["triggered_rules"])
        self.assertIn("negative_expectancy_after_fees",
                      out["triggered_rules"])


# ─── Robustness ─────────────────────────────────────────────────────────────

class TestRobustness(_Base):

    def test_never_raises_on_bad_input(self):
        # Even with garbage everywhere, returns a dict with KEEP / safe values.
        out = sdr.evaluate_disable_rules(
            strategy=None,            # type: ignore
            metrics="not-a-dict",     # type: ignore
            recent_violations="bad",  # type: ignore
            calibration_quality=None, # type: ignore
            instrument_breakdown=42,  # type: ignore
            emit_audit=False,
        )
        self.assertIsInstance(out, dict)
        self.assertIn(out["recommendation"], (
            sdr.KEEP, sdr.OBSERVE, sdr.DEGRADE,
            sdr.DISABLE_CANDIDATE, sdr.MANUAL_REVIEW_REQUIRED,
        ))
        self.assertIn("triggered_rules", out)
        self.assertIn("rationale", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
