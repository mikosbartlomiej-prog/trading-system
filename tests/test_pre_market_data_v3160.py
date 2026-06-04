"""v3.16.0 (2026-06-04) — Tests for shared/pre_market_data.py (FB-002).

All tests are LOCAL + DETERMINISTIC + NO NETWORK.
Every `requests.get` call is monkey-patched via unittest.mock.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


import pre_market_data as pmd  # noqa: E402


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _yahoo_payload_two_pm_bars(start_epoch: int = 1_717_500_000):
    """Build a Yahoo-shaped JSON payload with 2 valid pre-market bars."""
    end_epoch = start_epoch + 120
    return {
        "chart": {
            "result": [{
                "meta": {
                    "tradingPeriods": {
                        "pre": [[{"start": start_epoch, "end": end_epoch}]],
                    },
                },
                "timestamp": [start_epoch, start_epoch + 60],
                "indicators": {
                    "quote": [{
                        "open":   [100.0, 100.5],
                        "high":   [100.7, 101.0],
                        "low":    [99.8, 100.2],
                        "close":  [100.5, 100.9],
                        "volume": [1500, 1700],
                    }],
                },
            }],
        }
    }


def _yahoo_payload_with_nones():
    """Payload with some None OHLC entries — parser should skip those rows."""
    start = 1_717_500_000
    return {
        "chart": {
            "result": [{
                "meta": {"tradingPeriods": {"pre": [[{"start": start,
                                                     "end": start + 180}]]}},
                "timestamp": [start, start + 60, start + 120],
                "indicators": {
                    "quote": [{
                        "open":   [100.0, None, 101.0],
                        "high":   [100.5, None, 101.5],
                        "low":    [99.5,  None, 100.5],
                        "close":  [100.4, None, 101.2],
                        "volume": [1000,  0,    1200],
                    }],
                },
            }],
        }
    }


def _nasdaq_summary_payload():
    return {
        "symbol": "AAPL",
        "data": {
            "lastSalePrice": "$190.12",
            "netChange":     "+1.05",
            "percentageChange": "+0.55%",
            "volume":        12345,
            "marketType":    "pre",
        },
    }


def _mk_response(status_code: int, json_obj):
    """Build a fake requests.Response-like object."""
    r = mock.MagicMock()
    r.status_code = status_code
    r.json.return_value = json_obj
    return r


# ─── Test cases ───────────────────────────────────────────────────────────────

class TestYahooSuccess(unittest.TestCase):
    def setUp(self):
        pmd._clear_cache()

    def test_yahoo_success_returns_bars_with_expected_shape(self):
        with mock.patch.object(pmd.requests, "get",
                               return_value=_mk_response(200, _yahoo_payload_two_pm_bars())):
            bars = pmd.fetch_pre_market_bars("AAPL")
        self.assertIsInstance(bars, list)
        self.assertEqual(len(bars), 2)
        b = bars[0]
        for k in ("o", "h", "l", "c", "v", "t"):
            self.assertIn(k, b)
        self.assertIsInstance(b["o"], float)
        self.assertIsInstance(b["t"], str)
        # UTC ISO format
        self.assertTrue(b["t"].endswith("+00:00") or "T" in b["t"])


class TestYahoo429FallsThrough(unittest.TestCase):
    def setUp(self):
        pmd._clear_cache()

    def test_yahoo_429_returns_empty_bars(self):
        with mock.patch.object(pmd.requests, "get",
                               return_value=_mk_response(429, {})):
            bars = pmd.fetch_pre_market_bars("AAPL")
        self.assertEqual(bars, [])

    def test_yahoo_429_then_nasdaq_success_in_context(self):
        responses = [
            _mk_response(429, {}),                    # Yahoo 429
            _mk_response(200, _nasdaq_summary_payload()),  # Nasdaq OK
        ]
        with mock.patch.object(pmd.requests, "get", side_effect=responses):
            # Patch market_data.get_daily_bars to avoid network/import side
            # effects on prev-session lookup.
            with mock.patch.dict(sys.modules):
                # Provide a stub market_data if missing or just patch.
                with mock.patch("market_data.get_daily_bars",
                                return_value=None, create=True):
                    ctx = pmd.get_pre_market_context("AAPL")
        self.assertEqual(ctx["pre_market_bars"], [])
        self.assertEqual(ctx["source"], "nasdaq")
        self.assertIn("yahoo_no_bars", ctx["warnings"])


class TestYahooTimeout(unittest.TestCase):
    def setUp(self):
        pmd._clear_cache()

    def test_yahoo_timeout_returns_empty(self):
        # _http_get catches the requests exception → returns None.
        with mock.patch.object(pmd.requests, "get",
                               side_effect=Exception("Read timed out")):
            bars = pmd.fetch_pre_market_bars("AAPL")
        self.assertEqual(bars, [])


class TestYahooMalformedJSON(unittest.TestCase):
    def setUp(self):
        pmd._clear_cache()

    def test_yahoo_malformed_payload_returns_empty(self):
        # status 200 but malformed shape — no chart.result key
        with mock.patch.object(pmd.requests, "get",
                               return_value=_mk_response(200, {"not": "what we expect"})):
            bars = pmd.fetch_pre_market_bars("AAPL")
        self.assertEqual(bars, [])

    def test_yahoo_json_raises_returns_empty(self):
        # Simulate response.json() blowing up.
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("malformed")
        with mock.patch.object(pmd.requests, "get", return_value=resp):
            bars = pmd.fetch_pre_market_bars("AAPL")
        self.assertEqual(bars, [])

    def test_yahoo_payload_with_none_rows_skips_them(self):
        with mock.patch.object(pmd.requests, "get",
                               return_value=_mk_response(200, _yahoo_payload_with_nones())):
            bars = pmd.fetch_pre_market_bars("AAPL")
        # 3 bars in payload but middle row has None ohlc → skipped
        self.assertEqual(len(bars), 2)


class TestNasdaqSummary(unittest.TestCase):
    def setUp(self):
        pmd._clear_cache()

    def test_nasdaq_success_returns_summary(self):
        with mock.patch.object(pmd.requests, "get",
                               return_value=_mk_response(200, _nasdaq_summary_payload())):
            summary = pmd.fetch_pre_market_summary("AAPL")
        self.assertIsNotNone(summary)
        self.assertEqual(summary["session"], "pre")
        self.assertEqual(summary["last_price"], "$190.12")
        self.assertEqual(summary["volume"], 12345)

    def test_nasdaq_non_200_returns_none(self):
        with mock.patch.object(pmd.requests, "get",
                               return_value=_mk_response(503, {})):
            summary = pmd.fetch_pre_market_summary("AAPL")
        self.assertIsNone(summary)

    def test_nasdaq_transport_failure_returns_none(self):
        with mock.patch.object(pmd.requests, "get",
                               side_effect=Exception("conn refused")):
            summary = pmd.fetch_pre_market_summary("AAPL")
        self.assertIsNone(summary)


class TestBothFailContext(unittest.TestCase):
    def setUp(self):
        pmd._clear_cache()

    def test_both_sources_fail_returns_unavailable_context(self):
        # Yahoo 500 then Nasdaq 500
        responses = [
            _mk_response(500, {}),
            _mk_response(500, {}),
        ]
        with mock.patch.object(pmd.requests, "get", side_effect=responses):
            with mock.patch("market_data.get_daily_bars",
                            return_value=None, create=True):
                ctx = pmd.get_pre_market_context("AAPL")
        self.assertEqual(ctx["pre_market_bars"], [])
        self.assertEqual(ctx["source"], "unavailable")
        self.assertIn("yahoo_no_bars", ctx["warnings"])
        self.assertIn("nasdaq_no_summary", ctx["warnings"])
        self.assertIsNone(ctx["prev_session_close"])


class TestCache(unittest.TestCase):
    def setUp(self):
        pmd._clear_cache()

    def test_cache_hit_within_ttl_skips_http(self):
        payload = _yahoo_payload_two_pm_bars()
        with mock.patch.object(pmd.requests, "get",
                               return_value=_mk_response(200, payload)) as m:
            pmd.fetch_pre_market_bars("AAPL")
            pmd.fetch_pre_market_bars("AAPL")
            pmd.fetch_pre_market_bars("AAPL")
        # Only one HTTP call despite 3 fetches.
        self.assertEqual(m.call_count, 1)

    def test_cache_expires_after_ttl(self):
        payload = _yahoo_payload_two_pm_bars()
        with mock.patch.object(pmd.requests, "get",
                               return_value=_mk_response(200, payload)) as m:
            pmd.fetch_pre_market_bars("AAPL")
            # Manually expire the cache entry.
            for k in list(pmd._CACHE.keys()):
                _, payload_cached = pmd._CACHE[k]
                pmd._CACHE[k] = (time.time() - 1, payload_cached)
            pmd.fetch_pre_market_bars("AAPL")
        self.assertEqual(m.call_count, 2)


class TestSymbolEdgeCases(unittest.TestCase):
    def setUp(self):
        pmd._clear_cache()

    def test_empty_symbol_returns_empty_bars(self):
        bars = pmd.fetch_pre_market_bars("")
        self.assertEqual(bars, [])

    def test_none_symbol_returns_empty_bars(self):
        bars = pmd.fetch_pre_market_bars(None)  # type: ignore[arg-type]
        self.assertEqual(bars, [])

    def test_whitespace_only_symbol_returns_empty_bars(self):
        bars = pmd.fetch_pre_market_bars("   ")
        self.assertEqual(bars, [])

    def test_empty_symbol_summary_returns_none(self):
        self.assertIsNone(pmd.fetch_pre_market_summary(""))

    def test_empty_symbol_context_returns_unavailable(self):
        ctx = pmd.get_pre_market_context("")
        self.assertEqual(ctx["symbol"], "")
        self.assertEqual(ctx["source"], "unavailable")
        self.assertIn("empty_symbol", ctx["warnings"])

    def test_special_chars_in_symbol_url_encoded(self):
        captured = {}

        def fake_get(url, **kwargs):
            captured["url"] = url
            return _mk_response(200, _yahoo_payload_two_pm_bars())

        with mock.patch.object(pmd.requests, "get", side_effect=fake_get):
            pmd.fetch_pre_market_bars("BRK.B")
        # quote_plus URL-encodes the dot? Dot is in unreserved set so it stays;
        # check that no raw spaces / unsafe chars leaked. Try a symbol with
        # space to actually exercise quoting.
        pmd._clear_cache()
        with mock.patch.object(pmd.requests, "get", side_effect=fake_get):
            pmd.fetch_pre_market_bars("WEIRD SYM")
        self.assertIn("WEIRD+SYM", captured["url"])


class TestBarShapeMatchesAnalyzePreOpen(unittest.TestCase):
    """Integration: bars from pmd should be consumable by analyze_pre_open."""

    def setUp(self):
        pmd._clear_cache()

    def test_bars_feed_analyze_pre_open_without_error(self):
        from pre_open_behavior import analyze_pre_open  # late import
        with mock.patch.object(pmd.requests, "get",
                               return_value=_mk_response(200, _yahoo_payload_two_pm_bars())):
            bars = pmd.fetch_pre_market_bars("AAPL")
        self.assertGreaterEqual(len(bars), 2)
        result = analyze_pre_open(
            pre_market_bars=bars,
            prev_session_close=99.0,
            prev_session_high=101.5,
            prev_session_low=98.0,
        )
        # Should NOT return INSUFFICIENT_DATA — we gave it 2 valid bars + prev
        # close.
        self.assertFalse(result.insufficient_data)
        self.assertEqual(result.bars_count, len(bars))
        # gap_pct should be (100.9 - 99.0) / 99.0 ~ +0.019
        self.assertAlmostEqual(result.gap_pct, (100.9 - 99.0) / 99.0, places=5)


class TestTimestampsAreUTCISO(unittest.TestCase):
    def setUp(self):
        pmd._clear_cache()

    def test_timestamps_are_utc_iso_format(self):
        with mock.patch.object(pmd.requests, "get",
                               return_value=_mk_response(200, _yahoo_payload_two_pm_bars())):
            bars = pmd.fetch_pre_market_bars("AAPL")
        for b in bars:
            t = b["t"]
            self.assertIsInstance(t, str)
            self.assertTrue(t.endswith("+00:00"), msg=f"got {t!r}")
            # YYYY-MM-DDTHH:MM:SS+00:00 = 25 chars
            self.assertEqual(len(t), len("YYYY-MM-DDTHH:MM:SS+00:00"))


class TestContextStructure(unittest.TestCase):
    def setUp(self):
        pmd._clear_cache()

    def test_context_has_all_required_keys(self):
        with mock.patch.object(pmd.requests, "get",
                               return_value=_mk_response(200, _yahoo_payload_two_pm_bars())):
            with mock.patch("market_data.get_daily_bars",
                            return_value={"close": [99.0],
                                          "high":  [101.5],
                                          "low":   [98.0],
                                          "open":  [99.5],
                                          "volume":[100000],
                                          "time":  ["2026-06-03T00:00:00Z"]},
                            create=True):
                ctx = pmd.get_pre_market_context("AAPL")
        for k in (
            "symbol", "pre_market_bars", "prev_session_close",
            "prev_session_high", "prev_session_low",
            "source", "fetched_at_iso", "warnings",
        ):
            self.assertIn(k, ctx)
        self.assertEqual(ctx["source"], "yahoo")
        self.assertEqual(ctx["prev_session_close"], 99.0)
        self.assertEqual(ctx["prev_session_high"], 101.5)
        self.assertEqual(ctx["prev_session_low"], 98.0)


class TestLookbackMinutes(unittest.TestCase):
    def setUp(self):
        pmd._clear_cache()

    def test_lookback_minutes_slices_tail(self):
        # Build a payload with 10 bars; ask for last 3.
        start = 1_717_500_000
        end = start + 600
        payload = {
            "chart": {"result": [{
                "meta": {"tradingPeriods": {"pre": [[{"start": start,
                                                     "end": end}]]}},
                "timestamp": [start + 60 * i for i in range(10)],
                "indicators": {"quote": [{
                    "open":   [100.0 + i for i in range(10)],
                    "high":   [101.0 + i for i in range(10)],
                    "low":    [99.0 + i for i in range(10)],
                    "close":  [100.5 + i for i in range(10)],
                    "volume": [1000] * 10,
                }]},
            }]}
        }
        with mock.patch.object(pmd.requests, "get",
                               return_value=_mk_response(200, payload)):
            bars = pmd.fetch_pre_market_bars("AAPL", lookback_minutes=3)
        self.assertEqual(len(bars), 3)
        # The slice is from the tail — last bar's open should be 109.0.
        self.assertAlmostEqual(bars[-1]["o"], 109.0, places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
