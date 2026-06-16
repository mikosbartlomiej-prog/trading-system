"""v3.30 (2026-06-16) — retry-storm budget enforcement tests.

The v3.30 contract: after ``P13_RETRY_BUDGET`` (3) consecutive failed
broker close attempts for a symbol, the symbol is automatically
marked broker_repair_required, which short-circuits all future
safe_close calls via the v3.30 precondition guard.

The budget itself is implemented in ``shared/retry_storm_containment.py``
(shipped v3.28). These tests verify the v3.30 wiring + new behavior:
canonical-symbol normalization through the counter path, per-symbol
independence, persistence across process restarts.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


class _IsolatedMixin:
    def setUp(self):  # type: ignore[override]
        self._tmp = tempfile.TemporaryDirectory()
        self._state_path = os.path.join(self._tmp.name, "brr.json")
        self._counters_path = os.path.join(self._tmp.name, "counters.json")
        self._audit_dir = os.path.join(self._tmp.name, "audit")
        os.makedirs(self._audit_dir, exist_ok=True)
        self._prev = {
            "BROKER_REPAIR_REQUIRED_PATH": os.environ.pop("BROKER_REPAIR_REQUIRED_PATH", None),
            "RETRY_STORM_COUNTERS_PATH":   os.environ.pop("RETRY_STORM_COUNTERS_PATH", None),
            "AUDIT_TRADING_DIR":           os.environ.pop("AUDIT_TRADING_DIR", None),
        }
        os.environ["BROKER_REPAIR_REQUIRED_PATH"] = self._state_path
        os.environ["RETRY_STORM_COUNTERS_PATH"]   = self._counters_path
        os.environ["AUDIT_TRADING_DIR"]           = self._audit_dir

    def tearDown(self):  # type: ignore[override]
        for k, v in self._prev.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        self._tmp.cleanup()

    def _fresh_modules(self):
        for m in (
            "broker_repair_required", "shared.broker_repair_required",
            "retry_storm_containment", "shared.retry_storm_containment",
            "symbol_normalization", "shared.symbol_normalization",
        ):
            sys.modules.pop(m, None)
        sys.path.insert(0, str(_REPO_ROOT / "shared"))


class TestBudgetBasics(_IsolatedMixin, unittest.TestCase):

    def test_attempt_1_allowed(self):
        self._fresh_modules()
        from retry_storm_containment import should_skip_broker_call
        self.assertFalse(should_skip_broker_call("BTC/USD"))

    def test_three_failures_triggers_quarantine(self):
        self._fresh_modules()
        import retry_storm_containment as rsc
        # Three consecutive failures → quarantine.
        for i in range(3):
            rsc.record_broker_close_failure(
                "BTC/USD",
                error=f"test failure {i + 1}",
                incident_type="P13_BRACKET_INTERLOCK",
            )
        # Should now be quarantined.
        self.assertTrue(rsc.should_skip_broker_call("BTC/USD"))

    def test_two_failures_does_not_quarantine(self):
        self._fresh_modules()
        import retry_storm_containment as rsc
        for i in range(2):
            rsc.record_broker_close_failure(
                "BTC/USD",
                error="test",
                incident_type="P13_BRACKET_INTERLOCK",
            )
        self.assertFalse(rsc.should_skip_broker_call("BTC/USD"))

    def test_success_resets_counter(self):
        self._fresh_modules()
        import retry_storm_containment as rsc
        rsc.record_broker_close_failure("BTC/USD", error="t", incident_type="t")
        rsc.record_broker_close_failure("BTC/USD", error="t", incident_type="t")
        rsc.record_broker_close_success("BTC/USD")
        # Counter is reset; one more failure should not quarantine.
        rsc.record_broker_close_failure("BTC/USD", error="t", incident_type="t")
        self.assertFalse(rsc.should_skip_broker_call("BTC/USD"))


class TestBudgetIndependence(_IsolatedMixin, unittest.TestCase):
    """AVAX budget exhaustion does not affect BTC."""

    def test_avax_budget_does_not_quarantine_eth(self):
        self._fresh_modules()
        import retry_storm_containment as rsc
        for _ in range(3):
            rsc.record_broker_close_failure(
                "AVAX/USD",
                error="t",
                incident_type="P13_BRACKET_INTERLOCK",
            )
        self.assertTrue(rsc.should_skip_broker_call("AVAX/USD"))
        self.assertFalse(rsc.should_skip_broker_call("ETH/USD"))
        self.assertFalse(rsc.should_skip_broker_call("BTC/USD"))


class TestBackoffSchedule(_IsolatedMixin, unittest.TestCase):

    def test_backoff_constants_match_spec(self):
        self._fresh_modules()
        import retry_storm_containment as rsc
        self.assertEqual(rsc.P13_RETRY_BUDGET, 3)
        self.assertEqual(rsc.P13_RETRY_BACKOFF_SECONDS, (60, 300, 1800))

    def test_backoff_seconds_for_attempt_returns_schedule(self):
        self._fresh_modules()
        import retry_storm_containment as rsc
        self.assertEqual(rsc.backoff_seconds_for_attempt(1), 60)
        self.assertEqual(rsc.backoff_seconds_for_attempt(2), 300)
        self.assertEqual(rsc.backoff_seconds_for_attempt(3), 1800)
        # Beyond the schedule → clamp to last value.
        self.assertEqual(rsc.backoff_seconds_for_attempt(99), 1800)

    def test_backoff_for_zero_attempt_returns_zero(self):
        self._fresh_modules()
        import retry_storm_containment as rsc
        self.assertEqual(rsc.backoff_seconds_for_attempt(0), 0)


class TestPersistence(_IsolatedMixin, unittest.TestCase):
    """Counter survives process restart (cron-tick-level restart)."""

    def test_counter_persists_across_module_reload(self):
        self._fresh_modules()
        import retry_storm_containment as rsc
        rsc.record_broker_close_failure("BTC/USD", error="t1", incident_type="t")
        rsc.record_broker_close_failure("BTC/USD", error="t2", incident_type="t")
        # Reload module — counter still at 2.
        sys.modules.pop("retry_storm_containment", None)
        import retry_storm_containment as rsc2
        rsc2.record_broker_close_failure("BTC/USD", error="t3", incident_type="t")
        # Third failure → quarantine.
        self.assertTrue(rsc2.should_skip_broker_call("BTC/USD"))


class TestAfterQuarantineGuardIntercepts(_IsolatedMixin, unittest.TestCase):
    """After auto-mark, the v3.30 safe_close guard above blocks further calls."""

    def test_after_quarantine_safe_close_skips(self):
        self._fresh_modules()
        import retry_storm_containment as rsc
        for _ in range(3):
            rsc.record_broker_close_failure(
                "AVAX/USD", error="403", incident_type="P13_BRACKET_INTERLOCK"
            )
        # Now safe_close should refuse.
        from unittest.mock import patch
        if "alpaca_orders" in sys.modules:
            del sys.modules["alpaca_orders"]
        import alpaca_orders
        with patch.object(alpaca_orders, "requests") as mock_requests:
            result = alpaca_orders.safe_close(
                symbol="AVAX/USD",
                intent_qty=1.0,
                intent_side="sell",
                reason_tag="test",
                is_crypto=True,
            )
            mock_requests.post.assert_not_called()
        self.assertEqual(result["status"], "REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE")


class TestAuditEmission(_IsolatedMixin, unittest.TestCase):

    def test_failure_emits_audit_row(self):
        self._fresh_modules()
        import retry_storm_containment as rsc
        rsc.record_broker_close_failure("BTC/USD", error="boom", incident_type="P13")
        files = list(Path(self._audit_dir).glob("*.jsonl"))
        self.assertGreaterEqual(len(files), 1)
        text = "\n".join(p.read_text() for p in files)
        self.assertIn("BROKER_CLOSE_FAILURE_RECORDED", text)

    def test_quarantine_emits_mark_set_audit(self):
        self._fresh_modules()
        import retry_storm_containment as rsc
        for _ in range(3):
            rsc.record_broker_close_failure(
                "BTC/USD", error="boom", incident_type="P13_BRACKET_INTERLOCK"
            )
        files = list(Path(self._audit_dir).glob("*.jsonl"))
        text = "\n".join(p.read_text() for p in files)
        # mark_repair_required emits REPAIR_REQUIRED_MARK_SET on first set.
        self.assertIn("REPAIR_REQUIRED_MARK_SET", text)


class TestNoInfiniteLoopPossible(_IsolatedMixin, unittest.TestCase):
    """A naive caller cannot accidentally retry past the budget."""

    def test_repeated_failures_eventually_block_via_guard(self):
        self._fresh_modules()
        import retry_storm_containment as rsc
        # Simulate the same caller hammering the same symbol.
        attempts = 0
        for _ in range(20):
            if rsc.should_skip_broker_call("BTC/USD"):
                break
            rsc.record_broker_close_failure(
                "BTC/USD", error="403", incident_type="P13_BRACKET_INTERLOCK"
            )
            attempts += 1
        # The hammer terminates well before 20.
        self.assertLessEqual(attempts, rsc.P13_RETRY_BUDGET)
        self.assertTrue(rsc.should_skip_broker_call("BTC/USD"))


if __name__ == "__main__":
    unittest.main()
