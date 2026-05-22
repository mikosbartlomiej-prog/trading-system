"""
Tests for v3.9.6 (2026-05-22) — RECREATE_EXIT_PLAN refactor.

Verifies:
  - place_oco_exit happy path + reject conditions
  - _do_recreate_exit_plan fetches position + computes correct TP/SL
  - REMEDIATION_DISABLE_RECREATE env flag honored
  - Options + crypto are skipped (asset-class aware)
  - Audit emission produces SKIPPED for skip path (not FAILED)

Replaces the 2026-05-22 incident behavior where _do_recreate_exit_plan
would MARKET CLOSE the position instead of restoring protection.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))


class TestPlaceOcoExitGuards(unittest.TestCase):
    def test_rejects_qty_zero(self):
        from alpaca_orders import place_oco_exit
        self.assertIsNone(place_oco_exit("AMD", 0, 450.0, 400.0))

    def test_rejects_negative_prices(self):
        from alpaca_orders import place_oco_exit
        self.assertIsNone(place_oco_exit("AMD", 38, -1.0, 400.0))
        self.assertIsNone(place_oco_exit("AMD", 38, 450.0, 0.0))

    def test_rejects_bad_side(self):
        from alpaca_orders import place_oco_exit
        self.assertIsNone(place_oco_exit("AMD", 38, 450.0, 400.0, side="buy"))

    def test_rejects_inverted_tp_sl_long(self):
        """Long exit (side=sell): TP must be > SL or reject."""
        from alpaca_orders import place_oco_exit
        # TP=400 SL=450 — inverted (would mean selling at LOSS as TP)
        self.assertIsNone(place_oco_exit("AMD", 38, 400.0, 450.0, side="sell"))

    def test_rejects_inverted_tp_sl_short(self):
        """Short exit (side=buy_to_cover): TP must be < SL or reject."""
        from alpaca_orders import place_oco_exit
        # TP=500 SL=400 — inverted for short
        self.assertIsNone(place_oco_exit("AMD", 38, 500.0, 400.0, side="buy_to_cover"))


class TestPlaceOcoExitPayload(unittest.TestCase):
    """Verify the actual HTTP payload sent to Alpaca matches OCO spec."""

    def test_payload_shape(self):
        import alpaca_orders

        captured = {}
        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["payload"] = json
            resp = MagicMock()
            resp.status_code = 201
            resp.json = lambda: {"id": "oco-test-123", "client_order_id": json.get("client_order_id")}
            return resp

        with patch.object(alpaca_orders, "requests") as rq:
            rq.post = fake_post
            rq.RequestException = Exception
            result = alpaca_orders.place_oco_exit("AMD", 38, 520.0, 414.0,
                                                    side="sell")

        self.assertIsNotNone(result)
        p = captured["payload"]
        self.assertEqual(p["symbol"], "AMD")
        self.assertEqual(p["qty"], "38")
        self.assertEqual(p["side"], "sell")
        self.assertEqual(p["type"], "limit")
        self.assertEqual(p["limit_price"], "520.0")
        self.assertEqual(p["time_in_force"], "gtc")  # CRITICAL — survives sessions
        self.assertEqual(p["order_class"], "oco")
        self.assertEqual(p["stop_loss"]["stop_price"], "414.0")
        self.assertTrue(p["client_order_id"].startswith("recreate-exit-AMD-"))


class TestRecreateExitPlanEnvFlag(unittest.TestCase):
    def test_disabled_returns_skipped(self):
        """REMEDIATION_DISABLE_RECREATE=true should skip without calling Alpaca."""
        import remediation
        action = remediation.RemediationAction(
            action="RECREATE_EXIT_PLAN", subject="AMD",
            reason="position has no exit order", severity="WARN",
        )

        with patch.dict(os.environ, {"REMEDIATION_DISABLE_RECREATE": "true"}, clear=False):
            result = remediation._do_recreate_exit_plan(action)

        self.assertFalse(result["ok"])
        self.assertTrue(result.get("skipped"))
        self.assertIn("REMEDIATION_DISABLE_RECREATE", result["reason"])


class TestRecreateExitPlanLogic(unittest.TestCase):
    def _action(self, sym="AMD"):
        import remediation
        return remediation.RemediationAction(
            action="RECREATE_EXIT_PLAN", subject=sym,
            reason="position has no exit order", severity="WARN",
        )

    def test_no_position_returns_failure(self):
        import remediation
        with patch.dict(os.environ, {"REMEDIATION_DISABLE_RECREATE": "false"}), \
             patch("alpaca_orders._fetch_single_position", return_value=None):
            result = remediation._do_recreate_exit_plan(self._action("AMD"))
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["reason"])

    def test_options_symbol_skipped(self):
        """Option symbols (long, contains digits) should be skipped."""
        import remediation
        opt_sym = "AAPL260518P00295000"  # 21-char Alpaca option symbol
        with patch.dict(os.environ, {"REMEDIATION_DISABLE_RECREATE": "false"}), \
             patch("alpaca_orders._fetch_single_position",
                    return_value={"qty": "1", "avg_entry_price": "5.0", "side": "long"}):
            result = remediation._do_recreate_exit_plan(self._action(opt_sym))
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("skipped"))
        self.assertIn("option", result["reason"].lower())

    def test_crypto_symbol_skipped(self):
        """Crypto (contains /) should be skipped — Alpaca paper no OCO crypto."""
        import remediation
        with patch.dict(os.environ, {"REMEDIATION_DISABLE_RECREATE": "false"}), \
             patch("alpaca_orders._fetch_single_position",
                    return_value={"qty": "0.5", "avg_entry_price": "70000.0", "side": "long"}):
            result = remediation._do_recreate_exit_plan(self._action("BTC/USD"))
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("skipped"))
        self.assertIn("crypto", result["reason"].lower())

    def test_long_stock_position_places_oco(self):
        """Long stock position: TP @ +18%, SL @ -6% (stocks_etf defaults)."""
        import remediation
        captured = {}

        def fake_place(symbol, qty, tp, sl, side="sell", client_order_id_prefix="recreate-exit"):
            captured.update({"symbol": symbol, "qty": qty, "tp": tp, "sl": sl, "side": side})
            return {"id": "oco-123", "client_order_id": f"{client_order_id_prefix}-{symbol}-1234"}

        with patch.dict(os.environ, {"REMEDIATION_DISABLE_RECREATE": "false"}), \
             patch("alpaca_orders._fetch_single_position",
                    return_value={"qty": "38", "avg_entry_price": "440.87", "side": "long"}), \
             patch("alpaca_orders.place_oco_exit", side_effect=fake_place):
            result = remediation._do_recreate_exit_plan(self._action("AMD"))

        self.assertTrue(result["ok"], msg=f"result={result}")
        self.assertEqual(result["symbol"], "AMD")
        self.assertEqual(result["qty"], 38)
        # TP = 440.87 * 1.18 = 520.23
        self.assertAlmostEqual(result["tp_price"], 520.23, places=1)
        # SL = 440.87 * 0.94 = 414.42
        self.assertAlmostEqual(result["sl_price"], 414.42, places=1)
        self.assertEqual(captured["side"], "sell")

    def test_short_stock_position_places_inverted_oco(self):
        """Short position: TP @ -18% (cover lower), SL @ +6% (cover higher)."""
        import remediation
        captured = {}

        def fake_place(symbol, qty, tp, sl, side="sell", client_order_id_prefix="recreate-exit"):
            captured.update({"side": side, "tp": tp, "sl": sl})
            return {"id": "oco-456"}

        with patch.dict(os.environ, {"REMEDIATION_DISABLE_RECREATE": "false"}), \
             patch("alpaca_orders._fetch_single_position",
                    return_value={"qty": "10", "avg_entry_price": "100.0", "side": "short"}), \
             patch("alpaca_orders.place_oco_exit", side_effect=fake_place):
            result = remediation._do_recreate_exit_plan(self._action("SQQQ"))

        self.assertTrue(result["ok"], msg=f"result={result}")
        # TP = 100 * 0.82 = 82.00 (short profits when price falls)
        self.assertAlmostEqual(captured["tp"], 82.00, places=1)
        # SL = 100 * 1.06 = 106.00 (short loses when price rises)
        self.assertAlmostEqual(captured["sl"], 106.00, places=1)
        self.assertEqual(captured["side"], "buy_to_cover")


class TestBracketGTC(unittest.TestCase):
    """Verify place_stock_bracket now uses GTC TIF (v3.9.6 fix)."""

    def test_bracket_payload_uses_gtc(self):
        import alpaca_orders

        captured = {}
        def fake_post(url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            resp = MagicMock()
            resp.status_code = 201
            resp.json = lambda: {"id": "bracket-test"}
            return resp

        # Bypass risk gates by patching them
        with patch.object(alpaca_orders, "requests") as rq, \
             patch("alpaca_orders.can_trade_now", return_value=(True, "ok"), create=True) \
                 if False else patch("instrument_windows.can_trade_now",
                                      return_value=(True, "ok")), \
             patch("alpaca_orders._portfolio_risk_gate",
                    return_value=(True, [], [])), \
             patch("alpaca_orders._intraday_governor_gate",
                    return_value=(True, "ok")), \
             patch("alpaca_orders._pdt_gate", return_value=(True, "ok")), \
             patch("alpaca_orders.evaluate_trade", create=True,
                    return_value={"decision": "APPROVE", "warnings": []}):
            rq.post = fake_post
            rq.RequestException = Exception
            result = alpaca_orders.place_stock_bracket(
                "AMD", "buy", qty=38, entry_price=440.87,
                stop_loss=414.42, take_profit=520.23,
                strategy="allocator-rebalance",
            )

        self.assertIsNotNone(result)
        self.assertEqual(captured["payload"]["time_in_force"], "gtc",
                          msg="v3.9.6 must use GTC for bracket children to survive sessions")
        self.assertEqual(captured["payload"]["order_class"], "bracket")


if __name__ == "__main__":
    unittest.main()
