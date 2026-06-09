"""v3.27.1 (2026-06-09) — market data diagnostics tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestNineTokensExposed(unittest.TestCase):
    def test_all_status_tokens_present(self):
        import market_data_provider as mdp
        for tok in (
            "MARKET_DATA_CREDENTIALS_MISSING",
            "MARKET_DATA_AUTH_FAILED",
            "MARKET_DATA_PROVIDER_ERROR",
            "MARKET_DATA_EMPTY_RESPONSE",
            "MARKET_CLOSED_OR_NO_BARS",
            "MARKET_DATA_STALE",
            "INSUFFICIENT_BARS_FOR_SIGNAL",
            "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL",
            "REAL_MARKET_SIGNAL_RECORDS_EMITTED",
        ):
            self.assertIn(getattr(mdp, tok), mdp.ALL_STATUS_TOKENS)


class TestMissingCredentialsTagged(unittest.TestCase):
    def test_equity_quote_missing_creds(self):
        import market_data_provider as mdp
        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "",
                                "ALPACA_SECRET_KEY": ""},
                               clear=False):
            snap = mdp.fetch_equity_quote("SPY")
            self.assertEqual(snap.data_quality, mdp.NO_MARKET_DATA)
            self.assertEqual(snap.status_token,
                              mdp.MARKET_DATA_CREDENTIALS_MISSING)


class TestAuthFailureTagged(unittest.TestCase):
    def test_http_401_routes_to_auth_failed(self):
        import market_data_provider as mdp

        class _R:
            status_code = 401
            def json(self):
                return {}

        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "x",
                                "ALPACA_SECRET_KEY": "y"},
                               clear=False):
            with mock.patch("requests.get", return_value=_R()):
                snap = mdp.fetch_equity_quote("SPY")
        self.assertEqual(snap.status_token,
                          mdp.MARKET_DATA_AUTH_FAILED)
        self.assertEqual(snap.data_quality, mdp.PROVIDER_ERROR)

    def test_http_403_routes_to_auth_failed(self):
        import market_data_provider as mdp

        class _R:
            status_code = 403
            def json(self):
                return {}

        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "x",
                                "ALPACA_SECRET_KEY": "y"},
                               clear=False):
            with mock.patch("requests.get", return_value=_R()):
                snap = mdp.fetch_equity_quote("SPY")
        self.assertEqual(snap.status_token,
                          mdp.MARKET_DATA_AUTH_FAILED)


class TestGenericProviderError(unittest.TestCase):
    def test_http_500_routes_to_provider_error(self):
        import market_data_provider as mdp

        class _R:
            status_code = 503
            def json(self):
                return {}

        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "x",
                                "ALPACA_SECRET_KEY": "y"},
                               clear=False):
            with mock.patch("requests.get", return_value=_R()):
                snap = mdp.fetch_equity_quote("SPY")
        self.assertEqual(snap.status_token,
                          mdp.MARKET_DATA_PROVIDER_ERROR)


class TestEmptyResponseDistinct(unittest.TestCase):
    def test_missing_bid_ask_routes_to_empty_response(self):
        import market_data_provider as mdp

        class _R:
            status_code = 200
            def json(self):
                return {"quote": {}}

        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "x",
                                "ALPACA_SECRET_KEY": "y"},
                               clear=False):
            with mock.patch("requests.get", return_value=_R()):
                snap = mdp.fetch_equity_quote("SPY")
        self.assertEqual(snap.data_quality, mdp.NO_MARKET_DATA)
        self.assertEqual(snap.status_token,
                          mdp.MARKET_DATA_EMPTY_RESPONSE)


class TestFetchDailyBarsDiagnostic(unittest.TestCase):
    def test_missing_creds_routes_to_credentials_missing(self):
        import market_data_provider as mdp
        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "",
                                "ALPACA_SECRET_KEY": ""},
                               clear=False):
            bars, token = mdp.fetch_daily_bars_diagnostic("SPY")
        self.assertIsNone(bars)
        self.assertEqual(token, mdp.MARKET_DATA_CREDENTIALS_MISSING)

    def test_empty_bars_routes_to_market_closed_or_no_bars(self):
        # Patch the module-level resolver so we don't depend on which
        # module-object (``market_data`` vs ``shared.market_data``)
        # Python's path resolves first.
        import market_data_provider as mdp
        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "x",
                                "ALPACA_SECRET_KEY": "y"},
                               clear=False):
            with mock.patch.object(
                mdp, "_resolve_get_daily_bars",
                return_value=lambda symbol, days=35: [],
            ):
                bars, token = mdp.fetch_daily_bars_diagnostic("SPY")
        self.assertIsNone(bars)
        self.assertEqual(token, mdp.MARKET_CLOSED_OR_NO_BARS)

    def test_insufficient_bars_routes_to_insufficient_bars(self):
        import market_data_provider as mdp
        # 10 bars is way under 22 ATR-window.
        fake_bars = [{"o": 1, "h": 2, "l": 0, "c": 1, "v": 1}
                       for _ in range(10)]
        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "x",
                                "ALPACA_SECRET_KEY": "y"},
                               clear=False):
            with mock.patch.object(
                mdp, "_resolve_get_daily_bars",
                return_value=lambda symbol, days=35: fake_bars,
            ):
                bars, token = mdp.fetch_daily_bars_diagnostic("SPY")
        self.assertEqual(len(bars or []), 10)
        self.assertEqual(token, mdp.INSUFFICIENT_BARS_FOR_SIGNAL)

    def test_provider_exception_routes_to_provider_error(self):
        import market_data_provider as mdp

        def _raise(symbol, days=35):
            raise RuntimeError("x")

        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "x",
                                "ALPACA_SECRET_KEY": "y"},
                               clear=False):
            with mock.patch.object(
                mdp, "_resolve_get_daily_bars",
                return_value=_raise,
            ):
                bars, token = mdp.fetch_daily_bars_diagnostic("SPY")
        self.assertIsNone(bars)
        self.assertEqual(token, mdp.MARKET_DATA_PROVIDER_ERROR)

    def test_happy_path_routes_to_real_but_no_signal_yet(self):
        import market_data_provider as mdp
        fake_bars = [{"o": 1, "h": 2, "l": 0, "c": 1, "v": 1}
                       for _ in range(30)]
        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "x",
                                "ALPACA_SECRET_KEY": "y"},
                               clear=False):
            with mock.patch.object(
                mdp, "_resolve_get_daily_bars",
                return_value=lambda symbol, days=35: fake_bars,
            ):
                bars, token = mdp.fetch_daily_bars_diagnostic("SPY")
        self.assertEqual(len(bars or []), 30)
        self.assertEqual(
            token, mdp.REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL,
        )


class TestNoFabrication(unittest.TestCase):
    def test_provider_error_yields_no_price(self):
        import market_data_provider as mdp
        with mock.patch("requests.get",
                          side_effect=RuntimeError("offline")):
            snap = mdp.fetch_crypto_quote("BTC/USD")
        self.assertIsNone(snap.price)
        self.assertEqual(snap.status_token,
                          mdp.MARKET_DATA_PROVIDER_ERROR)


class TestSnapshotAsDictIncludesStatusToken(unittest.TestCase):
    def test_status_token_in_dict(self):
        import market_data_provider as mdp
        snap = mdp.MarketSnapshot(
            symbol="X", asset_class="us_equity",
            timestamp=None, price=None,
            data_quality=mdp.NO_MARKET_DATA,
            status_token=mdp.MARKET_DATA_CREDENTIALS_MISSING,
        )
        d = snap.as_dict()
        self.assertEqual(d["status_token"],
                          mdp.MARKET_DATA_CREDENTIALS_MISSING)


if __name__ == "__main__":
    unittest.main()
