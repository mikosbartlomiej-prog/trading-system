"""v3.11.3 part 2 (2026-05-30) — tests for 4 backlog fixes driven by
7-day learning-loop output review.

Fixes covered:

P0 #1 — Crypto-monitor OVERSOLD-BOUNCE path.
  Bypasses the predator-bracket 24h-move [3%, 15%] filter when the
  setup is clearly oversold (RSI ≤ 30 + 24h-move ≥ -10% + 1-bar
  reversal + ≥50% normal volume). Tags entries as
  'crypto-oversold-bounce' so analyzer attributes correctly.
  Background: 45-day SILENT period for crypto-momentum despite BTC/ETH
  RSI 20-27 (deep oversold). LLM Senior PM flagged this 9× in 5 days.

P0 #2 — analyzer._strategy_from_client_id symbol-based fallback.
  When client_order_id parse returns 'unknown' AND symbol is in
  SYMBOL_STRATEGY_MAP (XOM/CVX/RTX/LMT/GLD), return the mapped
  strategy. Drives fill_rate.unknown 37% → real per-strategy stats.

P1 #3 — adapter zombie-prune LLM-OVERRIDE LOCK (14 days).
  After an explicit LLM override (Senior PM re-enables a strategy),
  the next deterministic adapter run was canceling the override
  → endless re-enable/re-prune cycle (5+ days for crypto-momentum).
  Now: honor LLM override for 14 days via last_llm_override_at stamp.

P1 #4 — analyzer.compute_fill_rate exposes fill_rate_closed.
  Legacy fill_rate = filled/placed counts OPEN-GTC orders in the
  denominator → false 'limits too tight' alert when orders are simply
  waiting for the market. fill_rate_closed = filled/(filled+canceled+
  expired+rejected). adapter.heuristic_fill_rate_alert now prefers
  fill_rate_closed; skips emission when no closed orders yet.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in ("shared", "learning-loop", "crypto-monitor"):
    sys.path.insert(0, str(REPO_ROOT / p))


# ─── P0 #1: crypto oversold-bounce path ──────────────────────────────────────

def _make_bars(closes, vol=1000, hi_pad=0.01, lo_pad=0.01, last_vol_mult=2.0):
    """Construct 1h-bar list compatible with crypto-monitor's parser.

    last_vol_mult: scale the LAST bar's volume by this factor so the
    'current_volume > avg_vol × multiplier' filter can pass.
    """
    bars = []
    for c in closes:
        bars.append({
            "o": c,
            "h": c * (1 + hi_pad),
            "l": c * (1 - lo_pad),
            "c": c,
            "v": vol,
        })
    if bars and last_vol_mult > 1.0:
        bars[-1]["v"] = int(vol * last_vol_mult)
    return bars


class TestCryptoOversoldBounce(unittest.TestCase):

    def setUp(self):
        # Import inside setUp so the future-annotations import takes effect.
        import monitor
        self.monitor = monitor

    def _scenario_oversold(self):
        """25 monotonically falling bars + 1 tiny reversal — RSI < 30.

        Construction: start at 100, fall by 0.5% each bar for 25 bars,
        then final bar +0.1% reversal. This gives:
          * RSI strongly < 30 (only losses in the 14-period window)
          * 24h-move (last vs ~-24 bars) ≈ -10% — JUST inside the
            OVERSOLD_BOUNCE_MIN_MOVE_PCT floor
          * 1-bar reversal at the end
        """
        closes = [100.0]
        for _ in range(25):
            closes.append(closes[-1] * 0.997)  # -0.3% per bar
        # 24h-move ≈ -7% (24 bars × -0.3%), inside -10% floor
        # Final bar = tiny reversal (close > prior close)
        closes.append(closes[-1] * 1.002)
        return closes

    def test_oversold_bounce_fires_when_RSI_below_30(self):
        closes = self._scenario_oversold()
        bars = _make_bars(closes, vol=3000)  # high volume = passes vol filter
        with patch.object(self.monitor, "get_crypto_bars", return_value=bars):
            signal = self.monitor.check_crypto_signal("BTC/USD", btc_1h_change=0.0)
        self.assertIsNotNone(signal, "expected oversold-bounce signal")
        self.assertEqual(signal["strategy"], "crypto-oversold-bounce")
        self.assertEqual(signal["action"], "BUY")
        # Wider stop (1.5× normal sl_pct)
        self.assertLess(signal["stop_loss"], signal["price"] * 0.93)

    def test_oversold_bounce_requires_reversal(self):
        """Free-fall (last bar lower than prior) MUST NOT trigger."""
        closes = self._scenario_oversold()
        closes[-1] = closes[-2] * 0.99   # last bar DROPS instead of rising
        bars = _make_bars(closes, vol=3000)
        with patch.object(self.monitor, "get_crypto_bars", return_value=bars):
            signal = self.monitor.check_crypto_signal("BTC/USD", btc_1h_change=0.0)
        # No reversal → no oversold-bounce. (Predator bracket also fails.)
        self.assertIsNone(signal)

    def test_oversold_bounce_blocked_by_catastrophic_24h(self):
        """24h-move < -10% (knife-catch) must NOT trigger."""
        closes = self._scenario_oversold()
        # Force 24h move way below floor: scale all bars (last vs bar[-24]).
        # We need closes[-1] / closes[-24] - 1 ≤ -10%.
        # Easiest: replace closes[-25:-1] with high values so last is way below.
        closes[-25:-1] = [150.0] * 24
        # Reversal still True (last > prior)? No — last < prior now.
        # Instead: keep reversal but place prior bars high.
        closes[-1] = closes[-2] * 1.005
        bars = _make_bars(closes, vol=3000)
        with patch.object(self.monitor, "get_crypto_bars", return_value=bars):
            signal = self.monitor.check_crypto_signal("BTC/USD", btc_1h_change=0.0)
        # Catastrophic 24h-move (≤ -10%) → oversold-bounce skipped;
        # predator bracket also skipped (abs(move) > 15%). → None.
        self.assertIsNone(signal)

    def test_oversold_bounce_t2_blocked_during_btc_dump(self):
        """Tier-2 alt (SOL/USD) must respect BTC dominance guard."""
        closes = self._scenario_oversold()
        bars = _make_bars(closes, vol=3000)
        with patch.object(self.monitor, "get_crypto_bars", return_value=bars):
            # BTC down 5% in 1h → guard blocks alt longs
            signal = self.monitor.check_crypto_signal("SOL/USD", btc_1h_change=-5.0)
        self.assertIsNone(signal)

    def test_normal_rsi_does_not_fire_oversold_bounce(self):
        """RSI > 30 → oversold-bounce skipped, predator path also fails."""
        closes = [100.0 + i * 0.1 for i in range(26)]  # gentle uptrend, RSI ~60
        closes.append(closes[-1] * 1.001)
        bars = _make_bars(closes, vol=500)  # low volume so predator-long fails too
        with patch.object(self.monitor, "get_crypto_bars", return_value=bars):
            signal = self.monitor.check_crypto_signal("BTC/USD", btc_1h_change=0.0)
        # No oversold-bounce (RSI too high), no predator long (insufficient setup)
        if signal is not None:
            self.assertNotEqual(signal["strategy"], "crypto-oversold-bounce")


# ─── P0 #2: analyzer symbol-based attribution fallback ───────────────────────


class TestSymbolBasedAttribution(unittest.TestCase):

    def setUp(self):
        import analyzer
        self.a = analyzer

    def test_unknown_uuid_with_known_symbol_resolves_to_strategy(self):
        # UUID-shaped client_order_id + symbol XOM → maps to geo-xom
        coid = "12345678-aaaa-bbbb-cccc-1234567890ab"
        result = self.a._strategy_from_client_id(coid, "XOM")
        self.assertEqual(result, "geo-xom")

    def test_unknown_uuid_with_known_symbol_cvx_maps_to_geo_energy(self):
        coid = "deadbeef-1111-2222-3333-aabbccddeeff"
        result = self.a._strategy_from_client_id(coid, "CVX")
        self.assertEqual(result, "geo-energy")

    def test_empty_client_order_id_with_known_symbol(self):
        # No COID but symbol XOM → still resolve via symbol map
        self.assertEqual(self.a._strategy_from_client_id("", "XOM"), "geo-xom")

    def test_unknown_uuid_with_unknown_symbol_still_unknown(self):
        # Symbol not in map → remains unknown
        coid = "12345678-aaaa-bbbb-cccc-1234567890ab"
        self.assertEqual(self.a._strategy_from_client_id(coid, "AMD"), "unknown")

    def test_legacy_exit_format_uses_symbol_fallback(self):
        # "exit-tp-XOM-150000123" — no strategy embedded → symbol fallback
        coid = "exit-tp-XOM-150000123"
        result = self.a._strategy_from_client_id(coid, "XOM")
        # Symbol-based fallback should fire and return geo-xom
        self.assertEqual(result, "geo-xom")

    def test_real_strategy_in_coid_takes_priority_over_symbol(self):
        # "momentum-long-XOM-150000123" — explicit strategy wins, even
        # though XOM is in SYMBOL_STRATEGY_MAP as geo-xom.
        coid = "momentum-long-XOM-150000123"
        result = self.a._strategy_from_client_id(coid, "XOM")
        self.assertEqual(result, "momentum-long")


# ─── P1 #3: zombie-prune LLM lock ────────────────────────────────────────────


class TestZombiePruneLLMLock(unittest.TestCase):

    def setUp(self):
        import adapter
        self.adp = adapter

    def _state(self, days_since_llm: int | None, days_tracked: int = 30,
               placed: int = 10) -> dict:
        today = date(2026, 5, 30)
        if days_since_llm is not None:
            last_llm = (today - timedelta(days=days_since_llm)).isoformat()
        else:
            last_llm = None
        cfg = {
            "enabled": True,
            "size_multiplier": 1.0,
            "side_bias": "long",
            "paused_until": None,
            "enabled_at": (today - timedelta(days=days_tracked)).isoformat(),
            "trades_lifetime": 0,
            "placed_lifetime": placed,
        }
        if last_llm is not None:
            cfg["last_llm_override_at"] = last_llm
        return {
            "strategies": {"crypto-momentum": cfg},
            # _flag_silent_strategies reads days_tracked from state
            "days_tracked": days_tracked,
        }

    def _today_stats(self, placed_per_strat: int) -> dict:
        return {
            "by_strategy": {"crypto-momentum": {"trades_lifetime": 0, "trades_7d": 0}},
            "fill_rate": {
                "crypto-momentum": {
                    "placed": placed_per_strat,
                    "placed_lifetime": placed_per_strat,
                    "filled": 0,
                    "canceled": placed_per_strat,
                    "expired": 0,
                    "rejected": 0,
                    "other": 0,
                    "fill_rate": 0.0,
                },
            },
        }

    def test_fresh_llm_override_blocks_prune(self):
        """LLM override 3 days ago → LOCK active → must NOT prune."""
        s = self._state(days_since_llm=3, days_tracked=30, placed=10)
        out = self.adp._flag_silent_strategies(s, self._today_stats(10))
        msgs = " ".join(out)
        self.assertIn("LLM override", msgs)
        self.assertTrue(s["strategies"]["crypto-momentum"]["enabled"],
                        f"strategy must stay enabled; got {s}")

    def test_stale_llm_override_allows_prune(self):
        """LLM override 20 days ago (> 14-day lock) → prune normally."""
        s = self._state(days_since_llm=20, days_tracked=30, placed=10)
        out = self.adp._flag_silent_strategies(s, self._today_stats(10))
        # placed >= 5 + trades_lifetime=0 → AUTO-PRUNED
        msgs = " ".join(out)
        self.assertIn("AUTO-PRUNED", msgs)
        self.assertFalse(s["strategies"]["crypto-momentum"]["enabled"])

    def test_no_llm_override_history_allows_prune(self):
        """No last_llm_override_at → normal prune path."""
        s = self._state(days_since_llm=None, days_tracked=30, placed=10)
        out = self.adp._flag_silent_strategies(s, self._today_stats(10))
        msgs = " ".join(out)
        self.assertIn("AUTO-PRUNED", msgs)

    def test_malformed_llm_date_falls_through(self):
        """Bad date in last_llm_override_at → no crash, falls through to prune."""
        s = self._state(days_since_llm=3, days_tracked=30, placed=10)
        s["strategies"]["crypto-momentum"]["last_llm_override_at"] = "not-a-date"
        out = self.adp._flag_silent_strategies(s, self._today_stats(10))
        # Malformed → pretend no stamp → goes through normal prune path
        msgs = " ".join(out)
        self.assertIn("AUTO-PRUNED", msgs)

    def test_safe_apply_overrides_stamps_last_llm_override_at(self):
        """safe_apply_overrides must stamp the date when applying strategy fields."""
        import llm_client
        state = {
            "strategies": {
                "crypto-momentum": {"enabled": False, "size_multiplier": 1.0},
            },
        }
        overrides = {
            "strategies": {
                "crypto-momentum": {"enabled": True, "size_multiplier": 1.5},
            },
        }
        new_state, applied = llm_client.safe_apply_overrides(state, overrides)
        stamp = new_state["strategies"]["crypto-momentum"].get("last_llm_override_at")
        self.assertIsNotNone(stamp, "must stamp last_llm_override_at on apply")
        # ISO date format YYYY-MM-DD
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}$")


# ─── P1 #4: fill_rate_closed (OPEN vs UNFILLED separation) ───────────────────


class TestFillRateOpenSeparation(unittest.TestCase):

    def setUp(self):
        import analyzer
        import adapter
        self.a = analyzer
        self.adp = adapter

    def _orders(self, filled=0, canceled=0, expired=0, rejected=0, open_count=0,
                strategy="geo-xom", symbol="XOM"):
        orders = []
        for _ in range(filled):
            orders.append({
                "client_order_id": f"{strategy}-{symbol}-100000001",
                "symbol": symbol, "status": "filled",
            })
        for _ in range(canceled):
            orders.append({
                "client_order_id": f"{strategy}-{symbol}-100000002",
                "symbol": symbol, "status": "canceled",
            })
        for _ in range(expired):
            orders.append({
                "client_order_id": f"{strategy}-{symbol}-100000003",
                "symbol": symbol, "status": "expired",
            })
        for _ in range(rejected):
            orders.append({
                "client_order_id": f"{strategy}-{symbol}-100000004",
                "symbol": symbol, "status": "rejected",
            })
        for _ in range(open_count):
            orders.append({
                "client_order_id": f"{strategy}-{symbol}-100000005",
                "symbol": symbol, "status": "held",
            })
        return orders

    def test_all_open_gtc_no_alert(self):
        """3 placed, ALL still open (held GTC) → no closed orders → no alert."""
        orders = self._orders(open_count=3)
        fr = self.a.compute_fill_rate(orders)
        stats = fr["geo-xom"]
        self.assertEqual(stats["open_pending"], 3)
        self.assertIsNone(stats["fill_rate_closed"], "closed_total=0 → fill_rate_closed=None")
        # alert path: must NOT emit
        alerts = self.adp.heuristic_fill_rate_alert(fr, threshold=0.5, min_placed=3)
        self.assertEqual(alerts, [], f"open-only orders must not trigger alert; got {alerts}")

    def test_one_fill_two_open_no_alert(self):
        """1 filled + 2 open → fill_rate_closed = 1/1 = 100% → no alert."""
        orders = self._orders(filled=1, open_count=2)
        fr = self.a.compute_fill_rate(orders)
        self.assertEqual(fr["geo-xom"]["fill_rate_closed"], 1.0)
        alerts = self.adp.heuristic_fill_rate_alert(fr, threshold=0.5, min_placed=3)
        self.assertEqual(alerts, [])

    def test_one_fill_four_canceled_alerts(self):
        """1 filled + 4 canceled → fill_rate_closed = 20% → alert fires."""
        orders = self._orders(filled=1, canceled=4)
        fr = self.a.compute_fill_rate(orders)
        self.assertEqual(fr["geo-xom"]["fill_rate_closed"], 0.2)
        alerts = self.adp.heuristic_fill_rate_alert(fr, threshold=0.5, min_placed=3)
        self.assertEqual(len(alerts), 1)
        self.assertIn("closed orders", alerts[0]["alert"])
        self.assertIn("open-GTC ignored", alerts[0]["alert"])

    def test_legacy_fill_rate_still_present(self):
        """fill_rate (legacy) still set for backward compat."""
        orders = self._orders(filled=1, canceled=1, open_count=3)
        fr = self.a.compute_fill_rate(orders)
        # legacy: filled / placed = 1/5 = 0.2
        self.assertEqual(fr["geo-xom"]["fill_rate"], 0.2)
        # new: filled / closed = 1/2 = 0.5
        self.assertEqual(fr["geo-xom"]["fill_rate_closed"], 0.5)


if __name__ == "__main__":
    unittest.main()
