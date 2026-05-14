"""
Tests for shared/peak_tracker.py — intraday P&L peak + profit-lock cascade.

Mocks state file via tmp dir so no real state.json touched.

Run: python -m unittest tests.test_peak_tracker
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))


class TestPeakTracker(unittest.TestCase):

    def setUp(self):
        # v3.5 refactor: peak_tracker state moved from learning-loop/state.json
        # → learning-loop/runtime_state.json (owned by shared.runtime_state).
        # Tests now redirect that path via env var and reload the modules so
        # the new path is picked up. STATE_WRITE_ACTOR=test unlocks the
        # state_policy write check for both files. AUDIT_TRADING_DIR is
        # isolated so FSM transitions triggered by these tests don't pollute
        # the real journal/autonomy/ directory.
        import importlib, tempfile as _tf
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({}, self.tmp)
        self.tmp.close()
        self.audit_tmp = _tf.mkdtemp()
        os.environ["STATE_WRITE_ACTOR"]  = "test"
        os.environ["RUNTIME_STATE_PATH"] = self.tmp.name
        os.environ["AUDIT_TRADING_DIR"]  = self.audit_tmp
        import runtime_state
        importlib.reload(runtime_state)
        import audit
        importlib.reload(audit)
        import intraday_governor
        importlib.reload(intraday_governor)
        import peak_tracker
        importlib.reload(peak_tracker)
        self.pt = peak_tracker

    def tearDown(self):
        import shutil
        os.unlink(self.tmp.name)
        shutil.rmtree(self.audit_tmp, ignore_errors=True)
        os.environ.pop("RUNTIME_STATE_PATH", None)
        os.environ.pop("AUDIT_TRADING_DIR", None)

    def _account(self, equity: float, last_equity: float) -> dict:
        return {"equity": equity, "last_equity": last_equity}

    def test_new_day_starts_zero_peak(self):
        # v3.5: first call with flat equity initialises the FSM at STATE_FLAT
        # (peak < arm threshold). The legacy verdict mapping flattens FSM
        # STATE_FLAT to VERDICT_NORMAL, NOT VERDICT_NEW_DAY — NEW_DAY is now
        # the implicit pre-init state used only when no snapshot exists yet
        # for today.
        peak = self.pt.update_peak(self._account(100_000, 100_000))
        self.assertEqual(peak["verdict"], "NORMAL")
        self.assertEqual(peak["peak_pl_usd"], 0.0)

    def test_peak_climbs_with_gains(self):
        # First call: $500 gain
        p1 = self.pt.update_peak(self._account(100_500, 100_000))
        # second call: $1500 gain — peak should rise
        p2 = self.pt.update_peak(self._account(101_500, 100_000))
        self.assertEqual(p2["peak_pl_usd"], 1500.0)
        self.assertEqual(p2["current_pl_usd"], 1500.0)
        self.assertEqual(p2["retrace_from_peak"], 0.0)

    def test_peak_holds_when_retracing(self):
        self.pt.update_peak(self._account(103_000, 100_000))   # +$3000
        p = self.pt.update_peak(self._account(101_500, 100_000))  # back to +$1500
        self.assertEqual(p["peak_pl_usd"], 3000.0)
        self.assertEqual(p["current_pl_usd"], 1500.0)
        self.assertAlmostEqual(p["retrace_from_peak"], 0.5, places=2)

    def test_verdict_normal_when_peak_below_threshold(self):
        # $500 peak, $200 current — retrace 60% BUT peak < $1000 → NORMAL
        self.pt.update_peak(self._account(100_500, 100_000))
        p = self.pt.update_peak(self._account(100_200, 100_000))
        self.assertEqual(p["verdict"], "NORMAL")

    def test_verdict_warn_at_30pct(self):
        # v3.5: GIVEBACK_WARN window is 25-35%. 30% sits inside it → WARN.
        self.pt.update_peak(self._account(102_000, 100_000))   # +$2000 peak
        p = self.pt.update_peak(self._account(101_400, 100_000))   # +$1400 (30% retrace)
        self.assertEqual(p["verdict"], "WARN")

    def test_verdict_profit_lock_at_50pct(self):
        # v3.5: 50% retrace ratchets through PROFIT_LOCK into DEFEND_DAY
        # (defend_day_pct_of_peak=0.50). The legacy shim maps both states
        # to VERDICT_PROFIT_LOCK so existing callers stay correct.
        self.pt.update_peak(self._account(103_173, 100_000))   # +$3173 peak (yesterday's)
        p = self.pt.update_peak(self._account(101_586, 100_000))   # +$1586 (50% retrace)
        self.assertEqual(p["verdict"], "PROFIT_LOCK")

    def test_yesterday_disaster_scenario(self):
        """Replay 2026-05-12 timeline — peak $3173 → -$184 should fire PROFIT_LOCK."""
        # 17:56 UTC: +$3,173 peak (equity 100,496 from start 97,323)
        self.pt.update_peak(self._account(100_496, 97_323))
        # 19:21 UTC: +$1,779 (44% retrace) — v3.5 catches this as PROFIT_LOCK
        # (was WARN under v3.3 30/50 thresholds; the new 25/35/50/60 cascade
        # reacts one tier earlier on the same data, which is the point).
        p1 = self.pt.update_peak(self._account(99_102, 97_323))
        self.assertEqual(p1["verdict"], "PROFIT_LOCK")
        # 22:18 UTC: -$157 — 100%+ retrace from a $3k+ peak after green
        # → RED_DAY_AFTER_GREEN (legacy verdict still maps to PROFIT_LOCK).
        p2 = self.pt.update_peak(self._account(97_166, 97_323))
        self.assertEqual(p2["verdict"], "PROFIT_LOCK")
        # Validate the underlying FSM upgraded to RED tier:
        self.assertEqual(p2["pnl_state"], "RED_DAY_AFTER_GREEN")

    def test_harvest_threshold_present_only_in_lock(self):
        # NORMAL case → None
        self.pt.update_peak(self._account(100_500, 100_000))
        self.assertIsNone(self.pt.harvest_threshold_usd())
        # PROFIT_LOCK → returns peak * 0.70
        self.pt.update_peak(self._account(103_000, 100_000))
        self.pt.update_peak(self._account(101_000, 100_000))   # 67% retrace
        h = self.pt.harvest_threshold_usd()
        self.assertIsNotNone(h)
        self.assertAlmostEqual(h, 3000.0 * 0.70, places=1)

    def test_alert_dedup(self):
        # 28% retrace (between 25% and 35% thresholds) → GIVEBACK_WARN → legacy
        # verdict WARN. Earlier value of $1,300 (35% retrace) now triggers
        # PROFIT_LOCK after the threshold tightening — that's correct intent
        # but breaks the strictly-WARN sub-test, so we pick 28% here.
        self.pt.update_peak(self._account(102_000, 100_000))   # $2k peak
        self.pt.update_peak(self._account(101_440, 100_000))   # 28% retrace → WARN
        self.assertFalse(self.pt.alert_already_sent_today("WARN"))
        self.pt.mark_alert_sent("WARN")
        self.assertTrue(self.pt.alert_already_sent_today("WARN"))


class TestPositionAudit(unittest.TestCase):

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO_ROOT, "learning-loop"))
        try:
            from analyzer import compute_position_audit
        except (ModuleNotFoundError, TypeError) as e:
            # analyzer imports `requests` AND uses PEP 604 `X | None`
            # (Python 3.10+). Local 3.9 misses both; CI on 3.11 has them.
            self.skipTest(f"analyzer dependency missing: {e}")
        self.audit = compute_position_audit

    def test_empty_input(self):
        self.assertEqual(self.audit([], []), [])

    def test_winner_with_exit_order_not_flagged(self):
        positions = [{"symbol": "GLD", "side": "long", "asset_class": "us_equity",
                       "unrealized_plpc": 0.15, "market_value": 1500}]
        orders = [{"symbol": "GLD", "status": "open",
                    "client_order_id": "exit-tp-GLD-12345"}]
        self.assertEqual(self.audit(positions, orders), [])

    def test_options_winner_above_tp_no_exit_flagged(self):
        # +85% on option = above TP +80%; no exit order → SUSPECT
        positions = [{"symbol": "QQQ260518P00714000", "side": "long",
                       "asset_class": "us_option",
                       "unrealized_plpc": 0.85, "market_value": 1800}]
        out = self.audit(positions, [])
        self.assertEqual(len(out), 1)
        self.assertIn("QQQ260518P00714000", out[0]["symbol"])
        self.assertIn("TP", out[0]["reason"])

    def test_emergency_loss_no_exit_flagged(self):
        positions = [{"symbol": "AAPL260520P00295000", "side": "long",
                       "asset_class": "us_option",
                       "unrealized_plpc": -0.16, "market_value": 390}]
        out = self.audit(positions, [])
        self.assertEqual(len(out), 1)
        self.assertIn("emergency", out[0]["reason"])

    def test_filled_exit_does_not_protect_from_audit(self):
        # has_exit only counts OPEN exit orders, not filled ones
        positions = [{"symbol": "QQQ260518P00714000", "side": "long",
                       "asset_class": "us_option",
                       "unrealized_plpc": 0.85}]
        orders = [{"symbol": "QQQ260518P00714000", "status": "filled",
                    "client_order_id": "exit-tp-QQQ-old"}]
        out = self.audit(positions, orders)
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
