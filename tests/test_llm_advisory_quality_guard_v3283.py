"""v3.28.3 (2026-06-09) — quality guard tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _good_row(name="MARKET_REGIME_AGENT", *,
                recommendation="VIX 14; SPY 50d > 200d; risk-on regime.",
                rationale="Counters show 0 of 50 real opportunities.",
                risks=("data-still-thin",),
                next_actions=("await-more-cron-ticks",),
                confidence=0.6,
                provider_status="PROVIDER_USED"):
    return {
        "recommendation":       recommendation,
        "rationale":            rationale,
        "risks_identified":     list(risks),
        "proposed_next_actions": list(next_actions),
        "confidence":           confidence,
        "advisory_only":        True,
        "may_execute":          False,
        "broker_order_submitted": False,
        "affects_readiness_gate": False,
        "agent_name":           name,
        "provider_status":      provider_status,
        # v3.29.1 — evidence_values_used field; quality guard
        # requires this to declare ACCEPTABLE.
        "evidence_values_used": {
            "first_real_market_record_seen": False,
        },
    }


def _placeholder_row(name="MARKET_REGIME_AGENT"):
    return _good_row(
        name=name,
        recommendation=("OBSERVATION: advisory mesh ran; no execution; "
                          f"agent={name}; authority=L2_RECOMMEND_ONLY; "
                          "stage=MARKET_REGIME."),
        rationale=("v3.28 advisory output. Deterministic gates remain "
                     "final; this row is evidence, not authority."),
        risks=(),
        next_actions=(),
        confidence=0.0,
        provider_status="PROVIDER_SKIPPED_DISABLED",
    )


class TestEmpty(unittest.TestCase):
    def test_zero_rows_returns_insufficient_sample(self):
        import llm_advisory_quality as q
        rep = q.evaluate_quality([])
        self.assertEqual(rep.status,
                          q.LLM_ADVISORY_QUALITY_INSUFFICIENT_SAMPLE)


class TestGenericPlaceholder(unittest.TestCase):
    def test_all_placeholder_rows_returns_provider_not_used(self):
        import llm_advisory_quality as q
        rows = [_placeholder_row(n) for n in (
            "MARKET_REGIME_AGENT", "SIGNAL_QUALITY_AGENT",
            "DATA_QUALITY_AGENT", "NO_SIGNAL_DIAGNOSTIC_AGENT",
            "SHADOW_OUTCOME_REVIEW_AGENT")]
        rep = q.evaluate_quality(rows)
        # All rows are PROVIDER_SKIPPED_DISABLED → provider-not-used
        # takes precedence over generic.
        self.assertEqual(
            rep.status,
            q.LLM_ADVISORY_QUALITY_PROVIDER_OUTPUT_NOT_USED)

    def test_mixed_provider_used_but_all_empty_returns_empty_analysis(self):
        # v3.29.1 — EMPTY_ANALYSIS now takes precedence over
        # GENERIC_PLACEHOLDER when every row has empty risks AND
        # empty next-actions AND zero confidence.
        import llm_advisory_quality as q
        rows = [
            _good_row(name=f"A{i}",
                       recommendation="hi", rationale="meh",
                       risks=(), next_actions=(), confidence=0.0,
                       provider_status="PROVIDER_USED")
            for i in range(5)
        ]
        rep = q.evaluate_quality(rows)
        self.assertEqual(
            rep.status,
            q.LLM_ADVISORY_QUALITY_EMPTY_ANALYSIS)


class TestAcceptable(unittest.TestCase):
    def test_concrete_rows_with_provider_used_pass(self):
        import llm_advisory_quality as q
        rows = [_good_row(name=f"A{i}") for i in range(5)]
        rep = q.evaluate_quality(rows)
        self.assertEqual(
            rep.status, q.LLM_ADVISORY_QUALITY_ACCEPTABLE)
        self.assertEqual(rep.rows_with_provider_used, 5)


class TestSecretLeakBlocks(unittest.TestCase):
    def test_alpaca_key_shape_blocks(self):
        import llm_advisory_quality as q
        rows = [
            _good_row(rationale=(
                "context AKAAAAAAAAAAAAAAAAAA tail"))
        ]
        rep = q.evaluate_quality(rows)
        self.assertEqual(
            rep.status,
            q.LLM_ADVISORY_QUALITY_SECRET_LEAK_BLOCKED)

    def test_gemini_key_shape_blocks(self):
        import llm_advisory_quality as q
        rows = [_good_row(rationale=("leak AIza123456789012345678901234567890 here"))]
        rep = q.evaluate_quality(rows)
        self.assertEqual(
            rep.status,
            q.LLM_ADVISORY_QUALITY_SECRET_LEAK_BLOCKED)


class TestUnsafeBlocks(unittest.TestCase):
    def test_enable_broker_paper_blocks(self):
        import llm_advisory_quality as q
        rows = [_good_row(
            recommendation="Operator should enable broker paper soon.")]
        rep = q.evaluate_quality(rows)
        self.assertEqual(rep.status,
                          q.LLM_ADVISORY_QUALITY_UNSAFE_BLOCKED)

    def test_submit_order_blocks(self):
        import llm_advisory_quality as q
        rows = [_good_row(
            next_actions=("submit_order SPY 100 shares",))]
        rep = q.evaluate_quality(rows)
        self.assertEqual(rep.status,
                          q.LLM_ADVISORY_QUALITY_UNSAFE_BLOCKED)


class TestSchemaInvalid(unittest.TestCase):
    def test_missing_required_field_blocks(self):
        import llm_advisory_quality as q
        rep = q.evaluate_quality([{"recommendation": "hi"}])
        self.assertEqual(
            rep.status, q.LLM_ADVISORY_QUALITY_SCHEMA_INVALID)


class TestBlockingStatusesEnum(unittest.TestCase):
    def test_blocking_statuses_set(self):
        import llm_advisory_quality as q
        self.assertIn(q.LLM_ADVISORY_QUALITY_SECRET_LEAK_BLOCKED,
                       q.BLOCKING_STATUSES)
        self.assertIn(q.LLM_ADVISORY_QUALITY_UNSAFE_BLOCKED,
                       q.BLOCKING_STATUSES)
        # ACCEPTABLE / GENERIC are not blocking — runner may still write.
        self.assertNotIn(q.LLM_ADVISORY_QUALITY_ACCEPTABLE,
                          q.BLOCKING_STATUSES)
        self.assertNotIn(q.LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER,
                          q.BLOCKING_STATUSES)


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "shared"
                / "llm_advisory_quality.py").read_text(encoding="utf-8")
        for tok in ("alpaca_orders", "place_stock_bracket",
                     "place_crypto_order", "execute_stock_signal"):
            self.assertNotIn(tok, src, f"forbidden: {tok}")


if __name__ == "__main__":
    unittest.main()
