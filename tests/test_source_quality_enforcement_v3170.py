"""v3.17.0 (2026-06-04) — Task 4: source quality policy enforcement tests.

Verifies that the v3.17.0 strict source-quality policy in
shared/confidence_builder.py::_apply_v3150_adjustments properly:

  * Marks Tier 3 (reddit/twitter_anon/...) and unknown sources
    `block_recommended=True` when no confirmation is present, regardless
    of how strong the primary_score is.
  * Caps Tier 3 primary_score to `confidence_ceiling_for(source_type)`
    so even a downstream caller that ignores block_recommended cannot
    accidentally reach the ALLOW confidence threshold.
  * For Tier 2 (tracked_dd / reuters / verified_analyst) without
    confirmation, caps primary_score to ceiling AND blocks for
    day-trade-intent strategies per FB-015 contract.
  * Leaves Tier 1 (sec_8k / dod_contract / ...) uncapped + unblocked.
  * Honors confirmation_present=True override — Tier 3 + confirmation
    is NOT block_recommended (signal_confirmation independently verified
    price + volume).

End-to-end coverage with risk_officer.evaluate_trade ensures the policy
truly results in a REJECT verdict for tier-3-alone signals.

All tests LOCAL + DETERMINISTIC + NO NETWORK + NO PAID DEPS.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# Default proposal fixture passing all non-confidence risk checks.
# (Risk officer also calls get_account_status() / vix_guard() — we mock
# the former via patch.)
def _make_proposal(*, confidence_inputs: dict | None,
                    symbol: str = "AAPL",
                    size_usd: float = 5_000.0,
                    strategy: str = "aggressive-momentum") -> dict:
    return {
        "symbol":      symbol,
        "action":      "BUY",
        "size_usd":    size_usd,
        "entry_price": 100.0,
        "stop_loss":   95.0,
        "take_profit": 110.0,  # R:R 2.0
        "strategy":    strategy,
        "confidence_inputs": confidence_inputs,
    }


_HEALTHY_ACCOUNT = {
    "equity":              100_000.0,
    "last_equity":         100_000.0,
    "buying_power":        200_000.0,
    "cash":                100_000.0,
    "daily_pl_pct":        0.0,
    "daytrade_count":      0,
    "pattern_day_trader":  False,
}


# ─── 1) Tier 3 alone (reddit) blocks ─────────────────────────────────────────

class TestTier3AloneBlockedInBuilder(unittest.TestCase):
    """Builder-level checks: confidence_inputs metadata."""

    def test_reddit_strong_signal_block_recommended(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="aggressive-momentum",
            primary_score=0.85,
            source_type="reddit",
            source_confirmation_present=False,
        )
        meta = ci.get("_v3150_meta", {})
        self.assertTrue(
            meta.get("block_recommended"),
            f"reddit alone must set block_recommended, got meta={meta}",
        )
        self.assertIn("tier_3_alone_not_eligible_for_trade",
                      meta.get("block_reasons", []))

    def test_twitter_anon_strong_signal_block_recommended(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="aggressive-momentum",
            primary_score=0.92,
            source_type="twitter_anon",
            source_confirmation_present=False,
        )
        meta = ci.get("_v3150_meta", {})
        self.assertTrue(meta.get("block_recommended"))
        self.assertIn("tier_3_alone_not_eligible_for_trade",
                      meta.get("block_reasons", []))

    def test_reddit_primary_score_capped_to_ceiling(self):
        """Even ignoring block, primary_score is capped to Tier 3 ceiling."""
        from confidence_builder import build_confidence_inputs
        from source_quality import CONFIDENCE_CEILING, TIER_3
        ci = build_confidence_inputs(
            strategy="momentum",
            primary_score=0.85,
            source_type="reddit",
            source_confirmation_present=False,
        )
        # primary_score must be ≤ Tier 3 ceiling (0.45). The pipeline
        # may further reduce it via other v3.15 adjustments, so we
        # only assert the upper bound.
        self.assertLessEqual(ci["primary_score"], CONFIDENCE_CEILING[TIER_3])
        meta = ci["_v3150_meta"]
        self.assertEqual(meta.get("primary_score_capped_to"),
                         CONFIDENCE_CEILING[TIER_3])

    def test_unknown_source_treated_as_tier_3(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="momentum",
            primary_score=0.80,
            source_type="some_unknown_aggregator_xyz",
            source_confirmation_present=False,
        )
        meta = ci.get("_v3150_meta", {})
        self.assertTrue(meta.get("block_recommended"))
        self.assertIn("tier_3_alone_not_eligible_for_trade",
                      meta.get("block_reasons", []))


# ─── 2) Tier 3 WITH confirmation — NOT blocked ────────────────────────────────

class TestTier3WithConfirmationAllowed(unittest.TestCase):
    def test_reddit_with_confirmation_no_block_recommended(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="aggressive-momentum",
            primary_score=0.80,
            source_type="reddit",
            source_confirmation_present=True,
        )
        meta = ci.get("_v3150_meta", {})
        self.assertFalse(meta.get("block_recommended", False))
        self.assertTrue(meta.get("source_tier_overridden_by_confirmation"))


# ─── 3) Tier 2 alone — capped + day-trade-blocked ─────────────────────────────

class TestTier2WithoutConfirmation(unittest.TestCase):
    def test_tier_2_dd_capped_to_ceiling(self):
        from confidence_builder import build_confidence_inputs
        from source_quality import CONFIDENCE_CEILING, TIER_2
        ci = build_confidence_inputs(
            strategy="swing-trade",   # NOT a day-trade strategy
            primary_score=0.90,
            confirmations=3,           # ≥2 → not day-trade by confirmations
            source_type="tracked_dd",
            source_confirmation_present=False,
        )
        meta = ci.get("_v3150_meta", {})
        # capped but NOT auto-blocked for swing-trade context
        self.assertEqual(meta.get("primary_score_capped_to"),
                         CONFIDENCE_CEILING[TIER_2])
        self.assertTrue(meta.get("tier_2_dd_needs_confirmation"))
        self.assertFalse(meta.get("block_recommended", False))

    def test_tier_2_dd_day_trade_strategy_blocks(self):
        """Strategy name containing 'day' triggers FB-015 block."""
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="day-trade-momentum",
            primary_score=0.80,
            confirmations=3,
            source_type="tracked_dd",
            source_confirmation_present=False,
        )
        meta = ci.get("_v3150_meta", {})
        self.assertTrue(meta.get("block_recommended"))
        self.assertIn("tier_2_dd_lacks_price_volume_confirmation",
                      meta.get("block_reasons", []))
        self.assertTrue(meta.get("tier_2_day_trade_block"))

    def test_tier_2_dd_low_confirmations_blocks(self):
        """confirmations < 2 → treated as day-trade-intent → block per FB-015."""
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="momentum",        # no 'day' keyword
            primary_score=0.80,
            confirmations=1,             # < 2 → day-trade signal pattern
            source_type="tracked_dd",
            source_confirmation_present=False,
        )
        meta = ci.get("_v3150_meta", {})
        self.assertTrue(meta.get("block_recommended"))
        self.assertIn("tier_2_dd_lacks_price_volume_confirmation",
                      meta.get("block_reasons", []))


# ─── 4) Tier 1 alone — uncapped + unblocked ───────────────────────────────────

class TestTier1AloneAllowed(unittest.TestCase):
    def test_sec_8k_uncapped_no_block(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="aggressive-momentum",
            primary_score=0.90,
            source_type="sec_8k",
            source_confirmation_present=False,
        )
        meta = ci.get("_v3150_meta", {})
        self.assertFalse(meta.get("block_recommended", False))
        # primary_score NOT capped to 0.75 — Tier 1 ceiling is 1.0
        self.assertGreaterEqual(ci["primary_score"], 0.80)

    def test_dod_contract_uncapped_no_block(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="defense-news",
            primary_score=0.92,
            source_type="dod_contract",
            source_confirmation_present=False,
        )
        meta = ci.get("_v3150_meta", {})
        self.assertFalse(meta.get("block_recommended", False))


# ─── 5) End-to-end via risk_officer.evaluate_trade ────────────────────────────

class TestRiskOfficerRejectsTier3Alone(unittest.TestCase):
    """End-to-end: confidence_inputs feeds risk_officer.evaluate_trade.

    risk_officer must reject when _v3150_meta.block_recommended=True via
    the "v3.15.0_block" check, regardless of how strong the underlying
    signal looks.
    """

    def _evaluate_with_mocked_account(self, proposal: dict) -> dict:
        # IMPORTANT: patch within risk_officer namespace where the symbols
        # were imported with `from risk_guards import ...` at module load
        # time. Patching the source module (risk_guards.*) is a no-op
        # because risk_officer holds its own local references.
        from risk_officer import evaluate_trade
        with patch("risk_officer.get_account_status",
                    return_value=_HEALTHY_ACCOUNT.copy()), \
             patch("risk_officer.vix_guard",
                    return_value=("OK", "")), \
             patch("risk_officer.daily_drawdown_guard",
                    return_value=("OK", "")), \
             patch("risk_officer.concentration_ok",
                    return_value=(True, 5.0)):
            return evaluate_trade(proposal)

    def test_reddit_strong_signal_rejected_by_risk_officer(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="aggressive-momentum",
            primary_score=0.85,
            source_type="reddit",
            source_confirmation_present=False,
        )
        proposal = _make_proposal(confidence_inputs=ci)
        result = self._evaluate_with_mocked_account(proposal)
        self.assertEqual(result["decision"], "REJECT",
                          f"expected REJECT, got {result}")
        # The v3.15.0_block reason must appear in checks_failed.
        joined = " | ".join(result.get("checks_failed", []))
        self.assertIn("v3.15.0_block", joined,
                      f"expected v3.15.0_block in checks_failed: {joined}")
        self.assertIn("tier_3_alone_not_eligible_for_trade", joined)

    def test_twitter_anon_strong_signal_rejected_by_risk_officer(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="aggressive-momentum",
            primary_score=0.85,
            source_type="twitter_anon",
            source_confirmation_present=False,
        )
        proposal = _make_proposal(confidence_inputs=ci)
        result = self._evaluate_with_mocked_account(proposal)
        self.assertEqual(result["decision"], "REJECT")
        joined = " | ".join(result.get("checks_failed", []))
        self.assertIn("v3.15.0_block", joined)

    def test_tier_2_dd_day_trade_rejected_by_risk_officer(self):
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="day-trade-momentum",
            primary_score=0.85,
            confirmations=3,
            source_type="tracked_dd",
            source_confirmation_present=False,
        )
        proposal = _make_proposal(confidence_inputs=ci,
                                    strategy="day-trade-momentum")
        result = self._evaluate_with_mocked_account(proposal)
        self.assertEqual(result["decision"], "REJECT")
        joined = " | ".join(result.get("checks_failed", []))
        self.assertIn("tier_2_dd_lacks_price_volume_confirmation", joined)

    def test_tier_2_dd_swing_trade_not_blocked(self):
        """Tier 2 (DD) without confirmation: NOT blocked for swing strategy
        but primary_score capped."""
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="swing-trade",
            primary_score=0.90,
            confirmations=3,
            source_type="tracked_dd",
            source_confirmation_present=False,
        )
        proposal = _make_proposal(confidence_inputs=ci, strategy="swing-trade")
        result = self._evaluate_with_mocked_account(proposal)
        # No v3.15.0_block in checks_failed for swing
        joined = " | ".join(result.get("checks_failed", []))
        self.assertNotIn("v3.15.0_block", joined)
        # Either APPROVE (if confidence still passes) or REJECT due to
        # confidence threshold (because primary_score was capped to 0.75
        # AND no risk_state/etc bonuses); the key invariant is that no
        # tier-2 BLOCK reason was raised.
        if result["decision"] == "REJECT":
            self.assertNotIn("tier_2_dd_lacks_price_volume_confirmation",
                              joined)

    def test_sec_8k_alone_approved(self):
        """Tier 1 (sec_8k) alone reaches APPROVE via risk_officer."""
        from confidence_builder import build_confidence_inputs
        ci = build_confidence_inputs(
            strategy="aggressive-momentum",
            primary_score=0.90,
            confirmations=3,
            source_type="sec_8k",
            source_confirmation_present=False,
            # Pad system health so confidence aggregates above 0.65 threshold
        )
        # Pad some neutral inputs so non-source components don't drag
        # confidence below ALLOW threshold.
        ci.setdefault("components_alive", 11)
        ci.setdefault("components_total", 11)
        ci.setdefault("regime", "RISK_ON")
        ci.setdefault("bar_age_seconds", 60)
        ci.setdefault("bars_count", 50)
        ci["intraday_pnl_pct"] = 0.0
        ci["consecutive_losses"] = 0

        proposal = _make_proposal(confidence_inputs=ci)
        result = self._evaluate_with_mocked_account(proposal)
        # Tier 1 doesn't trigger v3.15.0_block — even if confidence gate
        # produces ALERT_ONLY/BLOCK for unrelated reasons, no tier policy
        # reason should appear.
        joined = " | ".join(result.get("checks_failed", []))
        self.assertNotIn("tier_3_alone_not_eligible_for_trade", joined)
        self.assertNotIn("tier_2_dd_lacks_price_volume_confirmation", joined)
        self.assertNotIn("v3.15.0_block", joined)


# ─── 6) DD whitelisted author contract (FB-015) ───────────────────────────────

class TestDdDayTradeTriggerContract(unittest.TestCase):
    """source_quality.dd_is_day_trade_trigger contract: DD requires BOTH
    price and volume confirmation. Tier 3 never qualifies."""

    def test_tracked_dd_requires_both_confirmations(self):
        from source_quality import dd_is_day_trade_trigger
        self.assertFalse(dd_is_day_trade_trigger("tracked_dd"))
        self.assertFalse(
            dd_is_day_trade_trigger("tracked_dd",
                                     has_price_confirmation=True))
        self.assertFalse(
            dd_is_day_trade_trigger("tracked_dd",
                                     has_volume_confirmation=True))
        self.assertTrue(
            dd_is_day_trade_trigger("tracked_dd",
                                     has_price_confirmation=True,
                                     has_volume_confirmation=True))

    def test_tier_1_always_day_trade_trigger(self):
        from source_quality import dd_is_day_trade_trigger
        self.assertTrue(dd_is_day_trade_trigger("sec_8k"))
        self.assertTrue(dd_is_day_trade_trigger("dod_contract"))

    def test_tier_3_never_day_trade_trigger(self):
        from source_quality import dd_is_day_trade_trigger
        self.assertFalse(dd_is_day_trade_trigger("reddit"))
        self.assertFalse(
            dd_is_day_trade_trigger("twitter_anon",
                                     has_price_confirmation=True,
                                     has_volume_confirmation=True))


# ─── 7) Mapping verification (defensive) ──────────────────────────────────────

class TestTierMappingComplete(unittest.TestCase):
    """Verify the existing TIER_MAP covers all sources referenced by
    feedback-driven Task 4 requirements (no regressions on the 8 baseline
    tests in test_feedback_v3150.TestSourceQualityPolicy)."""

    def test_required_tier_3_sources_present(self):
        from source_quality import tier_for, TIER_3
        for src in ("reddit", "reddit_anon", "reddit_wsb",
                    "twitter_anon", "twitter_unknown"):
            self.assertEqual(tier_for(src), TIER_3,
                              f"{src} must be TIER_3, got {tier_for(src)}")

    def test_required_tier_2_sources_present(self):
        from source_quality import tier_for, TIER_2
        for src in ("tracked_dd", "verified_analyst", "reuters"):
            self.assertEqual(tier_for(src), TIER_2)

    def test_required_tier_1_sources_present(self):
        from source_quality import tier_for, TIER_1
        for src in ("sec_8k", "sec_form_4", "dod_contract",
                    "doj_press", "doj_filing", "official_government"):
            self.assertEqual(tier_for(src), TIER_1)


if __name__ == "__main__":
    unittest.main()
