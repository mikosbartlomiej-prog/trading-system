"""v3.18.0 (2026-06-04) — Universe filter activation tests.

Covers:
  - shared/runtime_config.py::active_universe (env-driven default)
  - shared/universe_selector.py::filter_symbols_for_paper_trading
  - shared/universe_selector.py::is_paper_ready wiring contract
  - audit emission on rejection

All tests are LOCAL + DETERMINISTIC + NO NETWORK.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHARED_DIR = os.path.join(REPO_ROOT, "shared")
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import runtime_config  # noqa: E402
import universe_selector as us  # noqa: E402


class TestActiveUniverseEnv(unittest.TestCase):
    """ACTIVE_UNIVERSE env var resolution."""

    def test_default_is_us_large(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ACTIVE_UNIVERSE", None)
            self.assertEqual(runtime_config.active_universe(), "US_LARGE")

    def test_crypto_env_override(self):
        with mock.patch.dict(os.environ, {"ACTIVE_UNIVERSE": "CRYPTO"}):
            self.assertEqual(runtime_config.active_universe(), "CRYPTO")

    def test_typo_falls_back_to_us_large(self):
        with mock.patch.dict(os.environ, {"ACTIVE_UNIVERSE": "GARBAGE_VALUE"}):
            self.assertEqual(runtime_config.active_universe(), "US_LARGE")

    def test_lowercase_env_normalized(self):
        with mock.patch.dict(os.environ, {"ACTIVE_UNIVERSE": "crypto"}):
            self.assertEqual(runtime_config.active_universe(), "CRYPTO")


class TestFilterSymbolsBasics(unittest.TestCase):
    """Basic filter contract."""

    def test_empty_list_returns_empty(self):
        allowed, rejected = us.filter_symbols_for_paper_trading([], audit=False)
        self.assertEqual(allowed, [])
        self.assertEqual(rejected, {})

    def test_non_list_input_returns_empty(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(None, audit=False)  # type: ignore
        self.assertEqual(allowed, [])
        self.assertEqual(rejected, {})

    def test_unknown_universe_rejects_all(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["AAPL", "MSFT"], universe_id="DOES_NOT_EXIST", audit=False,
        )
        self.assertEqual(allowed, [])
        self.assertIn("AAPL", rejected)
        self.assertEqual(rejected["AAPL"], "unknown_universe")

    def test_us_large_typical_symbols_pass(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["AAPL", "MSFT", "SPY"], universe_id="US_LARGE", audit=False,
        )
        self.assertEqual(set(allowed), {"AAPL", "MSFT", "SPY"})
        self.assertEqual(rejected, {})


class TestForbiddenPatterns(unittest.TestCase):
    """Forbidden symbol patterns must reject regardless of data."""

    def test_ob_suffix_blocked(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["ABCDE.OB"], universe_id="US_LARGE", audit=False,
        )
        self.assertEqual(allowed, [])
        self.assertIn("ABCDE.OB", rejected)
        self.assertIn("forbidden_pattern", rejected["ABCDE.OB"])

    def test_spac_warrant_blocked(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["BLAH_W"], universe_id="US_LARGE", audit=False,
        )
        self.assertEqual(allowed, [])
        self.assertIn("BLAH_W", rejected)

    def test_cashtag_blocked(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["$AAPL"], universe_id="US_LARGE", audit=False,
        )
        self.assertEqual(allowed, [])
        self.assertIn("$AAPL", rejected)
        self.assertIn("forbidden_char", rejected["$AAPL"])

    def test_leading_underscore_blocked(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["_RESERVED"], universe_id="US_LARGE", audit=False,
        )
        self.assertEqual(allowed, [])
        self.assertIn("_RESERVED", rejected)

    def test_empty_string_blocked(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["", "   "], universe_id="US_LARGE", audit=False,
        )
        # Note: store the rejection by key — empty string is allowed as dict key
        self.assertEqual(allowed, [])
        # Both empty + whitespace-only get rejected
        self.assertEqual(len(rejected), 2)


class TestSpreadThreshold(unittest.TestCase):
    """Spread > 2x universe.typical_spread_bps → REJECT."""

    def test_spread_above_threshold_rejects(self):
        # US_LARGE typical_spread_bps = 2.0, so threshold = 4.0
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["AAPL", "WIDE"],
            spread_data={"AAPL": 1.5, "WIDE": 10.0},
            universe_id="US_LARGE",
            audit=False,
        )
        self.assertIn("AAPL", allowed)
        self.assertNotIn("WIDE", allowed)
        self.assertIn("spread_exceeds", rejected["WIDE"])

    def test_spread_at_threshold_passes(self):
        # Threshold is 2x typical = 4.0; exactly 4.0 should pass (>, not >=)
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["AAPL"],
            spread_data={"AAPL": 4.0},
            universe_id="US_LARGE",
            audit=False,
        )
        self.assertIn("AAPL", allowed)

    def test_missing_spread_non_strict_allows(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["AAPL"],
            spread_data={},  # missing for AAPL
            universe_id="US_LARGE",
            strict=False,
            audit=False,
        )
        self.assertIn("AAPL", allowed)

    def test_missing_spread_strict_rejects(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["AAPL"],
            spread_data={},
            universe_id="US_LARGE",
            strict=True,
            audit=False,
        )
        self.assertEqual(allowed, [])
        self.assertIn("missing_spread_data_strict", rejected["AAPL"])


class TestVolumeThreshold(unittest.TestCase):
    """Volume < universe.min_liquidity_usd_daily → REJECT."""

    def test_volume_below_threshold_rejects(self):
        # US_LARGE min_liquidity = $10M
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["AAPL", "ILLIQUID"],
            volume_data={"AAPL": 50_000_000, "ILLIQUID": 1_000},
            universe_id="US_LARGE",
            audit=False,
        )
        self.assertIn("AAPL", allowed)
        self.assertIn("ILLIQUID", rejected)
        self.assertIn("volume_below", rejected["ILLIQUID"])

    def test_missing_volume_non_strict_allows(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["AAPL"],
            volume_data={},
            universe_id="US_LARGE",
            strict=False,
            audit=False,
        )
        self.assertIn("AAPL", allowed)

    def test_missing_volume_strict_rejects(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["AAPL"],
            volume_data={},
            universe_id="US_LARGE",
            strict=True,
            audit=False,
        )
        self.assertNotIn("AAPL", allowed)


class TestHistoryThreshold(unittest.TestCase):
    """No bars in last 5 days → REJECT."""

    def test_zero_history_rejects(self):
        allowed, rejected = us.filter_symbols_for_paper_trading(
            ["AAPL", "DEAD"],
            history_data={"AAPL": 5, "DEAD": 0},
            universe_id="US_LARGE",
            audit=False,
        )
        self.assertIn("AAPL", allowed)
        self.assertIn("DEAD", rejected)

    def test_missing_history_non_strict_allows(self):
        allowed, _ = us.filter_symbols_for_paper_trading(
            ["AAPL"],
            history_data={},
            universe_id="US_LARGE",
            strict=False,
            audit=False,
        )
        self.assertIn("AAPL", allowed)


class TestAuditEmit(unittest.TestCase):
    """Audit JSONL emit fires on rejection."""

    def test_audit_called_once_per_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["AUDIT_TRADING_DIR"] = tmp
            try:
                allowed, rejected = us.filter_symbols_for_paper_trading(
                    ["AAPL", "$BAD", "MSFT.OB"],
                    universe_id="US_LARGE",
                    audit=True,
                )
                # Two rejected → two JSONL lines
                files = os.listdir(tmp)
                self.assertEqual(len(files), 1)
                with open(os.path.join(tmp, files[0])) as f:
                    lines = [l for l in f if l.strip()]
                self.assertEqual(len(lines), 2)
                rec = json.loads(lines[0])
                self.assertEqual(rec["type"], "universe_filter")
                self.assertEqual(rec["decision"], "REJECT")
                self.assertEqual(rec["universe_id"], "US_LARGE")
            finally:
                os.environ.pop("AUDIT_TRADING_DIR", None)

    def test_audit_failure_does_not_break_filter(self):
        with mock.patch("shared.universe_selector.write_audit_event",
                          side_effect=Exception("disk full"),
                          create=True):
            # Even if audit explodes, filter still returns a clean result.
            allowed, rejected = us.filter_symbols_for_paper_trading(
                ["AAPL", "$BAD"],
                universe_id="US_LARGE",
                audit=True,
            )
            self.assertIn("AAPL", allowed)
            self.assertIn("$BAD", rejected)


class TestIsPaperReadyContract(unittest.TestCase):
    """is_paper_ready remains the authoritative gate."""

    def test_us_large_is_ready(self):
        ready, reason = us.is_paper_ready("US_LARGE")
        self.assertTrue(ready)
        self.assertEqual(reason, "paper_ready")

    def test_us_microcap_not_ready(self):
        ready, reason = us.is_paper_ready("US_MICROCAP")
        self.assertFalse(ready)
        self.assertIn("disabled", reason.lower())

    def test_pl_gpw_not_ready(self):
        ready, reason = us.is_paper_ready("PL_GPW")
        self.assertFalse(ready)
        # PL_GPW is disabled → first check trips on enabled=False
        self.assertIn("disabled", reason.lower())


class TestActiveUniverseDefaultPath(unittest.TestCase):
    """filter_symbols defaults to active universe when universe_id=None."""

    def test_no_universe_id_uses_active_universe(self):
        # Explicit env override
        with mock.patch.dict(os.environ, {"ACTIVE_UNIVERSE": "US_LARGE"}):
            allowed, _ = us.filter_symbols_for_paper_trading(
                ["AAPL"], audit=False,
            )
            self.assertIn("AAPL", allowed)


if __name__ == "__main__":
    unittest.main()
