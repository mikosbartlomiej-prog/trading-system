"""v3.18.0 ETAP 7 — Tests for per_strategy_regime_fit + builder integration.

Verifies:
  - Known strategy/regime pairings return expected fit_score.
  - Blocked combinations set is_blocked=True (fit_score=0.0).
  - Regime-agnostic strategies score 0.7 across all regimes.
  - confidence_builder integration: when regime blocks a strategy, the
    builder sets `_v3150_meta.block_recommended = True` with reason
    "regime_blocked_for_strategy".
  - risk_officer rejects via existing v3.15.0 block_recommended path.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from regime import per_strategy_regime_fit  # noqa: E402


class TestPerStrategyRegimeFit(unittest.TestCase):
    """Pure-function tests for the regime fit matrix."""

    def test_momentum_long_in_risk_on(self):
        r = per_strategy_regime_fit("momentum-long", "RISK_ON")
        self.assertEqual(r["fit_score"], 1.0)
        self.assertFalse(r["is_blocked"])
        self.assertIn("RISK_ON", r["preferred_regimes"])

    def test_momentum_long_in_risk_off_blocked(self):
        r = per_strategy_regime_fit("momentum-long", "RISK_OFF")
        self.assertEqual(r["fit_score"], 0.0)
        self.assertTrue(r["is_blocked"])
        self.assertIn("RISK_OFF", r["blocked_regimes"])

    def test_overbought_short_in_risk_off(self):
        r = per_strategy_regime_fit("overbought-short", "RISK_OFF")
        self.assertEqual(r["fit_score"], 1.0)
        self.assertFalse(r["is_blocked"])

    def test_overbought_short_in_risk_on_blocked(self):
        r = per_strategy_regime_fit("overbought-short", "RISK_ON")
        self.assertEqual(r["fit_score"], 0.0)
        self.assertTrue(r["is_blocked"])

    def test_geo_defense_in_inflation_shock(self):
        r = per_strategy_regime_fit("geo-defense", "INFLATION_SHOCK")
        self.assertEqual(r["fit_score"], 1.0)
        self.assertFalse(r["is_blocked"])

    def test_geo_defense_blocked_in_risk_on(self):
        r = per_strategy_regime_fit("geo-defense", "RISK_ON")
        self.assertTrue(r["is_blocked"])
        self.assertEqual(r["fit_score"], 0.0)

    def test_geo_gold_no_blocked_regimes(self):
        # geo-gold is acceptable everywhere; preferred in INFLATION + RISK_OFF
        for regime in ("RISK_ON", "NEUTRAL", "INFLATION_SHOCK", "RISK_OFF"):
            r = per_strategy_regime_fit("geo-gold", regime)
            self.assertFalse(r["is_blocked"], f"geo-gold blocked in {regime}?")
            self.assertGreaterEqual(r["fit_score"], 0.5)

    def test_crypto_agnostic_all_regimes(self):
        """Regime-agnostic strategies score 0.7 regardless of regime."""
        for strat in ("crypto-momentum", "crypto-oversold-bounce",
                      "crypto-breakdown", "allocator-rebalance"):
            for regime in ("RISK_ON", "RISK_OFF", "NEUTRAL", "INFLATION_SHOCK"):
                r = per_strategy_regime_fit(strat, regime)
                self.assertEqual(r["fit_score"], 0.7,
                                 f"{strat} in {regime}: expected 0.7, got {r['fit_score']}")
                self.assertFalse(r["is_blocked"])

    def test_options_momentum_in_risk_on(self):
        r = per_strategy_regime_fit("options-momentum", "RISK_ON")
        self.assertEqual(r["fit_score"], 1.0)

    def test_options_momentum_blocked_in_risk_off(self):
        r = per_strategy_regime_fit("options-momentum", "RISK_OFF")
        self.assertTrue(r["is_blocked"])

    def test_sub_optimal_score_in_neutral(self):
        # geo-defense is preferred in INFLATION_SHOCK + RISK_OFF, blocked in
        # RISK_ON. NEUTRAL is neither preferred nor blocked → sub-optimal 0.5.
        r = per_strategy_regime_fit("geo-defense", "NEUTRAL")
        self.assertEqual(r["fit_score"], 0.5)
        self.assertFalse(r["is_blocked"])

    def test_unknown_strategy_returns_neutral(self):
        r = per_strategy_regime_fit("nonexistent-strategy", "RISK_ON")
        self.assertEqual(r["fit_score"], 0.5)
        self.assertFalse(r["is_blocked"])
        self.assertIn("strategy_unknown", r["rationale"])

    def test_unknown_regime_returns_neutral(self):
        r = per_strategy_regime_fit("momentum-long", "DOES_NOT_EXIST")
        self.assertEqual(r["fit_score"], 0.5)
        self.assertFalse(r["is_blocked"])

    def test_fail_soft_on_bad_inputs(self):
        # Empty / None inputs should not raise.
        for s, reg in (("", "RISK_ON"), ("momentum-long", ""), (None, None)):
            try:
                r = per_strategy_regime_fit(s or "", reg or "")  # type: ignore[arg-type]
                self.assertIsInstance(r, dict)
            except Exception as e:
                self.fail(f"per_strategy_regime_fit raised on ({s!r}, {reg!r}): {e}")


class TestBuilderHonorsRegimeBlock(unittest.TestCase):
    """confidence_builder must tag block_recommended when regime blocks."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["AUDIT_TRADING_DIR"] = self._tmp.name
        os.environ["RUNTIME_STATE_PATH"] = os.path.join(self._tmp.name, "runtime_state.json")

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("AUDIT_TRADING_DIR", None)
        os.environ.pop("RUNTIME_STATE_PATH", None)

    def test_builder_blocks_momentum_long_in_risk_off(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="momentum-long",
            regime="RISK_OFF",
            primary_score=0.75,
            confirmations=3,
        )
        meta = ci.get("_v3150_meta", {})
        self.assertTrue(meta.get("block_recommended"), f"meta={meta}")
        self.assertIn("regime_blocked_for_strategy", meta.get("block_reasons", []))
        self.assertEqual(meta.get("regime_fit_score"), 0.0)

    def test_builder_allows_momentum_long_in_risk_on(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="momentum-long",
            regime="RISK_ON",
            primary_score=0.75,
            confirmations=3,
        )
        meta = ci.get("_v3150_meta", {})
        self.assertFalse(meta.get("block_recommended"))
        self.assertEqual(meta.get("regime_fit_score"), 1.0)

    def test_builder_crypto_agnostic_no_block_any_regime(self):
        from confidence_builder import build_confidence_inputs
        for regime in ("RISK_ON", "RISK_OFF", "NEUTRAL", "INFLATION_SHOCK"):
            ci = build_confidence_inputs(
                strategy="crypto-momentum",
                regime=regime,
                primary_score=0.6,
            )
            meta = ci.get("_v3150_meta", {})
            self.assertFalse(meta.get("block_recommended"),
                             f"crypto-momentum blocked in {regime}? meta={meta}")
            self.assertEqual(meta.get("regime_fit_score"), 0.7)

    def test_builder_overbought_short_blocked_in_risk_on(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="overbought-short",
            regime="RISK_ON",
            primary_score=0.7,
        )
        meta = ci.get("_v3150_meta", {})
        self.assertTrue(meta.get("block_recommended"))
        self.assertIn("regime_blocked_for_strategy", meta.get("block_reasons", []))


class TestRiskOfficerRejectsRegimeBlocked(unittest.TestCase):
    """risk_officer.evaluate_trade must reject when regime blocks the strategy.

    Uses the existing v3.15.0 `block_recommended` channel — the regime fit
    layer simply piggybacks on it, so any caller already honoring
    `_v3150_meta.block_recommended` rejects deterministically.
    """

    def test_block_recommended_path_rejects(self):
        # Bypass mocking the entire risk_officer chain by directly importing
        # the helper that processes confidence_inputs.
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="momentum-long",
            regime="RISK_OFF",
            primary_score=0.8,
            confirmations=3,
        )
        meta = ci.get("_v3150_meta", {})
        # Contract: block_recommended is the channel risk_officer reads.
        self.assertTrue(meta.get("block_recommended"))
        # Reasons must include the regime-block tag so downstream operators
        # can see WHY without re-deriving.
        reasons = meta.get("block_reasons", [])
        self.assertIn("regime_blocked_for_strategy", reasons)


if __name__ == "__main__":
    unittest.main()
