"""v3.27.0 (2026-06-15) — Agent 3B — ETAP 8 — Watchlist-aware monitor diagnostics.

Test surface — 6 cases:
  * test_WATCHLIST_SYMBOL_SCANNED_token_recorded_when_symbol_in_watchlist
  * test_WATCHLIST_NO_TRIGGER_recorded_when_no_candidate
  * test_WATCHLIST_NEAR_MISS_recorded_when_distance_within_15pct
  * test_WATCHLIST_TRIGGER_CROSSED_recorded_when_signal_fires
  * test_monitor_diag_fail_soft_on_missing_watchlist_file
  * test_new_tokens_in_TOKEN_SET

Run:
    python3 -m unittest tests.test_watchlist_aware_diag_v3270 -v
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


class _DiagTestBase(unittest.TestCase):
    """Base — sets up isolated diag dir + watchlist file + clean env."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.diag_dir = self.tmp_path / "diag"
        self.diag_dir.mkdir(parents=True, exist_ok=True)
        self.watchlist_path = self.tmp_path / "trigger_watchlist_latest.json"

        # Reload modules so env overrides take effect freshly per test.
        os.environ["MONITOR_RUNTIME_DIAG_DIR"] = str(self.diag_dir)
        os.environ["TRIGGER_WATCHLIST_PATH"] = str(self.watchlist_path)

        # Force fresh import of both modules.
        for m in ("monitor_runtime_diag", "watchlist_diag"):
            if m in sys.modules:
                del sys.modules[m]
        self.mrd = importlib.import_module("monitor_runtime_diag")
        self.wd = importlib.import_module("watchlist_diag")

    def tearDown(self) -> None:
        os.environ.pop("MONITOR_RUNTIME_DIAG_DIR", None)
        os.environ.pop("TRIGGER_WATCHLIST_PATH", None)
        for m in ("monitor_runtime_diag", "watchlist_diag"):
            if m in sys.modules:
                del sys.modules[m]
        self.tmp.cleanup()

    # ── Helpers ───────────────────────────────────────────────────────────
    def _seed_watchlist(self, rows: list[dict]) -> None:
        self.watchlist_path.write_text(
            json.dumps({
                "rows": rows,
                "standing_markers": ["WATCHLIST_NEVER_PLACES_ORDERS"],
            }),
            encoding="utf-8",
        )

    def _read_diag_records(self) -> list[dict]:
        out: list[dict] = []
        for jsonl in self.diag_dir.glob("*.jsonl"):
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out


