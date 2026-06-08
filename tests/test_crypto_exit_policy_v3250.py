"""v3.25.0 (2026-06-09) — crypto exit policy tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import crypto_exit_policy as ex


def _make(symbol="ETHUSD", qty=1.0, otype="limit",
            price=None, notional=5000.0, reason=ex.EXIT_REASON_TIME_EXPIRY,
            operator_dust=False, recent=None, prec_fail=0,
            audit_ok=True, now=1_000_000_000.0):
    return ex.CryptoExitInputs(
        symbol=symbol, proposed_qty=qty,
        proposed_order_type=otype,
        proposed_limit_price=price,
        current_position_notional_usd=notional,
        reason=reason,
        operator_dust_close_approved=operator_dust,
        recent_close_attempts_epoch=recent or [],
        precision_failures_recent=prec_fail,
        audit_emit_available=audit_ok,
        now_epoch=now,
    )


class TestMarketExitRequiresReason(unittest.TestCase):
    def test_market_exit_with_no_reason_blocked(self):
        d = ex.evaluate_crypto_exit(_make(otype="market", reason=None))
        self.assertEqual(d.decision, ex.BLOCK_NO_REASON)

    def test_market_exit_with_non_risk_reason_blocked(self):
        d = ex.evaluate_crypto_exit(_make(
            otype="market", reason=ex.EXIT_REASON_REBALANCE,
        ))
        self.assertEqual(
            d.decision, ex.BLOCK_MARKET_EXIT_REQUIRES_RISK_REASON,
        )

    def test_market_exit_with_emergency_allowed(self):
        d = ex.evaluate_crypto_exit(_make(
            otype="market", reason=ex.EXIT_REASON_EMERGENCY,
            qty=1.0,
        ))
        self.assertEqual(d.decision, ex.ALLOW_MARKET)

    def test_market_exit_with_stop_like_allowed(self):
        d = ex.evaluate_crypto_exit(_make(
            otype="market", reason=ex.EXIT_REASON_STOP_LIKE,
        ))
        self.assertEqual(d.decision, ex.ALLOW_MARKET)


class TestDustOperatorDecision(unittest.TestCase):
    def test_dust_close_blocked_without_operator_approval(self):
        d = ex.evaluate_crypto_exit(_make(
            symbol="SOLUSD", qty=0.000000183,
            notional=0.000008, operator_dust=False,
        ))
        self.assertEqual(
            d.decision, ex.BLOCK_DUST_OPERATOR_DECISION_REQUIRED,
        )

    def test_dust_close_allowed_with_operator_approval(self):
        d = ex.evaluate_crypto_exit(_make(
            symbol="SOLUSD", qty=0.000000183,
            notional=0.000008, operator_dust=True,
            reason=ex.EXIT_REASON_OPERATOR_REQUESTED,
        ))
        # Allowed (limit by default)
        self.assertEqual(d.decision, ex.ALLOW_LIMIT)


class TestPrecisionRounding(unittest.TestCase):
    def test_round_qty_down_never_rounds_up(self):
        # Round 5.0724058 to 6 decimals should be 5.072405 (not 5.072406)
        out = ex._round_qty_down_safe(5.0724058, decimals=6)
        self.assertLessEqual(out, 5.0724058)

    def test_precision_race_guard_blocks_after_too_many_failures(self):
        d = ex.evaluate_crypto_exit(_make(prec_fail=5))
        self.assertEqual(d.decision, ex.BLOCK_PRECISION_RACE_GUARD)


class TestRepeatedCloseSpamDedup(unittest.TestCase):
    def test_recent_close_attempts_dedup_blocks(self):
        now = 1_000_000_000.0
        d = ex.evaluate_crypto_exit(_make(
            recent=[now - 60, now - 120],  # 1 and 2 min ago
            now=now,
        ))
        self.assertEqual(d.decision, ex.BLOCK_DEDUPED_REPEATED_CLOSE)

    def test_close_attempts_outside_window_do_not_dedup(self):
        now = 1_000_000_000.0
        d = ex.evaluate_crypto_exit(_make(
            recent=[now - 2 * 3600],  # 2 hours ago
            now=now,
        ))
        # Should be allowed (no dedup); reason is time_expiry so
        # limit exit is allowed.
        self.assertEqual(d.decision, ex.ALLOW_LIMIT)


class TestAuditRequired(unittest.TestCase):
    def test_no_audit_emission_blocks(self):
        d = ex.evaluate_crypto_exit(_make(audit_ok=False))
        self.assertEqual(d.decision, ex.BLOCK_AUDIT_PATH_UNAVAILABLE)


class TestNoUnauditedMarketExit(unittest.TestCase):
    """No code path may produce ALLOW_MARKET without passing the
    structured-reason gate AND the audit emission gate."""

    def test_market_with_audit_disabled_is_blocked(self):
        d = ex.evaluate_crypto_exit(_make(
            otype="market", reason=ex.EXIT_REASON_EMERGENCY,
            audit_ok=False,
        ))
        # Audit gate fires before market-exit reason gate.
        self.assertEqual(d.decision, ex.BLOCK_AUDIT_PATH_UNAVAILABLE)


class TestNoOrderSubmission(unittest.TestCase):
    def test_module_has_no_order_submission_imports(self):
        src = (REPO_ROOT / "shared"
                / "crypto_exit_policy.py").read_text()
        FORBIDDEN = (
            "place_crypto_order", "place_stock_bracket",
            "place_simple_buy", "safe_close",
            "execute_crypto_signal", "execute_stock_signal",
            "requests.post", "requests.put", "requests.delete",
        )
        for token in FORBIDDEN:
            self.assertNotIn(token, src,
                              f"forbidden token in exit policy: {token}")


class TestInvariants(unittest.TestCase):
    def test_invariants_true(self):
        self.assertTrue(ex.NEVER_PLACES_ORDERS)
        self.assertTrue(
            ex.NEVER_AUTO_CLOSES_DUST_WITHOUT_OPERATOR_DECISION)
        self.assertTrue(ex.NEVER_ROUNDS_UP)
        self.assertTrue(ex.NEVER_ALLOWS_MARKET_EXIT_WITHOUT_REASON)

    def test_status_tokens_present(self):
        for t in (
            ex.CRYPTO_EXIT_AUDIT_REQUIRED,
            ex.CRYPTO_EXIT_REASON_REQUIRED,
            ex.CRYPTO_DUST_EXIT_OPERATOR_DECISION,
            ex.CRYPTO_MARKET_EXIT_REQUIRES_RISK_REASON,
            ex.CRYPTO_PRECISION_CLOSE_GUARD_ACTIVE,
        ):
            self.assertIn(t, ex.ALL_STATUS_TOKENS)


class TestPolicySummary(unittest.TestCase):
    def test_summary_includes_all_decisions(self):
        s = ex.policy_summary()
        for d in (ex.ALLOW_MARKET, ex.ALLOW_LIMIT, ex.BLOCK_NO_REASON):
            self.assertIn(d, s["decisions"])


if __name__ == "__main__":
    unittest.main()
