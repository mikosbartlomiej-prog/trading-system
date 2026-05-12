"""
Unit tests for v3.0 aggressive momentum + event switch modules:
  shared/profile.py
  shared/regime.py
  shared/momentum_score.py
  shared/defensive_mode.py (light — full state.json mutation tests skipped)

Run: python -m unittest tests.aggressive.test_v3
"""

import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))


class TestProfile(unittest.TestCase):
    def setUp(self):
        from profile import reset_cache
        reset_cache()

    def test_load_profile_has_capital_section(self):
        from profile import load_profile
        p = load_profile()
        self.assertIn("capital", p)
        self.assertIn("max_single_position_pct_equity", p["capital"])

    def test_profile_value_dot_path(self):
        from profile import profile_value
        v = profile_value("capital.max_single_position_pct_equity")
        self.assertIsNotNone(v)
        self.assertGreater(float(v), 0)

    def test_profile_value_missing_returns_default(self):
        from profile import profile_value
        v = profile_value("nonexistent.deep.path", "fallback")
        self.assertEqual(v, "fallback")

    def test_load_watchlists_has_buckets(self):
        from profile import load_watchlists
        w = load_watchlists()
        self.assertIn("ai_nasdaq_semis", w)
        self.assertIn("inflation_energy", w)
        self.assertIn("crypto", w)
        self.assertIn("hedge_metals", w)

    def test_bucket_for_ticker(self):
        from profile import bucket_for_ticker
        self.assertEqual(bucket_for_ticker("NVDA"), "ai_nasdaq_semis")
        self.assertEqual(bucket_for_ticker("XLE"), "inflation_energy")
        self.assertEqual(bucket_for_ticker("BTC/USD"), "crypto")
        self.assertEqual(bucket_for_ticker("GLD"), "hedge_metals")
        self.assertEqual(bucket_for_ticker("TLT"), "hedge_bonds")
        self.assertIsNone(bucket_for_ticker("FAKE"))

    def test_v3_new_tickers_present(self):
        from profile import load_watchlists
        w = load_watchlists()
        ai = w["ai_nasdaq_semis"]["tickers"]
        for t in ("AMD", "AVGO", "SMH"):
            self.assertIn(t, ai, f"v3.0 expected {t} in ai_nasdaq_semis")
        inf = w["inflation_energy"]["tickers"]
        for t in ("USO", "CVX", "OXY"):
            self.assertIn(t, inf, f"v3.0 expected {t} in inflation_energy")
        self.assertIn("TLT", w["hedge_bonds"]["tickers"])


class TestRegime(unittest.TestCase):
    def test_auto_detect_risk_off_on_vix_panic(self):
        from regime import _auto_detect
        rules = {"vix_full_panic_threshold": 50,
                 "spy_5d_risk_off_threshold": -4.0,
                 "spy_5d_risk_on_threshold": 1.5,
                 "spy_5d_inflation_threshold": -2.0,
                 "energy_5d_inflation_signal_pct": 3.0}
        self.assertEqual(_auto_detect({"vix": 55, "spy_5d_pct": 0}, rules), "RISK_OFF")

    def test_auto_detect_risk_off_on_spy_breakdown(self):
        from regime import _auto_detect
        rules = {"vix_full_panic_threshold": 50,
                 "spy_5d_risk_off_threshold": -4.0,
                 "spy_5d_risk_on_threshold": 1.5,
                 "spy_5d_inflation_threshold": -2.0,
                 "energy_5d_inflation_signal_pct": 3.0}
        self.assertEqual(_auto_detect({"vix": 20, "spy_5d_pct": -5}, rules), "RISK_OFF")

    def test_auto_detect_inflation_shock(self):
        from regime import _auto_detect
        rules = {"vix_full_panic_threshold": 50,
                 "spy_5d_risk_off_threshold": -4.0,
                 "spy_5d_risk_on_threshold": 1.5,
                 "spy_5d_inflation_threshold": -2.0,
                 "energy_5d_inflation_signal_pct": 3.0}
        self.assertEqual(_auto_detect(
            {"vix": 22, "spy_5d_pct": -2.5, "energy_5d_pct": 4.5}, rules
        ), "INFLATION_SHOCK")

    def test_auto_detect_risk_on(self):
        from regime import _auto_detect
        rules = {"vix_full_panic_threshold": 50,
                 "spy_5d_risk_off_threshold": -4.0,
                 "spy_5d_risk_on_threshold": 1.5,
                 "spy_5d_inflation_threshold": -2.0,
                 "energy_5d_inflation_signal_pct": 3.0}
        self.assertEqual(_auto_detect({"vix": 18, "spy_5d_pct": 2.5}, rules), "RISK_ON")

    def test_auto_detect_neutral_default(self):
        from regime import _auto_detect
        rules = {"vix_full_panic_threshold": 50,
                 "spy_5d_risk_off_threshold": -4.0,
                 "spy_5d_risk_on_threshold": 1.5}
        self.assertEqual(_auto_detect({"vix": 22, "spy_5d_pct": 0.5}, rules), "NEUTRAL")

    def test_detect_regime_returns_full_payload(self):
        from regime import detect_regime
        info = detect_regime({"vix": 18, "spy_5d_pct": 2.5})
        self.assertIn("regime", info)
        self.assertIn("allowed_buckets", info)
        self.assertIn("size_multiplier", info)
        self.assertIn("options_side_bias", info)
        self.assertGreater(len(info["allowed_buckets"]), 0)

    def test_is_ticker_allowed_for_risk_on(self):
        from regime import is_ticker_allowed
        info = {"regime": "RISK_ON", "allowed_buckets": ["ai_nasdaq_semis", "crypto"]}
        allowed, why = is_ticker_allowed("NVDA", info)
        self.assertTrue(allowed)
        self.assertEqual(why, "ai_nasdaq_semis")

    def test_is_ticker_blocked_for_risk_off(self):
        from regime import is_ticker_allowed
        info = {"regime": "RISK_OFF", "allowed_buckets": ["hedge_metals", "hedge_bonds"]}
        allowed, why = is_ticker_allowed("NVDA", info)
        self.assertFalse(allowed)
        self.assertIn("not allowed", why)


