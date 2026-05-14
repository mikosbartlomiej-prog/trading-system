"""
Tests for shared.pdt_guard — PDT-safe order management.

Covers:
  - Mode classification (OK / CAUTION / RESTRICTED / LOCKED / UNKNOWN)
  - evaluate_order() decisions per mode per action
  - Emergency-close bypass
  - Crypto exemption
  - Fail-soft on Alpaca unreachable
  - Audit emission

All tests use mocks; no real Alpaca calls.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
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
)


def _mk_account(equity=94_000.0, bp=10_000.0, dt=0, pdt_flag=False):
    """Helper: shape of GET /v2/account response."""
    return {
        "equity":               str(equity),
        "buying_power":         str(bp),
        "daytrade_count":       str(dt),
        "pattern_day_trader":   pdt_flag,
    }


class TestModeClassification(unittest.TestCase):
    """_classify_mode is pure — easy to test directly."""

    def setUp(self):
        self.cfg = {
            "dt_limit":          3,
            "dt_caution_at":     2,
            "dt_restricted_at":  3,
            "bp_floor_pct":      0.05,
            "bp_hard_floor_usd": 100.0,
            "enabled":           True,
        }

    def test_ok_mode_normal_account(self):
        mode, _, remain = _classify_mode(
            daytrade_count=0, is_pdt=False, bp=50_000, equity=94_000,
            size_usd=2_000, cfg=self.cfg,
        )
        self.assertEqual(mode, "OK")
        self.assertEqual(remain, 3)

    def test_caution_at_2_daytrades(self):
        mode, reason, remain = _classify_mode(
            daytrade_count=2, is_pdt=True, bp=20_000, equity=94_000,
            size_usd=2_000, cfg=self.cfg,
        )
        self.assertEqual(mode, "CAUTION")
        self.assertIn("daytrade_count 2", reason)
        self.assertEqual(remain, 1)

    def test_caution_on_low_buying_power_pct(self):
        mode, reason, _ = _classify_mode(
            daytrade_count=0, is_pdt=False, bp=2_000, equity=94_000,
            size_usd=1_000, cfg=self.cfg,
        )
        self.assertEqual(mode, "CAUTION")
        self.assertIn("buying_power", reason)

    def test_restricted_at_3_daytrades(self):
        mode, _, remain = _classify_mode(
            daytrade_count=3, is_pdt=True, bp=20_000, equity=94_000,
            size_usd=2_000, cfg=self.cfg,
        )
        # dt_used (3) >= dt_limit (3) → LOCKED before RESTRICTED.
        self.assertEqual(mode, "LOCKED")
        self.assertEqual(remain, 0)

    def test_restricted_with_lower_threshold(self):
        cfg = dict(self.cfg, dt_restricted_at=2, dt_caution_at=1, dt_limit=3)
        mode, _, remain = _classify_mode(
            daytrade_count=2, is_pdt=True, bp=20_000, equity=94_000,
            size_usd=2_000, cfg=cfg,
        )
        self.assertEqual(mode, "RESTRICTED")
        self.assertEqual(remain, 1)

    def test_locked_when_bp_below_size(self):
        mode, _, _ = _classify_mode(
            daytrade_count=0, is_pdt=False, bp=500, equity=94_000,
            size_usd=2_000, cfg=self.cfg,
        )
        self.assertEqual(mode, "LOCKED")

    def test_locked_at_daytrade_limit(self):
        mode, _, _ = _classify_mode(
            daytrade_count=3, is_pdt=True, bp=20_000, equity=94_000,
            size_usd=1_000, cfg=self.cfg,
        )
        self.assertEqual(mode, "LOCKED")

    def test_locked_at_bp_hard_floor(self):
        mode, _, _ = _classify_mode(
            daytrade_count=0, is_pdt=False, bp=50, equity=94_000,
            size_usd=0, cfg=self.cfg,
        )
        self.assertEqual(mode, "LOCKED")


class TestGetPdtStatus(unittest.TestCase):
    """Snapshot integration with Alpaca fetch."""

    def test_fail_soft_when_account_unreachable(self):
        with patch.object(pdt_guard, "_fetch_account", return_value=None):
            snap = get_pdt_status(size_usd=1_000)
        self.assertEqual(snap.mode, "UNKNOWN")
        self.assertIn("unreachable", snap.reason)

    def test_classifies_from_passed_account(self):
        snap = get_pdt_status(account=_mk_account(equity=94_000, bp=20_000, dt=0))
        self.assertEqual(snap.mode, "OK")
        self.assertEqual(snap.daytrade_count, 0)
        self.assertEqual(snap.equity, 94_000)

    def test_malformed_account_returns_unknown(self):
        snap = get_pdt_status(account={"equity": "not-a-number"})
        self.assertEqual(snap.mode, "UNKNOWN")

    def test_pdt_account_at_limit_locked(self):
        snap = get_pdt_status(account=_mk_account(dt=3, pdt_flag=True))
        self.assertEqual(snap.mode, "LOCKED")
        self.assertEqual(snap.dt_remaining, 0)


class TestEvaluateOrder(unittest.TestCase):
    """End-to-end evaluate_order behaviour per mode + action."""

    def _ok_snap(self, mode="OK", dt_remain=3, bp=20_000):
        return PDTSnapshot(
            equity=94_000.0, buying_power=bp, daytrade_count=3 - dt_remain,
            pattern_day_trader=(mode != "OK"),
            dt_limit=3, dt_remaining=dt_remain,
            bp_pct_equity=(bp / 94_000.0 * 100.0),
            mode=mode,
            classified_at="2026-05-14T20:00:00+00:00",
            reason=f"test mode {mode}",
        )

    def test_ok_allows_open(self):
        v = evaluate_order("OPEN", "AAPL", "buy", 2_000,
                           snapshot=self._ok_snap("OK"))
        self.assertEqual(v["decision"], "ALLOW")

    def test_ok_allows_close(self):
        v = evaluate_order("CLOSE", "AAPL", "sell", 2_000,
                           snapshot=self._ok_snap("OK"))
        self.assertEqual(v["decision"], "ALLOW")

    def test_caution_allows_with_warning(self):
        v = evaluate_order("OPEN", "AAPL", "buy", 2_000,
                           snapshot=self._ok_snap("CAUTION", dt_remain=1))
        self.assertEqual(v["decision"], "ALLOW")
        self.assertIn("CAUTION", v["reason"])

    def test_restricted_allows_open_with_overnight_hint(self):
        v = evaluate_order("OPEN", "AAPL", "buy", 2_000,
                           snapshot=self._ok_snap("RESTRICTED", dt_remain=0))
        self.assertEqual(v["decision"], "ALLOW")
        self.assertIn("overnight", v["reason"].lower())

    def test_restricted_defers_non_emergency_close_when_day_trade(self):
        # skip_intraday_check=True forces "yes, this would be a day trade"
        # without hitting Alpaca.
        v = evaluate_order(
            "CLOSE", "AAPL", "sell", 2_000,
            is_emergency=False,
            snapshot=self._ok_snap("RESTRICTED", dt_remain=0),
            skip_intraday_check=True,
        )
        self.assertEqual(v["decision"], "DEFER")
        self.assertIn("DTMC", v["reason"])

    def test_restricted_allows_emergency_close(self):
        v = evaluate_order(
            "CLOSE", "AAPL", "sell", 2_000,
            is_emergency=True,
            snapshot=self._ok_snap("RESTRICTED", dt_remain=0),
            skip_intraday_check=True,
        )
        self.assertEqual(v["decision"], "ALLOW")
        self.assertIn("emergency", v["reason"].lower())

    def test_restricted_allows_overnight_close(self):
        # is_potential_day_trade returns False (no opens today) → not a DT.
        with patch.object(pdt_guard, "is_potential_day_trade", return_value=False):
            v = evaluate_order(
                "CLOSE", "AAPL", "sell", 2_000,
                is_emergency=False,
                snapshot=self._ok_snap("RESTRICTED", dt_remain=0),
            )
        self.assertEqual(v["decision"], "ALLOW")
        self.assertIn("overnight", v["reason"].lower())

    def test_locked_blocks_open(self):
        v = evaluate_order("OPEN", "AAPL", "buy", 2_000,
                           snapshot=self._ok_snap("LOCKED", dt_remain=0, bp=0))
        self.assertEqual(v["decision"], "BLOCK")
        self.assertIn("LOCKED", v["reason"])

    def test_locked_blocks_non_emergency_close(self):
        v = evaluate_order("CLOSE", "AAPL", "sell", 2_000,
                           is_emergency=False,
                           snapshot=self._ok_snap("LOCKED", dt_remain=0, bp=0))
        self.assertEqual(v["decision"], "BLOCK")

    def test_locked_honors_emergency_close(self):
        v = evaluate_order("CLOSE", "AAPL", "sell", 2_000,
                           is_emergency=True,
                           snapshot=self._ok_snap("LOCKED", dt_remain=0, bp=0))
        self.assertEqual(v["decision"], "ALLOW")
        self.assertIn("emergency", v["reason"].lower())

    def test_crypto_exempt_in_restricted_mode(self):
        v = evaluate_order(
            "CLOSE", "BTC/USD", "sell", 2_000,
            is_emergency=False,
            snapshot=self._ok_snap("RESTRICTED", dt_remain=0),
        )
        self.assertEqual(v["decision"], "ALLOW")
        self.assertIn("crypto", v["reason"].lower())

    def test_unknown_mode_fails_open(self):
        snap = PDTSnapshot(
            equity=0.0, buying_power=0.0, daytrade_count=0,
            pattern_day_trader=False, dt_limit=3, dt_remaining=3,
            bp_pct_equity=0.0, mode="UNKNOWN",
            classified_at="2026-05-14T20:00:00+00:00",
            reason="account unreachable",
        )
        v = evaluate_order("OPEN", "AAPL", "buy", 2_000, snapshot=snap)
        self.assertEqual(v["decision"], "ALLOW")
        self.assertIn("unknown", v["reason"].lower())

    def test_disabled_config_allows_everything(self):
        # Monkeypatch config to disabled.
        with patch.object(pdt_guard, "_load_pdt_config", return_value={
            "dt_limit": 3, "dt_caution_at": 2, "dt_restricted_at": 3,
            "bp_floor_pct": 0.05, "bp_hard_floor_usd": 100.0,
            "enabled": False,
        }):
            v = evaluate_order("OPEN", "AAPL", "buy", 2_000,
                               snapshot=self._ok_snap("LOCKED", bp=0))
        self.assertEqual(v["decision"], "ALLOW")
        self.assertIn("disabled", v["reason"])


class TestAuditEmission(unittest.TestCase):
    """record_decision writes JSONL only for non-ALLOW verdicts."""

    def test_emits_for_defer_decision(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["AUDIT_TRADING_DIR"] = td
            verdict = {
                "decision": "DEFER", "mode": "RESTRICTED",
                "dt_remaining": 0, "reason": "test defer",
            }
            pdt_guard.record_decision(verdict, "CLOSE", "AAPL")
            # Find any jsonl file written
            files = list(Path(td).glob("*.jsonl"))
            self.assertTrue(files, "No audit JSONL emitted")
            lines = files[0].read_text().strip().splitlines()
            self.assertGreater(len(lines), 0)
            rec = json.loads(lines[0])
            self.assertEqual(rec["decision"], "PDT_DEFER")
            self.assertEqual(rec["symbol"], "AAPL")

    def test_skips_allow_decisions(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["AUDIT_TRADING_DIR"] = td
            pdt_guard.record_decision(
                {"decision": "ALLOW", "mode": "OK"},
                "OPEN", "AAPL",
            )
            files = list(Path(td).glob("*.jsonl"))
            self.assertEqual(len(files), 0, "ALLOW should not emit audit")


class TestPotentialDayTrade(unittest.TestCase):
    """is_potential_day_trade queries Alpaca order history."""

    def test_returns_true_when_fills_today(self):
        with patch.object(
            pdt_guard, "_fetch_today_filled_orders",
            return_value=[{"status": "filled", "side": "buy"}],
        ):
            self.assertTrue(is_potential_day_trade("AAPL"))

    def test_returns_false_when_no_fills(self):
        with patch.object(pdt_guard, "_fetch_today_filled_orders", return_value=[]):
            self.assertFalse(is_potential_day_trade("AAPL"))

    def test_empty_symbol_returns_false(self):
        self.assertFalse(is_potential_day_trade(""))


if __name__ == "__main__":
    unittest.main()
