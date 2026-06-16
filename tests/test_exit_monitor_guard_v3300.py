"""v3.30 (2026-06-16) — exit-monitor place_emergency_close guard tests.

The v3.30 contract requires ``place_emergency_close`` to check
``broker_repair_required`` BEFORE invoking either the DELETE
/v2/positions path or the safe_close POST fallback. Both paths
are broker calls; both must short-circuit on quarantine.
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


class _IsolatedRepairStateMixin:
    def setUp(self):  # type: ignore[override]
        self._tmp = tempfile.TemporaryDirectory()
        state_path = os.path.join(self._tmp.name, "brr.json")
        counters_path = os.path.join(self._tmp.name, "counters.json")
        audit_dir = os.path.join(self._tmp.name, "audit")
        self._prev_state = os.environ.pop("BROKER_REPAIR_REQUIRED_PATH", None)
        self._prev_counters = os.environ.pop("RETRY_STORM_COUNTERS_PATH", None)
        self._prev_audit = os.environ.pop("AUDIT_TRADING_DIR", None)
        os.environ["BROKER_REPAIR_REQUIRED_PATH"] = state_path
        os.environ["RETRY_STORM_COUNTERS_PATH"] = counters_path
        os.environ["AUDIT_TRADING_DIR"] = audit_dir
        os.makedirs(audit_dir, exist_ok=True)
        self._audit_dir = audit_dir

    def tearDown(self):  # type: ignore[override]
        for key, prev in (
            ("BROKER_REPAIR_REQUIRED_PATH", self._prev_state),
            ("RETRY_STORM_COUNTERS_PATH", self._prev_counters),
            ("AUDIT_TRADING_DIR", self._prev_audit),
        ):
            os.environ.pop(key, None)
            if prev is not None:
                os.environ[key] = prev
        self._tmp.cleanup()

    def _mark(self, symbol):
        import broker_repair_required as brr
        return brr.mark_repair_required(
            symbol,
            incident_type="P13_BRACKET_INTERLOCK",
            error="test seed",
        )


class TestPlaceEmergencyCloseGuard(_IsolatedRepairStateMixin, unittest.TestCase):
    """Verify exit-monitor place_emergency_close respects broker_repair_required."""

    def test_guard_block_is_above_delete_call(self):
        """The v3.30 guard must be inserted BEFORE the DELETE /v2/positions call."""
        src_path = _REPO_ROOT / "exit-monitor" / "monitor.py"
        src = src_path.read_text(encoding="utf-8")
        # The v3.30 block we inserted must appear before the DELETE call.
        guard_pos = src.find("v3.30 HARD-WIRE")
        delete_pos = src.find("requests.delete")
        self.assertGreater(guard_pos, 0,
                           "v3.30 guard not found in exit-monitor")
        self.assertGreater(delete_pos, 0,
                           "DELETE call not found in exit-monitor")
        self.assertLess(guard_pos, delete_pos,
                        "v3.30 guard must be ABOVE the DELETE call")

    def test_guard_block_is_above_safe_close_post_fallback(self):
        """The v3.30 guard must be inserted BEFORE the safe_close POST fallback."""
        src_path = _REPO_ROOT / "exit-monitor" / "monitor.py"
        src = src_path.read_text(encoding="utf-8")
        guard_pos = src.find("v3.30 HARD-WIRE")
        safe_close_pos = src.find(
            "sc = safe_close(",
        )
        self.assertGreater(guard_pos, 0)
        self.assertGreater(safe_close_pos, 0)
        self.assertLess(guard_pos, safe_close_pos)

    def test_guard_audit_emission_on_skip(self):
        """When skip path triggers, an audit row must be emitted."""
        # Smoke-test via the module-level helpers directly.
        self._mark("AVAX/USD")
        from retry_storm_containment import (
            should_skip_broker_call,
            emit_skip_audit,
        )
        self.assertTrue(should_skip_broker_call("AVAX/USD"))
        emit_skip_audit("AVAX/USD", incident_type="P13_BRACKET_INTERLOCK")
        # Assert audit JSONL contains REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE
        files = list(Path(self._audit_dir).glob("*.jsonl"))
        self.assertGreaterEqual(len(files), 1)
        text = "\n".join(p.read_text() for p in files)
        self.assertIn("REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE", text)

    def test_guard_normalizes_avax_aliases(self):
        """exit-monitor with AVAXUSD seed blocks AVAX/USD call (and vice versa)."""
        self._mark("AVAX")
        from retry_storm_containment import should_skip_broker_call
        for caller_form in ("AVAX", "AVAXUSD", "AVAX/USD"):
            self.assertTrue(
                should_skip_broker_call(caller_form),
                f"should_skip_broker_call({caller_form!r}) returned False"
            )

    def test_guard_does_not_skip_clean_symbol(self):
        """Without quarantine, should_skip_broker_call returns False."""
        from retry_storm_containment import should_skip_broker_call
        self.assertFalse(should_skip_broker_call("SPY"))
        self.assertFalse(should_skip_broker_call("BTC/USD"))

    def test_guard_uses_retry_storm_containment_module(self):
        """The exit-monitor guard must call retry_storm_containment, not a local impl."""
        src_path = _REPO_ROOT / "exit-monitor" / "monitor.py"
        src = src_path.read_text(encoding="utf-8")
        # The v3.30 guard block we inserted must reference the shared module.
        v3300_block_start = src.find("v3.30 HARD-WIRE")
        v3300_block_end = src.find("v3.8.7 (2026-05-16): pre-market emergency close defer.")
        v3300_block = src[v3300_block_start:v3300_block_end]
        self.assertIn("retry_storm_containment", v3300_block)
        self.assertIn("should_skip_broker_call", v3300_block)

    def test_guard_returns_deferred_dict_with_broker_called_false(self):
        """The skip branch returns a dict where broker_called is False."""
        src_path = _REPO_ROOT / "exit-monitor" / "monitor.py"
        src = src_path.read_text(encoding="utf-8")
        v3300_block_start = src.find("v3.30 HARD-WIRE")
        v3300_block_end = src.find("v3.8.7 (2026-05-16)")
        v3300_block = src[v3300_block_start:v3300_block_end]
        self.assertIn('"broker_called": False', v3300_block)
        self.assertIn('"deferred"', v3300_block)


class TestExitMonitorArchitecturalInvariants(unittest.TestCase):
    """v3.30 hard-safety: the guard introduces no NEW broker call."""

    def test_v3300_guard_block_contains_no_requests_post(self):
        """The v3.30 guard block must NOT contain any broker call statement."""
        src_path = _REPO_ROOT / "exit-monitor" / "monitor.py"
        src = src_path.read_text(encoding="utf-8")
        v3300_block_start = src.find("v3.30 HARD-WIRE")
        v3300_block_end = src.find("v3.8.7 (2026-05-16): pre-market emergency close defer.")
        v3300_block = src[v3300_block_start:v3300_block_end]
        for forbidden in (
            "requests.post(",
            "requests.delete(",
            "alpaca_orders.safe_close(",
            "place_stock_bracket(",
            "submit_order(",
        ):
            self.assertNotIn(
                forbidden, v3300_block,
                f"v3.30 exit-monitor guard must not contain {forbidden!r}",
            )

    def test_v3300_guard_imports_no_alpaca_orders(self):
        """The v3.30 block must NOT import alpaca_orders (only retry_storm_containment)."""
        src_path = _REPO_ROOT / "exit-monitor" / "monitor.py"
        src = src_path.read_text(encoding="utf-8")
        v3300_block_start = src.find("v3.30 HARD-WIRE")
        v3300_block_end = src.find("v3.8.7 (2026-05-16)")
        v3300_block = src[v3300_block_start:v3300_block_end]
        self.assertNotIn("import alpaca_orders", v3300_block)


if __name__ == "__main__":
    unittest.main()
