"""
Tests for shared.pdt_guard v3.8 — intent-aware decision matrix.

Coverage:
  - Mode classification (OK / CAUTION / RESTRICTED / LOCKED / UNKNOWN)
    with v3.8 thresholds (caution=1, restricted=2, lock=3)
  - evaluate_order() per (action, asset_class, mode, intent, same_day, emergency)
  - OPEN actions never block on PDT count (BP gate only)
  - OPEN intraday-intent blocked in RESTRICTED+
  - CLOSE crypto always allowed
  - CLOSE overnight position always allowed
  - CLOSE same-day budget-aware
  - Emergency CLOSE always allowed (except absolute BP-zero)
  - Fail-soft on Alpaca unreachable
  - Audit emission

All tests use mocks; no real Alpaca calls.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

import pdt_guard  # noqa: E402
from pdt_guard import (  # noqa: E402
    PDTSnapshot,
    evaluate_order,
    get_pdt_status,
    is_potential_day_trade,
    _classify_mode,
    _load_pdt_config,
    _is_crypto,
    INTENT_SWING,
    INTENT_INTRADAY,
    INTENT_EMERGENCY,
)


def _mk_account(equity=94_000.0, bp=346_000.0, dt=0, pdt_flag=False):
    """Helper: shape of GET /v2/account response."""
    return {
        "equity":               str(equity),
        "buying_power":         str(bp),
        "daytrade_count":       str(dt),
        "pattern_day_trader":   pdt_flag,
    }


def _snap(mode="OK", dt_used=0, bp=346_000, equity=94_000):
    return PDTSnapshot(
        equity=float(equity), buying_power=float(bp),
        daytrade_count=int(dt_used), pattern_day_trader=(dt_used > 0),
        dt_limit=3, dt_remaining=max(0, 3 - dt_used),
        bp_pct_equity=(bp / equity * 100.0) if equity > 0 else 0.0,
        mode=mode,
        classified_at="2026-05-14T20:00:00+00:00",
        reason=f"test mode {mode}",
    )


# ─── Mode classification (v3.8 thresholds) ───────────────────────────────────


class TestModeClassificationV38(unittest.TestCase):
    """v3.8 thresholds: caution=1, restricted=2, lock=3."""

    def setUp(self):
        self.cfg = {
            "dt_limit":            3,
            "dt_caution_at":       1,
            "dt_restricted_at":    2,
            "bp_floor_pct":        0.05,
            "bp_hard_floor_usd":   100.0,
            "enabled":             True,
            "swing_max_pct_equity": 0.20,
        }

    def test_dt0_is_ok(self):
        mode, _, remain = _classify_mode(
            daytrade_count=0, is_pdt=False, bp=50_000, equity=94_000,
            size_usd=2_000, cfg=self.cfg,
        )
        self.assertEqual(mode, "OK")
        self.assertEqual(remain, 3)

    def test_dt1_is_caution(self):
        mode, reason, remain = _classify_mode(
            daytrade_count=1, is_pdt=False, bp=50_000, equity=94_000,
            size_usd=2_000, cfg=self.cfg,
        )
        self.assertEqual(mode, "CAUTION")
        self.assertEqual(remain, 2)
        self.assertIn("daytrade_count 1", reason)

    def test_dt2_is_restricted(self):
        mode, reason, remain = _classify_mode(
            daytrade_count=2, is_pdt=True, bp=20_000, equity=94_000,
            size_usd=2_000, cfg=self.cfg,
        )
        self.assertEqual(mode, "RESTRICTED")
        self.assertEqual(remain, 1)
        self.assertIn("save last slot", reason)

    def test_dt3_is_locked(self):
        mode, _, remain = _classify_mode(
            daytrade_count=3, is_pdt=True, bp=20_000, equity=94_000,
            size_usd=2_000, cfg=self.cfg,
        )
        self.assertEqual(mode, "LOCKED")
        self.assertEqual(remain, 0)

    def test_dt4_is_locked(self):
        # Current real account state (dt=4)
        mode, _, _ = _classify_mode(
            daytrade_count=4, is_pdt=True, bp=346_000, equity=94_000,
            size_usd=10_000, cfg=self.cfg,
        )
        self.assertEqual(mode, "LOCKED")

    def test_locked_via_bp_hard_floor(self):
        # BP exhausted even with low DT count → LOCKED
        mode, _, _ = _classify_mode(
            daytrade_count=0, is_pdt=False, bp=50, equity=94_000,
            size_usd=0, cfg=self.cfg,
        )
        self.assertEqual(mode, "LOCKED")

    def test_caution_via_low_bp_pct_at_dt0(self):
        # dt=0 but BP < 5% of equity → CAUTION (not OK)
        mode, _, _ = _classify_mode(
            daytrade_count=0, is_pdt=False, bp=2_000, equity=94_000,
            size_usd=0, cfg=self.cfg,
        )
        self.assertEqual(mode, "CAUTION")


# ─── Crypto detection ────────────────────────────────────────────────────────


class TestCryptoDetection(unittest.TestCase):

    def test_btc_usd_is_crypto(self):
        self.assertTrue(_is_crypto("BTC/USD"))

    def test_eth_usd_is_crypto(self):
        self.assertTrue(_is_crypto("ETH/USD"))

    def test_aapl_is_not_crypto(self):
        self.assertFalse(_is_crypto("AAPL"))

    def test_option_symbol_is_not_crypto(self):
        self.assertFalse(_is_crypto("AAPL260520P00295000"))

    def test_empty_symbol_is_not_crypto(self):
        self.assertFalse(_is_crypto(""))


# ─── evaluate_order: OPEN actions (v3.8 — never blocked by PDT count) ────────


class TestEvaluateOpenActions(unittest.TestCase):

    def test_open_stock_in_locked_allowed_when_bp_ok(self):
        """v3.8 KEY behavior: LOCKED does NOT block opens (only BP matters)."""
        v = evaluate_order("OPEN", "AAPL", "buy", 10_000,
                           intent=INTENT_SWING,
                           snapshot=_snap("LOCKED", dt_used=3, bp=50_000))
        self.assertEqual(v["decision"], "ALLOW")
        self.assertEqual(v["dt_impact"], 0)
        self.assertIn("OPEN allowed", v["reason"])

    def test_open_stock_blocked_when_bp_insufficient(self):
        v = evaluate_order("OPEN", "AAPL", "buy", 10_000,
                           intent=INTENT_SWING,
                           snapshot=_snap("OK", dt_used=0, bp=500))
        self.assertEqual(v["decision"], "BLOCK")
        self.assertIn("BP $500", v["reason"])

    def test_open_intraday_intent_deferred_in_restricted(self):
        """RESTRICTED + intraday intent → DEFER (would burn saved slot)."""
        v = evaluate_order("OPEN", "AAPL", "buy", 10_000,
                           intent=INTENT_INTRADAY,
                           snapshot=_snap("RESTRICTED", dt_used=2, bp=50_000))
        self.assertEqual(v["decision"], "DEFER")
        self.assertIn("intraday-intent blocked", v["reason"])
        self.assertIn("swing", v["reason"])

    def test_open_intraday_intent_deferred_in_locked(self):
        v = evaluate_order("OPEN", "AAPL", "buy", 10_000,
                           intent=INTENT_INTRADAY,
                           snapshot=_snap("LOCKED", dt_used=3, bp=50_000))
        self.assertEqual(v["decision"], "DEFER")

    def test_open_swing_intent_allowed_in_restricted(self):
        v = evaluate_order("OPEN", "AAPL", "buy", 10_000,
                           intent=INTENT_SWING,
                           snapshot=_snap("RESTRICTED", dt_used=2, bp=50_000))
        self.assertEqual(v["decision"], "ALLOW")

    def test_open_crypto_always_allowed(self):
        v = evaluate_order("OPEN", "BTC/USD", "buy", 5_000,
                           intent=INTENT_SWING,
                           snapshot=_snap("LOCKED", dt_used=3, bp=10_000))
        self.assertEqual(v["decision"], "ALLOW")
        self.assertIn("crypto exempt", v["reason"])

    def test_open_at_caution_mode_allowed(self):
        v = evaluate_order("OPEN", "AAPL", "buy", 10_000,
                           intent=INTENT_INTRADAY,
                           snapshot=_snap("CAUTION", dt_used=1, bp=50_000))
        # CAUTION does NOT defer intraday opens (only RESTRICTED+ does)
        self.assertEqual(v["decision"], "ALLOW")


# ─── evaluate_order: CLOSE actions ───────────────────────────────────────────


class TestEvaluateCloseCryptoAlwaysAllowed(unittest.TestCase):

    def test_close_crypto_in_locked(self):
        v = evaluate_order("CLOSE", "BTC/USD", "sell", 5_000,
                           snapshot=_snap("LOCKED", dt_used=3, bp=10_000))
        self.assertEqual(v["decision"], "ALLOW")

    def test_close_crypto_in_restricted(self):
        v = evaluate_order("CLOSE", "ETH/USD", "sell", 2_000,
                           snapshot=_snap("RESTRICTED", dt_used=2))
        self.assertEqual(v["decision"], "ALLOW")


class TestEvaluateCloseOvernightAlwaysAllowed(unittest.TestCase):
    """Position opened on prior day → no DT impact regardless of mode."""

    def test_close_overnight_in_locked(self):
        with patch.object(pdt_guard, "is_potential_day_trade", return_value=False):
            v = evaluate_order("CLOSE", "AAPL", "sell", 10_000,
                               snapshot=_snap("LOCKED", dt_used=3))
        self.assertEqual(v["decision"], "ALLOW")
        self.assertEqual(v["dt_impact"], 0)
        self.assertIn("overnight", v["reason"].lower())

    def test_close_overnight_in_restricted(self):
        with patch.object(pdt_guard, "is_potential_day_trade", return_value=False):
            v = evaluate_order("CLOSE", "AAPL", "sell", 10_000,
                               snapshot=_snap("RESTRICTED", dt_used=2))
        self.assertEqual(v["decision"], "ALLOW")
        self.assertEqual(v["dt_impact"], 0)


class TestEvaluateCloseSameDayBudgetAware(unittest.TestCase):
    """CLOSE of today-opened stock is budget-aware."""

    def test_same_day_close_in_ok_allowed(self):
        v = evaluate_order("CLOSE", "AAPL", "sell", 10_000,
                           snapshot=_snap("OK", dt_used=0),
                           skip_intraday_check=True)
        self.assertEqual(v["decision"], "ALLOW")
        self.assertEqual(v["dt_impact"], 1)

    def test_same_day_close_in_caution_allowed_with_after_count(self):
        v = evaluate_order("CLOSE", "AAPL", "sell", 10_000,
                           snapshot=_snap("CAUTION", dt_used=1),
                           skip_intraday_check=True)
        self.assertEqual(v["decision"], "ALLOW")
        self.assertIn("CAUTION", v["reason"])

    def test_same_day_close_in_restricted_deferred(self):
        """RESTRICTED + same-day close non-emergency → DEFER (save slot)."""
        v = evaluate_order("CLOSE", "AAPL", "sell", 10_000,
                           is_emergency=False,
                           snapshot=_snap("RESTRICTED", dt_used=2),
                           skip_intraday_check=True)
        self.assertEqual(v["decision"], "DEFER")
        self.assertIn("save last DT slot", v["reason"])

    def test_same_day_close_in_locked_blocked(self):
        v = evaluate_order("CLOSE", "AAPL", "sell", 10_000,
                           is_emergency=False,
                           snapshot=_snap("LOCKED", dt_used=3),
                           skip_intraday_check=True)
        self.assertEqual(v["decision"], "BLOCK")


class TestEvaluateEmergencyAlwaysAllowed(unittest.TestCase):
    """Emergency closes bypass all DEFER/BLOCK."""

    def test_emergency_in_restricted(self):
        v = evaluate_order("CLOSE", "AAPL", "sell", 10_000,
                           is_emergency=True,
                           snapshot=_snap("RESTRICTED", dt_used=2),
                           skip_intraday_check=True)
        self.assertEqual(v["decision"], "ALLOW")
        self.assertIn("emergency honored", v["reason"].lower())

    def test_emergency_in_locked(self):
        v = evaluate_order("CLOSE", "AAPL", "sell", 10_000,
                           is_emergency=True,
                           snapshot=_snap("LOCKED", dt_used=3),
                           skip_intraday_check=True)
        self.assertEqual(v["decision"], "ALLOW")

    def test_emergency_overnight_in_locked(self):
        with patch.object(pdt_guard, "is_potential_day_trade", return_value=False):
            v = evaluate_order("CLOSE", "AAPL", "sell", 10_000,
                               is_emergency=True,
                               snapshot=_snap("LOCKED", dt_used=3))
        self.assertEqual(v["decision"], "ALLOW")


# ─── UNKNOWN mode (fail-soft) ────────────────────────────────────────────────


class TestUnknownMode(unittest.TestCase):

    def test_unknown_open_allows(self):
        snap = PDTSnapshot(
            equity=0.0, buying_power=0.0, daytrade_count=0,
            pattern_day_trader=False, dt_limit=3, dt_remaining=3,
            bp_pct_equity=0.0, mode="UNKNOWN",
            classified_at="2026-05-14T20:00:00+00:00",
            reason="account unreachable",
        )
        v = evaluate_order("OPEN", "AAPL", "buy", 10_000, snapshot=snap)
        self.assertEqual(v["decision"], "ALLOW")

    def test_unknown_close_allows(self):
        snap = PDTSnapshot(
            equity=0.0, buying_power=0.0, daytrade_count=0,
            pattern_day_trader=False, dt_limit=3, dt_remaining=3,
            bp_pct_equity=0.0, mode="UNKNOWN",
            classified_at="2026-05-14T20:00:00+00:00",
            reason="account unreachable",
        )
        v = evaluate_order("CLOSE", "AAPL", "sell", 10_000, snapshot=snap)
        self.assertEqual(v["decision"], "ALLOW")


# ─── Disabled config ─────────────────────────────────────────────────────────


class TestDisabledConfig(unittest.TestCase):

    def test_disabled_allows_everything(self):
        with patch.object(pdt_guard, "_load_pdt_config", return_value={
            "dt_limit": 3, "dt_caution_at": 1, "dt_restricted_at": 2,
            "bp_floor_pct": 0.05, "bp_hard_floor_usd": 100.0,
            "enabled": False, "swing_max_pct_equity": 0.20,
        }):
            v = evaluate_order("CLOSE", "AAPL", "sell", 10_000,
                               snapshot=_snap("LOCKED", dt_used=4),
                               skip_intraday_check=True)
        self.assertEqual(v["decision"], "ALLOW")
        self.assertIn("disabled", v["reason"])


# ─── Snapshot fetch ──────────────────────────────────────────────────────────


class TestGetPdtStatus(unittest.TestCase):

    def test_fail_soft_when_account_unreachable(self):
        with patch.object(pdt_guard, "_fetch_account", return_value=None):
            snap = get_pdt_status(size_usd=1_000)
        self.assertEqual(snap.mode, "UNKNOWN")

    def test_classifies_from_passed_account(self):
        snap = get_pdt_status(account=_mk_account(equity=94_000, bp=20_000, dt=0))
        self.assertEqual(snap.mode, "OK")

    def test_real_locked_account_state(self):
        """Real production state: dt=4, BP=$346k → LOCKED."""
        snap = get_pdt_status(account=_mk_account(equity=94_598, bp=346_972, dt=4, pdt_flag=True))
        self.assertEqual(snap.mode, "LOCKED")
        self.assertEqual(snap.dt_remaining, 0)


# ─── is_potential_day_trade ──────────────────────────────────────────────────


class TestPotentialDayTrade(unittest.TestCase):

    def test_crypto_is_never_pdt(self):
        # No Alpaca call needed for crypto
        self.assertFalse(is_potential_day_trade("BTC/USD"))

    def test_returns_true_when_filled_open_today(self):
        with patch.object(pdt_guard, "_fetch_today_filled_orders",
                          return_value=[{"status": "filled", "side": "buy"}]):
            self.assertTrue(is_potential_day_trade("AAPL"))

    def test_returns_false_when_no_fills(self):
        with patch.object(pdt_guard, "_fetch_today_filled_orders", return_value=[]):
            self.assertFalse(is_potential_day_trade("AAPL"))

    def test_empty_symbol_returns_false(self):
        self.assertFalse(is_potential_day_trade(""))


# ─── Audit emission ──────────────────────────────────────────────────────────


class TestAuditEmission(unittest.TestCase):

    def test_emits_for_defer(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["AUDIT_TRADING_DIR"] = td
            verdict = {
                "decision": "DEFER", "mode": "RESTRICTED",
                "dt_remaining": 1, "dt_impact": 1, "intent": "swing",
                "reason": "test defer",
            }
            pdt_guard.record_decision(verdict, "CLOSE", "AAPL")
            files = list(Path(td).glob("*.jsonl"))
            self.assertTrue(files)
            rec = json.loads(files[0].read_text().strip().splitlines()[0])
            self.assertEqual(rec["decision"], "PDT_DEFER")
            self.assertEqual(rec["intent"], "swing")

    def test_skips_allow(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["AUDIT_TRADING_DIR"] = td
            pdt_guard.record_decision(
                {"decision": "ALLOW"}, "OPEN", "AAPL",
            )
            files = list(Path(td).glob("*.jsonl"))
            self.assertEqual(len(files), 0)


# ─── End-to-end profit-maximizing scenario tests ─────────────────────────────


class TestProfitMaximizingScenarios(unittest.TestCase):
    """v3.8 design intent: PDT guard must NOT block profitable moves."""

    def test_locked_account_can_buy_swing_crypto(self):
        """User at dt=4 LOCKED. Crypto BUY should ALWAYS succeed."""
        v = evaluate_order("OPEN", "BTC/USD", "buy", 8_000,
                           intent=INTENT_SWING,
                           snapshot=_snap("LOCKED", dt_used=4, bp=346_000))
        self.assertEqual(v["decision"], "ALLOW")

    def test_locked_account_can_buy_swing_stocks(self):
        """User at dt=4 LOCKED. Stock BUY (swing intent) should ALLOW."""
        v = evaluate_order("OPEN", "AAPL", "buy", 15_000,
                           intent=INTENT_SWING,
                           snapshot=_snap("LOCKED", dt_used=4, bp=346_000))
        self.assertEqual(v["decision"], "ALLOW")

    def test_locked_account_can_close_overnight_winners(self):
        """User at dt=4 LOCKED. Sell yesterday's winner = NOT DT."""
        with patch.object(pdt_guard, "is_potential_day_trade", return_value=False):
            v = evaluate_order("CLOSE", "GLD", "sell", 1_200,
                               intent=INTENT_SWING,
                               snapshot=_snap("LOCKED", dt_used=4))
        self.assertEqual(v["decision"], "ALLOW")

    def test_locked_account_can_emergency_close_intraday_loser(self):
        """User at dt=4 LOCKED. SL hit on same-day position. Honored."""
        v = evaluate_order("CLOSE", "AAPL", "sell", 8_000,
                           is_emergency=True,
                           snapshot=_snap("LOCKED", dt_used=4),
                           skip_intraday_check=True)
        self.assertEqual(v["decision"], "ALLOW")

    def test_restricted_saves_slot_for_emergency(self):
        """At dt=2 RESTRICTED, discretionary close DEFER but emergency OK."""
        discretionary = evaluate_order(
            "CLOSE", "AAPL", "sell", 8_000,
            is_emergency=False,
            snapshot=_snap("RESTRICTED", dt_used=2),
            skip_intraday_check=True,
        )
        emergency = evaluate_order(
            "CLOSE", "AAPL", "sell", 8_000,
            is_emergency=True,
            snapshot=_snap("RESTRICTED", dt_used=2),
            skip_intraday_check=True,
        )
        self.assertEqual(discretionary["decision"], "DEFER")
        self.assertEqual(emergency["decision"], "ALLOW")


if __name__ == "__main__":
    unittest.main()
