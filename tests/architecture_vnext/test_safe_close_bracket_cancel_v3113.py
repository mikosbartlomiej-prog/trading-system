"""v3.11.3 (2026-05-30) — safe_close bracket-interlock fix tests.

After the 2026-05-29 14:11-14:21 UTC incident where 6 governor-driven
`safe_close` calls all returned Alpaca 403 because bracket OCO children
held the full position qty (`held_for_orders=N`), `safe_close` now
cancels open orders for the symbol BEFORE placing the protective close.

These tests pin down:
1. cancel-brackets-first default ON — bracket children DELETE'd before POST close
2. cancel-brackets-first OFF — original behavior preserved (regression guard)
3. cancel cascade error → still attempts close (fail-soft contract)
4. result dict + audit emission include bracket cancellation info
5. crypto path skips bracket cancel (Alpaca crypto has no OCO support)
6. position-not-found short-circuit unchanged

Plus tests for the matching P13 incident detector that catches the
"impossible" scenario where v3.11.3 cancel itself fails.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def setUpModule():
    # v3.11.3: keep test audit emissions OUT of production journal/autonomy/.
    # Without this, mocked safe_close calls in this module pollute the real
    # journal with CLOSE_POSITION FAILED events, which then triggers
    # P13_bracket_interlock_blocked_close on the next live detector run.
    global _AUDIT_TMP, _BROKER_REPAIR_TMP
    _AUDIT_TMP = tempfile.mkdtemp(prefix="audit_test_safe_close_")
    os.environ["AUDIT_TRADING_DIR"] = _AUDIT_TMP

    # v3.30: tests that mock a 403 "held_for_orders" Alpaca response trip
    # safe_close's auto-mark code path, which writes to
    # learning-loop/broker_repair_required_latest.json by default. Without
    # this redirect the production state file gets polluted with an AMD
    # quarantine entry — and the precondition guard then short-circuits
    # every AMD test in the same discovery run with
    # REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE. broker_repair_required honors
    # BROKER_REPAIR_REQUIRED_PATH as a tempdir override.
    _BROKER_REPAIR_TMP = tempfile.mkdtemp(prefix="broker_repair_test_safe_close_")
    os.environ["BROKER_REPAIR_REQUIRED_PATH"] = str(
        Path(_BROKER_REPAIR_TMP) / "broker_repair_required_latest.json"
    )

    # v3.32: these tests exercise safe_close / bracket-cancel behavior at
    # the "what does the function return for X mock scenario" level. The
    # canonical ExecutionMode gate blocks broker mutation whenever mode≠
    # PAPER_CANARY. Since this test harness cannot (and MUST not) create
    # PAPER_CANARY_APPROVED.marker, we set the documented test-only
    # bypass. The bypass is scanned for by CI env audits to guarantee it
    # never leaks into a real workflow.
    os.environ["EXECUTION_MODE_GATE_TEST_BYPASS"] = "true"


def tearDownModule():
    import shutil
    os.environ.pop("AUDIT_TRADING_DIR", None)
    os.environ.pop("BROKER_REPAIR_REQUIRED_PATH", None)
    os.environ.pop("EXECUTION_MODE_GATE_TEST_BYPASS", None)
    try:
        shutil.rmtree(_AUDIT_TMP)
    except Exception:
        pass
    try:
        shutil.rmtree(_BROKER_REPAIR_TMP)
    except Exception:
        pass


def _make_response(status_code: int, json_payload=None, text: str = "") -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_payload if json_payload is not None else []
    m.text = text or (str(json_payload) if json_payload else "")
    return m


def _fake_position(symbol: str = "AMD", qty: float = 33, side: str = "long",
                   market_value: float = 14000.0) -> dict:
    return {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "market_value": str(market_value),
        "avg_entry_price": "440.0",
        "current_price": "450.0",
    }


def _bracket_orders(symbol: str = "AMD", parent_id: str = "p-1",
                    leg_ids=("leg-tp", "leg-sl")) -> list:
    """Mimic Alpaca's open orders JSON with bracket parent + 2 OCO children."""
    legs = [{"id": lid, "symbol": symbol, "side": "sell"} for lid in leg_ids]
    return [{
        "id": parent_id,
        "symbol": symbol,
        "status": "held",
        "order_class": "bracket",
        "legs": legs,
    }]


