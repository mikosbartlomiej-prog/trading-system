"""v3.30 (2026-06-09) — shadow universe expansion contract."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CFG = REPO_ROOT / "configs" / "shadow_universe_v330.json"


class TestShadowUniverseV330(unittest.TestCase):

    def setUp(self):
        self.assertTrue(CFG.exists(),
                          "configs/shadow_universe_v330.json missing")
        self.d = json.loads(CFG.read_text(encoding="utf-8"))

    def test_us_equity_symbols_minimum_count(self):
        syms = self.d.get("us_equity_symbols") or []
        self.assertGreaterEqual(
            len(syms), 15,
            "v3.30 expands shadow universe to ≥15 liquid US-equity "
            "symbols")
        self.assertTrue(all(isinstance(s, str) and s.isupper()
                              for s in syms))

    def test_no_crypto_no_options_no_penny(self):
        self.assertFalse(self.d.get("crypto_enabled", True))
        self.assertFalse(self.d.get("options_enabled", True))
        self.assertFalse(self.d.get("penny_stocks_allowed", True))

    def test_no_broker_execution_in_shadow_universe(self):
        self.assertFalse(
            self.d.get("broker_execution_allowed", True))

    def test_minimum_universe_diversity(self):
        # ETFs + at least 6 mega-cap single names.
        syms = set(self.d.get("us_equity_symbols") or [])
        etf_baseline = {"SPY", "QQQ"}
        self.assertTrue(etf_baseline.issubset(syms),
                          "shadow universe must include SPY+QQQ")
        single_names = syms - {"SPY", "QQQ", "IWM", "DIA",
                                  "XLK", "XLF", "XLV", "XLE", "XLY",
                                  "XLI", "XLB", "XLP", "XLU", "XLRE",
                                  "XLC"}
        self.assertGreaterEqual(len(single_names), 6,
                                  "must include ≥6 single-name mega-caps")


if __name__ == "__main__":
    unittest.main()
