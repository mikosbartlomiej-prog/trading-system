"""v3.30 (2026-06-16) — tests for shared/symbol_normalization.py.

Asserts the canonical-key contract that closes the
``AVAX / AVAXUSD / AVAX/USD`` membership leak.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))

import symbol_normalization as sn  # noqa: E402


class TestCanonicalCrypto(unittest.TestCase):
    """The leak that triggered v3.30 was crypto-only — test it first."""

    def test_avax_bare_canonicalizes_to_slash_usd(self):
        self.assertEqual(sn.canonical_for("AVAX"), "AVAX/USD")

    def test_avax_with_usd_suffix_canonicalizes_to_slash_usd(self):
        self.assertEqual(sn.canonical_for("AVAXUSD"), "AVAX/USD")

    def test_avax_slash_usd_is_idempotent(self):
        self.assertEqual(sn.canonical_for("AVAX/USD"), "AVAX/USD")

    def test_btc_three_forms_all_canonical(self):
        self.assertEqual(sn.canonical_for("BTC"), "BTC/USD")
        self.assertEqual(sn.canonical_for("BTCUSD"), "BTC/USD")
        self.assertEqual(sn.canonical_for("BTC/USD"), "BTC/USD")

    def test_lower_case_and_whitespace_tolerated(self):
        self.assertEqual(sn.canonical_for("  avax  "), "AVAX/USD")
        self.assertEqual(sn.canonical_for("eth/usd"), "ETH/USD")


class TestCanonicalEquity(unittest.TestCase):
    def test_spy_stays_spy(self):
        self.assertEqual(sn.canonical_for("SPY"), "SPY")

    def test_lowercase_equity_uppercased(self):
        self.assertEqual(sn.canonical_for("spy"), "SPY")


class TestCanonicalEdgeCases(unittest.TestCase):
    def test_empty_string_returns_empty(self):
        self.assertEqual(sn.canonical_for(""), "")

    def test_none_returns_empty(self):
        self.assertEqual(sn.canonical_for(None), "")

    def test_unknown_crypto_alias_falls_through_to_equity_form(self):
        # FOOUSD looks like a crypto alias but FOO is not in CRYPTO_BASES
        # → treated as an unknown equity-shaped symbol, NOT crypto.
        self.assertEqual(sn.canonical_for("FOOUSD"), "FOOUSD")

    def test_random_pair_with_unknown_base_not_promoted(self):
        # FOO/USD is not in CRYPTO_BASES → leave as-is (don't claim crypto).
        self.assertEqual(sn.canonical_for("FOO/USD"), "FOO/USD")


class TestAliasesFor(unittest.TestCase):
    def test_avax_aliases_returns_all_three_forms(self):
        self.assertEqual(
            sn.aliases_for("AVAX"),
            {"AVAX", "AVAXUSD", "AVAX/USD"},
        )

    def test_btc_aliases_complete(self):
        self.assertEqual(
            sn.aliases_for("BTC"),
            {"BTC", "BTCUSD", "BTC/USD"},
        )

    def test_avax_aliases_round_trip_from_avaxusd(self):
        self.assertEqual(
            sn.aliases_for("AVAXUSD"),
            sn.aliases_for("AVAX/USD"),
        )

    def test_spy_aliases_only_itself(self):
        self.assertEqual(sn.aliases_for("SPY"), {"SPY"})

    def test_empty_aliases_empty_set(self):
        self.assertEqual(sn.aliases_for(""), set())
        self.assertEqual(sn.aliases_for(None), set())


class TestIsCryptoCanonical(unittest.TestCase):
    def test_avax_slash_usd_is_crypto(self):
        self.assertTrue(sn.is_crypto_canonical("AVAX/USD"))

    def test_avax_bare_is_not_crypto_canonical(self):
        # bare AVAX is NOT canonical crypto form even though it's a base.
        # is_crypto_canonical asks "is this in <BASE>/USD form?" — bare
        # AVAX answers no. Use canonical_for() first if you want to
        # promote it to canonical form.
        self.assertFalse(sn.is_crypto_canonical("AVAX"))

    def test_spy_is_not_crypto(self):
        self.assertFalse(sn.is_crypto_canonical("SPY"))

    def test_foo_slash_usd_is_not_crypto(self):
        # Unknown base — not in CRYPTO_BASES.
        self.assertFalse(sn.is_crypto_canonical("FOO/USD"))


class TestPureFunctionInvariants(unittest.TestCase):
    """Hard invariants from the module docstring."""

    def test_no_alpaca_orders_import(self):
        # Check via AST that no `import alpaca_orders` or
        # `from alpaca_orders import ...` statement exists; the docstring
        # may mention the name in narrative text without violating the rule.
        src_path = _REPO_ROOT / "shared" / "symbol_normalization.py"
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn("alpaca_orders", n.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn("alpaca_orders", node.module or "")

    def test_no_broker_repair_required_import(self):
        # Avoid circular: broker_repair_required imports US, not vice versa.
        # AST-level check; docstring textual mention is permitted.
        src_path = _REPO_ROOT / "shared" / "symbol_normalization.py"
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn("broker_repair_required", n.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn("broker_repair_required", node.module or "")

    def test_no_io_calls_in_module(self):
        src_path = _REPO_ROOT / "shared" / "symbol_normalization.py"
        src = src_path.read_text(encoding="utf-8")
        # AST walk: no open() / json.dump() / requests.* / urllib.* calls.
        tree = ast.parse(src)
        forbidden = {"open", "loads", "dump", "dumps", "load", "post", "get", "delete"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id == "open":
                    self.fail("symbol_normalization must not call open()")
                if isinstance(fn, ast.Attribute):
                    # Allow .split() / .strip() / .upper() / .endswith() string
                    # methods; only flag full module.method() forms like
                    # json.dump() / requests.post().
                    if isinstance(fn.value, ast.Name) and fn.value.id in (
                        "json", "requests", "urllib", "os", "subprocess"
                    ) and fn.attr in forbidden:
                        self.fail(
                            f"symbol_normalization must not call "
                            f"{fn.value.id}.{fn.attr}()"
                        )

    def test_module_has_no_network_imports(self):
        src_path = _REPO_ROOT / "shared" / "symbol_normalization.py"
        src = src_path.read_text(encoding="utf-8")
        for forbidden in ("requests", "urllib", "http.client", "socket"):
            self.assertNotIn(
                f"import {forbidden}", src,
                f"symbol_normalization must not import {forbidden}",
            )


class TestCanonicalSet(unittest.TestCase):
    def test_set_canonicalizes_and_dedupes(self):
        result = sn.canonical_set(["AVAX", "AVAXUSD", "AVAX/USD", "BTC"])
        self.assertEqual(result, {"AVAX/USD", "BTC/USD"})

    def test_set_drops_empty_entries(self):
        result = sn.canonical_set(["AVAX", "", None, "SPY"])
        self.assertEqual(result, {"AVAX/USD", "SPY"})


if __name__ == "__main__":
    unittest.main()
