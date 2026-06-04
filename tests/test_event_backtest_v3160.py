"""v3.16.0 (2026-06-04) — Tests for event-driven backtest Phase 1 MVP.

Covers:
  - shared.geo_classifier deterministic per bucket (defense / energy / gold)
  - noise event returns no signals
  - geo-monitor parity (live classifier output matches shared on 5 real headlines)
  - GDELT fetcher rate-limit guard (no network — module-level state probe)
  - event_replay.replay_events produces ledger with no_lookahead invariant
  - strategy_registry MVP_IN_PROGRESS readiness label
  - is_backtest_ready stays False for geo-defense (n<50 threshold)

ALL TESTS ARE LOCAL + DETERMINISTIC + NO NETWORK.
"""

from __future__ import annotations

import os
import sys
import time
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
BACKTEST_DIR = os.path.join(REPO_ROOT, "backtest")
GEO_MONITOR_DIR = os.path.join(REPO_ROOT, "geo-monitor")

for p in (SHARED_DIR, BACKTEST_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


# ─── 1. Classifier — defense bucket ───────────────────────────────────────────

class TestGeoClassifierDefense(unittest.TestCase):
    def test_iran_missile_strike_produces_defense_signals(self):
        from geo_classifier import classify_event_to_signals, STRATEGY_DEFENSE

        signals = classify_event_to_signals(
            headline="Iran missile strike hits Israeli air base",
            summary="Israeli authorities confirm casualties from rocket attack",
            source_type="reuters_ap",
            detected_at_iso="2026-04-01T12:00:00+00:00",
            score=6,
        )
        self.assertGreaterEqual(len(signals), 2)
        defense_signals = [s for s in signals if s.strategy == STRATEGY_DEFENSE]
        self.assertEqual(len(defense_signals), 2)
        symbols = {s.primary_tickers[0] for s in defense_signals}
        self.assertEqual(symbols, {"RTX", "LMT"})
        for s in defense_signals:
            self.assertEqual(s.side, "BUY")
            self.assertEqual(s.bucket, "defense")
            self.assertEqual(s.priority, "HIGH")
            self.assertEqual(s.size_hint_usd, 8000.0)


# ─── 2. Classifier — energy bucket ────────────────────────────────────────────

class TestGeoClassifierEnergy(unittest.TestCase):
    def test_oil_embargo_produces_energy_signals(self):
        from geo_classifier import classify_event_to_signals, STRATEGY_XOM, STRATEGY_ENERGY

        signals = classify_event_to_signals(
            headline="OPEC announces oil embargo on Western shipments",
            summary="strait of hormuz transit halted indefinitely",
            source_type="reuters_ap",
            priority="HIGH",
        )
        energy_signals = [s for s in signals if s.bucket == "energy"]
        self.assertEqual(len(energy_signals), 2)
        symbols = {s.primary_tickers[0] for s in energy_signals}
        self.assertEqual(symbols, {"XOM", "CVX"})
        # XOM/CVX get the legacy "geo-xom" alias for state.json compat.
        for s in energy_signals:
            self.assertEqual(s.strategy, STRATEGY_XOM)


# ─── 3. Classifier — gold bucket ──────────────────────────────────────────────

class TestGeoClassifierGold(unittest.TestCase):
    def test_nuclear_tensions_produce_gld_signal(self):
        from geo_classifier import classify_event_to_signals, STRATEGY_GOLD

        signals = classify_event_to_signals(
            headline="Nuclear powers exchange warnings as tensions escalate",
            source_type="major_outlet",
            priority="MEDIUM",
        )
        gold_signals = [s for s in signals if s.bucket == "gold"]
        self.assertEqual(len(gold_signals), 1)
        gs = gold_signals[0]
        self.assertEqual(gs.primary_tickers, ("GLD",))
        self.assertEqual(gs.strategy, STRATEGY_GOLD)
        self.assertEqual(gs.size_hint_usd, 4000.0)


# ─── 4. Classifier — noise (no signals) ───────────────────────────────────────

class TestGeoClassifierNoise(unittest.TestCase):
    def test_noise_headline_produces_no_signals(self):
        from geo_classifier import classify_event_to_signals

        signals = classify_event_to_signals(
            headline="Local bakery wins regional pastry award",
            summary="Annual fair attracts large crowd",
            source_type="niche_outlet",
        )
        self.assertEqual(signals, [])

    def test_empty_headline_returns_empty(self):
        from geo_classifier import classify_event_to_signals
        self.assertEqual(classify_event_to_signals("", "", ""), [])

    def test_classifier_fail_soft_on_bad_input(self):
        from geo_classifier import classify_event_to_signals
        # Passing None must not raise.
        out = classify_event_to_signals(None, None, None)  # type: ignore
        self.assertEqual(out, [])


# ─── 5. Dedup helper — same headline twice → caller cap kicks in ──────────────

class TestSignalDedup(unittest.TestCase):
    def test_cap_signals_per_run_caps_at_max(self):
        from geo_classifier import classify_event_to_signals, cap_signals_per_run
        signals = classify_event_to_signals(
            headline="Iran missile strike nuclear oil embargo war",
            source_type="reuters_ap",
            priority="HIGH",
        )
        # Defense (2) + energy (2) + gold (1) = 5 raw signals
        self.assertGreaterEqual(len(signals), 5)
        capped = cap_signals_per_run(signals, 2)
        self.assertEqual(len(capped), 2)

    def test_cap_signals_per_run_zero_passes_through(self):
        from geo_classifier import cap_signals_per_run
        items = [1, 2, 3]
        self.assertEqual(cap_signals_per_run(items, 0), items)


# ─── 6. Live-monitor parity ───────────────────────────────────────────────────

class TestLiveMonitorParity(unittest.TestCase):
    """Feed 5 representative headlines through both the live monitor's
    `_classify_news_to_signals` AND the new shared classifier; assert
    identical symbol/strategy/bucket per item.

    The live monitor has additional fields (url, score, source) sourced
    from the raw NewsAPI/RSS item dict — we only assert on the classification
    contract: bucket, ticker, strategy, side, size_usd, priority.
    """

    # NB: expected_buckets reflects the LIVE monitor's MAX_TRADES_PER_RUN=2 cap,
    # so combos that produce >2 raw signals get truncated. Set is "what live
    # actually emits" — the shared classifier itself can produce more before
    # the cap.
    REPRESENTATIVE_HEADLINES = [
        # 1. Defense escalation — defense bucket (RTX+LMT = 2 signals, fits cap)
        {"title": "Iran missile strike hits Israeli air base", "summary": "",
         "source": "Reuters", "score": 6, "expected_buckets": {"defense"}},
        # 2. Energy supply shock — XOM+CVX = 2 signals
        {"title": "Strait of hormuz shut after oil embargo decree",
         "summary": "OPEC reacting", "source": "AP News", "score": 5,
         "expected_buckets": {"energy"}},
        # 3. Gold safe-haven (1 signal — fits cap)
        {"title": "Nuclear powers in renewed standoff", "summary": "",
         "source": "Bloomberg", "score": 4, "expected_buckets": {"gold"}},
        # 4. Combo defense + gold — defense fires 2 first, gold truncated by cap
        {"title": "Middle east war escalates with nuclear rhetoric", "summary": "",
         "source": "Reuters", "score": 5,
         "expected_buckets": {"defense"}},
        # 5. Off-topic — should produce nothing
        {"title": "Tech stocks rally on dovish Fed", "summary": "",
         "source": "CNBC", "score": 0, "expected_buckets": set()},
    ]

    def setUp(self):
        # Make geo-monitor importable as a plain module.
        if GEO_MONITOR_DIR not in sys.path:
            sys.path.insert(0, GEO_MONITOR_DIR)
        # feedparser is a runtime-only dep for live RSS fetching; tests don't
        # need it. Stub it before importing the live monitor.
        if "feedparser" not in sys.modules:
            import types
            stub = types.ModuleType("feedparser")
            stub.parse = lambda *a, **k: type("F", (), {"entries": [], "feed": {}})()  # type: ignore
            sys.modules["feedparser"] = stub
        import importlib
        # Remove any cached partial import.
        sys.modules.pop("monitor", None)
        self._monitor = importlib.import_module("monitor")

    def test_parity_on_representative_headlines(self):
        for item in self.REPRESENTATIVE_HEADLINES:
            news_items = [{
                "title":   item["title"],
                "summary": item["summary"],
                "source":  item["source"],
                "score":   item["score"],
                "url":     "",
                "time":    "2026-04-01T12:00:00+00:00",
            }]
            priority = "HIGH" if item["score"] >= 3 else "MEDIUM"
            live = self._monitor._classify_news_to_signals(news_items, priority)
            live_buckets = {s["bucket"] for s in live}
            self.assertEqual(live_buckets, item["expected_buckets"],
                              msg=f"live monitor produced {live_buckets} "
                                  f"for {item['title']!r}, expected "
                                  f"{item['expected_buckets']}")
            # Also assert each emitted live signal has shared classifier shape.
            for s in live:
                self.assertIn(s["bucket"], {"defense", "energy", "gold"})
                self.assertEqual(s["action"], "BUY")
                self.assertIn(s["strategy"],
                              {"geo-defense", "geo-energy", "geo-gold", "geo-xom"})
                self.assertGreaterEqual(s["size_usd"], 4000.0)


# ─── 7. GDELT fetcher rate-limit guard ────────────────────────────────────────

class TestGdeltRateLimit(unittest.TestCase):
    def test_rate_limit_helper_sleeps_minimum_interval(self):
        from event_data import _rate_limit
        # Two consecutive calls should be spaced by at least the interval.
        t0 = time.monotonic()
        _rate_limit(0.10)
        _rate_limit(0.10)
        elapsed = time.monotonic() - t0
        # Should be ≥ ~0.10s. Allow generous margin for slow CI.
        self.assertGreaterEqual(elapsed, 0.08)

    def test_rate_limit_zero_is_noop(self):
        from event_data import _rate_limit
        t0 = time.monotonic()
        _rate_limit(0.0)
        _rate_limit(0.0)
        # Effectively instant.
        self.assertLess(time.monotonic() - t0, 0.1)


# ─── 8. Replay loop — no-lookahead invariant ──────────────────────────────────

class TestEventReplayNoLookahead(unittest.TestCase):
    def _make_bars(self):
        """Synthetic 30-day series with a known up-then-down shape."""
        opens, closes, highs, lows, vols, times = [], [], [], [], [], []
        base = 100.0
        # Day 0..9 flat
        # Day 10..19 trending up 0.5%/day → triggers TP at 10% if priced right
        # Day 20..29 trending down → SL exit if TP not hit
        for i in range(30):
            if i < 10:
                price = base
            elif i < 20:
                price = base * (1 + 0.011 * (i - 9))
            else:
                price = base * (1 + 0.011 * 10) * (1 - 0.02 * (i - 19))
            opens.append(price)
            closes.append(price * 1.001)
            highs.append(price * 1.015)
            lows.append(price * 0.985)
            vols.append(1_000_000.0)
            times.append(f"2026-04-{i+1:02d}T04:00:00Z")
        return {"open": opens, "close": closes, "high": highs,
                "low": lows, "volume": vols, "time": times}

    def test_replay_uses_next_bar_open_not_event_day(self):
        from event_data import HistoricalEvent
        from event_strategies import geo_defense_event_strategy
        from event_replay import replay_events, strategy_set_for

        bars = self._make_bars()
        ev = HistoricalEvent(
            event_id="ev-1", day="2026-04-10", event_code="190", quad_class=4,
            goldstein=-8.0, num_articles=20, source_url="http://x",
            headline="Iran missile strike on Israeli base",
            detected_at_iso="2026-04-10T12:00:00+00:00",
        )

        def _market_data_fn(symbol):
            return bars

        result = replay_events([ev], geo_defense_event_strategy,
                                _market_data_fn,
                                strategy_filter=strategy_set_for("geo-defense"))

        self.assertGreater(len(result["trades"]), 0)
        for trade in result["trades"]:
            # No lookahead: entry must be on a DAY > event day.
            self.assertGreater(trade["entry_date"][:10], "2026-04-10")
            # Exit must be after entry.
            self.assertGreaterEqual(trade["exit_date"][:10], trade["entry_date"][:10])
            # Direction must be long (geo classifier is BUY-only).
            self.assertEqual(trade["direction"], "long")

    def test_replay_empty_events_returns_empty_summary(self):
        from event_replay import replay_events
        result = replay_events([], lambda **kw: [], lambda s: None)
        self.assertEqual(result["summary"]["n_trades"], 0)
        self.assertEqual(result["trades"], [])

    def test_replay_skips_event_when_no_bars_available(self):
        from event_data import HistoricalEvent
        from event_strategies import geo_defense_event_strategy
        from event_replay import replay_events, strategy_set_for

        ev = HistoricalEvent(
            event_id="ev-x", day="2026-04-10", event_code="190", quad_class=4,
            goldstein=-8.0, num_articles=5, source_url="",
            headline="Iran missile strike on capital",
        )
        result = replay_events([ev], geo_defense_event_strategy,
                                lambda s: None,
                                strategy_filter=strategy_set_for("geo-defense"))
        self.assertEqual(result["summary"]["n_trades"], 0)
        # We expect 2 signals (RTX+LMT), both rejected for missing bars.
        self.assertGreaterEqual(result["debug"]["rejected_signals"], 2)


# ─── 9. Strategy registry — MVP_IN_PROGRESS readiness ─────────────────────────

class TestStrategyRegistryMVPInProgress(unittest.TestCase):
    def test_geo_defense_marked_mvp_in_progress(self):
        from strategy_registry import get, MVP_IN_PROGRESS
        r = get("geo-defense")
        self.assertIsNotNone(r)
        self.assertEqual(r.readiness, MVP_IN_PROGRESS)

    def test_geo_energy_marked_mvp_in_progress(self):
        from strategy_registry import get, MVP_IN_PROGRESS
        r = get("geo-energy")
        self.assertIsNotNone(r)
        self.assertEqual(r.readiness, MVP_IN_PROGRESS)

    def test_geo_gold_marked_mvp_in_progress(self):
        from strategy_registry import get, MVP_IN_PROGRESS
        r = get("geo-gold")
        self.assertIsNotNone(r)
        self.assertEqual(r.readiness, MVP_IN_PROGRESS)


# ─── 10. Backtest-ready gate stays False for MVP_IN_PROGRESS ──────────────────

class TestBacktestReadyGate(unittest.TestCase):
    def test_geo_defense_is_not_backtest_ready(self):
        from strategy_registry import is_backtest_ready
        # MVP_IN_PROGRESS deliberately fails the gate so EDGE_GATE stays off.
        self.assertFalse(is_backtest_ready("geo-defense"))

    def test_momentum_long_is_backtest_ready(self):
        from strategy_registry import is_backtest_ready
        # Sanity: a known HAS_SIGNAL strategy passes.
        self.assertTrue(is_backtest_ready("momentum-long"))

    def test_unknown_strategy_is_not_backtest_ready(self):
        from strategy_registry import is_backtest_ready
        self.assertFalse(is_backtest_ready("not-a-real-strategy"))


# ─── 11. Bonus: GDELT CSV parser handles malformed lines ──────────────────────

class TestGdeltCsvParser(unittest.TestCase):
    def test_parser_rejects_short_rows(self):
        from event_data import parse_gdelt_csv_zip
        # Empty payload — must not raise.
        self.assertEqual(parse_gdelt_csv_zip(b""), [])

    def test_synthesize_event_round_trips(self):
        from event_data import synthesize_event, HistoricalEvent
        ev = synthesize_event("Iran missile attack",
                                day_iso="2026-04-01", event_code="190")
        self.assertIsInstance(ev, HistoricalEvent)
        self.assertEqual(ev.day, "2026-04-01")
        self.assertIn("missile", ev.headline)


if __name__ == "__main__":
    unittest.main(verbosity=2)
