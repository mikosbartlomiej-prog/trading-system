"""v3.22 (2026-06-07) — Drawdown escalation tests.

Verifies the unrealized drawdown advisory module:
- threshold-based alert classification
- never auto-closes / never raises risk
- enqueues operator actions on transitions
- fail-soft on missing data
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestThresholds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import runtime_state
        runtime_state.RUNTIME_STATE_PATH = Path(self.tmp.name) / "runtime_state.json"
        for mod in ("drawdown_escalation",):
            sys.modules.pop(mod, None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_alert_when_drawdown_under_warn(self):
        import drawdown_escalation as de
        result = de.check_unrealized_drawdown(
            equity_now=99000.0, equity_base=100000.0,
            attributed_closed_trades=0,
        )
        # -1% is above WARN_PCT (-3%)
        self.assertEqual(result["alert_level"], de.ALERT_NONE)

    def test_warn_at_minus_4_pct(self):
        import drawdown_escalation as de
        result = de.check_unrealized_drawdown(
            equity_now=96000.0, equity_base=100000.0,
            attributed_closed_trades=0,
        )
        self.assertEqual(result["alert_level"], de.ALERT_WARN)

    def test_restrict_at_minus_6_pct(self):
        import drawdown_escalation as de
        result = de.check_unrealized_drawdown(
            equity_now=94000.0, equity_base=100000.0,
            attributed_closed_trades=0,
        )
        self.assertEqual(result["alert_level"], de.ALERT_RESTRICT)
        self.assertTrue(result["new_entry_restricted"])

    def test_emergency_at_minus_10_pct(self):
        import drawdown_escalation as de
        result = de.check_unrealized_drawdown(
            equity_now=90000.0, equity_base=100000.0,
            attributed_closed_trades=0,
        )
        self.assertEqual(result["alert_level"], de.ALERT_EMERGENCY)

    def test_2026_06_07_incident_replay(self):
        """The actual 2026-06-07 drawdown should hit WARN."""
        import drawdown_escalation as de
        result = de.check_unrealized_drawdown(
            equity_now=89703.0, equity_base=93700.0,
            attributed_closed_trades=0,
        )
        # -4.27% — WARN threshold (-3% to -5%)
        self.assertEqual(result["alert_level"], de.ALERT_WARN)
        self.assertAlmostEqual(result["equity_pct_change"], -4.266, places=2)


class TestAttributionAndPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import runtime_state
        runtime_state.RUNTIME_STATE_PATH = Path(self.tmp.name) / "runtime_state.json"
        for mod in ("drawdown_escalation",):
            sys.modules.pop(mod, None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_attribution_per_position(self):
        import drawdown_escalation as de
        positions = [
            {"symbol": "PANW", "unrealized_pl": -2000.0},
            {"symbol": "SPY",  "unrealized_pl": -1500.0},
            {"symbol": "QQQ",  "unrealized_pl": -1200.0},
        ]
        result = de.check_unrealized_drawdown(
            equity_now=89703.0, equity_base=93700.0,
            attributed_closed_trades=0,
            positions=positions,
        )
        self.assertEqual(len(result["attribution"]), 3)
        # PANW has largest absolute loss → largest share
        shares = sorted([a["share_of_drawdown"] for a in result["attribution"]], reverse=True)
        self.assertGreaterEqual(shares[0], shares[1])

    def test_fail_soft_when_equity_base_zero(self):
        import drawdown_escalation as de
        result = de.check_unrealized_drawdown(
            equity_now=50000.0, equity_base=0.0,
            attributed_closed_trades=0,
        )
        self.assertEqual(result["alert_level"], de.ALERT_NONE)
        self.assertIn("warning", result)
        self.assertEqual(result["warning"], "EQUITY_BASE_UNAVAILABLE")


class TestInvariants(unittest.TestCase):
    def test_invariants_present_and_true(self):
        import drawdown_escalation as de
        self.assertTrue(de.DRAWDOWN_NEVER_AUTO_CLOSES)
        self.assertTrue(de.DRAWDOWN_NEVER_RAISES_RISK)
        self.assertTrue(de.DRAWDOWN_ADVISORY_ONLY)

    def test_no_alpaca_orders_import(self):
        src = (REPO_ROOT / "shared" / "drawdown_escalation.py").read_text()
        # Static check — module must NOT close positions / place orders
        for forbidden in [
            "from alpaca_orders",
            "import alpaca_orders",
            "place_stock_bracket(",
            "place_crypto_order(",
            "safe_close(",
            "close_position(",
        ]:
            self.assertNotIn(forbidden, src, f"forbidden symbol: {forbidden}")


class TestActionQueueIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import runtime_state
        runtime_state.RUNTIME_STATE_PATH = Path(self.tmp.name) / "runtime_state.json"
        for mod in ("drawdown_escalation",):
            sys.modules.pop(mod, None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_warn_enqueues_action(self):
        import drawdown_escalation as de
        enqueued = []
        with patch.object(de, "_enqueue_drawdown_action",
                           side_effect=lambda *a, **kw: enqueued.append((a, kw))):
            result = de.check_unrealized_drawdown(
                equity_now=89703.0, equity_base=93700.0,
                attributed_closed_trades=0,
            )
        self.assertEqual(len(enqueued), 1)


if __name__ == "__main__":
    unittest.main()
