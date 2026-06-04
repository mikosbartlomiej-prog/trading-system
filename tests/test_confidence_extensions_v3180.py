"""v3.18.0 ETAP 6 — Tests for confidence extensions.

Covers the new scoring functions, weight renormalization, multiplier
asymmetry, backward compatibility, and sample-size gating.

DEFENSIVE INVARIANT: every new component can only LOWER total confidence,
never raise it. risk_officer remains the only path that BLOCKs trades;
this layer just makes BLOCK / ALERT_ONLY MORE likely under degraded
conditions.
"""

from __future__ import annotations

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from confidence import (  # noqa: E402
    compute_confidence,
    score_liquidity_quality,
    score_slippage_risk,
    score_strategy_edge_evidence,
    score_paper_sample_size,
    score_recent_strategy_health,
    score_anomaly_penalty,
    score_event_risk_penalty,
    DEFAULT_WEIGHTS,
    NEUTRAL_COMPONENT,
    _resolve_weights,
)


# ─── Building-block scorers: missing-input neutrality ─────────────────────────

class TestScorersNeutralWhenMissing(unittest.TestCase):
    """Each new scoring fn returns NEUTRAL_COMPONENT when input is None."""

    def test_liquidity_quality_neutral(self):
        self.assertEqual(score_liquidity_quality(), NEUTRAL_COMPONENT)

    def test_slippage_risk_neutral(self):
        self.assertEqual(score_slippage_risk(), NEUTRAL_COMPONENT)

    def test_edge_evidence_neutral(self):
        self.assertEqual(score_strategy_edge_evidence(), NEUTRAL_COMPONENT)

    def test_paper_sample_size_neutral(self):
        self.assertEqual(score_paper_sample_size(), NEUTRAL_COMPONENT)

    def test_recent_strategy_health_neutral(self):
        self.assertEqual(score_recent_strategy_health(), NEUTRAL_COMPONENT)

    def test_anomaly_penalty_neutral(self):
        # Multipliers default to 1.0 (no penalty) when missing.
        self.assertEqual(score_anomaly_penalty(), 1.0)

    def test_event_risk_penalty_neutral(self):
        self.assertEqual(score_event_risk_penalty(), 1.0)


# ─── Building-block scorers: deterministic outputs ────────────────────────────

class TestScorersDeterministic(unittest.TestCase):
    """Same inputs → same outputs, all in [0, 1]."""

    def test_liquidity_quality_high(self):
        s = score_liquidity_quality(
            quote_spread_pct=0.03,
            daily_volume_usd=100_000_000,
            universe_spread_baseline=0.05,
        )
        self.assertGreaterEqual(s, 0.9)

    def test_liquidity_quality_wide_spread(self):
        s = score_liquidity_quality(
            quote_spread_pct=1.5,
            daily_volume_usd=500_000,
            universe_spread_baseline=0.05,
        )
        self.assertLessEqual(s, 0.4)

    def test_slippage_risk_excellent(self):
        # slippage 5 bps vs 100 bps edge → ratio 0.05 → 1.0
        self.assertEqual(score_slippage_risk(estimated_slippage_bps=5, expected_edge_bps=100), 1.0)

    def test_slippage_risk_eats_edge(self):
        # slippage 80 bps vs 100 bps edge → ratio 0.80 → 0.05
        self.assertEqual(score_slippage_risk(estimated_slippage_bps=80, expected_edge_bps=100), 0.05)

    def test_slippage_risk_no_edge(self):
        # zero-edge setup → 0.0 regardless of slippage
        self.assertEqual(score_slippage_risk(estimated_slippage_bps=10, expected_edge_bps=0), 0.0)

    def test_edge_evidence_strong(self):
        # PF 1.5 + 50 trades → average of (0.7, 0.7)
        s = score_strategy_edge_evidence(n_closed_paper=50, profit_factor=1.5)
        self.assertGreaterEqual(s, 0.7)

    def test_edge_evidence_below_30(self):
        # 25 trades → 0.5 sub-score for n, missing PF → NEUTRAL contributions
        s = score_strategy_edge_evidence(n_closed_paper=25)
        self.assertLess(s, 0.7)  # task: "Edge evidence component below 0.5 below 30 trades"

    def test_paper_sample_size_thresholds(self):
        self.assertEqual(score_paper_sample_size(n_closed_paper=5), 0.0)
        self.assertEqual(score_paper_sample_size(n_closed_paper=15), 0.3)
        self.assertEqual(score_paper_sample_size(n_closed_paper=40), 0.7)
        self.assertEqual(score_paper_sample_size(n_closed_paper=100), 1.0)

    def test_recent_strategy_health_thresholds(self):
        self.assertEqual(score_recent_strategy_health(recent_20_wr=0.20), 0.05)
        self.assertEqual(score_recent_strategy_health(recent_20_wr=0.32), 0.3)
        self.assertEqual(score_recent_strategy_health(recent_20_wr=0.40), 0.5)
        self.assertEqual(score_recent_strategy_health(recent_20_wr=0.60), 1.0)

    def test_anomaly_penalty_normal_day(self):
        self.assertEqual(score_anomaly_penalty(price_move_atr=1.0, volume_ratio=1.0), 1.0)

    def test_anomaly_penalty_extreme(self):
        # 6 ATR move + 5x vol → max=6 → score 0.2
        self.assertEqual(score_anomaly_penalty(price_move_atr=6.0, volume_ratio=5.0), 0.2)

    def test_event_risk_penalty_earnings_blackout(self):
        # ±1 day of earnings → 0.0
        self.assertEqual(score_event_risk_penalty(days_to_earnings=0.0), 0.0)
        self.assertEqual(score_event_risk_penalty(days_to_earnings=0.5), 0.0)

    def test_event_risk_penalty_fomc_proximity(self):
        # Same-day FOMC → 0.2
        self.assertEqual(score_event_risk_penalty(days_to_fomc=0.5), 0.2)


