"""
Tests for learning-loop/analyzer.py::_strategy_from_client_id.

v3.8.5 (2026-05-16): added UUID-pattern detection to stop fake-strategy
pollution in state.json. Background: Alpaca bracket child orders (SL+TP
legs) inherit auto-generated UUID client_order_ids when the parent
uses bracket. The pre-v3.8.5 fallback "-".join(parts[:-2]) parsed
"cda058d6-1d5f-4b67-a222-ca7c9b29a9ae" as strategy "cda058d6-1d5f-4b67"
and grew state.json with one fake strategy per bracket child per day.
"""

import importlib.util
import os
import sys
import unittest

# Load _strategy_from_client_id directly from source without running analyzer
# imports (which pull llm_client → PEP 604 syntax incompatible w Python 3.9
# locally; CI 3.11 is fine). We exec only the relevant top-of-file
# definitions and grab the function from globals.
_ANALYZER_PATH = os.path.join(os.path.dirname(__file__), "..", "learning-loop", "analyzer.py")
_NAMESPACE: dict = {}
with open(_ANALYZER_PATH, encoding="utf-8") as f:
    _src = f.read()
# Take only up to (and including) _strategy_from_client_id's definition.
# Find first 'def reconstruct_trades' line — everything above is what we need.
_cut = _src.find("def reconstruct_trades")
assert _cut > 0, "marker 'def reconstruct_trades' not found in analyzer.py"
# We need just the imports + UUID regex + _strategy_from_client_id.
# Bound the slice to start at `import re as` to skip module-level imports
# that would fail on Python 3.9 (other source-level `from foo import ...`
# would otherwise execute). Find the _UUID_RE line as the start anchor.
_start = _src.find("import re as _re_strategy_parse")
assert _start > 0, "anchor 'import re as _re_strategy_parse' missing"
_snippet = _src[_start:_cut]
exec(_snippet, _NAMESPACE)
_strategy_from_client_id = _NAMESPACE["_strategy_from_client_id"]


class TestEntryFormat(unittest.TestCase):
    """ENTRY format: <strategy>-<symbol>-<HHMMSSmmm>"""

    def test_simple_strategy_name(self):
        self.assertEqual(
            _strategy_from_client_id("momentum-long-AAPL-141234567", "AAPL"),
            "momentum-long",
        )

    def test_hyphenated_strategy(self):
        self.assertEqual(
            _strategy_from_client_id("crypto-momentum-BTCUSD-141234567", "BTC/USD"),
            "crypto-momentum",
        )

    def test_allocator_rebalance(self):
        self.assertEqual(
            _strategy_from_client_id("allocator-rebalance-NVDA-141234567", "NVDA"),
            "allocator-rebalance",
        )


class TestExitFormatNew(unittest.TestCase):
    """EXIT new (v3-shipped): exit-<reason>-<strategy>-<symbol>-<ts>"""

    def test_tp_exit_with_strategy(self):
        self.assertEqual(
            _strategy_from_client_id("exit-tp-options-momentum-AAPL230101P00150000-141234567",
                                      "AAPL230101P00150000"),
            "options-momentum",
        )

    def test_emergency_exit_with_strategy(self):
        self.assertEqual(
            _strategy_from_client_id("exit-emergency-momentum-long-AAPL-141234567", "AAPL"),
            "momentum-long",
        )

    def test_governor_exit(self):
        self.assertEqual(
            _strategy_from_client_id("exit-governor-options-momentum-QQQ250101P00400000-141234567",
                                      "QQQ250101P00400000"),
            "options-momentum",
        )


class TestExitFormatLegacy(unittest.TestCase):
    """EXIT legacy (pre-v3): exit-<reason>-<symbol>-<ts> (no strategy)"""

    def test_legacy_format_returns_unknown(self):
        self.assertEqual(
            _strategy_from_client_id("exit-emergency-AAPL-141234567", "AAPL"),
            "unknown",
        )


class TestUUIDDetection(unittest.TestCase):
    """v3.8.5: Alpaca bracket-child UUIDs must NOT create fake strategies."""

    def test_pure_uuid_returns_unknown(self):
        self.assertEqual(
            _strategy_from_client_id("cda058d6-1d5f-4b67-a222-ca7c9b29a9ae", "AAPL"),
            "unknown",
        )

    def test_uuid_uppercase_returns_unknown(self):
        self.assertEqual(
            _strategy_from_client_id("CDA058D6-1D5F-4B67-A222-CA7C9B29A9AE", "AAPL"),
            "unknown",
        )

    def test_my_gld_cleanup_uuid_was_polluting(self):
        # Real example from 2026-05-15 GLD cleanup:
        # state.json had "59241d37-ee7b-4ae1" as fake strategy.
        # client_order_id="59241d37-ee7b-4ae1-ae73-39ff08016837" should
        # now return "unknown" not "59241d37-ee7b-4ae1".
        self.assertEqual(
            _strategy_from_client_id("59241d37-ee7b-4ae1-ae73-39ff08016837", "GLD"),
            "unknown",
        )

    def test_uuid_without_symbol_arg(self):
        self.assertEqual(
            _strategy_from_client_id("cda058d6-1d5f-4b67-a222-ca7c9b29a9ae"),
            "unknown",
        )


class TestEdgeCases(unittest.TestCase):

    def test_empty_string_returns_unknown(self):
        self.assertEqual(_strategy_from_client_id("", "AAPL"), "unknown")

    def test_none_returns_unknown(self):
        self.assertEqual(_strategy_from_client_id(None, "AAPL"), "unknown")

    def test_single_segment_returns_unknown(self):
        self.assertEqual(_strategy_from_client_id("abc", "AAPL"), "unknown")

    def test_partial_uuid_in_strategy_position(self):
        # Defensive: if a strategy somehow gets a UUID-shaped prefix
        # (8-hex-4-hex-4-hex pattern), the candidate-check catches it.
        # e.g. allocator stitched UUID + symbol + ts.
        self.assertEqual(
            _strategy_from_client_id("cda058d6-1d5f-4b67-AAPL-141234567", "AAPL"),
            "unknown",
        )


class TestRegressionRealCases(unittest.TestCase):
    """Real cases from production state.json (post-v3.8.5 should not pollute)."""

    UUID_CASES = (
        "8cfae0b1-b666-45b7-aaaa-aaaaaaaaaaaa",
        "197c428c-55de-484c-bbbb-bbbbbbbbbbbb",
        "e32dbb74-e810-4776-cccc-cccccccccccc",
        "5e5e7366-b480-4f17-dddd-dddddddddddd",
        "8a12bf8b-a8b8-406f-eeee-eeeeeeeeeeee",
        "cda058d6-1d5f-4b67-ffff-ffffffffffff",
        "bb6af536-d8c0-4373-0000-000000000000",
    )

    def test_all_uuid_artifacts_return_unknown(self):
        for cid in self.UUID_CASES:
            with self.subTest(cid=cid):
                self.assertEqual(_strategy_from_client_id(cid, ""), "unknown")


if __name__ == "__main__":
    unittest.main()
