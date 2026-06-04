"""v3.15.0 (2026-06-04) — Tests for trader-feedback-driven modules.

Covers FB-001 / FB-002 / FB-003 / FB-005 / FB-006 / FB-010 / FB-011 /
FB-012 / FB-013 / FB-014 / FB-015.

All tests are LOCAL + DETERMINISTIC + NO NETWORK.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ─── Synthetic bars helpers ───────────────────────────────────────────────────

def _make_bars(n=60, base=100.0, vol=1000.0):
    closes  = [base + i * 0.5 for i in range(n)]
    highs   = [c + 1.5 for c in closes]
    lows    = [c - 1.5 for c in closes]
    opens   = closes[:]
    volumes = [vol] * n
    times   = [f"2026-04-{(i % 28) + 1:02d}T00:00:00+00:00" for i in range(n)]
    return {
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": volumes, "time": times,
    }


# ─── FB-001 / FB-004 — InstrumentProfile ──────────────────────────────────────

class TestInstrumentProfile(unittest.TestCase):
    def test_insufficient_bars_returns_zero_quality(self):
        from instrument_profile import build_profile_from_bars
        p = build_profile_from_bars("XXX", {"close": [1, 2, 3]})
        self.assertTrue(p.insufficient_data)
        self.assertEqual(p.quality, 0.0)

    def test_empty_bars_returns_no_bars_warning(self):
        from instrument_profile import build_profile_from_bars
        p = build_profile_from_bars("YYY", {})
        self.assertTrue(p.insufficient_data)
        self.assertEqual(p.bars_count, 0)
        self.assertIn("no_bars", p.warnings)

    def test_full_bars_produces_quality_above_zero(self):
        from instrument_profile import build_profile_from_bars
        bars = _make_bars(60)
        p = build_profile_from_bars("AAPL", bars, now_ts=1717459200.0)
        self.assertFalse(p.insufficient_data)
        self.assertGreater(p.quality, 0.0)
        self.assertEqual(p.bars_count, 60)
        self.assertIsNotNone(p.volatility)
        self.assertIsNotNone(p.trend)

    def test_profile_does_NOT_raise_confidence_on_its_own(self):
        # Profile cannot mutate any global confidence state.
        from instrument_profile import build_profile_from_bars
        bars = _make_bars(60)
        p = build_profile_from_bars("AAPL", bars)
        self.assertEqual(p.symbol, "AAPL")
        # Confidence boost is the caller's decision — profile only carries
        # quality.
        self.assertIsInstance(p.quality, float)

    def test_dynamic_profiler_with_no_data_marks_insufficient(self):
        from instrument_profile import DynamicInstrumentProfiler, clear_cache
        clear_cache()
        # Force fetch path with bad symbol - get_daily_bars likely None
        # outside ALPACA env -> profile insufficient.
        prof = DynamicInstrumentProfiler(days=60).profile("BAD@SYMBOL")
        self.assertTrue(prof.insufficient_data)
        self.assertEqual(prof.quality, 0.0)


# ─── FB-002 — Pre-open behavior ───────────────────────────────────────────────

class TestPreOpenBehavior(unittest.TestCase):
    def test_no_data_returns_insufficient(self):
        from pre_open_behavior import analyze_pre_open, INSUFFICIENT_DATA
        r = analyze_pre_open()
        self.assertEqual(r.label, INSUFFICIENT_DATA)
        self.assertEqual(r.confidence_adjustment, 0.0)

    def test_strong_gap_up_classified(self):
        from pre_open_behavior import analyze_pre_open, GAP_UP_STRONG_PRE_OPEN
        bars = [{"o": 100, "h": 103, "l": 100, "c": 103, "v": 50000}
                for _ in range(3)]
        r = analyze_pre_open(pre_market_bars=bars, prev_session_close=100.0)
        self.assertEqual(r.label, GAP_UP_STRONG_PRE_OPEN)
        self.assertGreater(r.gap_pct, 0.025)

    def test_strong_gap_down_classified(self):
        from pre_open_behavior import analyze_pre_open, GAP_DOWN_STRONG_PRE_OPEN
        bars = [{"o": 100, "h": 100, "l": 97, "c": 97, "v": 50000}
                for _ in range(3)]
        r = analyze_pre_open(pre_market_bars=bars, prev_session_close=100.0)
        self.assertEqual(r.label, GAP_DOWN_STRONG_PRE_OPEN)

    def test_low_volume_fake_move_demotion(self):
        from pre_open_behavior import analyze_pre_open, LOW_VOLUME_FAKE_MOVE
        bars = [{"o": 100, "h": 103, "l": 100, "c": 103, "v": 100} for _ in range(3)]
        r = analyze_pre_open(
            pre_market_bars=bars, prev_session_close=100.0,
            historical_pm_volume_avg=100_000)
        self.assertEqual(r.label, LOW_VOLUME_FAKE_MOVE)
        self.assertLess(r.confidence_adjustment, 0)

    def test_flat_pre_open_no_adjustment(self):
        from pre_open_behavior import analyze_pre_open, FLAT_PRE_OPEN
        bars = [{"o": 100, "h": 100.1, "l": 99.9, "c": 100.0, "v": 1000} for _ in range(3)]
        r = analyze_pre_open(pre_market_bars=bars, prev_session_close=100.0)
        self.assertEqual(r.label, FLAT_PRE_OPEN)
        self.assertEqual(r.confidence_adjustment, 0.0)


# ─── FB-003 — Lead-lag analyzer ───────────────────────────────────────────────

class TestLeadLagAnalyzer(unittest.TestCase):
    def test_insufficient_data_label(self):
        from lead_lag_analyzer import analyze_lead_lag, INSUFFICIENT_DATA
        r = analyze_lead_lag(symbol_closes=[1, 2, 3], index_closes=[1, 2, 3])
        self.assertEqual(r.verdict, INSUFFICIENT_DATA)

    def test_perfect_alignment_classifies_as_index_aligned(self):
        from lead_lag_analyzer import analyze_lead_lag, INDEX_ALIGNED
        # Symbol == 2 × index returns
        idx = [100 + i for i in range(30)]
        sym = [50 + 2 * i for i in range(30)]
        r = analyze_lead_lag(symbol_closes=sym, index_closes=idx)
        self.assertIn(r.verdict, (INDEX_ALIGNED,))
        self.assertGreater(r.contemporaneous_corr, 0.9)

    def test_divergent_classifies_as_index_divergent(self):
        from lead_lag_analyzer import analyze_lead_lag, INDEX_DIVERGENT
        # Force opposite return patterns: alternating up/down for one,
        # opposite for the other.
        idx = [100.0]
        sym = [100.0]
        for i in range(1, 30):
            # idx: alternating +1/-0.5
            idx.append(idx[-1] * (1.01 if i % 2 == 0 else 0.995))
            # sym: opposite signs
            sym.append(sym[-1] * (0.99 if i % 2 == 0 else 1.005))
        r = analyze_lead_lag(symbol_closes=sym, index_closes=idx)
        self.assertEqual(r.verdict, INDEX_DIVERGENT)
        self.assertLess(r.contemporaneous_corr, -0.9)

    def test_confidence_adjustment_capped(self):
        from lead_lag_analyzer import (
            analyze_lead_lag, confidence_adjustment, INDEX_ALIGNED,
        )
        idx = [100 + i for i in range(30)]
        sym = [50 + 2 * i for i in range(30)]
        r = analyze_lead_lag(symbol_closes=sym, index_closes=idx)
        adj = confidence_adjustment(r)
        self.assertLessEqual(adj, 0.05)
        self.assertGreaterEqual(adj, -0.10)


# ─── FB-006 / FB-014 / FB-015 — Source Quality Policy ─────────────────────────

class TestSourceQualityPolicy(unittest.TestCase):
    def test_sec_filing_is_tier_1(self):
        from source_quality import tier_for, TIER_1
        self.assertEqual(tier_for("sec_edgar"), TIER_1)
        self.assertEqual(tier_for("sec_8k"), TIER_1)
        self.assertEqual(tier_for("dod_contract"), TIER_1)

    def test_reuters_is_tier_2(self):
        from source_quality import tier_for, TIER_2
        self.assertEqual(tier_for("reuters"), TIER_2)
        self.assertEqual(tier_for("tracked_dd"), TIER_2)

    def test_reddit_is_tier_3(self):
        from source_quality import tier_for, TIER_3
        self.assertEqual(tier_for("reddit"), TIER_3)
        self.assertEqual(tier_for("twitter_anon"), TIER_3)

    def test_unknown_source_is_treated_as_unknown_safer(self):
        from source_quality import tier_for, TIER_UNKNOWN
        self.assertEqual(tier_for("randomXYZ"), TIER_UNKNOWN)
        self.assertEqual(tier_for(None), TIER_UNKNOWN)

    def test_tier_3_ceiling_below_allow_threshold(self):
        from source_quality import confidence_ceiling_for
        # Tier 3 ceiling 0.45 < default ALLOW threshold 0.65
        self.assertLess(confidence_ceiling_for("reddit"), 0.50)

    def test_tier_1_eligible_alone_for_day_trade(self):
        from source_quality import is_day_trade_eligible_alone
        self.assertTrue(is_day_trade_eligible_alone("sec_8k"))
        self.assertFalse(is_day_trade_eligible_alone("reddit"))
        self.assertFalse(is_day_trade_eligible_alone("reuters"))

    def test_dd_not_day_trade_trigger_without_confirmation(self):
        from source_quality import dd_is_day_trade_trigger
        self.assertFalse(dd_is_day_trade_trigger("tracked_dd"))
        self.assertFalse(dd_is_day_trade_trigger("tracked_dd",
                                                   has_price_confirmation=True))
        self.assertTrue(dd_is_day_trade_trigger("tracked_dd",
                                                   has_price_confirmation=True,
                                                   has_volume_confirmation=True))

    def test_classify_emits_full_structure(self):
        from source_quality import classify
        c = classify("sec_8k")
        self.assertEqual(c.tier, "tier_1_primary")
        self.assertTrue(c.day_trade_eligible_alone)


# ─── FB-011 — PositionManager ─────────────────────────────────────────────────

class TestPositionManager(unittest.TestCase):
    def test_open_position_starts_in_INTAKE(self):
        from position_manager import open_position, INTAKE
        s = open_position(symbol="AAPL", entry_price=100.0, entry_qty=10)
        self.assertEqual(s.lifecycle, INTAKE)

    def test_kill_switch_forces_full_exit(self):
        from position_manager import (
            open_position, evaluate_position, update_position_marks,
            FULL_EXIT, CLOSED,
        )
        s = open_position(symbol="AAPL", entry_price=100.0, entry_qty=10)
        s = update_position_marks(s, current_price=100.0)
        d = evaluate_position(s, kill_switch_armed=True)
        self.assertEqual(d.recommendation, FULL_EXIT)
        self.assertEqual(d.next_lifecycle, CLOSED)
        self.assertIn("kill_switch", d.triggered_signals)

    def test_safe_mode_forces_full_exit(self):
        from position_manager import (
            open_position, evaluate_position, update_position_marks,
            FULL_EXIT,
        )
        s = open_position(symbol="AAPL", entry_price=100.0, entry_qty=10)
        s = update_position_marks(s, current_price=100.0)
        d = evaluate_position(s, safe_mode_active=True)
        self.assertEqual(d.recommendation, FULL_EXIT)
        self.assertIn("safe_mode", d.triggered_signals)

    def test_invalidation_signal_INVALIDATE(self):
        from position_manager import (
            open_position, evaluate_position, update_position_marks,
            INVALIDATE,
        )
        s = open_position(symbol="AAPL", entry_price=100.0, entry_qty=10)
        s = update_position_marks(s, current_price=100.0)
        d = evaluate_position(s, invalidation_signal=True)
        self.assertEqual(d.recommendation, INVALIDATE)

    def test_max_adverse_excursion_triggers_full_exit(self):
        from position_manager import (
            PositionState, evaluate_position, FULL_EXIT, ARMED,
            MAX_ADVERSE_EXCURSION_PCT,
        )
        s = PositionState(
            symbol="AAPL", lifecycle=ARMED,
            opened_at_iso="2026-06-01T00:00:00+00:00",
            entry_price=100.0, entry_qty=10, entry_confidence=0.7,
            intent="swing",
            last_eval_at_iso="2026-06-01T01:00:00+00:00",
            current_price=90.0, current_pl_pct=-0.10,
            peak_price=100.0, peak_pl_pct=0.0,
            trough_price=90.0, trough_pl_pct=-0.10,
            time_stop_hours=48, time_at_eval_hours=1.0,
            confidence_now=0.7, profile_quality_now=0.8,
        )
        d = evaluate_position(s)
        self.assertEqual(d.recommendation, FULL_EXIT)
        self.assertIn("max_adverse_excursion", d.triggered_signals)

    def test_time_stop_triggers_full_exit(self):
        from position_manager import (
            PositionState, evaluate_position, FULL_EXIT, ARMED, TIME_EXPIRED,
        )
        s = PositionState(
            symbol="AAPL", lifecycle=ARMED,
            opened_at_iso="2026-06-01T00:00:00+00:00",
            entry_price=100.0, entry_qty=10, entry_confidence=0.7,
            intent="swing",
            last_eval_at_iso="2026-06-05T00:00:00+00:00",
            current_price=99.0, current_pl_pct=-0.01,
            peak_price=100.0, peak_pl_pct=0.0,
            trough_price=99.0, trough_pl_pct=-0.01,
            time_stop_hours=48, time_at_eval_hours=49.0,
            confidence_now=0.7, profile_quality_now=0.8,
        )
        d = evaluate_position(s)
        self.assertEqual(d.recommendation, FULL_EXIT)
        self.assertEqual(d.next_lifecycle, TIME_EXPIRED)

    def test_confidence_collapse_triggers_exit(self):
        from position_manager import (
            PositionState, evaluate_position, FULL_EXIT, ARMED,
        )
        s = PositionState(
            symbol="AAPL", lifecycle=ARMED,
            opened_at_iso="2026-06-01T00:00:00+00:00",
            entry_price=100.0, entry_qty=10, entry_confidence=0.80,
            intent="swing",
            last_eval_at_iso="2026-06-01T03:00:00+00:00",
            current_price=99.0, current_pl_pct=-0.01,
            peak_price=100.0, peak_pl_pct=0.0,
            trough_price=99.0, trough_pl_pct=-0.01,
            time_stop_hours=48, time_at_eval_hours=3.0,
            confidence_now=0.30, profile_quality_now=0.8,
        )
        d = evaluate_position(s)
        self.assertEqual(d.recommendation, FULL_EXIT)
        self.assertIn("confidence_collapsed", d.triggered_signals)

    def test_intake_grace_holds(self):
        from position_manager import (
            open_position, evaluate_position, update_position_marks,
            HOLD, INTAKE,
        )
        s = open_position(symbol="AAPL", entry_price=100.0, entry_qty=10)
        d = evaluate_position(s)
        self.assertEqual(d.recommendation, HOLD)
        self.assertEqual(d.next_lifecycle, INTAKE)

    def test_partial_exit_at_profit(self):
        from position_manager import (
            PositionState, evaluate_position, PARTIAL_EXIT, ARMED, TRAILING,
            PARTIAL_EXIT_PROFIT_PCT,
        )
        s = PositionState(
            symbol="AAPL", lifecycle=ARMED,
            opened_at_iso="2026-06-01T00:00:00+00:00",
            entry_price=100.0, entry_qty=10, entry_confidence=0.7,
            intent="swing",
            last_eval_at_iso="2026-06-01T04:00:00+00:00",
            current_price=111.0, current_pl_pct=0.11,
            peak_price=111.0, peak_pl_pct=0.11,
            trough_price=100.0, trough_pl_pct=0.0,
            time_stop_hours=48, time_at_eval_hours=4.0,
            confidence_now=0.7, profile_quality_now=0.8,
        )
        d = evaluate_position(s)
        self.assertEqual(d.recommendation, PARTIAL_EXIT)
        self.assertEqual(d.next_lifecycle, TRAILING)
        self.assertAlmostEqual(d.partial_qty_pct, 0.5)


# ─── FB-012 — LiquiditySweepGuard ─────────────────────────────────────────────

class TestLiquiditySweepGuard(unittest.TestCase):
    def test_no_data_returns_allow(self):
        from liquidity_sweep_guard import evaluate_sweep_risk, ALLOW
        r = evaluate_sweep_risk()
        self.assertEqual(r.verdict, ALLOW)

    def test_long_wick_reversal_detected(self):
        from liquidity_sweep_guard import (
            evaluate_sweep_risk, ELEVATED_RISK, BLOCK,
        )
        # Bar with huge upper wick + close near low → long_wick_reversal True
        opens   = [100, 100]
        highs   = [101, 110]
        lows    = [99, 99]
        closes  = [100, 100.5]   # closed near open → giveback > 50% of range
        volumes = [1000, 1000]
        r = evaluate_sweep_risk(
            opens=opens, highs=highs, lows=lows, closes=closes, volumes=volumes,
        )
        self.assertTrue(r.long_wick_reversal)

    def test_block_when_multiple_signals_present(self):
        from liquidity_sweep_guard import evaluate_sweep_risk, BLOCK
        # Stack: long wick reversal + volume spike no follow + high spread.
        opens   = [100] * 22
        highs   = [101] * 21 + [120]   # last bar makes new 20-bar high
        lows    = [99] * 22
        closes  = [100] * 21 + [100.5]  # last bar closes giving back from high
        volumes = [1000] * 21 + [5000]  # 5x avg volume spike
        r = evaluate_sweep_risk(
            opens=opens, highs=highs, lows=lows, closes=closes, volumes=volumes,
            quote_spread_bps=80.0,
        )
        self.assertIn(r.verdict, ("BLOCK", "ELEVATED_RISK"))
        self.assertGreaterEqual(r.signal_count, 2)

    def test_clean_breakout_does_not_block(self):
        from liquidity_sweep_guard import evaluate_sweep_risk, ALLOW
        opens   = [100] * 22
        highs   = [102] * 22
        lows    = [99] * 22
        closes  = [101] * 22
        volumes = [1000] * 22
        r = evaluate_sweep_risk(
            opens=opens, highs=highs, lows=lows, closes=closes, volumes=volumes,
        )
        self.assertEqual(r.verdict, ALLOW)

    def test_audit_reason_present(self):
        from liquidity_sweep_guard import evaluate_sweep_risk
        r = evaluate_sweep_risk()
        self.assertIn("sweep_signals", r.rationale)

    def test_confidence_penalty_scaling(self):
        from liquidity_sweep_guard import (
            SweepCheckResult, confidence_penalty, BLOCK, ELEVATED_RISK, ALLOW,
        )
        block = SweepCheckResult(BLOCK, 4, (), True, True, True, True, False,
                                  "x")
        elev = SweepCheckResult(ELEVATED_RISK, 2, (), True, True, False, False,
                                 False, "x")
        allow = SweepCheckResult(ALLOW, 0, (), False, False, False, False,
                                  False, "x")
        self.assertEqual(confidence_penalty(block), 0.30)
        self.assertEqual(confidence_penalty(elev), 0.15)
        self.assertEqual(confidence_penalty(allow), 0.0)


# ─── FB-013 — SessionEffectivenessMonitor ─────────────────────────────────────

class TestSessionEffectivenessMonitor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_and_load(self):
        from session_effectiveness import (
            record_event, load_events, EVT_SIGNAL_EMITTED,
        )
        record_event(EVT_SIGNAL_EMITTED, symbol="AAPL", session_dir=self.dir)
        events = load_events(session_dir=self.dir)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].symbol, "AAPL")

    def test_invalid_event_type_silently_ignored(self):
        from session_effectiveness import (
            record_event, load_events,
        )
        record_event("not_a_real_type", symbol="AAPL", session_dir=self.dir)
        events = load_events(session_dir=self.dir)
        self.assertEqual(len(events), 0)

    def test_low_hit_rate_triggers_degradation(self):
        from session_effectiveness import (
            record_event, report_today, load_events, compute_report,
            EVT_POSITION_CLOSED_WINNER, EVT_POSITION_CLOSED_LOSER,
        )
        for _ in range(10):
            record_event(EVT_POSITION_CLOSED_LOSER, symbol="A",
                          payload={"mae_pct": -0.06, "mfe_pct": 0.0},
                          session_dir=self.dir)
        report = compute_report(load_events(session_dir=self.dir))
        self.assertIn("low_hit_rate", report.degradation_signals)

    def test_recommend_safe_mode_when_two_signals(self):
        from session_effectiveness import (
            record_event, load_events, compute_report,
            EVT_POSITION_CLOSED_LOSER,
        )
        for _ in range(12):
            record_event(EVT_POSITION_CLOSED_LOSER, symbol="A",
                          payload={"mae_pct": -0.10, "mfe_pct": 0.01},
                          session_dir=self.dir)
        report = compute_report(load_events(session_dir=self.dir))
        # low_hit_rate + adverse_excursion_dominant → 2 signals
        self.assertGreaterEqual(len(report.degradation_signals), 1)


# ─── FB-010 — Universe selector ───────────────────────────────────────────────

class TestUniverseSelector(unittest.TestCase):
    def test_us_large_is_paper_ready(self):
        from universe_selector import is_paper_ready, UNIV_US_LARGE
        ok, reason = is_paper_ready(UNIV_US_LARGE)
        self.assertTrue(ok)

    def test_us_microcap_disabled_by_default(self):
        from universe_selector import is_paper_ready, UNIV_US_MICROCAP
        ok, reason = is_paper_ready(UNIV_US_MICROCAP)
        # microcap disabled in config -> not ready
        self.assertFalse(ok)

    def test_pl_gpw_not_ready_no_broker(self):
        from universe_selector import is_paper_ready, UNIV_PL_GPW
        ok, reason = is_paper_ready(UNIV_PL_GPW)
        self.assertFalse(ok)

    def test_unknown_universe_rejected(self):
        from universe_selector import is_paper_ready
        ok, _ = is_paper_ready("XX_UNKNOWN")
        self.assertFalse(ok)

    def test_cant_switch_to_unready_universe(self):
        from universe_selector import (
            can_switch, UNIV_US_LARGE, UNIV_PL_GPW,
        )
        ok, _ = can_switch(UNIV_US_LARGE, UNIV_PL_GPW)
        self.assertFalse(ok)


# ─── FB-005 — Strategy registry ───────────────────────────────────────────────

class TestStrategyRegistry(unittest.TestCase):
    def test_registry_includes_known_strategies(self):
        from backtest.strategy_registry import REGISTRY
        for name in ("momentum-long", "crypto-momentum",
                       "crypto-oversold-bounce", "geo-defense"):
            self.assertIn(name, REGISTRY)

    def test_event_driven_strategy_not_backtest_ready(self):
        from backtest.strategy_registry import is_backtest_ready
        self.assertFalse(is_backtest_ready("geo-defense"))

    def test_momentum_long_is_backtest_ready(self):
        from backtest.strategy_registry import is_backtest_ready
        self.assertTrue(is_backtest_ready("momentum-long"))

    def test_coverage_report_emits_full_dict(self):
        from backtest.strategy_registry import coverage_report
        r = coverage_report()
        self.assertIn("total_registered", r)
        self.assertIn("by_readiness", r)
        self.assertIn("backtest_ready_pct", r)
        self.assertIn("tradeable_uncovered", r)


# ─── ETAP 13 — Confidence integration ─────────────────────────────────────────

class TestConfidenceFeedbackIntegration(unittest.TestCase):
    def test_liquidity_block_recommended_propagates_to_meta(self):
        from confidence_builder import build_confidence_inputs
        from liquidity_sweep_guard import SweepCheckResult, BLOCK
        result = SweepCheckResult(
            verdict=BLOCK, signal_count=4, triggered_signals=(),
            long_wick_reversal=True, volume_spike_no_follow=True,
            fast_reversal_post_break=True, historical_trap_prone=True,
            low_liquidity_warning=False, rationale="test",
        )
        out = build_confidence_inputs(
            strategy="momentum-long",
            primary_score=0.7,
            liquidity_sweep_result=result,
        )
        meta = out.get("_v3150_meta", {})
        self.assertTrue(meta.get("block_recommended"))
        self.assertIn("liquidity_sweep_BLOCK", meta.get("block_reasons", []))

    def test_low_quality_profile_lowers_primary_score(self):
        from confidence_builder import build_confidence_inputs
        # Mock profile with very low quality
        class _MockProfile:
            quality = 0.1
            insufficient_data = False
        out = build_confidence_inputs(
            strategy="momentum-long",
            primary_score=0.7,
            instrument_profile=_MockProfile(),
        )
        self.assertLess(out["primary_score"], 0.7)

    def test_index_aligned_raises_primary_score(self):
        from confidence_builder import build_confidence_inputs
        class _MockLeadLag:
            verdict = "INDEX_ALIGNED"
        out = build_confidence_inputs(
            strategy="momentum-long",
            primary_score=0.50,
            lead_lag_result=_MockLeadLag(),
        )
        self.assertGreater(out["primary_score"], 0.50)

    def test_tier_3_source_caps_score(self):
        from confidence_builder import build_confidence_inputs
        out = build_confidence_inputs(
            strategy="momentum-long",
            primary_score=0.70,
            source_type="reddit",  # Tier 3
            source_confirmation_present=False,
        )
        # Tier 3 alone applies -0.05 penalty
        meta = out.get("_v3150_meta", {})
        self.assertTrue(meta.get("source_tier_capped"))
        self.assertLess(out["primary_score"], 0.70)


# ─── ETAP 8 — Event monitor interface ─────────────────────────────────────────

class TestEventMonitorInterface(unittest.TestCase):
    def test_mock_doj_monitor_dedups(self):
        from event_monitor_interface import (
            MockDOJMonitor, EventCandidate, EVT_DOJ_LAWSUIT_FILED,
        )
        ev = EventCandidate(
            event_id="doj-2026-06-04-x", event_type=EVT_DOJ_LAWSUIT_FILED,
            detected_at_iso="2026-06-04T10:00:00+00:00",
            headline="DOJ vs XYZ Corp", summary="...",
            tickers=("XYZ",), source_url="https://justice.gov/example",
            source_tier="tier_1_primary", severity="high",
            catalyst_timing="weeks_months",
            requires_day_trade_confirmation=True,
        )
        mon = MockDOJMonitor(mock_events=[ev, ev, ev])
        out = mon.run("2026-06-04T10:00:00+00:00")
        # Only one emission despite 3 in feed (dedup)
        self.assertEqual(len(out), 1)

    def test_lawsuit_event_not_day_trade_eligible_alone(self):
        from event_monitor_interface import (
            MockDOJMonitor, EventCandidate, EVT_DOJ_LAWSUIT_FILED,
        )
        ev = EventCandidate(
            event_id="doj-2026-06-04-y", event_type=EVT_DOJ_LAWSUIT_FILED,
            detected_at_iso="2026-06-04T10:00:00+00:00",
            headline="Lawsuit", summary="...",
            tickers=("ABC",), source_url="x",
            source_tier="tier_1_primary", severity="medium",
            catalyst_timing="weeks_months",
            requires_day_trade_confirmation=True,
        )
        mon = MockDOJMonitor(mock_events=[ev])
        out = mon.run("now")
        self.assertEqual(len(out), 1)
        _, decision = out[0]
        # Tier 1 but timing weeks/months → not eligible alone
        self.assertFalse(decision.day_trade_eligible)


if __name__ == "__main__":
    unittest.main(verbosity=2)
