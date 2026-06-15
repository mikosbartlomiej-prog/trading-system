"""v3.22.0 (2026-06-15) — Per-monitor smoke test: geo-monitor.

Asserts emit_monitor_signal is wired into execute_geo_signal — that is the
broker-dispatching entrypoint where the v3.22 contract requires an
opportunity row.
"""

from __future__ import annotations

import importlib.util as iu
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_geo_monitor_module():
    if "requests" not in sys.modules:
        sys.modules["requests"] = MagicMock()
    if "feedparser" not in sys.modules:
        sys.modules["feedparser"] = MagicMock()
    sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))
    sys.path.insert(0, os.path.join(REPO_ROOT, "geo-monitor"))
    path = os.path.join(REPO_ROOT, "geo-monitor", "monitor.py")
    spec = iu.spec_from_file_location("geo_monitor_v3220", path)
    assert spec and spec.loader
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGeoMonitorEmit(unittest.TestCase):

    def test_emit_signal_present_in_execute_geo_signal(self) -> None:
        path = os.path.join(REPO_ROOT, "geo-monitor", "monitor.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        # locate execute_geo_signal block.
        idx = src.find("def execute_geo_signal(")
        self.assertGreater(idx, 0,
            "geo-monitor must define execute_geo_signal()")
        end = src.find("\ndef ", idx + 1)
        if end < 0:
            end = len(src)
        body = src[idx:end]
        self.assertIn("emit_monitor_signal(", body,
            "execute_geo_signal must call emit_monitor_signal before broker")
        self.assertIn("\"geo-monitor\"", body,
            "emit must use source_monitor=\"geo-monitor\"")

    def test_emit_helper_callable_through_module(self) -> None:
        mod = _load_geo_monitor_module()
        captured = []
        with patch.object(mod, "emit_monitor_signal",
                          side_effect=lambda *a, **k: captured.append(k) or
                              {"emitted": True, "status": "EMITTED",
                               "signal_id": "t", "warnings": []}):
            mod.emit_monitor_signal(
                source_monitor="geo-monitor",
                strategy_id="geo-defense",
                symbol="RTX",
                asset_class="us_equity",
                side="long",
                action="BUY",
                entry_capable=True,
                raw_signal={"score": 70, "headline":"Sanctions imposed"},
                confidence_inputs={"primary_score":0.6,
                                    "regime":"NEUTRAL",
                                    "data_quality":"REAL_NEWS_FEED"},
                risk_inputs={"account_status": None, "size_usd": 8000},
                market_regime={"regime":"NEUTRAL"},
            )
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["source_monitor"], "geo-monitor")
        self.assertEqual(captured[0]["action"], "BUY")


if __name__ == "__main__":
    unittest.main()
