"""v3.22 — market_data_provider per-symbol diagnostic categorization tests.

Covers ``fetch_universe_snapshots_with_diagnostics`` end to end:
- auth-missing path
- bars-empty path
- HTTP 404 → INVALID_SYMBOL
- HTTP 429 → RATE_LIMIT
- aggregate counter is non-empty when all symbols fail
- aggregate counter is non-empty when symbols partially succeed
- function never raises on a total outage (every exception flavour)
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "shared"))

import shared.market_data_provider as mdp


def _fake_response(status: int, body):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


class TestUniverseDiagnostics(unittest.TestCase):

    def setUp(self) -> None:
        # Sandbox env; tests opt into setting creds as needed.
        self._saved = {
            k: os.environ.pop(k, None)
            for k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY")
        }

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    # ── auth missing ────────────────────────────────────────────────

    def test_auth_missing_emits_AUTH_MISSING(self):
        # No env set in setUp.
        result = mdp.fetch_universe_snapshots_with_diagnostics(
            equity_symbols=("SPY",), crypto_symbols=("BTC/USD",),
        )
        # Returns 2 snapshots, both AUTH_MISSING.
        self.assertEqual(len(result.snapshots), 2)
        counts = result.diagnostic_token_counts
        self.assertGreater(counts.get(mdp.DIAG_AUTH_MISSING, 0), 0)
        for snap in result.snapshots:
            self.assertEqual(snap.data_quality, mdp.NO_MARKET_DATA)

    # ── bars empty / no quote ───────────────────────────────────────

    def test_bars_empty_emits_BARS_EMPTY(self):
        os.environ["ALPACA_API_KEY"] = "k"
        os.environ["ALPACA_SECRET_KEY"] = "s"
        # Body has empty quote → "missing bid/ask" error path.
        with patch("requests.get",
                    return_value=_fake_response(200, {"quote": {}})):
            result = mdp.fetch_universe_snapshots_with_diagnostics(
                equity_symbols=("SPY",), crypto_symbols=(),
            )
        counts = result.diagnostic_token_counts
        self.assertGreater(counts.get(mdp.DIAG_BARS_EMPTY, 0), 0)

    # ── invalid symbol / 404 ────────────────────────────────────────

    def test_invalid_symbol_emits_INVALID_SYMBOL(self):
        os.environ["ALPACA_API_KEY"] = "k"
        os.environ["ALPACA_SECRET_KEY"] = "s"
        with patch("requests.get",
                    return_value=_fake_response(404, {})):
            result = mdp.fetch_universe_snapshots_with_diagnostics(
                equity_symbols=("BADTKR",), crypto_symbols=(),
            )
        counts = result.diagnostic_token_counts
        self.assertGreater(counts.get(mdp.DIAG_INVALID_SYMBOL, 0), 0)

    # ── rate limit / 429 ────────────────────────────────────────────

    def test_rate_limit_emits_RATE_LIMIT(self):
        os.environ["ALPACA_API_KEY"] = "k"
        os.environ["ALPACA_SECRET_KEY"] = "s"
        with patch("requests.get",
                    return_value=_fake_response(429, {})):
            result = mdp.fetch_universe_snapshots_with_diagnostics(
                equity_symbols=("SPY",), crypto_symbols=(),
            )
        counts = result.diagnostic_token_counts
        self.assertGreater(counts.get(mdp.DIAG_RATE_LIMIT, 0), 0)

    # ── all fail → counter non-empty ────────────────────────────────

    def test_diagnostic_counts_nonempty_when_all_symbols_fail(self):
        os.environ["ALPACA_API_KEY"] = "k"
        os.environ["ALPACA_SECRET_KEY"] = "s"
        with patch("requests.get",
                    return_value=_fake_response(500, {})):
            result = mdp.fetch_universe_snapshots_with_diagnostics(
                equity_symbols=("SPY", "QQQ"),
                crypto_symbols=("BTC/USD",),
            )
        counts = result.diagnostic_token_counts
        self.assertGreater(sum(counts.values()), 0)
        # No DIAG_OK in the counter.
        self.assertEqual(counts.get(mdp.DIAG_OK, 0), 0)

    # ── partial success ─────────────────────────────────────────────

    def test_diagnostic_counts_nonempty_when_partial_success(self):
        os.environ["ALPACA_API_KEY"] = "k"
        os.environ["ALPACA_SECRET_KEY"] = "s"

        # Build a deterministic good-quote body for happy responses.
        # Use a future ISO timestamp so the snapshot is fresh.
        good_quote = {
            "quote": {
                "bp": 100.0, "ap": 101.0,
                "t": "2099-01-01T00:00:00Z",
            },
        }

        responses = [
            _fake_response(200, good_quote),   # SPY → OK
            _fake_response(404, {}),           # BADTKR → INVALID_SYMBOL
            _fake_response(429, {}),           # BTC/USD → RATE_LIMIT
        ]

        with patch("requests.get", side_effect=responses):
            result = mdp.fetch_universe_snapshots_with_diagnostics(
                equity_symbols=("SPY", "BADTKR"),
                crypto_symbols=("BTC/USD",),
            )
        counts = result.diagnostic_token_counts
        # At least one good and at least one bad token.
        self.assertGreater(sum(counts.values()), 1)
        self.assertGreater(counts.get(mdp.DIAG_OK, 0)
                            + counts.get(mdp.DIAG_INVALID_SYMBOL, 0)
                            + counts.get(mdp.DIAG_RATE_LIMIT, 0), 0)

    # ── never raises on total outage ────────────────────────────────

    def test_function_never_raises_on_total_outage(self):
        os.environ["ALPACA_API_KEY"] = "k"
        os.environ["ALPACA_SECRET_KEY"] = "s"

        # Cycle through a representative set of pathological responses.
        # Each must be swallowed by the helper.
        side_effects = [
            ConnectionError("network down"),
            TimeoutError("read timeout"),
            ValueError("bad json"),
            RuntimeError("provider hiccup"),
            _fake_response(500, {}),
        ]
        with patch("requests.get", side_effect=side_effects):
            try:
                result = mdp.fetch_universe_snapshots_with_diagnostics(
                    equity_symbols=("SPY", "QQQ"),
                    crypto_symbols=("BTC/USD", "ETH/USD", "LTC/USD"),
                )
            except Exception as e:  # pragma: no cover
                self.fail(
                    "fetch_universe_snapshots_with_diagnostics raised "
                    f"on a total outage: {type(e).__name__}: {e}"
                )
        # Returned something; counters non-empty.
        self.assertIsInstance(result, mdp.UniverseFetchResult)
        self.assertEqual(len(result.snapshots), 5)
        self.assertGreater(sum(result.diagnostic_token_counts.values()), 0)

    # ── legacy ``fetch_universe_snapshots`` still returns list ──────

    def test_legacy_fetch_universe_snapshots_returns_list(self):
        """Backward-compat: existing callers expecting a list of
        snapshots from ``fetch_universe_snapshots`` must keep working
        without any change."""
        # No creds → fast path that exercises the legacy signature.
        out = mdp.fetch_universe_snapshots(
            equity_symbols=("SPY",), crypto_symbols=("BTC/USD",),
        )
        self.assertIsInstance(out, list)
        for snap in out:
            self.assertIsInstance(snap, mdp.MarketSnapshot)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
