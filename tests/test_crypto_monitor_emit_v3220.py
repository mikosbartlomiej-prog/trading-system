"""v3.22.0 (2026-06-15) — Per-monitor smoke test: crypto-monitor.

Asserts that the migrated ``_emit_opportunity`` now routes through
``shared/signal_emitter.py`` (instead of calling record_opportunity
directly) and that source_monitor is "crypto-monitor".

No network. No broker calls.
"""

from __future__ import annotations

import importlib.util as iu
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_crypto_monitor_module():
    if "requests" not in sys.modules:
        sys.modules["requests"] = MagicMock()
    sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))
    sys.path.insert(0, os.path.join(REPO_ROOT, "crypto-monitor"))
    path = os.path.join(REPO_ROOT, "crypto-monitor", "monitor.py")
    spec = iu.spec_from_file_location("crypto_monitor_v3220", path)
    assert spec and spec.loader
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCryptoMonitorEmitMigration(unittest.TestCase):

    def test_emit_opportunity_routes_through_shared_emitter(self) -> None:
        mod = _load_crypto_monitor_module()
        # The crypto monitor's _emit_opportunity does a local
        # `from signal_emitter import emit_signal_opportunity` (no package
        # prefix). To intercept, we patch the underlying module's attribute
        # which is the same object the local import resolves to.
        import signal_emitter as se  # type: ignore

        captured: list = []

        def capture_emit(event, *, dry_run=False, idempotency_key=None):
            captured.append((event, dry_run, idempotency_key))
            return {"emitted": True, "status": "EMITTED",
                    "signal_id": event.signal_id, "warnings": []}

        with patch.object(se, "emit_signal_opportunity",
                          side_effect=capture_emit):
            mod._emit_opportunity(
                strategy="crypto-momentum",
                symbol="BTC/USD",
                signal_state="DETECTED",
                rsi=58.2,
                raw_signal={"action": "BUY", "price": 70000.0,
                            "stop_loss": 65100.0, "take_profit": 84000.0},
                market_regime="NEUTRAL",
            )

        self.assertEqual(len(captured), 1,
            "Migration must route exactly ONE emit through "
            "shared.signal_emitter.emit_signal_opportunity")
        event = captured[0][0]
        # Validate canonical SignalEvent shape.
        self.assertEqual(event.source_monitor, "crypto-monitor")
        self.assertEqual(event.symbol, "BTC/USD")
        self.assertEqual(event.strategy_id, "crypto-momentum")
        self.assertEqual(event.asset_class, "crypto")
        self.assertEqual(event.pipeline, "monitor")
        self.assertEqual(event.evidence_source, "PAPER")
        # action "DETECTED" carries the BUY intent in raw_signal.
        self.assertIn(event.action, ("BUY", "DETECTED"))

    def test_no_direct_record_opportunity_call_remains(self) -> None:
        """The legacy direct record_opportunity import should be gone."""
        with open(os.path.join(REPO_ROOT, "crypto-monitor", "monitor.py"),
                  encoding="utf-8") as f:
            src = f.read()
        # Inside the migrated _emit_opportunity helper body specifically.
        helper_start = src.find("def _emit_opportunity")
        helper_end   = src.find("\ndef ", helper_start + 1)
        if helper_end < 0:
            helper_end = len(src)
        helper_src = src[helper_start:helper_end]
        self.assertNotIn("record_opportunity(", helper_src,
            "Migrated _emit_opportunity must NOT call record_opportunity "
            "directly — it must route through shared.signal_emitter.")

    def test_emit_state_halted_is_observability_only(self) -> None:
        """HALTED_BY_* signal states must produce entry_capable=False."""
        mod = _load_crypto_monitor_module()
        import signal_emitter as se  # type: ignore
        captured: list = []
        with patch.object(se, "emit_signal_opportunity",
                          side_effect=lambda ev, **k: captured.append(ev) or
                              {"emitted": True, "status": "EMITTED",
                               "signal_id": ev.signal_id, "warnings": []}):
            mod._emit_opportunity(
                strategy="crypto-momentum",
                symbol="BTC/USD",
                signal_state="HALTED_BY_DRAWDOWN_GUARD",
                rejection_reasons=["drawdown_halt"],
                paper_action="halted",
            )
        self.assertEqual(len(captured), 1)
        self.assertFalse(captured[0].entry_capable)
        self.assertEqual(captured[0].action, "HALTED")


if __name__ == "__main__":
    unittest.main()