class TestMomentumScore(unittest.TestCase):
    def _make_bars(self, closes, highs=None, lows=None, volumes=None):
        if highs is None:
            highs = [c * 1.01 for c in closes]
        if lows is None:
            lows = [c * 0.99 for c in closes]
        if volumes is None:
            volumes = [1_000_000] * len(closes)
        return {"close": closes, "high": highs, "low": lows,
                "open": closes, "volume": volumes, "time": list(range(len(closes)))}

    def test_score_uptrend_with_breakout_high(self):
        from momentum_score import score_symbol
        # Strong uptrend: 1.5%/day for 30 days = ~57% gain — well above threshold
        closes = [100 * (1.015 ** i) for i in range(30)]
        bars = self._make_bars(closes)
        # Today's volume 4× avg
        bars["volume"][-1] = 4_000_000
        result = score_symbol("TEST", bars)
        self.assertGreater(result["score"], 0)
        # Strong uptrend + volume + breakout should clear min_score_for_entry=0.35
        self.assertTrue(result["tradeable"],
                          f"strong uptrend should be tradeable; got score={result['score']:.3f}, components={result['components']}")

    def test_score_downtrend_negative(self):
        from momentum_score import score_symbol
        closes = [100 - i * 0.5 for i in range(30)]
        bars = self._make_bars(closes)
        result = score_symbol("TEST", bars)
        self.assertLess(result["score"], 0)

    def test_score_insufficient_data(self):
        from momentum_score import score_symbol
        bars = self._make_bars([100, 101, 102])
        result = score_symbol("TEST", bars)
        self.assertEqual(result["score"], 0.0)
        self.assertFalse(result["tradeable"])
        self.assertEqual(result["reason"], "insufficient_data")

    def test_score_with_benchmark_relative_strength(self):
        from momentum_score import score_symbol
        # Asset outperforms benchmark
        asset_closes = [100 + i for i in range(30)]
        bench_closes = [100 + i * 0.3 for i in range(30)]
        bars = self._make_bars(asset_closes)
        spy_bars = self._make_bars(bench_closes)
        result = score_symbol("OUTPERFORMER", bars, spy_bars=spy_bars)
        # Should have positive RS component
        self.assertGreater(result["components"].get("relative_strength", 0), 0)


class TestRiskGuards(unittest.TestCase):
    def setUp(self):
        # Clear ALPACA creds to force fail-open path
        self.saved = {
            "key":    os.environ.pop("ALPACA_API_KEY", None),
            "secret": os.environ.pop("ALPACA_SECRET_KEY", None),
        }

    def tearDown(self):
        if self.saved["key"]:    os.environ["ALPACA_API_KEY"]    = self.saved["key"]
        if self.saved["secret"]: os.environ["ALPACA_SECRET_KEY"] = self.saved["secret"]

    def test_daily_drawdown_guard_reads_profile(self):
        """v3.0 daily threshold should come from profile (-3% by default)."""
        from risk_guards import _profile_threshold_pct
        v = _profile_threshold_pct("max_daily_loss_pct_equity", -99.0)
        # Profile has 0.03 → expect -3.0
        self.assertEqual(v, -3.0)

    def test_weekly_drawdown_guard_no_creds_fail_open(self):
        from risk_guards import weekly_drawdown_guard
        status, _ = weekly_drawdown_guard()
        self.assertEqual(status, "OK")  # fail-open

    def test_max_drawdown_guard_no_creds_fail_open(self):
        from risk_guards import max_drawdown_guard
        status, _ = max_drawdown_guard()
        self.assertEqual(status, "OK")

    def test_max_drawdown_guard_full_stop_triggered(self):
        from risk_guards import max_drawdown_guard
        # Simulate: peak $100k, current $79k → -21% > -20% threshold
        acct = {"equity": 79000, "last_equity": 78000, "daily_pl_pct": 1.3,
                "buying_power": 100000}
        level, _ = max_drawdown_guard(account=acct, peak_equity=100000)
        self.assertEqual(level, "FULL_STOP")

    def test_max_drawdown_guard_defensive_triggered(self):
        from risk_guards import max_drawdown_guard
        # Peak $100k, current $87k → -13% > -12% threshold
        acct = {"equity": 87000, "last_equity": 87500, "daily_pl_pct": -0.6,
                "buying_power": 100000}
        level, _ = max_drawdown_guard(account=acct, peak_equity=100000)
        self.assertEqual(level, "DEFENSIVE")


if __name__ == "__main__":
    unittest.main()