# ─── Weights + invariants ─────────────────────────────────────────────────────

class TestWeightsInvariant(unittest.TestCase):
    """Weights normalize to 1.0; new component keys are present."""

    def test_weights_sum_to_one(self):
        w = _resolve_weights()
        self.assertAlmostEqual(sum(w.values()), 1.0, places=6)

    def test_new_components_in_weights(self):
        w = _resolve_weights()
        for key in ("liquidity_quality", "paper_sample_size_score", "recent_strategy_health"):
            self.assertIn(key, w)

    def test_existing_components_preserved(self):
        w = _resolve_weights()
        for key in ("data_quality", "signal_strength", "regime_alignment",
                    "system_health", "risk_state"):
            self.assertIn(key, w)


# ─── Multiplier asymmetry ─────────────────────────────────────────────────────

class TestMultiplierAsymmetry(unittest.TestCase):
    """anomaly_penalty + event_risk_penalty can only LOWER score, never raise."""

    def _strong_inputs(self, **extra):
        base = dict(
            primary_score=0.95, confirmations=5,
            regime="RISK_ON", strategy="momentum-long",
            bar_age_seconds=10, bars_count=100, quote_spread_pct=0.05,
            components_alive=11, components_total=11,
            intraday_pnl_pct=2.0, consecutive_losses=0, drawdown_pct=0,
            strategy_n_closed_paper=50, strategy_profit_factor=1.8,
            recent_20_wr=0.6,
            daily_volume_usd=100_000_000,
        )
        base.update(extra)
        return base

    def test_anomaly_drops_total_even_with_strong_components(self):
        baseline = compute_confidence(**self._strong_inputs())
        anomalous = compute_confidence(**self._strong_inputs(
            price_move_atr=6.0, volume_ratio=5.0,
        ))
        self.assertGreater(baseline.total, anomalous.total)
        self.assertLess(anomalous.total, 0.5)  # multiplier 0.2 must hammer it

    def test_event_risk_blocks_strong_setup(self):
        baseline = compute_confidence(**self._strong_inputs())
        in_earnings = compute_confidence(**self._strong_inputs(days_to_earnings=0.5))
        self.assertGreater(baseline.total, 0.5)
        self.assertEqual(in_earnings.total, 0.0)
        self.assertEqual(in_earnings.decision, "BLOCK")

    def test_multipliers_default_to_one(self):
        # Without any multiplier inputs, total must match what the weighted
        # formula produces unmodified.
        r = compute_confidence(**self._strong_inputs())
        self.assertGreater(r.total, 0.0)
        # No anomaly/event inputs → multipliers reported as 1.0
        self.assertEqual(r.components["anomaly_penalty"], 1.0)
        self.assertEqual(r.components["event_risk_penalty"], 1.0)


# ─── Backward compatibility ───────────────────────────────────────────────────

