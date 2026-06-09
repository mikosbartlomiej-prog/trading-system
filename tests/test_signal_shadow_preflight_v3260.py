"""v3.26.0 (2026-06-09) — signal/shadow preflight tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import signal_shadow_preflight as sp


def _clear_envs(monkeypatch_dict: dict) -> dict:
    """Build an env override dict that clears every broker-execution
    related env var so we start from a known clean state."""
    cleared = {
        "ALLOW_BROKER_PAPER": "false",
        "EDGE_GATE_ENABLED": "false",
        "BROKER_EXECUTION_ENABLED": "false",
        "LIVE_TRADING": "false",
        "LIVE_ENABLED": "false",
        "GO_LIVE": "false",
        "LIVE_TRADING_ENABLED": "false",
    }
    cleared.update(monkeypatch_dict or {})
    return cleared


class TestPreflightPassesUnderCleanState(unittest.TestCase):
    def test_clean_env_yields_pass(self):
        with mock.patch.dict(os.environ, _clear_envs({}), clear=False):
            r = sp.run_preflight()
            self.assertEqual(r.verdict,
                              sp.SIGNAL_SHADOW_PREFLIGHT_PASS,
                              f"blockers: {r.blockers}")

    def test_pass_includes_broker_execution_disabled_confirmation(self):
        with mock.patch.dict(os.environ, _clear_envs({}), clear=False):
            r = sp.run_preflight()
            self.assertIn(sp.BROKER_EXECUTION_DISABLED_CONFIRMED,
                            r.confirmations)
            self.assertIn(sp.BROKER_PAPER_DISABLED_CONFIRMED,
                            r.confirmations)
            self.assertIn(sp.LIVE_TRADING_UNSUPPORTED_CONFIRMED,
                            r.confirmations)
            self.assertIn(sp.EDGE_GATE_DISABLED_CONFIRMED,
                            r.confirmations)

    def test_supplying_operator_snapshot_adds_confirmations(self):
        with mock.patch.dict(os.environ, _clear_envs({}), clear=False):
            r = sp.run_preflight(sp.PreflightInputs(
                open_orders_count=0,
                open_equity_positions_count=0,
                crypto_positions_reconciled=True,
            ))
            self.assertEqual(r.verdict,
                              sp.SIGNAL_SHADOW_PREFLIGHT_PASS)
            for token in (
                sp.OPEN_ORDERS_ZERO_CONFIRMED,
                sp.OPEN_EQUITY_POSITIONS_ZERO_CONFIRMED,
                sp.CRYPTO_POSITIONS_RECONCILED_CONFIRMED,
            ):
                self.assertIn(token, r.confirmations)


class TestPreflightBlockerCases(unittest.TestCase):
    def test_allow_broker_paper_true_blocks(self):
        env = _clear_envs({"ALLOW_BROKER_PAPER": "true"})
        with mock.patch.dict(os.environ, env, clear=False):
            r = sp.run_preflight()
            self.assertEqual(r.verdict,
                              sp.SIGNAL_SHADOW_PREFLIGHT_BLOCKED)
            blockers_text = " ".join(r.blockers)
            self.assertIn("ALLOW_BROKER_PAPER", blockers_text)

    def test_edge_gate_enabled_true_blocks(self):
        env = _clear_envs({"EDGE_GATE_ENABLED": "true"})
        with mock.patch.dict(os.environ, env, clear=False):
            r = sp.run_preflight()
            self.assertEqual(r.verdict,
                              sp.SIGNAL_SHADOW_PREFLIGHT_BLOCKED)
            self.assertIn("EDGE_GATE_ENABLED", " ".join(r.blockers))

    def test_live_trading_env_blocks(self):
        env = _clear_envs({"LIVE_TRADING": "true"})
        with mock.patch.dict(os.environ, env, clear=False):
            r = sp.run_preflight()
            self.assertEqual(r.verdict,
                              sp.SIGNAL_SHADOW_PREFLIGHT_BLOCKED)

    def test_broker_execution_enabled_blocks(self):
        env = _clear_envs({"BROKER_EXECUTION_ENABLED": "true"})
        with mock.patch.dict(os.environ, env, clear=False):
            r = sp.run_preflight()
            self.assertEqual(r.verdict,
                              sp.SIGNAL_SHADOW_PREFLIGHT_BLOCKED)

    def test_open_orders_nonzero_blocks_when_supplied(self):
        env = _clear_envs({})
        with mock.patch.dict(os.environ, env, clear=False):
            r = sp.run_preflight(
                sp.PreflightInputs(open_orders_count=3),
            )
            self.assertEqual(r.verdict,
                              sp.SIGNAL_SHADOW_PREFLIGHT_BLOCKED)

    def test_open_equity_positions_nonzero_blocks(self):
        env = _clear_envs({})
        with mock.patch.dict(os.environ, env, clear=False):
            r = sp.run_preflight(
                sp.PreflightInputs(open_equity_positions_count=2),
            )
            self.assertEqual(r.verdict,
                              sp.SIGNAL_SHADOW_PREFLIGHT_BLOCKED)

    def test_drawdown_threshold_weaker_than_3pct_blocks(self):
        env = _clear_envs({})
        with mock.patch.dict(os.environ, env, clear=False):
            r = sp.run_preflight(sp.PreflightInputs(
                operator_drawdown_guard_threshold_pct=-8.0,
            ))
            self.assertEqual(r.verdict,
                              sp.SIGNAL_SHADOW_PREFLIGHT_BLOCKED)


class TestCryptoGuardsPresentCheck(unittest.TestCase):
    def test_crypto_guards_present_against_real_repo(self):
        env = _clear_envs({})
        with mock.patch.dict(os.environ, env, clear=False):
            r = sp.run_preflight()
            self.assertIn(sp.CRYPTO_GUARDS_PRESENT_CONFIRMED,
                            r.confirmations)


class TestUnlockReadinessIntegration(unittest.TestCase):
    def test_unlock_readiness_verdict_confirmed(self):
        env = _clear_envs({})
        with mock.patch.dict(os.environ, env, clear=False):
            r = sp.run_preflight()
            self.assertIn(sp.UNLOCK_READINESS_VERDICT_CONFIRMED,
                            r.confirmations)
            self.assertEqual(
                r.details["unlock_verdict"],
                "SIGNAL_SHADOW_UNLOCK_READY",
            )

    def test_broker_paper_not_ready_confirmed(self):
        env = _clear_envs({})
        with mock.patch.dict(os.environ, env, clear=False):
            r = sp.run_preflight()
            self.assertIn(sp.BROKER_PAPER_NOT_READY_CONFIRMED,
                            r.confirmations)


class TestInvariantConstants(unittest.TestCase):
    def test_invariants_true(self):
        self.assertTrue(sp.BROKER_EXECUTION_NEVER_ENABLED_IN_PREFLIGHT)
        self.assertTrue(sp.NEVER_PROMOTES_BROKER_PAPER)
        self.assertTrue(sp.NEVER_FLIPS_EDGE_GATE)
        self.assertTrue(sp.NEVER_LOWERS_DRAWDOWN_GUARD)
        self.assertTrue(sp.NEVER_RESETS_BASELINE)

    def test_all_confirmations_set(self):
        self.assertIsInstance(sp.ALL_CONFIRMATIONS, frozenset)
        for token in (
            sp.BROKER_EXECUTION_DISABLED_CONFIRMED,
            sp.BROKER_PAPER_DISABLED_CONFIRMED,
            sp.LIVE_TRADING_UNSUPPORTED_CONFIRMED,
            sp.EDGE_GATE_DISABLED_CONFIRMED,
            sp.CRYPTO_GUARDS_PRESENT_CONFIRMED,
            sp.AUDIT_BYPASS_INVARIANT_CONFIRMED,
            sp.QUARANTINED_SCRIPTS_STILL_DISABLED_CONFIRMED,
            sp.UNLOCK_READINESS_VERDICT_CONFIRMED,
            sp.BROKER_PAPER_NOT_READY_CONFIRMED,
            sp.BASELINE_UNCHANGED_CONFIRMED,
            sp.DRAWDOWN_GUARD_NOT_LOWERED_CONFIRMED,
            sp.OPEN_ORDERS_ZERO_CONFIRMED,
            sp.OPEN_EQUITY_POSITIONS_ZERO_CONFIRMED,
            sp.CRYPTO_POSITIONS_RECONCILED_CONFIRMED,
        ):
            self.assertIn(token, sp.ALL_CONFIRMATIONS)


class TestNoForbiddenImportsInPreflight(unittest.TestCase):
    def test_preflight_does_not_import_order_submission(self):
        src = (REPO_ROOT / "shared"
                / "signal_shadow_preflight.py").read_text()
        FORBIDDEN = (
            "place_stock_bracket", "place_crypto_order",
            "place_simple_buy", "place_oco_exit",
            "safe_close", "execute_crypto_signal",
            "execute_stock_signal",
            "requests.post", "requests.put", "requests.delete",
        )
        for token in FORBIDDEN:
            self.assertNotIn(
                token, src,
                f"forbidden token in preflight module: {token}",
            )


if __name__ == "__main__":
    unittest.main()