class TestWatchlistAwareDiag(_DiagTestBase):
    # ── 1. WATCHLIST_SYMBOL_SCANNED emitted when symbol on watchlist ──────
    def test_WATCHLIST_SYMBOL_SCANNED_token_recorded_when_symbol_in_watchlist(
        self,
    ) -> None:
        self._seed_watchlist([
            {"symbol": "AAPL", "strategy_id": "momentum-long",
             "priority": "P1"},
        ])
        cache = self.wd.load_watchlist_cache_for_scan()
        emitted = self.wd.diag_watchlist_scan_started(
            "price-monitor", "AAPL", cache)
        self.assertTrue(emitted)
        recs = self._read_diag_records()
        tokens = [r["token"] for r in recs]
        self.assertIn("WATCHLIST_SYMBOL_SCANNED", tokens)
        scan_rec = next(r for r in recs
                        if r["token"] == "WATCHLIST_SYMBOL_SCANNED")
        self.assertEqual(scan_rec["monitor"], "price-monitor")
        self.assertEqual(scan_rec["detail"]["symbol"], "AAPL")
        self.assertEqual(scan_rec["detail"]["watchlist_priority"], "P1")

    # ── 2. WATCHLIST_NO_TRIGGER recorded when no candidate ────────────────
    def test_WATCHLIST_NO_TRIGGER_recorded_when_no_candidate(self) -> None:
        self._seed_watchlist([
            {"symbol": "MSFT", "strategy_id": "momentum-long",
             "priority": "P2"},
        ])
        cache = self.wd.load_watchlist_cache_for_scan()
        # No signal detected; distance None or > NEAR_MISS_BAND.
        emitted_token = self.wd.diag_watchlist_scan_finished(
            "price-monitor", "MSFT", cache,
            signal_detected=False,
            distance=0.50,
        )
        self.assertEqual(emitted_token, "WATCHLIST_NO_TRIGGER")
        recs = self._read_diag_records()
        no_trig = next(r for r in recs
                       if r["token"] == "WATCHLIST_NO_TRIGGER")
        self.assertEqual(no_trig["detail"]["symbol"], "MSFT")
        self.assertEqual(no_trig["detail"]["current_distance"], 0.5)

    # ── 3. WATCHLIST_NEAR_MISS recorded when distance within band ────────
    def test_WATCHLIST_NEAR_MISS_recorded_when_distance_within_15pct(
        self,
    ) -> None:
        self._seed_watchlist([
            {"symbol": "NVDA", "strategy_id": "overbought-short",
             "priority": "P2"},
        ])
        cache = self.wd.load_watchlist_cache_for_scan()
        # No signal but distance = 0.10 (≤ 0.15 default near-miss band).
        emitted = self.wd.diag_watchlist_scan_finished(
            "price-monitor", "NVDA", cache,
            signal_detected=False,
            distance=0.10,
            near_miss_band=0.15,
        )
        self.assertEqual(emitted, "WATCHLIST_NEAR_MISS")
        recs = self._read_diag_records()
        nm = next(r for r in recs if r["token"] == "WATCHLIST_NEAR_MISS")
        self.assertEqual(nm["detail"]["symbol"], "NVDA")
        self.assertAlmostEqual(nm["detail"]["distance"], 0.10, places=4)
        self.assertEqual(nm["detail"]["band"], 0.15)

    # ── 4. WATCHLIST_TRIGGER_CROSSED recorded when signal fires ──────────
    def test_WATCHLIST_TRIGGER_CROSSED_recorded_when_signal_fires(
        self,
    ) -> None:
        self._seed_watchlist([
            {"symbol": "AMZN", "strategy_id": "momentum-long",
             "priority": "P1"},
        ])
        cache = self.wd.load_watchlist_cache_for_scan()
        emitted = self.wd.diag_watchlist_scan_finished(
            "price-monitor", "AMZN", cache,
            signal_detected=True,
            signal_id="momentum-long-amzn-20260615T1200",
            strategy_id_override="momentum-long",
        )
        self.assertEqual(emitted, "WATCHLIST_TRIGGER_CROSSED")
        recs = self._read_diag_records()
        cross = next(r for r in recs
                     if r["token"] == "WATCHLIST_TRIGGER_CROSSED")
        self.assertEqual(cross["detail"]["symbol"], "AMZN")
        self.assertEqual(cross["detail"]["strategy"], "momentum-long")
        self.assertEqual(
            cross["detail"]["signal_id"],
            "momentum-long-amzn-20260615T1200",
        )

    # ── 5. Fail-soft on missing watchlist file ────────────────────────────
    def test_monitor_diag_fail_soft_on_missing_watchlist_file(self) -> None:
        # Watchlist file does NOT exist.
        self.assertFalse(self.watchlist_path.exists())
        cache = self.wd.load_watchlist_cache_for_scan()
        # Cache must be empty, not raise.
        self.assertEqual(cache, {})
        # Started + finished must both return False/None silently.
        started = self.wd.diag_watchlist_scan_started(
            "price-monitor", "AAPL", cache)
        self.assertFalse(started)
        finished = self.wd.diag_watchlist_scan_finished(
            "price-monitor", "AAPL", cache,
            signal_detected=True,
        )
        self.assertIsNone(finished)
        # No diag records emitted because symbol is not on the watchlist.
        recs = self._read_diag_records()
        watchlist_tokens = [r["token"] for r in recs
                            if r["token"].startswith("WATCHLIST_")]
        self.assertEqual(watchlist_tokens, [])

    # ── 6. New tokens present in TOKEN_SET ────────────────────────────────
    def test_new_tokens_in_TOKEN_SET(self) -> None:
        token_set = self.mrd.TOKEN_SET
        self.assertIn("WATCHLIST_SYMBOL_SCANNED", token_set)
        self.assertIn("WATCHLIST_NO_TRIGGER", token_set)
        self.assertIn("WATCHLIST_NEAR_MISS", token_set)
        self.assertIn("WATCHLIST_TRIGGER_CROSSED", token_set)
        # DIAG_TOKENS alias should also contain them (back-compat).
        self.assertIn("WATCHLIST_SYMBOL_SCANNED", self.mrd.DIAG_TOKENS)
        self.assertIn("WATCHLIST_NO_TRIGGER", self.mrd.DIAG_TOKENS)
        self.assertIn("WATCHLIST_NEAR_MISS", self.mrd.DIAG_TOKENS)
        self.assertIn("WATCHLIST_TRIGGER_CROSSED", self.mrd.DIAG_TOKENS)


if __name__ == "__main__":
    unittest.main()