def _set_creds(env):
    env["ALPACA_API_KEY"] = "test-key"
    env["ALPACA_SECRET_KEY"] = "test-sec"


class TestSafeCloseBracketCancelDefault(unittest.TestCase):
    """v3.11.3 default behavior: cancel_brackets_first=True."""

    @patch.dict(os.environ, {}, clear=False)
    def test_brackets_canceled_before_post_close(self):
        _set_creds(os.environ)
        # Reload to pick env creds (module reads at import time but headers re-read).
        import alpaca_orders
        import importlib
        importlib.reload(alpaca_orders)

        with patch.object(alpaca_orders, "_fetch_single_position", return_value=_fake_position()), \
             patch.object(alpaca_orders, "requests") as rq:
            # 1) GET /v2/orders?symbols=AMD&status=open → returns bracket parent
            # 2) DELETE /v2/orders/p-1 → 204 No Content (success)
            # 3) POST /v2/orders → 200 + filled response
            rq.get.return_value    = _make_response(200, _bracket_orders())
            rq.delete.return_value = _make_response(204, None, "")
            rq.post.return_value   = _make_response(200, {"id": "ord-final-1", "status": "accepted"})

            sc = alpaca_orders.safe_close(
                symbol="AMD",
                intent_qty=33,
                intent_side="sell",
                reason_tag="exit-governor",
                order_type="market",
                allow_market=True,
            )

            # Assertions
            self.assertEqual(sc["status"], "placed", f"expected placed, got {sc}")
            self.assertEqual(sc.get("brackets_checked"), 1)
            self.assertIn("p-1", sc.get("brackets_canceled", []))
            self.assertEqual(sc.get("brackets_failed"), [])

            # GET orders called BEFORE post
            self.assertGreaterEqual(rq.get.call_count, 1)
            self.assertEqual(rq.delete.call_count, 1, "should have canceled bracket parent once")
            self.assertEqual(rq.post.call_count, 1, "should have placed close once")

    def test_position_without_open_orders_proceeds_directly(self):
        import alpaca_orders, importlib
        _set_creds(os.environ)
        importlib.reload(alpaca_orders)
        with patch.object(alpaca_orders, "_fetch_single_position", return_value=_fake_position()), \
             patch.object(alpaca_orders, "requests") as rq:
            rq.get.return_value    = _make_response(200, [])   # no open orders
            rq.delete.return_value = _make_response(204)
            rq.post.return_value   = _make_response(200, {"id": "ord-final-2"})

            sc = alpaca_orders.safe_close(
                symbol="AMD", intent_qty=33, intent_side="sell",
                reason_tag="alloc-exit", order_type="market", allow_market=True,
            )
            self.assertEqual(sc["status"], "placed")
            self.assertEqual(sc.get("brackets_checked"), 0)
            self.assertEqual(sc.get("brackets_canceled"), [])
            # Delete should NOT have been called for any order id
            self.assertEqual(rq.delete.call_count, 0)


class TestSafeCloseBracketCancelDisabled(unittest.TestCase):
    """cancel_brackets_first=False preserves pre-v3.11.3 behavior."""

    def test_no_cancel_when_disabled(self):
        import alpaca_orders, importlib
        _set_creds(os.environ)
        importlib.reload(alpaca_orders)
        with patch.object(alpaca_orders, "_fetch_single_position", return_value=_fake_position()), \
             patch.object(alpaca_orders, "requests") as rq:
            # Even though bracket exists, we explicitly disable cancel-first
            rq.get.return_value = _make_response(200, _bracket_orders())
            rq.delete.return_value = _make_response(204)
            rq.post.return_value = _make_response(200, {"id": "ord-final-3"})

            sc = alpaca_orders.safe_close(
                symbol="AMD", intent_qty=33, intent_side="sell",
                reason_tag="alloc-exit", order_type="market", allow_market=True,
                cancel_brackets_first=False,
            )
            self.assertEqual(sc["status"], "placed")
            # No GET orders, no DELETE
            self.assertEqual(rq.get.call_count, 0)
            self.assertEqual(rq.delete.call_count, 0)


