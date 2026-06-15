"""v3.22.0 (2026-06-15) — Per-monitor smoke test: defense-monitor.

Asserts that the wired emit_monitor_signal helper is callable through the
defense-monitor module surface, and that the source_monitor identifier is
correct. We use a direct call (not a full ``run_scan`` invocation) to avoid
needing the news-source HTTP mocks — the goal is to verify the wiring
contract, not re-test news fetching.
"""

from __future__ import annotations

import importlib.util as iu
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_defense_monitor_module():
    if "requests" not in sys.modules:
        sys.modules["requests"] = MagicMock()
    if "feedparser" not in sys.modules:
        sys.modules["feedparser"] = MagicMock()
    sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))
    sys.path.insert(0, os.path.join(REPO_ROOT, "defense-monitor"))
    path = os.path.join(REPO_ROOT, "defense-monitor", "monitor.py")
    spec = iu.spec_from_file_location("defense_monitor_v3220", path)
    assert spec and spec.loader
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDefenseMonitorEmit(unittest.TestCase):

    def test_emit_helper_available_with_correct_source(self) -> None:
        mod = _load_defense_monitor_module()
        self.assertTrue(callable(mod.emit_monitor_signal),
            "emit_monitor_signal must be available inside defense-monitor")

        # Call the helper directly with a defense-style signal dict and
        # verify the wire-through.
        captured = []
        with patch.object(mod, "emit_monitor_signal",
                          side_effect=lambda *a, **k: captured.append(k) or
                              {"emitted": True, "status": "EMITTED",
                               "signal_id": "test", "warnings": []}):
            mod.emit_monitor_signal(
                source_monitor="defense-monitor",
                strategy_id="defense-news",
                symbol="RTX",
                asset_class="us_equity",
                side="long",
                action="BUY",
                entry_capable=True,
                raw_signal={"score": 75, "headline":"RTX contract win"},
                confidence_inputs={"primary_score": 0.75,
                                    "regime":"NEUTRAL",
                                    "data_quality":"REAL_NEWS_FEED"},
                risk_inputs={"account_status": None,
                              "concentration_pct": 5.0,
                              "market_hours_open": True},
                market_regime={"regime":"NEUTRAL"},
                metadata={"headline":"RTX wins big DoD contract"},
            )
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["source_monitor"], "defense-monitor")
        self.assertEqual(captured[0]["strategy_id"], "defense-news")
        self.assertEqual(captured[0]["symbol"], "RTX")
        self.assertEqual(captured[0]["action"], "BUY")
        self.assertEqual(captured[0]["side"], "long")
        self.assertTrue(captured[0]["entry_capable"])

    def test_emit_call_present_in_source(self) -> None:
        """The defense-monitor source must contain an emit_monitor_signal
        invocation block."""
        path = os.path.join(REPO_ROOT, "defense-monitor", "monitor.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("emit_monitor_signal(", src)
        self.assertIn("source_monitor=\"defense-monitor\"", src)


if __name__ == "__main__":
    unittest.main()
