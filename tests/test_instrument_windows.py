"""
Unit tests for shared/instrument_windows.py — per-instrument trading window gate.

Covers:
  1. Asset class inference (us_equity / us_option / crypto)
  2. Crypto always allowed during default window
  3. US equity allowed only during regular hours weekday
  4. US equity blocked weekend / pre-market / after-hours / holiday
  5. US option allowed only during regular hours
  6. Per-symbol override: enabled=false blocks (MSTR / SMCI)
  7. Per-symbol paused_until: auto-resume after date
  8. Per-symbol paused_until: bad date → conservative block
  9. Unknown asset_class → blocked
 10. extended_hours_opt_in helper
 11. list_paused_instruments helper
 12. asset_class_window diagnostic helper
 13. is_ticker_enabled integration (learning_state.py)
 14. disabled_tickers integration (learning_state.py)

Run: python -m unittest tests.test_instrument_windows
"""

import os
import sys
import unittest
from datetime import datetime, timezone, date
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))


def _dt(y, mo, d, h, mi, weekday=None):
    """UTC datetime helper. weekday optional override."""
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


class TestAssetClassInference(unittest.TestCase):

    def setUp(self):
        from instrument_windows import _infer_asset_class
        self.infer = _infer_asset_class

    def test_crypto_slash_usd(self):
        self.assertEqual(self.infer("BTC/USD"), "crypto")
        self.assertEqual(self.infer("ETH/USD"), "crypto")
        self.assertEqual(self.infer("SOL/USD"), "crypto")

    def test_us_option_occ_format(self):
        # OCC: ticker + YYMMDD + P/C + 8 digit strike
        self.assertEqual(self.infer("AMZN260520P00270000"), "us_option")
        self.assertEqual(self.infer("AAPL260620C00150000"), "us_option")

    def test_us_equity_plain_ticker(self):
        self.assertEqual(self.infer("AAPL"), "us_equity")
        self.assertEqual(self.infer("SPY"), "us_equity")
        self.assertEqual(self.infer("MSTR"), "us_equity")


class TestCryptoWindow(unittest.TestCase):

    def setUp(self):
        from instrument_windows import can_trade_now, _reset_cache
        self.can_trade = can_trade_now
        _reset_cache()

    def test_crypto_allowed_weekend(self):
        # Sunday 03:00 UTC
        ok, reason = self.can_trade("BTC/USD", "crypto", _dt(2026, 5, 10, 3, 0))
        self.assertTrue(ok, f"crypto should be allowed weekend: {reason}")

    def test_crypto_allowed_holiday(self):
        # New Year's Day
        ok, reason = self.can_trade("BTC/USD", "crypto", _dt(2026, 1, 1, 14, 0))
        self.assertTrue(ok, f"crypto should be allowed on US holiday: {reason}")

    def test_crypto_allowed_overnight(self):
        ok, _ = self.can_trade("ETH/USD", "crypto", _dt(2026, 5, 12, 23, 30))
        self.assertTrue(ok)


class TestUSEquityWindow(unittest.TestCase):

    def setUp(self):
        from instrument_windows import can_trade_now, _reset_cache
        self.can_trade = can_trade_now
        _reset_cache()

    def test_open_during_regular_hours_weekday(self):
        # Tuesday 14:00 UTC = 10:00 ET (regular hours)
        ok, reason = self.can_trade("AAPL", "us_equity", _dt(2026, 5, 12, 14, 0))
        self.assertTrue(ok, f"expected open, got: {reason}")

    def test_blocked_pre_market(self):
        # Tuesday 13:00 UTC = 09:00 ET (pre-market)
        ok, reason = self.can_trade("AAPL", "us_equity", _dt(2026, 5, 12, 13, 0))
        self.assertFalse(ok)
        self.assertIn("pre_market", reason)

    def test_blocked_after_hours(self):
        # Tuesday 20:30 UTC = 16:30 ET (after-hours)
        ok, reason = self.can_trade("AAPL", "us_equity", _dt(2026, 5, 12, 20, 30))
        self.assertFalse(ok)
        self.assertIn("after_hours", reason)

    def test_blocked_weekend(self):
        ok, reason = self.can_trade("AAPL", "us_equity", _dt(2026, 5, 10, 14, 0))
        self.assertFalse(ok)
        self.assertIn("weekend", reason)

    def test_blocked_holiday(self):
        # New Year's Day during what would be regular hours
        ok, reason = self.can_trade("AAPL", "us_equity", _dt(2026, 1, 1, 14, 0))
        self.assertFalse(ok)
        self.assertIn("holiday", reason)


class TestUSOptionWindow(unittest.TestCase):

    def setUp(self):
        from instrument_windows import can_trade_now, _reset_cache
        self.can_trade = can_trade_now
        _reset_cache()

    def test_option_open_during_regular(self):
        ok, _ = self.can_trade("AMZN260520P00270000", None, _dt(2026, 5, 12, 14, 0))
        self.assertTrue(ok)

    def test_option_blocked_pre_market(self):
        ok, reason = self.can_trade("AMZN260520P00270000", None, _dt(2026, 5, 12, 13, 0))
        self.assertFalse(ok)
        self.assertIn("pre_market", reason)


