"""v3.22.0 (2026-06-15) — Per-monitor smoke test: price-monitor.

Injects a synthetic candidate that flows through ``check_long_signal`` and
``run_checks`` and asserts ``emit_monitor_signal`` is called.

No network. No broker calls. All external dependencies are mocked.
"""

from __future__ import annotations

import contextlib
import importlib.util as iu
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_price_monitor_module():
    # Provide stubs for any unavailable third-party modules.
    if "schedule" not in sys.modules:
        sys.modules["schedule"] = MagicMock()
    if "pytz" not in sys.modules:
        sys.modules["pytz"] = MagicMock()
    if "requests" not in sys.modules:
        sys.modules["requests"] = MagicMock()
    sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))
    sys.path.insert(0, os.path.join(REPO_ROOT, "price-monitor"))
    path = os.path.join(REPO_ROOT, "price-monitor", "monitor.py")
    spec = iu.spec_from_file_location("price_monitor_v3220", path)
    assert spec and spec.loader
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPriceMonitorEmit(unittest.TestCase):

    def test_long_signal_emits_signal_event(self) -> None:
        mod = _load_price_monitor_module()

        captured: list[tuple[tuple, dict]] = []

        def capture_emit(*args, **kwargs):
            captured.append((args, kwargs))
            return {"emitted": True, "status": "EMITTED",
                    "signal_id": "test-sid", "warnings": []}

        synthetic_signal = {
            "symbol": "AAPL",
            "action": "BUY",
            "strategy": "momentum-long",
            "price": 195.0,
            "stop_loss": 190.0,
            "take_profit": 205.0,
            "size_usd": 10000,
            "rsi": 60.0,
            "atr": 2.5,
        }
        sent_alerts: list[bool] = []

        patches = [
            patch.object(mod, "emit_monitor_signal", side_effect=capture_emit),
            patch.object(mod, "is_market_open", return_value=True),
            patch.object(mod, "is_defensive_mode_active", return_value=False),
            patch.object(mod, "get_account_status",
                          return_value={"equity": 100_000, "buying_power": 200_000}),
            patch.object(mod, "daily_drawdown_guard",
                          return_value=("OK", "ok")),
            patch.object(mod, "vix_guard", return_value=("OK", 1.0)),
            patch.object(mod, "detect_regime",
                          return_value={"regime": "RISK_ON", "source": "test",
                                        "allowed_buckets": ["mega_cap_long"],
                                        "size_multiplier": 1.0,
                                        "options_side_bias": None,
                                        "max_alt_positions": 3,
                                        "reason": "test"}),
            patch.object(mod, "is_ticker_allowed", return_value=(True, "ok")),
            patch.object(mod, "is_ticker_enabled", return_value=True),
            patch.object(mod, "get_daily_bars",
                          return_value={"close": [100.0]*30,
                                        "high":  [101.0]*30,
                                        "low":   [99.0]*30,
                                        "open":  [100.0]*30,
                                        "volume":[1_000_000]*30}),
            patch.object(mod, "score_symbol",
                          return_value={"ticker":"AAPL", "score":0.55,
                                        "tradeable":True, "reason":"top1"}),
            patch.object(mod, "profile_value",
                          side_effect=lambda key, default=None:
                               {"scoring.top_n_picks": 1,
                                "scoring.min_score_for_entry": 0.35}.get(key, default)),
            patch.object(mod, "check_long_signal", return_value=synthetic_signal),
            patch.object(mod, "check_short_signal", return_value=None),
            patch.object(mod, "has_open_position", return_value=False),
            patch.object(mod, "concentration_ok", return_value=(True, 5.0)),
            patch.object(mod, "send_alert",
                          side_effect=lambda a: sent_alerts.append(True) or True),
            patch.object(mod, "notify_signal"),
            patch.object(mod, "notify_summary"),
            patch.object(mod, "TICKERS_LONG", ["AAPL"]),
            patch.object(mod, "TICKERS_SHORT", []),
            patch.object(mod, "TICKERS_LEVERAGED", []),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            mod.run_checks()

        self.assertGreaterEqual(len(captured), 1,
            f"emit_monitor_signal should fire at least once for the LONG path; "
            f"captured={captured}")
        # The first call's source_monitor must be the price-monitor identifier.
        first_kwargs = captured[0][1]
        self.assertEqual(first_kwargs.get("source_monitor"), "price-monitor")
        # entry_capable must be True for LONG entries.
        self.assertTrue(first_kwargs.get("entry_capable"))
        # Action must be BUY.
        self.assertEqual(first_kwargs.get("action"), "BUY")
        # No broker calls (send_alert was patched and only called via this test).
        self.assertTrue(sent_alerts, "send_alert should be invoked once for the synthetic signal")


if __name__ == "__main__":
    unittest.main()
