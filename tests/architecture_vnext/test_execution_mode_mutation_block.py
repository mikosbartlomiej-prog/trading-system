"""Structural tests that broker mutation is UNREACHABLE unless the
execution mode is exactly ``PAPER_CANARY`` and every precondition passes.

These tests are safety-critical. They must be strictly non-network. They
must NOT depend on state files at all — the guard is exercised directly
with mocked environments and mocked state.

If any test here fails, DO NOT weaken the assertion. The failure means
the mutation guard has a bypass and must be repaired.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _reload():
    """Reload execution_mode to pick up patched os.environ."""
    import execution_mode
    importlib.reload(execution_mode)
    return execution_mode


class TestResolveModeDefaultsToOff(unittest.TestCase):
    """Absent every "please trade" env flag, resolver must return OFF."""

    def test_empty_env_returns_off(self):
        with patch.dict(os.environ, {}, clear=True):
            em = _reload()
            r = em.resolve_mode()
            self.assertEqual(r.mode, em.ExecutionMode.OFF)
            self.assertEqual(r.resolved_from, "default")

    def test_only_trading_execution_on_true_still_off(self):
        # Without ALLOW_BROKER_PAPER=true AND EDGE_GATE_ENABLED=true this
        # cannot escalate to PAPER_CANARY.
        with patch.dict(os.environ, {"TRADING_EXECUTION_ON": "true"}, clear=True):
            em = _reload()
            r = em.resolve_mode()
            self.assertEqual(r.mode, em.ExecutionMode.OFF)

    def test_only_allow_broker_paper_true_still_off(self):
        with patch.dict(os.environ, {"ALLOW_BROKER_PAPER": "true"}, clear=True):
            em = _reload()
            r = em.resolve_mode()
            self.assertEqual(r.mode, em.ExecutionMode.OFF)

    def test_all_three_flags_true_yields_paper_canary_nominal(self):
        # Nominal mode only — actual authorization still requires
        # assert_can_mutate_broker() to pass.
        with patch.dict(os.environ, {
            "ALLOW_BROKER_PAPER": "true",
            "TRADING_EXECUTION_ON": "true",
            "EDGE_GATE_ENABLED": "true",
        }, clear=True):
            em = _reload()
            r = em.resolve_mode()
            self.assertEqual(r.mode, em.ExecutionMode.PAPER_CANARY)

    def test_live_flags_yield_live_unsupported(self):
        with patch.dict(os.environ, {"LIVE_TRADING_ENABLED": "true"}, clear=True):
            em = _reload()
            r = em.resolve_mode()
            self.assertEqual(r.mode, em.ExecutionMode.LIVE_UNSUPPORTED)

    def test_go_live_flag_yields_live_unsupported(self):
        with patch.dict(os.environ, {"GO_LIVE": "true"}, clear=True):
            em = _reload()
            r = em.resolve_mode()
            self.assertEqual(r.mode, em.ExecutionMode.LIVE_UNSUPPORTED)

    def test_shadow_mode_enabled_yields_shadow(self):
        with patch.dict(os.environ, {"SHADOW_MODE_ENABLED": "true"}, clear=True):
            em = _reload()
            r = em.resolve_mode()
            self.assertEqual(r.mode, em.ExecutionMode.SHADOW)

    def test_explicit_execution_mode_env_overrides(self):
        for value in ("OFF", "SHADOW", "PAPER_CANARY", "LIVE_UNSUPPORTED"):
            with patch.dict(os.environ, {"EXECUTION_MODE": value}, clear=True):
                em = _reload()
                r = em.resolve_mode()
                self.assertEqual(r.mode.value, value)
                self.assertEqual(r.resolved_from, "env:EXECUTION_MODE")


class TestMutationBlockedInOffMode(unittest.TestCase):
    """The core structural invariant: OFF/SHADOW/LIVE_UNSUPPORTED cannot
    authorize mutation regardless of state."""

    def test_off_mode_blocks(self):
        with patch.dict(os.environ, {}, clear=True):
            em = _reload()
            with self.assertRaises(em.BrokerMutationBlocked) as ctx:
                em.assert_can_mutate_broker(
                    em.resolve_mode(),
                    intent="place_stock_bracket",
                    intended_notional_usd=1.0,
                    idempotency_key="abc",
                )
            self.assertIn("mode_is_paper_canary", str(ctx.exception))

    def test_shadow_mode_blocks(self):
        with patch.dict(os.environ, {"SHADOW_MODE_ENABLED": "true"}, clear=True):
            em = _reload()
            with self.assertRaises(em.BrokerMutationBlocked) as ctx:
                em.assert_can_mutate_broker(
                    em.resolve_mode(),
                    intent="safe_close",
                    intended_notional_usd=1.0,
                    idempotency_key="abc",
                )
            self.assertIn("PAPER_CANARY", str(ctx.exception))

    def test_live_unsupported_blocks(self):
        with patch.dict(os.environ, {"LIVE_TRADING_ENABLED": "true"}, clear=True):
            em = _reload()
            with self.assertRaises(em.BrokerMutationBlocked):
                em.assert_can_mutate_broker(
                    em.resolve_mode(),
                    intent="place_stock_bracket",
                    intended_notional_usd=1.0,
                    idempotency_key="abc",
                )


class TestPaperCanaryRequiresAllPreconditions(unittest.TestCase):
    """PAPER_CANARY nominal mode must still fail every one of the required
    preconditions when any is missing."""

    def setUp(self):
        # Provide the 3-flag env that yields PAPER_CANARY nominal.
        self._paper_env = {
            "ALLOW_BROKER_PAPER": "true",
            "TRADING_EXECUTION_ON": "true",
            "EDGE_GATE_ENABLED": "true",
        }
        # tempdir for markers so tests don't leak into repo
        self._tmp = tempfile.mkdtemp(prefix="exec_mode_test_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_missing_approved_canary_marker_blocks(self):
        with patch.dict(os.environ, self._paper_env, clear=True):
            em = _reload()
            with self.assertRaises(em.BrokerMutationBlocked) as ctx:
                em.assert_can_mutate_broker(
                    em.resolve_mode(),
                    intent="test",
                    intended_notional_usd=1.0,
                    idempotency_key="test-idem-1",
                )
            self.assertIn("approved_canary_policy_marker", str(ctx.exception))

    def test_missing_idempotency_key_blocks(self):
        with patch.dict(os.environ, self._paper_env, clear=True):
            em = _reload()
            with self.assertRaises(em.BrokerMutationBlocked) as ctx:
                em.assert_can_mutate_broker(
                    em.resolve_mode(),
                    intent="test",
                    intended_notional_usd=1.0,
                    idempotency_key=None,
                )
            self.assertIn("idempotency_key_provided", str(ctx.exception))

    def test_notional_over_cap_blocks(self):
        env = dict(self._paper_env)
        env["PAPER_CANARY_MAX_ORDER_NOTIONAL_USD"] = "100"
        with patch.dict(os.environ, env, clear=True):
            em = _reload()
            with self.assertRaises(em.BrokerMutationBlocked) as ctx:
                em.assert_can_mutate_broker(
                    em.resolve_mode(),
                    intent="test",
                    intended_notional_usd=500.0,
                    idempotency_key="k",
                )
            self.assertIn("per_order_cap_respected", str(ctx.exception))

    def test_endpoint_not_paper_blocks(self):
        env = dict(self._paper_env)
        env["ALPACA_BASE_URL"] = "https://api.alpaca.markets"  # live endpoint
        with patch.dict(os.environ, env, clear=True):
            em = _reload()
            with self.assertRaises(em.BrokerMutationBlocked) as ctx:
                em.assert_can_mutate_broker(
                    em.resolve_mode(),
                    intent="test",
                    intended_notional_usd=1.0,
                    idempotency_key="k",
                )
            self.assertIn("endpoint_is_paper", str(ctx.exception))


class TestGuardContextManager(unittest.TestCase):
    """broker_mutation_guard raises on __enter__ — the network call in the
    with-body is UNREACHABLE."""

    def test_context_manager_blocks_off_mode(self):
        with patch.dict(os.environ, {}, clear=True):
            em = _reload()
            unreachable_ran = False
            try:
                with em.broker_mutation_guard(
                    intent="place_stock_bracket",
                    intended_notional_usd=1.0,
                    idempotency_key="k",
                ):
                    # This code MUST NEVER run because __enter__ raised.
                    unreachable_ran = True
            except em.BrokerMutationBlocked:
                pass
            self.assertFalse(
                unreachable_ran,
                "with-body ran when execution mode was OFF — "
                "guard is bypassable!",
            )


class TestAuditFieldsInResolution(unittest.TestCase):
    """Provenance is captured in the resolution for audit."""

    def test_resolution_frozen_and_has_provenance(self):
        with patch.dict(os.environ, {}, clear=True):
            em = _reload()
            r = em.resolve_mode()
            # Must be immutable
            with self.assertRaises((AttributeError, TypeError)):
                r.mode = em.ExecutionMode.PAPER_CANARY  # type: ignore
            self.assertTrue(r.resolved_from)
            self.assertIsInstance(r.reasons, tuple)


if __name__ == "__main__":
    unittest.main()
