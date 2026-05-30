"""
v3.9.7 (2026-05-23) — Test NEW_DAY peak reset bug fix.

Bug observed 2026-05-23 08:31 UTC:
  - Saturday morning, 0 positions, $0 actual intraday P&L
  - Alpaca's last_equity returned previous-session-OPEN value (= Thursday close)
  - daily_pl = equity - last_equity = Friday's full P&L (~$1,400)
  - On NEW_DAY transition (01:22 UTC), governor set peak_pnl = $1,400 from this
  - Later when last_equity refreshed to Friday's CLOSE, daily_pl = $0
  - But intraday_peak_pnl was PRESERVED as $1,400
  - giveback = (peak - current)/peak = 100% → triggered RED_DAY_AFTER_GREEN
  - max_gross_target dropped to 0.25 → BLOCKS new entries
  - On Monday allocator would be unable to open positions

Fix: on new_day, ignore Alpaca's reported daily_pl when seeding peak.
Set peak = 0 + peak_equity = current_equity. Subsequent ticks will
naturally accumulate peak as REAL intraday gains arrive.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))


class TestNewDayPeakReset(unittest.TestCase):

    def _fresh_run(self, prev_date: str, today_equity: float,
                    today_last_equity: float, prev_peak: float = 0.0):
        """
        Run governor.update() with mocked Alpaca account state + mocked
        prior runtime_state.

        Returns the snapshot dict.
        """
        import intraday_governor as ig

        prev_raw = {
            "date":                 prev_date,
            "pnl_state":            "GREEN",
            "intraday_peak_pnl":    prev_peak,
            "intraday_peak_equity": today_last_equity + prev_peak,
            "peak_at":              "2026-05-22T15:00:00Z",
            "alerts_sent":          {},
            "state_entered_at":     "2026-05-22T15:00:00Z",
        }
        account = {
            "equity":      today_equity,
            "last_equity": today_last_equity,
        }

        with patch.object(ig, "read_section", return_value=prev_raw), \
             patch.object(ig, "write_section") as mock_write, \
             patch.object(ig, "emit_audit", lambda *a, **kw: None), \
             patch.object(ig, "_today", return_value="2026-05-23"):
            snap = ig.update(account=account)

        return snap

    def test_new_day_ignores_stale_alpaca_daily_pl(self):
        """
        CRITICAL: 2026-05-23 incident replay.
        Saturday morning, Alpaca last_equity = Thursday close = $96,427,
        current equity = Friday close = $97,832. daily_pl looks like
        $1,405 but this is STALE (Friday's gain, already finalized).
        On NEW_DAY, peak MUST be 0, not $1,405.
        """
        snap = self._fresh_run(
            prev_date="2026-05-22",     # different from today → new_day=True
            today_equity=97832.94,
            today_last_equity=96427.97,  # Alpaca's stale value
            prev_peak=1404.97,           # yesterday's preserved peak (ignored on new_day)
        )

        # Peak MUST be 0 on new day, not the misleading $1,405
        self.assertEqual(snap.intraday_peak_pnl, 0.0,
                          msg="v3.9.7: NEW_DAY must seed peak at 0, ignoring "
                              "Alpaca's stale last_equity-based daily_pl")
        self.assertAlmostEqual(snap.intraday_peak_equity, 97832.94, places=1,
                                msg="peak_equity baseline = current equity, not stale ratchet")
        self.assertEqual(snap.giveback_pct_of_peak, 0.0,
                          msg="giveback must be 0 on fresh day start")

    def test_same_day_preserves_peak_correctly(self):
        """
        Sanity: same-day update preserves real intraday peak. This was the
        pre-existing behavior and v3.9.7 must NOT break it.
        """
        # Mid-day update: prev_date matches today
        snap = self._fresh_run(
            prev_date="2026-05-23",     # same as today → new_day=False
            today_equity=99000.0,        # current up $1,200 from last_equity
            today_last_equity=97832.0,
            prev_peak=800.0,             # previous intraday peak was $800
        )

        # Peak ratchets up from $800 to current $1,168 (= 99000 - 97832)
        self.assertGreater(snap.intraday_peak_pnl, 800.0,
                            msg="same-day peak should ratchet up with rising current P&L")
        self.assertAlmostEqual(snap.intraday_peak_pnl, 1168.0, places=1)

    def test_new_day_with_actual_zero_pl_stays_clean(self):
        """
        Saturday no-position scenario (today's reality):
        equity == last_equity (Alpaca refreshed correctly).
        Should produce clean FLAT state with 0 peak.
        """
        snap = self._fresh_run(
            prev_date="2026-05-22",
            today_equity=97832.88,
            today_last_equity=97832.88,  # equal — true zero daily_pl
            prev_peak=1404.97,
        )

        self.assertEqual(snap.intraday_peak_pnl, 0.0)
        self.assertEqual(snap.giveback_pct_of_peak, 0.0)
        self.assertIn(snap.pnl_state, ("FLAT", "NEW_DAY"))

    def test_new_day_avoids_red_after_green_false_positive(self):
        """
        End-to-end: simulate the 2026-05-23 incident sequence.
        New day starts with stale Alpaca data → peak=0 (not $1,405).
        Later when daily_pl resolves to 0, no false RED_DAY_AFTER_GREEN.
        """
        # Step 1: new day, stale Alpaca data → governor properly starts at 0
        snap1 = self._fresh_run(
            prev_date="2026-05-22",
            today_equity=97832.94,
            today_last_equity=96427.97,
            prev_peak=1404.97,
        )
        self.assertEqual(snap1.intraday_peak_pnl, 0.0)
        self.assertNotEqual(snap1.pnl_state, "RED_DAY_AFTER_GREEN",
                              msg="must NOT enter defensive cascade on new day with stale peak")

        # Step 2: same day later, real zero P&L → still clean
        snap2 = self._fresh_run(
            prev_date="2026-05-23",
            today_equity=97832.88,
            today_last_equity=97832.88,
            prev_peak=0.0,                  # carried from snap1
        )
        self.assertEqual(snap2.intraday_peak_pnl, 0.0)
        self.assertNotEqual(snap2.pnl_state, "RED_DAY_AFTER_GREEN")
        self.assertNotEqual(snap2.pnl_state, "PROFIT_LOCK")


if __name__ == "__main__":
    unittest.main()
