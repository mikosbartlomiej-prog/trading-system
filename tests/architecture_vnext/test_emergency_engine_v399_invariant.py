"""v3.9.9 invariant test — emergency_engine NEVER targets repairable states.

After 2026-05-26 incident (3 SPY/QQQ/GLD positions market-closed because
emergency_engine flagged duplicate_exits as EmergencyTarget with
CANCEL_AND_DELETE), the scanner was tightened: blocks for `no_exit_plan`,
`duplicate_exits`, and `stale_exit_order` removed. Those states are
handled non-destructively by shared/remediation.py:
  - no_exit_plan    → RECREATE_EXIT_PLAN (v3.9.6: OCO recreate)
  - duplicate_exits → CANCEL_STALE_ORDERS with keep_one=True
  - stale_exit_order → CANCEL_STALE_ORDERS

This test is a regression guard: if any future change re-introduces those
EmergencyTarget reasons, the test fails. The principle: EMERGENCY_CLOSE
is for irreversible losses (hard_loss, deep-DTE option, defensive_mode),
NEVER for repairable order-management artifacts.
"""
import os
import sys
import tempfile
import unittest

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

import emergency_engine as ee


REPAIRABLE_REASONS = {"no_exit_plan", "duplicate_exits", "stale_exit_order"}


def _pos(symbol="SPY", qty=10, plpc=-0.02):
    return {
        "symbol": symbol, "qty": str(qty), "side": "long",
        "unrealized_plpc": str(plpc), "asset_class": "us_equity",
        "avg_entry_price": "100",
    }


class TestEmergencyEngineInvariant(unittest.TestCase):
    """Invariant: no EmergencyTarget shall have a repairable reason."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        os.environ["AUDIT_TRADING_DIR"] = self._tmp

    def test_no_exit_plan_does_not_trigger_emergency(self):
        """Position with no SELL exit order → NO emergency target.
        remediation.py handles via RECREATE_EXIT_PLAN (v3.9.6 OCO recreate)."""
        positions = [_pos("SPY", qty=10, plpc=-0.02)]
        open_orders = []  # no exits at all
        targets = ee.scan_emergency_conditions(
            account={"equity": "100000", "daily_pl_pct": "-0.5"},
            positions=positions, open_orders=open_orders, state=None,
        )
        for t in targets:
            self.assertNotIn(
                "no_exit_plan", t.reason,
                f"Regression: {t.symbol} flagged as emergency for no_exit_plan; "
                f"should go through remediation.RECREATE_EXIT_PLAN instead.",
            )

    def test_duplicate_exits_does_not_trigger_emergency(self):
        """Position with 2+ SELL OCO chains → NO emergency target.
        remediation.py handles via CANCEL_STALE_ORDERS keep_one=True."""
        positions = [_pos("QQQ", qty=10, plpc=-0.01)]
        # Two competing SELL TP orders → duplicate
        open_orders = [
            {"symbol": "QQQ", "side": "sell", "qty": "10",
             "order_type": "limit", "status": "open",
             "submitted_at": "2026-05-26T14:16:00Z"},
            {"symbol": "QQQ", "side": "sell", "qty": "10",
             "order_type": "limit", "status": "open",
             "submitted_at": "2026-05-26T16:57:00Z"},
        ]
        targets = ee.scan_emergency_conditions(
            account={"equity": "100000", "daily_pl_pct": "-0.5"},
            positions=positions, open_orders=open_orders, state=None,
        )
        for t in targets:
            self.assertNotIn(
                "duplicate_exits", t.reason,
                f"Regression: {t.symbol} flagged as emergency for duplicate_exits; "
                f"should go through remediation.CANCEL_STALE_ORDERS keep_one=True.",
            )

    def test_stale_exit_does_not_trigger_emergency(self):
        """Old SELL exit → NO emergency target.
        remediation.py handles via CANCEL_STALE_ORDERS (age-based)."""
        positions = [_pos("GLD", qty=18, plpc=0.00)]
        # Stale exit order (old timestamp)
        open_orders = [
            {"symbol": "GLD", "side": "sell", "qty": "18",
             "order_type": "limit", "status": "open",
             "submitted_at": "2026-05-01T14:00:00Z"},  # ~26 days old
        ]
        targets = ee.scan_emergency_conditions(
            account={"equity": "100000", "daily_pl_pct": "-0.5"},
            positions=positions, open_orders=open_orders, state=None,
        )
        for t in targets:
            self.assertNotIn(
                "stale_exit_order", t.reason,
                f"Regression: {t.symbol} flagged as emergency for stale_exit_order; "
                f"should go through remediation.CANCEL_STALE_ORDERS.",
            )

    def test_invariant_holds_across_all_repairable_reasons(self):
        """Cross-check: union of all 3 scenarios → ZERO repairable-reason targets."""
        positions = [
            _pos("AAA", qty=10, plpc=-0.02),  # would have been no_exit_plan
            _pos("BBB", qty=10, plpc=-0.01),  # would have been duplicate_exits
            _pos("CCC", qty=10, plpc=0.00),   # would have been stale_exit
        ]
        open_orders = [
            # BBB has two SELLs
            {"symbol": "BBB", "side": "sell", "qty": "10",
             "order_type": "limit", "status": "open",
             "submitted_at": "2026-05-26T14:00:00Z"},
            {"symbol": "BBB", "side": "sell", "qty": "10",
             "order_type": "limit", "status": "open",
             "submitted_at": "2026-05-26T16:00:00Z"},
            # CCC has stale SELL
            {"symbol": "CCC", "side": "sell", "qty": "10",
             "order_type": "limit", "status": "open",
             "submitted_at": "2026-05-01T14:00:00Z"},
        ]
        targets = ee.scan_emergency_conditions(
            account={"equity": "100000", "daily_pl_pct": "-0.5"},
            positions=positions, open_orders=open_orders, state=None,
        )
        repairable_targets = [t for t in targets
                              if any(r in t.reason for r in REPAIRABLE_REASONS)]
        self.assertEqual(
            len(repairable_targets), 0,
            f"INVARIANT VIOLATION: {len(repairable_targets)} target(s) with "
            f"repairable reasons leaked into emergency-close path: "
            f"{[(t.symbol, t.reason) for t in repairable_targets]}. "
            f"These must be handled by remediation.py non-destructively.",
        )

    def test_legitimate_emergencies_still_trigger(self):
        """v3.9.9 only removed REPAIRABLE blocks. Hard-loss + defensive_mode
        + option_near_dte must still produce EmergencyTargets."""
        # Hard loss should still fire
        positions = [_pos("LOSS", qty=10, plpc=-0.25)]  # -25%
        targets = ee.scan_emergency_conditions(
            account={"equity": "100000", "daily_pl_pct": "-0.5"},
            positions=positions, open_orders=[], state=None,
        )
        hard_loss_targets = [t for t in targets if "hard_loss" in t.reason]
        self.assertEqual(len(hard_loss_targets), 1,
                         "Hard-loss emergency must still fire after v3.9.9")


if __name__ == "__main__":
    unittest.main()