class TestInstrumentOverrides(unittest.TestCase):

    def setUp(self):
        from instrument_windows import can_trade_now, _reset_cache
        self.can_trade = can_trade_now
        _reset_cache()

    def test_mstr_paused(self):
        # Market would normally be open, but MSTR has enabled=false in config
        ok, reason = self.can_trade("MSTR", "us_equity", _dt(2026, 5, 12, 14, 0))
        self.assertFalse(ok)
        self.assertIn("paused", reason.lower())
        self.assertIn("MSTR", reason)

    def test_smci_paused(self):
        ok, reason = self.can_trade("SMCI", "us_equity", _dt(2026, 5, 12, 14, 0))
        self.assertFalse(ok)
        self.assertIn("paused", reason.lower())

    def test_unpaused_ticker_normal_flow(self):
        # AAPL has no override → normal market-hours logic
        ok, _ = self.can_trade("AAPL", "us_equity", _dt(2026, 5, 12, 14, 0))
        self.assertTrue(ok)


class TestPausedUntilLogic(unittest.TestCase):

    def setUp(self):
        from instrument_windows import _reset_cache
        _reset_cache()

    def test_paused_until_future_blocks(self):
        from instrument_windows import _override_blocks, _load_config
        with patch.object(_load_config, "cache_clear", lambda: None), \
             patch("instrument_windows._load_config",
                    return_value={"instrument_overrides": {
                        "FOO": {"enabled": False, "paused_until": "2026-12-31"}
                    }}):
            blocked, reason = _override_blocks("FOO", _dt(2026, 5, 12, 14, 0))
            self.assertTrue(blocked)
            self.assertIn("2026-12-31", reason)

    def test_paused_until_past_auto_resumes(self):
        from instrument_windows import _override_blocks
        with patch("instrument_windows._load_config",
                    return_value={"instrument_overrides": {
                        "FOO": {"enabled": False, "paused_until": "2025-01-01"}
                    }}):
            blocked, _ = _override_blocks("FOO", _dt(2026, 5, 12, 14, 0))
            self.assertFalse(blocked)

    def test_paused_until_invalid_blocks_conservatively(self):
        from instrument_windows import _override_blocks
        with patch("instrument_windows._load_config",
                    return_value={"instrument_overrides": {
                        "FOO": {"enabled": False, "paused_until": "not-a-date"}
                    }}):
            blocked, reason = _override_blocks("FOO", _dt(2026, 5, 12, 14, 0))
            self.assertTrue(blocked)
            self.assertIn("invalid", reason.lower())


class TestUnknownAssetClass(unittest.TestCase):

    def test_unknown_blocked(self):
        from instrument_windows import can_trade_now
        ok, reason = can_trade_now("FOO", "futures", _dt(2026, 5, 12, 14, 0))
        self.assertFalse(ok)
        self.assertIn("unknown", reason.lower())


class TestHelpers(unittest.TestCase):

    def setUp(self):
        from instrument_windows import _reset_cache
        _reset_cache()

    def test_list_paused_instruments_includes_mstr_smci(self):
        from instrument_windows import list_paused_instruments
        paused = list_paused_instruments()
        self.assertIn("MSTR", paused)
        self.assertIn("SMCI", paused)

    def test_extended_hours_default_empty(self):
        from instrument_windows import is_extended_hours_enabled
        self.assertFalse(is_extended_hours_enabled("AAPL"))

    def test_asset_class_window_us_equity(self):
        from instrument_windows import asset_class_window
        w = asset_class_window("us_equity")
        self.assertEqual(w.get("open_utc"), "13:30")
        self.assertEqual(w.get("close_utc"), "20:00")
        self.assertTrue(w.get("respect_us_holidays"))


class TestLearningStateIntegration(unittest.TestCase):
    """is_ticker_enabled now consults instrument_windows.json first."""

    def test_mstr_reported_disabled_via_instrument_windows(self):
        # Adjust sys.path so learning_state imports correctly
        from instrument_windows import _reset_cache
        _reset_cache()
        from learning_state import is_ticker_enabled
        # MSTR is paused in instrument_windows.json → should be disabled
        # NOTE: paused_until_past_auto_resume not triggered (null)
        self.assertFalse(is_ticker_enabled("MSTR"))
        self.assertFalse(is_ticker_enabled("SMCI"))

    def test_aapl_enabled_no_override(self):
        from learning_state import is_ticker_enabled
        self.assertTrue(is_ticker_enabled("AAPL"))

    def test_disabled_tickers_dedup(self):
        from instrument_windows import _reset_cache
        _reset_cache()
        from learning_state import disabled_tickers
        d = disabled_tickers()
        # Should include MSTR + SMCI (deduped if also in state.json)
        self.assertIn("MSTR", d)
        self.assertIn("SMCI", d)
        # No duplicates
        self.assertEqual(len(d), len(set(d)))


if __name__ == "__main__":
    unittest.main()
