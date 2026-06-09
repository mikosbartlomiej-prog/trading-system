"""v3.28 (2026-06-09) — LLM budget governor tests."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _Iso(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {
            "LLM_BUDGET_STATE_DIR": str(self.tmp),
            # Reset every v3.28 env to defaults to isolate from
            # operator overrides.
            "LLM_AGENTS_ENABLED": "false",
            "LLM_AGENT_DAILY_CALL_BUDGET": "20",
            "LLM_AGENT_PER_RUN_BUDGET":    "5",
            "LLM_AGENT_MAX_COST_USD_PER_DAY": "1.00",
            "LLM_PROVIDER": "offline_mock",
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY":    "",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestDefaultDisabled(_Iso):
    def test_default_disabled(self):
        import llm_agent_budget as b
        self.assertFalse(b.llm_agents_enabled())

    def test_check_returns_disabled_by_default(self):
        import llm_agent_budget as b
        v, _ = b.check_budget(run_id="x")
        self.assertEqual(v, b.LLM_BUDGET_DISABLED)


class TestProviderKey(_Iso):
    def test_offline_mock_does_not_require_key(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {"LLM_AGENTS_ENABLED": "true"},
                                clear=False):
            v, _ = b.check_budget(run_id="x")
            self.assertEqual(v, b.LLM_BUDGET_ALLOWED)

    def test_anthropic_without_key_returns_key_missing(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENTS_ENABLED": "true",
            "LLM_PROVIDER": "anthropic",
        }, clear=False):
            v, reason = b.check_budget(run_id="x")
            self.assertEqual(v, b.LLM_PROVIDER_KEY_MISSING)
            self.assertIn("ANTHROPIC_API_KEY", reason)


class TestCaps(_Iso):
    def test_daily_cap_exhausts(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENTS_ENABLED": "true",
            "LLM_AGENT_DAILY_CALL_BUDGET": "2",
        }, clear=False):
            now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
            b.record_call(run_id="r1", now=now)
            b.record_call(run_id="r2", now=now)
            v, _ = b.check_budget(run_id="r3", now=now)
            self.assertEqual(v, b.LLM_BUDGET_EXHAUSTED_DAILY)

    def test_run_cap_exhausts(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENTS_ENABLED": "true",
            "LLM_AGENT_DAILY_CALL_BUDGET": "100",
            "LLM_AGENT_PER_RUN_BUDGET": "1",
        }, clear=False):
            now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
            b.record_call(run_id="solo", now=now)
            v, _ = b.check_budget(run_id="solo", now=now)
            self.assertEqual(v, b.LLM_BUDGET_EXHAUSTED_RUN)

    def test_cost_cap_exhausts(self):
        import llm_agent_budget as b
        with mock.patch.dict(os.environ, {
            "LLM_AGENTS_ENABLED": "true",
            "LLM_AGENT_MAX_COST_USD_PER_DAY": "0.50",
        }, clear=False):
            now = datetime(2026, 6, 9, 14, 0, tzinfo=timezone.utc)
            b.record_call(run_id="r1", cost_usd=0.50, now=now)
            v, reason = b.check_budget(run_id="r2", now=now)
            self.assertEqual(v, b.LLM_BUDGET_EXHAUSTED_DAILY)
            self.assertIn("cost", reason)


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "shared"
                / "llm_agent_budget.py").read_text(encoding="utf-8")
        for tok in (
            "alpaca_orders", "safe_close",
            "place_stock_bracket", "place_crypto_order",
            "execute_stock_signal", "execute_crypto_signal",
            "requests.post", "requests.put", "requests.delete",
        ):
            self.assertNotIn(tok, src, f"forbidden: {tok}")


if __name__ == "__main__":
    unittest.main()
