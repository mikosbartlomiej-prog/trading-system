"""
Tests for shared/intraday_governor.py — IntradayProfitGovernor.

Each test isolates persistence by pointing shared.runtime_state.RUNTIME_STATE_PATH
to a tmp file. STATE_WRITE_ACTOR=test lets writes through.

Run:
    python -m unittest tests.test_intraday_governor
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))


class _GovBase(unittest.TestCase):
    """Common setUp/tearDown: isolate runtime_state.json + reload modules."""

    def setUp(self):
        # Build a tmp file and redirect both module-level constants. We have
        # to reload the modules because they cache the path at import time.
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump({}, self.tmp)
        self.tmp.close()
        # Isolate the audit trail too — tests trigger FSM transitions, and
        # every transition writes to AUDIT_TRADING_DIR. Without this, every
        # `unittest tests.test_intraday_governor` run would pollute the real
        # journal/autonomy/ directory.
        self.audit_tmp = tempfile.mkdtemp()

        os.environ["STATE_WRITE_ACTOR"]   = "test"
        os.environ["RUNTIME_STATE_PATH"]  = self.tmp.name
        os.environ["AUDIT_TRADING_DIR"]   = self.audit_tmp
        # Make sure the env knobs are honored.
        import importlib
        import runtime_state
        importlib.reload(runtime_state)
        self.runtime_state = runtime_state
        import audit
        importlib.reload(audit)

        import intraday_governor
        importlib.reload(intraday_governor)
        self.ig = intraday_governor

    def tearDown(self):
        import shutil
        os.unlink(self.tmp.name)
        shutil.rmtree(self.audit_tmp, ignore_errors=True)
        os.environ.pop("RUNTIME_STATE_PATH", None)
        os.environ.pop("AUDIT_TRADING_DIR", None)

    def acct(self, equity: float, last_equity: float = 100_000) -> dict:
        return {"equity": equity, "last_equity": last_equity}


# ─── Scenario A: +5000 → -2000 must trip every protection tier ──────────────

class TestPlus5000ToMinus2000Scenario(_GovBase):
    """
    The exact pattern this iteration solves: a day that hit +$5,000 cannot
    end -$2,000 without deterministic action firing.
    """

    def test_full_giveback_cascade(self):
        ig = self.ig
        # 09:45 ET — +$2k (armed, GREEN, but not yet STRONG)
        s1 = ig.update(self.acct(102_000))
        self.assertIn(s1.pnl_state, (ig.STATE_GREEN, ig.STATE_STRONG_GREEN))
        self.assertEqual(s1.intraday_peak_pnl, 2_000)

        # 11:30 ET — +$5k peak (STRONG_GREEN)
        s2 = ig.update(self.acct(105_000))
        self.assertEqual(s2.pnl_state, ig.STATE_STRONG_GREEN)
        self.assertEqual(s2.intraday_peak_pnl, 5_000)
        self.assertAlmostEqual(s2.profit_floor_usd, 5_000 * 0.50, places=1)

        # 13:00 ET — back to +$3,500 (30% giveback → GIVEBACK_WARN)
        s3 = ig.update(self.acct(103_500))
        self.assertEqual(s3.pnl_state, ig.STATE_GIVEBACK_WARN)

        # 14:00 ET — +$2,500 (50% giveback → PROFIT_LOCK; actually crosses
        # defend threshold too since defend_day_pct_of_peak=0.50)
        s4 = ig.update(self.acct(102_500))
        self.assertEqual(s4.pnl_state, ig.STATE_DEFEND_DAY)
        self.assertTrue(s4.block_new_entries)

        # 15:00 ET — +$1,000 (80% giveback → RED_DAY_AFTER_GREEN check)
        # 80% > 60% red_after_green threshold → RED
        s5 = ig.update(self.acct(101_000))
        self.assertEqual(s5.pnl_state, ig.STATE_RED_DAY_AFTER_GREEN)
        self.assertTrue(s5.block_new_entries)

        # 15:30 ET — -$2,000 (cur ≤ 0 after green peak → RED still)
        s6 = ig.update(self.acct(98_000))
        self.assertEqual(s6.pnl_state, ig.STATE_RED_DAY_AFTER_GREEN)
        self.assertTrue(s6.block_new_entries)
        self.assertTrue(s6.options_first_reduction)

        # Gross-exposure target ratchets down monotonically.
        self.assertGreaterEqual(s2.max_gross_target, s3.max_gross_target)
        self.assertGreaterEqual(s3.max_gross_target, s4.max_gross_target)
        self.assertGreaterEqual(s4.max_gross_target, s6.max_gross_target)
        self.assertAlmostEqual(s6.max_gross_target, 0.25, places=2)

    def test_terminal_states_dont_downgrade(self):
        """Once in DEFEND_DAY, a bounce should NOT roll us back to GREEN."""
        ig = self.ig
        ig.update(self.acct(105_000))
        ig.update(self.acct(102_500))            # → DEFEND_DAY
        bounce = ig.update(self.acct(103_500))   # would be GIVEBACK_WARN
        self.assertEqual(bounce.pnl_state, ig.STATE_DEFEND_DAY)


# ─── Scenario B: green-to-red protection (peak ≥ $3k AND current ≤ 0) ──────

class TestGreenToRedProtection(_GovBase):
    def test_green_to_red_fires_red_day_state(self):
        ig = self.ig
        ig.update(self.acct(103_500))                  # +$3.5k peak
        snap = ig.update(self.acct(99_500))            # → red (-$500)
        self.assertEqual(snap.pnl_state, ig.STATE_RED_DAY_AFTER_GREEN)
        self.assertTrue(snap.block_new_entries)

    def test_peak_below_arm_then_red_is_just_flat(self):
        """Peak never crossed $1k arm threshold → no RED state, just FLAT."""
        ig = self.ig
        ig.update(self.acct(100_500))                  # +$500 (below arm)
        snap = ig.update(self.acct(99_500))            # -$500
        self.assertNotEqual(snap.pnl_state, ig.STATE_RED_DAY_AFTER_GREEN)
        self.assertFalse(snap.block_new_entries)


# ─── Scenario C: profit floor matches tier table ───────────────────────────

class TestProfitFloor(_GovBase):
    def test_tier_1(self):
        ig = self.ig
        s = ig.update(self.acct(101_500))   # +$1.5k peak
        self.assertAlmostEqual(s.profit_floor_usd, 1_500 * 0.25, places=1)

    def test_tier_2(self):
        s = self.ig.update(self.acct(103_500))   # +$3.5k peak
        self.assertAlmostEqual(s.profit_floor_usd, 3_500 * 0.40, places=1)

    def test_tier_3(self):
        s = self.ig.update(self.acct(107_000))   # +$7k peak
        self.assertAlmostEqual(s.profit_floor_usd, 7_000 * 0.50, places=1)

    def test_no_floor_below_arm(self):
        s = self.ig.update(self.acct(100_500))   # +$500 only
        self.assertEqual(s.profit_floor_usd, 0.0)


# ─── Scenario D: position-level MFE harvest ────────────────────────────────

class TestPositionMFE(_GovBase):
    def test_tier1_peak8_retrace40_reduces(self):
        # Peak at +8% then drop to +4.5% → retrace ≈ 44% → tier1 reduce 50%
        self.ig.position_mfe_action({"symbol": "AAPL", "unrealized_plpc": 0.08})
        out = self.ig.position_mfe_action(
            {"symbol": "AAPL", "unrealized_plpc": 0.045}
        )
        self.assertEqual(out["action"], "REDUCE")
        self.assertAlmostEqual(out["reduce_pct"], 0.50, places=2)

    def test_tier3_peak20_retrace30_harvests(self):
        self.ig.position_mfe_action({"symbol": "NVDA", "unrealized_plpc": 0.22})
        out = self.ig.position_mfe_action(
            {"symbol": "NVDA", "unrealized_plpc": 0.155}
        )
        self.assertEqual(out["action"], "HARVEST")
        self.assertEqual(out["reduce_pct"], 1.0)

    def test_hold_within_tolerance(self):
        self.ig.position_mfe_action({"symbol": "MSFT", "unrealized_plpc": 0.10})
        out = self.ig.position_mfe_action(
            {"symbol": "MSFT", "unrealized_plpc": 0.085}
        )
        self.assertEqual(out["action"], "HOLD")

    def test_alpaca_percent_form_handled(self):
        # Alpaca sometimes returns plpc as a percent (e.g. 8.5 instead of 0.085).
        out = self.ig.position_mfe_action({"symbol": "X", "unrealized_plpc": 12.0})
        # 12% peak; same tick treated as both peak and current → 0 retrace.
        self.assertEqual(out["action"], "HOLD")


# ─── Scenario E: account state unavailable → block new entries ─────────────

class TestAccountUnavailable(_GovBase):
    def test_account_none_blocks_entries(self):
        snap = self.ig.update(account=None)
        self.assertTrue(snap.block_new_entries)
        self.assertTrue(snap.account_unavailable)

    def test_account_missing_last_equity_blocks_entries(self):
        snap = self.ig.update({"equity": 100_000, "last_equity": 0})
        self.assertTrue(snap.block_new_entries)
        self.assertTrue(snap.account_unavailable)


# ─── Scenario F: entry-gate API ────────────────────────────────────────────

class TestBlockNewEntriesGate(_GovBase):
    def test_allow_in_green_state(self):
        self.ig.update(self.acct(102_000))   # GREEN/STRONG_GREEN
        block, reason = self.ig.block_new_entries(symbol="NVDA", score=0.40)
        self.assertFalse(block)

    def test_block_in_defend_day(self):
        self.ig.update(self.acct(105_000))
        self.ig.update(self.acct(102_500))   # → DEFEND_DAY
        block, reason = self.ig.block_new_entries(symbol="NVDA", score=0.80)
        self.assertTrue(block)
        self.assertIn("DEFEND_DAY", reason)

    def test_profit_lock_allows_high_score(self):
        self.ig.update(self.acct(105_000))
        # Force PROFIT_LOCK but NOT DEFEND_DAY by giving back ~35-49%.
        self.ig.update(self.acct(103_200))   # 36% retrace
        # Sanity: state must be PROFIT_LOCK to make the test meaningful.
        snap = self.ig.get_snapshot()
        self.assertEqual(snap.pnl_state, self.ig.STATE_PROFIT_LOCK)
        # Low-score signal → block
        b1, _ = self.ig.block_new_entries(symbol="X", score=0.40)
        self.assertTrue(b1)
        # High-score override → allow
        b2, _ = self.ig.block_new_entries(symbol="X", score=0.80)
        self.assertFalse(b2)

    def test_account_unavailable_blocks(self):
        self.ig.update(account=None)
        block, reason = self.ig.block_new_entries()
        self.assertTrue(block)
        self.assertIn("account_unavailable", reason)


# ─── Scenario G: max_gross_target / options_first per state ─────────────────

class TestExposureAndOptionsFirst(_GovBase):
    def test_options_first_in_profit_lock_cascade(self):
        self.ig.update(self.acct(105_000))
        self.ig.update(self.acct(103_200))   # PROFIT_LOCK
        self.assertTrue(self.ig.should_close_options_first())

    def test_options_first_not_in_green(self):
        self.ig.update(self.acct(102_000))
        self.assertFalse(self.ig.should_close_options_first())

    def test_max_gross_clamps_with_state(self):
        self.ig.update(self.acct(105_000))
        self.ig.update(self.acct(102_500))   # DEFEND_DAY
        self.assertAlmostEqual(self.ig.max_gross_exposure_target(), 0.50, places=2)
        self.ig.update(self.acct(99_500))    # RED
        self.assertAlmostEqual(self.ig.max_gross_exposure_target(), 0.25, places=2)


# ─── Scenario H: audit JSONL written on transitions ────────────────────────

class TestAuditEventsOnTransition(_GovBase):
    def test_profit_lock_transition_writes_audit_line(self):
        # Trigger a PROFIT_LOCK transition (audit dir is already isolated
        # by _GovBase.setUp).
        self.ig.update(self.acct(105_000))
        self.ig.update(self.acct(103_200))   # PROFIT_LOCK
        # Scan the isolated audit dir for any file with PROFIT_LOCK_TRIGGERED
        found = False
        for fn in os.listdir(self.audit_tmp):
            with open(os.path.join(self.audit_tmp, fn), encoding="utf-8") as f:
                for line in f:
                    if "PROFIT_LOCK_TRIGGERED" in line:
                        found = True
                        rec = json.loads(line)
                        self.assertEqual(rec["actor"], "intraday-governor")
                        self.assertEqual(rec["state_after"], self.ig.STATE_PROFIT_LOCK)
        self.assertTrue(found, "expected PROFIT_LOCK_TRIGGERED audit line not written")


# ─── Scenario I: legacy peak_tracker shim still works ──────────────────────

class TestLegacyPeakTrackerShim(_GovBase):
    def test_shim_translates_state_to_verdict(self):
        import importlib
        import peak_tracker
        importlib.reload(peak_tracker)
        peak_tracker.update_peak(self.acct(105_000))
        # 50% retrace → DEFEND_DAY → legacy VERDICT_PROFIT_LOCK
        legacy = peak_tracker.update_peak(self.acct(102_500))
        self.assertEqual(legacy["verdict"], peak_tracker.VERDICT_PROFIT_LOCK)
        in_lock, _ = peak_tracker.should_profit_lock()
        self.assertTrue(in_lock)


if __name__ == "__main__":
    unittest.main()