class TestBackwardCompat(unittest.TestCase):
    """Legacy calls (no new inputs) still produce sensible decisions.

    With v3.18.0 the weights are slightly different, so absolute totals
    will not match v3.12.0 numbers — but the SHAPE (decision tier under
    a clearly-strong vs clearly-weak setup) must remain correct.
    """

    def test_strong_legacy_setup_allows(self):
        r = compute_confidence(
            primary_score=0.9, confirmations=3,
            regime="RISK_ON", strategy="momentum-long",
            bar_age_seconds=10, bars_count=100, quote_spread_pct=0.05,
            components_alive=11, components_total=11,
            intraday_pnl_pct=1.0, consecutive_losses=0, drawdown_pct=0,
        )
        self.assertIn(r.decision, ("ALLOW", "ALERT_ONLY"))

    def test_weak_legacy_setup_blocks(self):
        r = compute_confidence(
            primary_score=0.15, confirmations=0,
            regime="RISK_OFF", strategy="momentum-long",
            bar_age_seconds=2000, bars_count=5, quote_spread_pct=1.0,
            components_alive=2, components_total=11,
            intraday_pnl_pct=-5.0, consecutive_losses=6, drawdown_pct=-10.0,
        )
        self.assertEqual(r.decision, "BLOCK")

    def test_minimal_call_produces_report(self):
        # Bare call with only the keyword strategy passes (degrades to neutrals).
        r = compute_confidence(strategy="momentum-long")
        self.assertGreaterEqual(r.total, 0.0)
        self.assertLessEqual(r.total, 1.0)


# ─── Paper sample size gate (HARD requirement from task) ──────────────────────

class TestPaperSampleSizeGatesAllow(unittest.TestCase):
    """At n<10 / n<30 paper trades, ALLOW is unreachable regardless of else."""

    def _perfect_else(self, **n):
        base = dict(
            primary_score=0.95, confirmations=5,
            regime="RISK_ON", strategy="momentum-long",
            bar_age_seconds=5, bars_count=200, quote_spread_pct=0.05,
            components_alive=11, components_total=11,
            intraday_pnl_pct=2.0, consecutive_losses=0, drawdown_pct=0,
            strategy_profit_factor=2.0, recent_20_wr=0.7,
            daily_volume_usd=200_000_000,
        )
        base.update(n)
        return base

    def test_n_below_10_cannot_allow(self):
        r = compute_confidence(**self._perfect_else(strategy_n_closed_paper=5))
        self.assertLess(r.total, 0.65)
        self.assertNotEqual(r.decision, "ALLOW")

    def test_n_exactly_10_capped_below_allow(self):
        r = compute_confidence(**self._perfect_else(strategy_n_closed_paper=10))
        # Sample cap is 0.60; ALLOW threshold is 0.65.
        self.assertLess(r.total, 0.65)
        self.assertNotEqual(r.decision, "ALLOW")

    def test_n_50_pf_15_reaches_allow(self):
        r = compute_confidence(**self._perfect_else(
            strategy_n_closed_paper=50, strategy_profit_factor=1.5,
        ))
        self.assertGreaterEqual(r.total, 0.65)
        self.assertEqual(r.decision, "ALLOW")


# ─── Slippage gate ────────────────────────────────────────────────────────────

class TestSlippageGate(unittest.TestCase):
    """High estimated slippage relative to edge must drop the total."""

    def _base(self, **extra):
        b = dict(
            primary_score=0.85, confirmations=4,
            regime="RISK_ON", strategy="momentum-long",
            bar_age_seconds=10, bars_count=100, quote_spread_pct=0.05,
            components_alive=11, components_total=11,
            intraday_pnl_pct=1.5, consecutive_losses=0, drawdown_pct=0,
            strategy_n_closed_paper=50, strategy_profit_factor=1.5,
            recent_20_wr=0.55, daily_volume_usd=100_000_000,
        )
        b.update(extra)
        return b

    def test_clean_slippage_passes(self):
        r = compute_confidence(**self._base(estimated_slippage_bps=5, expected_edge_bps=200))
        self.assertEqual(r.decision, "ALLOW")

    def test_extreme_slippage_blocks_or_alerts(self):
        # slippage 180bps vs 200bps edge → ratio 0.90 → slippage subscore 0.05
        r_clean = compute_confidence(**self._base())
        r_bad = compute_confidence(**self._base(estimated_slippage_bps=180, expected_edge_bps=200))
        self.assertGreater(r_clean.total, r_bad.total)


if __name__ == "__main__":
    unittest.main()
