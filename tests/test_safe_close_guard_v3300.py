"""v3.30 (2026-06-16) — tests for safe_close precondition guard.

Asserts that ``shared.alpaca_orders.safe_close`` refuses-and-returns
when the symbol is broker_repair_required, WITHOUT placing a broker
call. Also asserts symbol normalization (AVAX, AVAXUSD, AVAX/USD all
match the same quarantine) and auto-mark on 403 state-divergence.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


class _IsolatedRepairStateMixin:
    """Point broker_repair_required + retry counters at a tmp dir."""

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
        self._state_path = state_path
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


class TestGuardSkipsBrokerWhenQuarantined(_IsolatedRepairStateMixin, unittest.TestCase):

    def test_quarantined_symbol_skips_broker(self):
        """Marked symbol → safe_close returns REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE."""
        self._mark("AVAX/USD")

        # Re-import so module-level cached state (if any) is fresh.
        if "alpaca_orders" in sys.modules:
            del sys.modules["alpaca_orders"]
        import alpaca_orders

        with patch.object(alpaca_orders, "requests") as mock_requests:
            result = alpaca_orders.safe_close(
                symbol="AVAX/USD",
                intent_qty=1.0,
                intent_side="sell",
                reason_tag="test",
                order_type="market",
                is_crypto=True,
            )
            # Broker MUST NOT be called.
            mock_requests.post.assert_not_called()
            mock_requests.delete.assert_not_called()
            mock_requests.get.assert_not_called()
        self.assertEqual(result["status"], "REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE")
        self.assertFalse(result["broker_called"])
        self.assertEqual(result["symbol"], "AVAX/USD")

    def test_clean_symbol_calls_broker(self):
        """No quarantine → safe_close proceeds to position fetch."""
        if "alpaca_orders" in sys.modules:
            del sys.modules["alpaca_orders"]
        import alpaca_orders

        # Mock position fetch to return None (404 path); we just verify
        # that the guard did NOT short-circuit before position fetch.
        with patch.object(alpaca_orders, "_fetch_single_position", return_value=None) as mock_fetch:
            with patch.object(alpaca_orders, "requests"):
                result = alpaca_orders.safe_close(
                    symbol="SPY",
                    intent_qty=1.0,
                    intent_side="sell",
                    reason_tag="test",
                    order_type="market",
                )
            # Position fetch SHOULD have been called — guard didn't block.
            mock_fetch.assert_called_once_with("SPY")
        # 404 path → skipped (position gone), NOT REPAIR_REQUIRED.
        self.assertEqual(result["status"], "skipped")
        self.assertIn("not found", result["reason"])


class TestSymbolNormalizationInGuard(_IsolatedRepairStateMixin, unittest.TestCase):
    """The original leak: AVAX/USD passed to safe_close while state had AVAX."""

    def test_avax_quarantine_blocks_avaxusd_call(self):
        """Marking AVAX should block subsequent AVAXUSD call."""
        self._mark("AVAX")

        if "alpaca_orders" in sys.modules:
            del sys.modules["alpaca_orders"]
        import alpaca_orders

        with patch.object(alpaca_orders, "requests") as mock_requests:
            result = alpaca_orders.safe_close(
                symbol="AVAXUSD",
                intent_qty=1.0,
                intent_side="sell",
                reason_tag="test",
                is_crypto=True,
            )
            mock_requests.post.assert_not_called()
        self.assertEqual(result["status"], "REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE")

    def test_avax_quarantine_blocks_avax_slash_usd_call(self):
        """The actual production leak: AVAX marked, AVAX/USD called."""
        self._mark("AVAX")

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

    def test_eth_aliases_all_blocked(self):
        self._mark("ETHUSD")

        if "alpaca_orders" in sys.modules:
            del sys.modules["alpaca_orders"]
        import alpaca_orders

        for caller_form in ("ETH", "ETHUSD", "ETH/USD"):
            with patch.object(alpaca_orders, "requests") as mock_requests:
                result = alpaca_orders.safe_close(
                    symbol=caller_form,
                    intent_qty=1.0,
                    intent_side="sell",
                    reason_tag="test",
                    is_crypto=True,
                )
                mock_requests.post.assert_not_called()
            self.assertEqual(
                result["status"], "REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE",
                f"failed for caller form {caller_form!r}",
            )

    def test_ltc_canonical_form_blocked(self):
        self._mark("LTCUSD")

        if "alpaca_orders" in sys.modules:
            del sys.modules["alpaca_orders"]
        import alpaca_orders

        with patch.object(alpaca_orders, "requests") as mock_requests:
            result = alpaca_orders.safe_close(
                symbol="LTC/USD",
                intent_qty=1.0,
                intent_side="sell",
                reason_tag="test",
                is_crypto=True,
            )
            mock_requests.post.assert_not_called()
        self.assertEqual(result["status"], "REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE")


class TestAutoMarkOn403(_IsolatedRepairStateMixin, unittest.TestCase):
    """When broker returns 403 with state-divergence, mark the symbol."""

    def test_403_insufficient_balance_triggers_mark(self):
        if "alpaca_orders" in sys.modules:
            del sys.modules["alpaca_orders"]
        import alpaca_orders
        import broker_repair_required as brr

        # NOT pre-marked — so guard does NOT skip; we test the post-call mark.
        self.assertFalse(brr.is_repair_required("AVAX/USD"))

        live_pos = {"qty": "1.0", "side": "long"}

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "insufficient balance for AVAX"

        with patch.object(alpaca_orders, "_fetch_single_position", return_value=live_pos):
            with patch.object(alpaca_orders, "_cancel_open_orders_for_symbol",
                              return_value={"canceled": [], "failed": [], "checked": 0, "error": None}):
                with patch.object(alpaca_orders, "requests") as mock_requests:
                    mock_requests.post.return_value = mock_resp
                    result = alpaca_orders.safe_close(
                        symbol="AVAX/USD",
                        intent_qty=1.0,
                        intent_side="sell",
                        reason_tag="test",
                        is_crypto=True,
                    )

        self.assertEqual(result["status"], "failed")
        self.assertIn("403", result["reason"])
        # The 403 state-divergence handler must have marked the symbol.
        self.assertTrue(brr.is_repair_required("AVAX/USD"))

    def test_422_qty_must_be_gt_zero_triggers_mark(self):
        if "alpaca_orders" in sys.modules:
            del sys.modules["alpaca_orders"]
        import alpaca_orders
        import broker_repair_required as brr

        self.assertFalse(brr.is_repair_required("LTC/USD"))

        live_pos = {"qty": "1.0", "side": "long"}
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.text = "qty must be > 0"

        with patch.object(alpaca_orders, "_fetch_single_position", return_value=live_pos):
            with patch.object(alpaca_orders, "_cancel_open_orders_for_symbol",
                              return_value={"canceled": [], "failed": [], "checked": 0, "error": None}):
                with patch.object(alpaca_orders, "requests") as mock_requests:
                    mock_requests.post.return_value = mock_resp
                    alpaca_orders.safe_close(
                        symbol="LTC/USD",
                        intent_qty=1.0,
                        intent_side="sell",
                        reason_tag="test",
                        is_crypto=True,
                    )

        self.assertTrue(brr.is_repair_required("LTC/USD"))

    def test_500_does_not_trigger_mark(self):
        """Generic 500 is NOT state-divergence — do not over-quarantine."""
        if "alpaca_orders" in sys.modules:
            del sys.modules["alpaca_orders"]
        import alpaca_orders
        import broker_repair_required as brr

        live_pos = {"qty": "1.0", "side": "long"}
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "internal server error"

        with patch.object(alpaca_orders, "_fetch_single_position", return_value=live_pos):
            with patch.object(alpaca_orders, "_cancel_open_orders_for_symbol",
                              return_value={"canceled": [], "failed": [], "checked": 0, "error": None}):
                with patch.object(alpaca_orders, "requests") as mock_requests:
                    mock_requests.post.return_value = mock_resp
                    alpaca_orders.safe_close(
                        symbol="BTC/USD",
                        intent_qty=1.0,
                        intent_side="sell",
                        reason_tag="test",
                        is_crypto=True,
                    )

        # 500 = transient — NOT state-divergence.
        self.assertFalse(brr.is_repair_required("BTC/USD"))


class TestAuditEmittedOnSkip(_IsolatedRepairStateMixin, unittest.TestCase):
    def test_skip_writes_audit_jsonl(self):
        self._mark("AVAX/USD")

        if "alpaca_orders" in sys.modules:
            del sys.modules["alpaca_orders"]
        import alpaca_orders

        with patch.object(alpaca_orders, "requests"):
            alpaca_orders.safe_close(
                symbol="AVAX/USD",
                intent_qty=1.0,
                intent_side="sell",
                reason_tag="test",
                is_crypto=True,
            )

        # Look at any JSONL in the tmp audit dir.
        events: list[dict] = []
        for f in Path(self._audit_dir).glob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        skip_events = [e for e in events
                       if e.get("decision_type") == "REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE"]
        self.assertGreaterEqual(len(skip_events), 1,
                                "REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE audit not emitted")
        # symbol propagated
        self.assertEqual(skip_events[0].get("symbol"), "AVAX/USD")


class TestFailSoftOnGuardImportError(_IsolatedRepairStateMixin, unittest.TestCase):
    """If broker_repair_required is missing, safe_close must NOT crash."""

    def test_guard_import_error_does_not_crash(self):
        if "alpaca_orders" in sys.modules:
            del sys.modules["alpaca_orders"]
        import alpaca_orders

        live_pos = {"qty": "1.0", "side": "long"}
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": "alpaca-id-123"}

        # Patch the guard's import to raise ImportError WITHIN safe_close.
        # We simulate this by temporarily removing both module names.
        saved_brr = sys.modules.pop("broker_repair_required", None)
        saved_shared_brr = sys.modules.pop("shared.broker_repair_required", None)

        # Block re-import via a custom finder.
        class _BlockBRR:
            def find_module(self, name, path=None):
                if name in ("broker_repair_required", "shared.broker_repair_required"):
                    return self
                return None

            def load_module(self, name):
                raise ImportError("blocked for test")

            def find_spec(self, name, path=None, target=None):
                if name in ("broker_repair_required", "shared.broker_repair_required"):
                    raise ImportError("blocked for test")
                return None

        blocker = _BlockBRR()
        sys.meta_path.insert(0, blocker)
        try:
            with patch.object(alpaca_orders, "_fetch_single_position", return_value=live_pos):
                with patch.object(alpaca_orders, "_cancel_open_orders_for_symbol",
                                  return_value={"canceled": [], "failed": [], "checked": 0, "error": None}):
                    with patch.object(alpaca_orders, "requests") as mock_requests:
                        mock_requests.post.return_value = mock_resp
                        # Even with guard imports broken, this must succeed.
                        result = alpaca_orders.safe_close(
                            symbol="SPY",
                            intent_qty=1.0,
                            intent_side="sell",
                            reason_tag="test",
                        )
            self.assertEqual(result["status"], "placed")
            self.assertEqual(result["alpaca_order_id"], "alpaca-id-123")
        finally:
            sys.meta_path.remove(blocker)
            if saved_brr is not None:
                sys.modules["broker_repair_required"] = saved_brr
            if saved_shared_brr is not None:
                sys.modules["shared.broker_repair_required"] = saved_shared_brr


class TestArchitecturalInvariants(unittest.TestCase):
    """The v3.30 contract — verify NO NEW BROKER CALL in the guard."""

    def test_guard_block_is_above_any_requests_post_call(self):
        """The guard's refuse-and-return path must NOT call requests.post."""
        src_path = _REPO_ROOT / "shared" / "alpaca_orders.py"
        src = src_path.read_text(encoding="utf-8")
        # Find the v3.30 guard block.
        guard_start = src.find("v3.30 HARD-WIRE: broker-repair-required precondition.")
        guard_end = src.find("# ── v3.30 HARD-WIRE", guard_start + 1)
        # The guard block we care about is just the first one in safe_close.
        # Pull text between guard_start and the closing `result: dict = {`.
        result_init = src.find("result: dict = {", guard_start)
        self.assertGreater(result_init, guard_start)
        guard_block = src[guard_start:result_init]
        # Must NOT contain a direct broker call.
        for forbidden in ("requests.post", "requests.delete", "submit_order(", "place_order("):
            self.assertNotIn(
                forbidden, guard_block,
                f"v3.30 guard block must not contain {forbidden!r}",
            )

    def test_guard_skip_dict_has_broker_called_false(self):
        """The skip return dict must include ``broker_called=False`` for ops audit."""
        src_path = _REPO_ROOT / "shared" / "alpaca_orders.py"
        src = src_path.read_text(encoding="utf-8")
        guard_start = src.find("v3.30 HARD-WIRE: broker-repair-required precondition.")
        result_init = src.find("result: dict = {", guard_start)
        guard_block = src[guard_start:result_init]
        self.assertIn('"broker_called":', guard_block)
        self.assertIn("False", guard_block)


if __name__ == "__main__":
    unittest.main()
