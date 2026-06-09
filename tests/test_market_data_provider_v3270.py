"""v3.27.0 (2026-06-09) — market data provider tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestProviderReadOnly(unittest.TestCase):
    def test_module_does_not_import_alpaca_orders(self):
        # Import the module fresh — alpaca_orders must NOT appear in
        # sys.modules as a side-effect.
        if "alpaca_orders" in sys.modules:
            del sys.modules["alpaca_orders"]
        if "market_data_provider" in sys.modules:
            del sys.modules["market_data_provider"]
        import market_data_provider  # noqa: F401
        self.assertNotIn("alpaca_orders", sys.modules)

    def test_source_has_no_forbidden_tokens(self):
        src = (REPO_ROOT / "shared"
                / "market_data_provider.py").read_text()
        FORBIDDEN = (
            "place_stock_bracket", "place_crypto_order",
            "place_simple_buy", "safe_close",
            "execute_crypto_signal", "execute_stock_signal",
            "from shared.alpaca_orders", "from alpaca_orders",
            "import alpaca_orders", "requests.post",
            "requests.put", "requests.delete",
        )
        for tok in FORBIDDEN:
            self.assertNotIn(
                tok, src,
                f"forbidden token in provider: {tok!r}",
            )

    def test_no_url_uses_broker_host(self):
        """The provider may MENTION the forbidden host in a comment
        or docstring (and does, by design — to document what it
        must never reach), but no URL construction must reference
        it."""
        src = (REPO_ROOT / "shared"
                / "market_data_provider.py").read_text()
        # Look for f-string or concat-style URL building that
        # references the broker host.
        FORBIDDEN_URL_PATTERNS = (
            'f"https://paper-api',
            "f'https://paper-api",
            '"https://paper-api',
            "'https://paper-api",
        )
        for pat in FORBIDDEN_URL_PATTERNS:
            self.assertNotIn(
                pat, src,
                f"broker-host URL string in provider: {pat!r}",
            )

    def test_invariants_true(self):
        import market_data_provider as mdp
        self.assertTrue(mdp.NEVER_SUBMITS_ORDERS)
        self.assertTrue(mdp.NEVER_TOUCHES_BROKER_HOST)
        self.assertTrue(mdp.NEVER_IMPORTS_ALPACA_ORDERS)
        self.assertTrue(mdp.NEVER_FABRICATES_PRICE)

    def test_data_url_is_data_host(self):
        import market_data_provider as mdp
        self.assertIn("data.alpaca.markets", mdp.ALPACA_DATA_URL)
        self.assertNotIn("paper-api.alpaca.markets",
                          mdp.ALPACA_DATA_URL)


class TestQualityEnum(unittest.TestCase):
    def test_four_qualities_exposed(self):
        import market_data_provider as mdp
        for q in (mdp.REAL_MARKET_DATA, mdp.NO_MARKET_DATA,
                   mdp.STALE_MARKET_DATA, mdp.PROVIDER_ERROR):
            self.assertIn(q, mdp.ALL_DATA_QUALITIES)


class TestFetchEquityQuoteFailSoft(unittest.TestCase):
    def test_missing_creds_returns_no_market_data(self):
        import market_data_provider as mdp
        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "",
                                "ALPACA_SECRET_KEY": ""},
                               clear=False):
            snap = mdp.fetch_equity_quote("SPY")
            self.assertEqual(snap.symbol, "SPY")
            self.assertEqual(snap.asset_class, "us_equity")
            self.assertEqual(snap.data_quality, mdp.NO_MARKET_DATA)
            self.assertIsNone(snap.price)


class TestFetchCryptoQuoteNeverFabricates(unittest.TestCase):
    def test_provider_error_returns_no_price(self):
        import market_data_provider as mdp
        # Trigger an error by patching requests.get to raise.
        with mock.patch("requests.get",
                          side_effect=RuntimeError("offline")):
            snap = mdp.fetch_crypto_quote("BTC/USD")
            self.assertEqual(snap.symbol, "BTC/USD")
            self.assertEqual(snap.asset_class, "crypto")
            self.assertEqual(snap.data_quality, mdp.PROVIDER_ERROR)
            self.assertIsNone(snap.price)


class TestFetchUniverseFailSoft(unittest.TestCase):
    def test_universe_fetch_returns_one_snapshot_per_symbol(self):
        import market_data_provider as mdp
        # Force offline: missing equity creds + provider error on
        # crypto so neither path can fabricate prices in CI.
        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "",
                                "ALPACA_SECRET_KEY": ""},
                               clear=False):
            with mock.patch("requests.get",
                              side_effect=RuntimeError("offline")):
                snaps = mdp.fetch_universe_snapshots(
                    equity_symbols=("SPY", "QQQ"),
                    crypto_symbols=("BTC/USD",),
                )
        self.assertEqual(len(snaps), 3)
        # None should carry REAL_MARKET_DATA.
        for s in snaps:
            self.assertNotEqual(s.data_quality, mdp.REAL_MARKET_DATA)
            self.assertIsNone(s.price)


class TestSnapshotDispatch(unittest.TestCase):
    def test_symbol_with_slash_routes_crypto(self):
        import market_data_provider as mdp
        with mock.patch("requests.get",
                          side_effect=RuntimeError("offline")):
            s = mdp.fetch_snapshot("ETH/USD")
        self.assertEqual(s.asset_class, "crypto")

    def test_bare_symbol_routes_equity(self):
        import market_data_provider as mdp
        with mock.patch.dict(os.environ,
                               {"ALPACA_API_KEY": "",
                                "ALPACA_SECRET_KEY": ""},
                               clear=False):
            s = mdp.fetch_snapshot("AMD")
        self.assertEqual(s.asset_class, "us_equity")


class TestPolicySummary(unittest.TestCase):
    def test_summary_carries_invariants(self):
        import market_data_provider as mdp
        s = mdp.policy_summary()
        self.assertEqual(s["version"], "v3.27.0")
        inv = s["invariants"]
        self.assertTrue(inv["NEVER_SUBMITS_ORDERS"])
        self.assertTrue(inv["NEVER_TOUCHES_BROKER_HOST"])
        self.assertTrue(inv["NEVER_IMPORTS_ALPACA_ORDERS"])
        self.assertTrue(inv["NEVER_FABRICATES_PRICE"])


if __name__ == "__main__":
    unittest.main()
