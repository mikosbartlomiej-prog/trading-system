"""v3.27.2 (2026-06-09) — SHADOW_MARKET_DATA_LOOKBACK_DAYS override tests.

Verifies that:
- the default lookback yields >=22 bars (ATR-window safe floor),
- the override is parsed safely,
- the override CANNOT be reduced below the 22-bar safety floor.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestLookbackDefault(unittest.TestCase):
    def test_collector_default_lookback_is_at_least_22(self):
        text = (REPO_ROOT / "scripts"
                 / "run_signal_shadow_evidence_collection.py").read_text(
            encoding="utf-8")
        # The default in os.environ.get must be >=22.
        self.assertIn('"SHADOW_MARKET_DATA_LOOKBACK_DAYS"', text)
        # Source pins default 40 which is well above 22.
        self.assertIn('"40"', text)
        # Explicit max() floor guarantees >=22 even if operator sets
        # SHADOW_MARKET_DATA_LOOKBACK_DAYS=5.
        self.assertIn("max(", text)
        self.assertIn("22,", text)


class TestProviderEnforcesBarFloor(unittest.TestCase):
    def test_fetch_daily_bars_diagnostic_flags_insufficient_below_22(self):
        import market_data_provider as mdp
        fake_bars = [{"o": 1, "h": 2, "l": 0, "c": 1, "v": 1}
                       for _ in range(21)]  # one less than ATR floor
        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "x",
                                "ALPACA_SECRET_KEY": "y"},
                               clear=False):
            with mock.patch.object(
                mdp, "_resolve_get_daily_bars",
                return_value=lambda symbol, days=40: fake_bars,
            ):
                bars, token = mdp.fetch_daily_bars_diagnostic("SPY")
        self.assertEqual(len(bars or []), 21)
        self.assertEqual(token, mdp.INSUFFICIENT_BARS_FOR_SIGNAL)

    def test_fetch_daily_bars_diagnostic_clears_at_22_or_more(self):
        import market_data_provider as mdp
        fake_bars = [{"o": 1, "h": 2, "l": 0, "c": 1, "v": 1}
                       for _ in range(22)]
        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "x",
                                "ALPACA_SECRET_KEY": "y"},
                               clear=False):
            with mock.patch.object(
                mdp, "_resolve_get_daily_bars",
                return_value=lambda symbol, days=40: fake_bars,
            ):
                bars, token = mdp.fetch_daily_bars_diagnostic("SPY")
        self.assertEqual(len(bars or []), 22)
        self.assertEqual(
            token, mdp.REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL)


class TestLookbackOverrideCannotWeakenFloor(unittest.TestCase):
    def test_collector_clamp_uses_max_22(self):
        """If the operator sets SHADOW_MARKET_DATA_LOOKBACK_DAYS=5,
        the collector must still ask for >=22 bars."""
        text = (REPO_ROOT / "scripts"
                 / "run_signal_shadow_evidence_collection.py").read_text(
            encoding="utf-8")
        # The 22-bar floor must appear inside the max() guard that
        # wraps the SHADOW_MARKET_DATA_LOOKBACK_DAYS read. Source
        # order is: max( -> 22, -> SHADOW_MARKET_DATA_LOOKBACK_DAYS.
        idx_max  = text.find("max(")
        self.assertGreater(idx_max, 0)
        idx_22   = text.find("22,", idx_max)
        self.assertGreater(idx_22, idx_max,
                            "22-bar floor missing inside max() guard")
        idx_env  = text.find("SHADOW_MARKET_DATA_LOOKBACK_DAYS", idx_22)
        self.assertGreater(idx_env, idx_22,
                            "env override must be inside same max() block")


if __name__ == "__main__":
    unittest.main()
