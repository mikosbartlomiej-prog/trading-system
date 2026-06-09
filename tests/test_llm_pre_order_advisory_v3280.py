"""v3.28 (2026-06-09) — pre-order advisory tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _Iso(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "LLM_AGENTS_ENABLED": "false",
            "LLM_PROVIDER": "offline_mock",
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "LLM_PRE_ORDER_VETO_HONORED": "false",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()


class TestVerdictEnum(_Iso):
    def test_no_execute_verdict(self):
        import llm_pre_order_advisory as a
        # The enum MUST NOT contain anything that looks like EXECUTE.
        for v in a.ALL_ADVISORY_VERDICTS:
            self.assertNotIn("EXECUTE", v.upper())

    def test_all_verdicts_enumerated(self):
        import llm_pre_order_advisory as a
        for tok in (
            "ADVISORY_PASS", "ADVISORY_WARN",
            "ADVISORY_VETO_RECOMMENDED",
            "ADVISORY_SKIPPED_DISABLED", "ADVISORY_SKIPPED_BUDGET",
            "ADVISORY_SKIPPED_NO_PROVIDER",
            "ADVISORY_ERROR_FAIL_SOFT",
        ):
            self.assertIn(getattr(a, tok), a.ALL_ADVISORY_VERDICTS)


class TestDefaultDisabledSkipsAdvisory(_Iso):
    def test_disabled_returns_skipped(self):
        import llm_pre_order_advisory as a
        result = a.consult(draft_order_context={"symbol": "SPY"})
        self.assertEqual(result.verdict, a.ADVISORY_SKIPPED_DISABLED)


class TestVetoNotHonoredByDefault(_Iso):
    def test_pre_order_veto_honored_default_false(self):
        import llm_pre_order_advisory as a
        self.assertFalse(a.pre_order_veto_honored())

    def test_is_blocking_false_when_not_honored(self):
        import llm_pre_order_advisory as a
        # Even with the right verdict, is_blocking is False unless
        # the deterministic flag is on.
        self.assertFalse(a.is_blocking(a.ADVISORY_VETO_RECOMMENDED))

    def test_is_blocking_true_only_when_explicitly_honored(self):
        import llm_pre_order_advisory as a
        with mock.patch.dict(os.environ, {
            "LLM_PRE_ORDER_VETO_HONORED": "true",
        }, clear=False):
            self.assertTrue(a.is_blocking(a.ADVISORY_VETO_RECOMMENDED))
        # PASS / WARN / SKIPPED / ERROR are NEVER blocking, even with
        # the flag on.
        with mock.patch.dict(os.environ, {
            "LLM_PRE_ORDER_VETO_HONORED": "true",
        }, clear=False):
            self.assertFalse(a.is_blocking(a.ADVISORY_PASS))
            self.assertFalse(a.is_blocking(a.ADVISORY_WARN))
            self.assertFalse(a.is_blocking(a.ADVISORY_SKIPPED_DISABLED))
            self.assertFalse(a.is_blocking(a.ADVISORY_ERROR_FAIL_SOFT))


class TestResultDictPinsContract(_Iso):
    def test_to_dict_pins_safety_flags(self):
        import llm_pre_order_advisory as a
        result = a.consult(draft_order_context={"symbol": "SPY"})
        d = result.to_dict()
        self.assertTrue(d["advisory_only"])
        self.assertFalse(d["may_execute"])
        self.assertFalse(d["may_modify_risk"])
        self.assertFalse(d["may_unlock_broker_paper"])
        self.assertFalse(d["broker_order_submitted"])
        self.assertFalse(d["broker_execution_enabled"])
        self.assertFalse(d["affects_readiness_gate"])


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "shared"
                / "llm_pre_order_advisory.py").read_text(encoding="utf-8")
        for tok in ("alpaca_orders", "safe_close",
                     "place_stock_bracket", "place_crypto_order",
                     "execute_stock_signal", "execute_crypto_signal",
                     "submit_order", "place_order"):
            self.assertNotIn(tok, src, f"forbidden: {tok}")


if __name__ == "__main__":
    unittest.main()