class TestSafeCloseCancelFailSoft(unittest.TestCase):
    """Cancel cascade error must NOT block the close attempt (fail-soft)."""

    def test_cancel_get_500_still_attempts_close(self):
        import alpaca_orders, importlib
        _set_creds(os.environ)
        importlib.reload(alpaca_orders)
        with patch.object(alpaca_orders, "_fetch_single_position", return_value=_fake_position()), \
             patch.object(alpaca_orders, "requests") as rq:
            rq.get.return_value    = _make_response(500, [], "Alpaca down")
            rq.delete.return_value = _make_response(204)  # not called
            # Subsequent POST 403 because brackets still hold qty — surface clean reason
            rq.post.return_value = _make_response(403, {}, '{"code":40310000,"available":"0","held_for_orders":"33"}')

            sc = alpaca_orders.safe_close(
                symbol="AMD", intent_qty=33, intent_side="sell",
                reason_tag="exit-governor", order_type="market", allow_market=True,
            )
            # Cancel failed but close still attempted, surfaces 403 clearly
            self.assertEqual(sc["status"], "failed")
            self.assertIn("403", sc["reason"])
            # brackets_failed should be empty (no DELETE attempted) but checked=0
            self.assertEqual(sc.get("brackets_checked"), 0)
            self.assertEqual(rq.post.call_count, 1)

    def test_cancel_delete_403_still_attempts_close(self):
        import alpaca_orders, importlib
        _set_creds(os.environ)
        importlib.reload(alpaca_orders)
        with patch.object(alpaca_orders, "_fetch_single_position", return_value=_fake_position()), \
             patch.object(alpaca_orders, "requests") as rq:
            rq.get.return_value    = _make_response(200, _bracket_orders())
            # Bracket cancel refused (e.g. partially filled) — DELETE returns 422
            rq.delete.return_value = _make_response(422, {}, "order cannot be canceled")
            rq.post.return_value   = _make_response(200, {"id": "ord-final-4"})

            sc = alpaca_orders.safe_close(
                symbol="AMD", intent_qty=33, intent_side="sell",
                reason_tag="exit-governor", order_type="market", allow_market=True,
            )
            # Close still placed
            self.assertEqual(sc["status"], "placed")
            self.assertEqual(sc.get("brackets_canceled"), [])
            self.assertEqual(len(sc.get("brackets_failed", [])), 1)
            self.assertEqual(sc["brackets_failed"][0]["status"], 422)


class TestSafeCloseCryptoSkipsCancel(unittest.TestCase):
    """Crypto has no OCO support — cancel_brackets_first should not call Alpaca."""

    def test_crypto_skips_bracket_cancel(self):
        import alpaca_orders, importlib
        _set_creds(os.environ)
        importlib.reload(alpaca_orders)
        crypto_pos = _fake_position(symbol="BTC/USD", qty=0.5)
        with patch.object(alpaca_orders, "_fetch_single_position", return_value=crypto_pos), \
             patch.object(alpaca_orders, "requests") as rq:
            rq.post.return_value = _make_response(200, {"id": "btc-1"})
            sc = alpaca_orders.safe_close(
                symbol="BTC/USD", intent_qty=0.5, intent_side="sell",
                reason_tag="alloc-exit", order_type="market", is_crypto=True, allow_market=True,
            )
            self.assertEqual(sc["status"], "placed")
            # No GET orders / DELETE for crypto
            self.assertEqual(rq.get.call_count, 0)
            self.assertEqual(rq.delete.call_count, 0)
            self.assertEqual(sc.get("brackets_checked"), 0)


class TestSafeClosePositionGoneShortCircuit(unittest.TestCase):
    """Position 404 still short-circuits — no GET/DELETE/POST."""

    def test_position_not_found(self):
        import alpaca_orders, importlib
        _set_creds(os.environ)
        importlib.reload(alpaca_orders)
        with patch.object(alpaca_orders, "_fetch_single_position", return_value=None), \
             patch.object(alpaca_orders, "requests") as rq:
            sc = alpaca_orders.safe_close(
                symbol="GONE", intent_qty=1, intent_side="sell",
                reason_tag="alloc-exit", order_type="market", allow_market=True,
            )
            self.assertEqual(sc["status"], "skipped")
            self.assertIn("not found", sc["reason"])
            # No HTTP calls at all
            self.assertEqual(rq.get.call_count, 0)
            self.assertEqual(rq.delete.call_count, 0)
            self.assertEqual(rq.post.call_count, 0)


