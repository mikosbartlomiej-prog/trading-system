"""
Tests for learning-loop/adapter.py v3.9.0 SILENT-warning grace period.

Background: strategies that get re-enabled (auto-resume from paused_until,
or manual flip) shouldn't immediately get "SILENT — 0 trades lifetime"
warning — they need time to accumulate trades. 5-day grace period after
enabled_at timestamp.

LLM proposal 2026-05-17 — "Suppress SILENT adapter flag for strategies
within 5 days of re-enable".
"""

import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "learning-loop"))

from adapter import _flag_silent_strategies as silent_strategy_warnings


def _today() -> str:
    return date.today().isoformat()


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _base_state(strategies: dict) -> dict:
    return {
        "days_tracked": 30,
        "strategies":   strategies,
    }


def _empty_stats() -> dict:
    return {"by_strategy": {}}


class TestSilentGrace(unittest.TestCase):

    def test_no_grace_no_enabled_at(self):
        """Strategy enabled long ago (no enabled_at) — SILENT fires normally."""
        state = _base_state({
            "geo-xom": {"enabled": True},   # no enabled_at = old strategy
        })
        result = silent_strategy_warnings(state, _empty_stats())
        self.assertEqual(len(result), 1)
        self.assertIn("geo-xom", result[0])
        self.assertIn("SILENT", result[0])

    def test_grace_active_within_5_days(self):
        """Strategy enabled 3 days ago — within grace window, no SILENT."""
        state = _base_state({
            "geo-defense": {"enabled": True, "enabled_at": _days_ago(3)},
        })
        result = silent_strategy_warnings(state, _empty_stats())
        self.assertEqual(result, [], "Should suppress SILENT within 5-day grace")

    def test_grace_boundary_4_days(self):
        """Day 4 — still within grace (< 5 days)."""
        state = _base_state({
            "options-momentum": {"enabled": True, "enabled_at": _days_ago(4)},
        })
        result = silent_strategy_warnings(state, _empty_stats())
        self.assertEqual(result, [])

    def test_grace_expired_at_5_days(self):
        """Day 5 — grace expired, SILENT fires."""
        state = _base_state({
            "geo-energy": {"enabled": True, "enabled_at": _days_ago(5)},
        })
        result = silent_strategy_warnings(state, _empty_stats())
        self.assertEqual(len(result), 1)
        self.assertIn("geo-energy", result[0])

    def test_grace_expired_at_10_days(self):
        """10 days post-enable — definitely SILENT-able."""
        state = _base_state({
            "crypto-momentum": {"enabled": True, "enabled_at": _days_ago(10)},
        })
        result = silent_strategy_warnings(state, _empty_stats())
        self.assertEqual(len(result), 1)

    def test_grace_with_trades_no_silent(self):
        """Has trades within window — never silent regardless of grace."""
        state = _base_state({
            "geo-xom": {"enabled": True, "enabled_at": _days_ago(3)},
        })
        stats = {"by_strategy": {"geo-xom": {"trades_lifetime": 1, "trades_7d": 1}}}
        result = silent_strategy_warnings(state, stats)
        self.assertEqual(result, [])

    def test_disabled_strategy_no_warning(self):
        """Disabled strategy — no SILENT regardless of grace."""
        state = _base_state({
            "geo-xom": {"enabled": False, "enabled_at": _days_ago(3)},
        })
        result = silent_strategy_warnings(state, _empty_stats())
        self.assertEqual(result, [])

    def test_allocator_tag_no_warning(self):
        """Allocator-level tag — excluded regardless of grace state."""
        state = _base_state({
            "alloc-exit": {"enabled": True, "enabled_at": _days_ago(10)},
        })
        result = silent_strategy_warnings(state, _empty_stats())
        self.assertEqual(result, [])

    def test_malformed_enabled_at_falls_through(self):
        """Bad timestamp → grace ignored, normal behavior."""
        state = _base_state({
            "geo-xom": {"enabled": True, "enabled_at": "not-a-date"},
        })
        result = silent_strategy_warnings(state, _empty_stats())
        # Falls through to normal silent check (no trades → SILENT)
        self.assertEqual(len(result), 1)

    def test_multi_strategy_mixed(self):
        """Mix: 1 within grace + 1 expired + 1 with trades + 1 disabled."""
        state = _base_state({
            "geo-defense":   {"enabled": True, "enabled_at": _days_ago(2)},      # grace
            "geo-energy":    {"enabled": True, "enabled_at": _days_ago(10)},     # silent
            "momentum-long": {"enabled": True, "enabled_at": _days_ago(20)},     # has trades
            "overbought-short": {"enabled": False},                              # disabled
        })
        stats = {"by_strategy": {"momentum-long": {"trades_lifetime": 5}}}
        result = silent_strategy_warnings(state, stats)
        # Only geo-energy should fire
        self.assertEqual(len(result), 1)
        self.assertIn("geo-energy", result[0])


if __name__ == "__main__":
    unittest.main()
