"""runtime_config — kill switches, risk profile, limits."""
import os
import unittest
from unittest import mock

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

import runtime_config


def with_env(**kv):
    """Decorator: patch the env, clear keys with value=None."""
    def deco(fn):
        def wrapper(*a, **k):
            ctx = {}
            for key, val in kv.items():
                if val is None:
                    ctx[key] = ""  # mock.patch.dict can't unset, but we use exists-check
                else:
                    ctx[key] = val
            with mock.patch.dict(os.environ, ctx, clear=False):
                # If val is None, ensure the key is actually absent for the test
                for key, val in kv.items():
                    if val is None and key in os.environ:
                        del os.environ[key]
                return fn(*a, **k)
        return wrapper
    return deco


class TestRuntimeConfig(unittest.TestCase):
    def test_llm_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_ENABLED", None)
            self.assertFalse(runtime_config.llm_enabled())

    def test_llm_enabled_truthy(self):
        with mock.patch.dict(os.environ, {"LLM_ENABLED": "true"}):
            self.assertTrue(runtime_config.llm_enabled())
        with mock.patch.dict(os.environ, {"LLM_ENABLED": "1"}):
            self.assertTrue(runtime_config.llm_enabled())
        with mock.patch.dict(os.environ, {"LLM_ENABLED": "yes"}):
            self.assertTrue(runtime_config.llm_enabled())

    def test_llm_disabled_falsy(self):
        with mock.patch.dict(os.environ, {"LLM_ENABLED": "false"}):
            self.assertFalse(runtime_config.llm_enabled())
        with mock.patch.dict(os.environ, {"LLM_ENABLED": "0"}):
            self.assertFalse(runtime_config.llm_enabled())

    def test_llm_execution_influence_default_false(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_EXECUTION_INFLUENCE_ENABLED", None)
            self.assertFalse(runtime_config.llm_execution_influence_enabled())

    def test_options_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPTIONS_ENABLED", None)
            self.assertFalse(runtime_config.options_enabled())

    def test_options_enabled_true(self):
        with mock.patch.dict(os.environ, {"OPTIONS_ENABLED": "true"}):
            self.assertTrue(runtime_config.options_enabled())

    def test_risk_profile_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RISK_PROFILE", None)
            self.assertEqual(runtime_config.risk_profile(), "BALANCED_PAPER")

    def test_risk_profile_misconfigured_falls_back(self):
        with mock.patch.dict(os.environ, {"RISK_PROFILE": "YOLO_LIVE"}):
            self.assertEqual(runtime_config.risk_profile(), "BALANCED_PAPER")

    def test_safe_free_is_most_conservative(self):
        safe = runtime_config.profile_limits("SAFE_FREE")
        bal = runtime_config.profile_limits("BALANCED_PAPER")
        aggr = runtime_config.profile_limits("AGGRESSIVE_PAPER")

        # Single-trade cap monotone
        self.assertLess(safe["max_single_trade_pct"], bal["max_single_trade_pct"])
        self.assertLess(bal["max_single_trade_pct"], aggr["max_single_trade_pct"])

        # SAFE_FREE disables margin, AGGRESSIVE_PAPER enables it
        self.assertFalse(safe["margin_enabled"])
        self.assertTrue(aggr["margin_enabled"])

    def test_snapshot_is_paper_only(self):
        snap = runtime_config.snapshot()
        self.assertTrue(snap["paper_only"])
        self.assertNotIn("live_trading", snap)


if __name__ == "__main__":
    unittest.main()