class TestCancelHelperLegsMatch(unittest.TestCase):
    """_cancel_open_orders_for_symbol matches by parent.symbol OR leg.symbol."""

    def test_matches_via_leg_symbol(self):
        import alpaca_orders, importlib
        _set_creds(os.environ)
        importlib.reload(alpaca_orders)
        # Parent uses generic symbol field but child legs reference the target
        orders = [{
            "id": "parent-x",
            "symbol": "MSFT",       # parent's bracket "wrapper" symbol may differ in nested format
            "legs": [{"id": "leg-1", "symbol": "AMD"}],
        }]
        with patch.object(alpaca_orders, "requests") as rq:
            rq.get.return_value    = _make_response(200, orders)
            rq.delete.return_value = _make_response(204)
            out = alpaca_orders._cancel_open_orders_for_symbol("AMD")
            self.assertEqual(out["checked"], 1)
            self.assertIn("parent-x", out["canceled"])

    def test_404_treated_as_canceled(self):
        import alpaca_orders, importlib
        _set_creds(os.environ)
        importlib.reload(alpaca_orders)
        with patch.object(alpaca_orders, "requests") as rq:
            rq.get.return_value    = _make_response(200, _bracket_orders())
            rq.delete.return_value = _make_response(404, {}, "Already gone")
            out = alpaca_orders._cancel_open_orders_for_symbol("AMD")
            self.assertEqual(out["checked"], 1)
            self.assertIn("p-1", out["canceled"])
            self.assertEqual(out["failed"], [])


class TestP13BracketInterlockDetector(unittest.TestCase):
    """Pattern P13 fires when ≥3 CLOSE_POSITION FAILED with 403/insufficient."""

    def _make_event(self, ts_iso: str, symbol: str, decision_type="CLOSE_POSITION",
                    decision="FAILED", reason="safe_close: Alpaca 403: insufficient qty available"):
        return {
            "timestamp": ts_iso,
            "decision_type": decision_type,
            "decision": decision,
            "reason": reason,
            "affected_symbols": [symbol],
        }

    def test_fires_on_three_failures_in_30min(self):
        import incident_pattern_detector as ipd
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        events = [
            self._make_event((now - timedelta(minutes=5)).isoformat(), "AMD"),
            self._make_event((now - timedelta(minutes=10)).isoformat(), "QQQ"),
            self._make_event((now - timedelta(minutes=15)).isoformat(), "SPY"),
        ]
        findings = ipd.p13_bracket_interlock_blocked_close(events)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["pattern"], "P13_bracket_interlock_blocked_close")
        self.assertEqual(findings[0]["severity"], "CRITICAL")

    def test_does_not_fire_below_threshold(self):
        import incident_pattern_detector as ipd
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        events = [
            self._make_event((now - timedelta(minutes=5)).isoformat(), "AMD"),
            self._make_event((now - timedelta(minutes=10)).isoformat(), "QQQ"),
        ]
        self.assertEqual(ipd.p13_bracket_interlock_blocked_close(events), [])

    def test_old_events_excluded(self):
        import incident_pattern_detector as ipd
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        events = [
            self._make_event((now - timedelta(minutes=45)).isoformat(), "AMD"),
            self._make_event((now - timedelta(minutes=50)).isoformat(), "QQQ"),
            self._make_event((now - timedelta(minutes=55)).isoformat(), "SPY"),
        ]
        self.assertEqual(ipd.p13_bracket_interlock_blocked_close(events), [])

    def test_unrelated_failure_reasons_ignored(self):
        import incident_pattern_detector as ipd
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        # Failures, but NOT bracket-interlock signature
        events = [
            self._make_event((now - timedelta(minutes=5)).isoformat(), "AMD",
                              reason="safe_close: connection timeout"),
            self._make_event((now - timedelta(minutes=10)).isoformat(), "QQQ",
                              reason="safe_close: position malformed data"),
            self._make_event((now - timedelta(minutes=15)).isoformat(), "SPY",
                              reason="safe_close: invalid intent_side 'X'"),
        ]
        self.assertEqual(ipd.p13_bracket_interlock_blocked_close(events), [])


if __name__ == "__main__":
    unittest.main()
