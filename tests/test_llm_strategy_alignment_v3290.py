"""v3.29 (2026-06-09) — LLM strategy alignment gate tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _good(**over):
    base = {
        "recommendation": "VIX 14; counters 0/50; regime risk-on.",
        "rationale":      "Counters confirm 0 real opportunities.",
        "risks_identified":     ["data still thin"],
        "proposed_next_actions": ["await more cron ticks"],
        "confidence":     0.5,
        "advisory_only":  True,
        "may_execute":    False,
        "may_modify_risk": False,
        "may_unlock_broker_paper": False,
        "broker_order_submitted":  False,
        "broker_execution_enabled": False,
        "affects_readiness_gate":  False,
        "provider_status": "PROVIDER_USED",
    }
    base.update(over)
    return base


class TestAcceptablePasses(unittest.TestCase):
    def test_concrete_rows_with_provider_used_and_acceptable_pass(self):
        import llm_strategy_alignment as a
        rows = [_good() for _ in range(5)]
        rep = a.evaluate_alignment(
            rows=rows,
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self.assertEqual(rep.status,
                          a.LLM_STRATEGY_ALIGNMENT_PASS)


class TestExecutionAuthorityFails(unittest.TestCase):
    def test_may_execute_true_fails(self):
        import llm_strategy_alignment as a
        rep = a.evaluate_alignment(
            rows=[_good(may_execute=True)],
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self.assertEqual(
            rep.status,
            a.LLM_STRATEGY_ALIGNMENT_FAIL_EXECUTION_AUTHORITY)

    def test_submit_order_phrase_fails(self):
        import llm_strategy_alignment as a
        rep = a.evaluate_alignment(
            rows=[_good(rationale="Operator should submit_order SPY.")],
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self.assertEqual(
            rep.status,
            a.LLM_STRATEGY_ALIGNMENT_FAIL_EXECUTION_AUTHORITY)


class TestRiskMutationFails(unittest.TestCase):
    def test_lower_drawdown_phrase_fails(self):
        import llm_strategy_alignment as a
        rep = a.evaluate_alignment(
            rows=[_good(recommendation="Operator should lower the drawdown guard.")],
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self.assertEqual(
            rep.status,
            a.LLM_STRATEGY_ALIGNMENT_FAIL_RISK_MUTATION)

    def test_may_modify_risk_true_fails(self):
        import llm_strategy_alignment as a
        rep = a.evaluate_alignment(
            rows=[_good(may_modify_risk=True)],
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self.assertEqual(
            rep.status,
            a.LLM_STRATEGY_ALIGNMENT_FAIL_RISK_MUTATION)


class TestReadinessBypassFails(unittest.TestCase):
    def test_affects_readiness_true_fails(self):
        import llm_strategy_alignment as a
        rep = a.evaluate_alignment(
            rows=[_good(affects_readiness_gate=True)],
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self.assertEqual(
            rep.status,
            a.LLM_STRATEGY_ALIGNMENT_FAIL_READINESS_BYPASS)

    def test_count_advisory_as_real_phrase_fails(self):
        import llm_strategy_alignment as a
        rep = a.evaluate_alignment(
            rows=[_good(rationale="We should count advisory output as real evidence.")],
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self.assertEqual(
            rep.status,
            a.LLM_STRATEGY_ALIGNMENT_FAIL_READINESS_BYPASS)


class TestFakeEvidenceFails(unittest.TestCase):
    def test_fabricate_evidence_fails(self):
        import llm_strategy_alignment as a
        rep = a.evaluate_alignment(
            rows=[_good(rationale="Need to fabricate market data to advance.")],
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self.assertEqual(
            rep.status,
            a.LLM_STRATEGY_ALIGNMENT_FAIL_FAKE_EVIDENCE)


class TestUnsupportedLiveFails(unittest.TestCase):
    def test_enable_live_trading_fails(self):
        import llm_strategy_alignment as a
        rep = a.evaluate_alignment(
            rows=[_good(recommendation="Time to enable live trading.")],
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self.assertEqual(
            rep.status,
            a.LLM_STRATEGY_ALIGNMENT_FAIL_UNSUPPORTED_LIVE)


class TestInsufficientProviderQuality(unittest.TestCase):
    def test_quality_not_acceptable_fails(self):
        import llm_strategy_alignment as a
        rep = a.evaluate_alignment(
            rows=[_good()],
            quality_status="LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER")
        self.assertEqual(
            rep.status,
            a.LLM_STRATEGY_ALIGNMENT_INSUFFICIENT_PROVIDER_QUALITY)

    def test_no_provider_used_fails_even_if_quality_acceptable(self):
        import llm_strategy_alignment as a
        rep = a.evaluate_alignment(
            rows=[_good(provider_status="PROVIDER_FAILED_FAIL_SOFT")],
            quality_status="LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self.assertEqual(
            rep.status,
            a.LLM_STRATEGY_ALIGNMENT_INSUFFICIENT_PROVIDER_QUALITY)


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "shared"
                / "llm_strategy_alignment.py").read_text(encoding="utf-8")
        for tok in (
            "alpaca_orders", "place_stock_bracket",
            "place_crypto_order", "execute_stock_signal",
            "execute_crypto_signal",
        ):
            self.assertNotIn(tok, src, f"forbidden: {tok}")


if __name__ == "__main__":
    unittest.main()
