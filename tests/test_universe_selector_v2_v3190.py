"""v3.19.0 (2026-06-04) — Universe Selector v2 ranking tests.

Covers:
  - rank_symbols core contract (PURE, deterministic, fail-soft)
  - 4-status classification (TRADE_ELIGIBLE / OBSERVE_ONLY / NEEDS_DATA / REJECTED)
  - write_universe_report writes md+json
  - Audit emit on ranking decision

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
for _p in (SHARED_DIR, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import universe_selector as us  # noqa: E402


def _make_universe_data(symbols, n_closed=10):
    """Build a complete-looking ranking input dict."""
    spread = {s: 2.0 for s in symbols}
    volume = {s: 50_000_000 for s in symbols}
    perf = {s: {
        "n_closed": n_closed,
        "profit_factor": 1.5,
        "daily_vol_pct": 2.0,
        "days_with_bars_last_5d": 5,
    } for s in symbols}
    compat = {s: 3 for s in symbols}
    cal = {s: {"calibration_error": 0.1} for s in symbols}
    regime = {s: {"fit_score": 0.7} for s in symbols}
    dd = {s: 0.10 for s in symbols}
    anoms = {s: 0 for s in symbols}
    return {
        "spread_data": spread,
        "volume_data": volume,
        "paper_performance": perf,
        "strategy_compat": compat,
        "confidence_calibration": cal,
        "regime_fit": regime,
        "drawdown_history": dd,
        "recent_anomalies": anoms,
    }


class TestRankSymbolsBasics(unittest.TestCase):
    def test_empty_input_returns_empty(self):
        out = us.rank_symbols([], audit=False)
        self.assertEqual(out, [])

    def test_non_list_input_returns_empty(self):
        out = us.rank_symbols(None, audit=False)  # type: ignore
        self.assertEqual(out, [])

    def test_unknown_universe_rejects_all(self):
        out = us.rank_symbols(
            ["AAPL", "MSFT"], universe_id="DOES_NOT_EXIST", audit=False,
        )
        self.assertEqual(len(out), 2)
        for r in out:
            self.assertEqual(r["status"], "REJECTED")
            self.assertEqual(r["reason"], "unknown_universe")

    def test_trade_eligible_basic(self):
        symbols = ["AAPL", "MSFT", "SPY"]
        inputs = _make_universe_data(symbols, n_closed=10)
        out = us.rank_symbols(symbols, universe_id="US_LARGE",
                              audit=False, **inputs)
        self.assertEqual(len(out), 3)
        statuses = {r["status"] for r in out}
        self.assertEqual(statuses, {"TRADE_ELIGIBLE"})
        for r in out:
            self.assertGreater(r["score"], 0.0)
            self.assertLessEqual(r["score"], 1.0)


class TestRankSymbolsStatuses(unittest.TestCase):
    def test_forbidden_pattern_rejected(self):
        out = us.rank_symbols(["AAPL", "BLAH_W"], universe_id="US_LARGE",
                              audit=False)
        statuses = {r["symbol"]: r["status"] for r in out}
        self.assertEqual(statuses["BLAH_W"], "REJECTED")
        self.assertIn("forbidden_pattern", out[-1]["reason"])

    def test_high_spread_rejected_hard(self):
        symbols = ["AAPL"]
        inputs = _make_universe_data(symbols)
        # US_LARGE typical_spread_bps = 2.0, threshold = 4.0
        inputs["spread_data"]["AAPL"] = 50.0
        out = us.rank_symbols(symbols, universe_id="US_LARGE",
                              audit=False, **inputs)
        self.assertEqual(out[0]["status"], "REJECTED")
        self.assertIn("spread_exceeds", out[0]["reason"])

    def test_no_volume_history_perf_marks_needs_data(self):
        # Pass only spread data; volume + perf + days_with_bars all absent
        out = us.rank_symbols(
            ["AAPL"], universe_id="US_LARGE",
            spread_data={"AAPL": 1.0},
            audit=False,
        )
        self.assertEqual(out[0]["status"], "NEEDS_DATA")

    def test_observe_only_low_evidence(self):
        symbols = ["AAPL"]
        inputs = _make_universe_data(symbols, n_closed=2)  # < 5
        out = us.rank_symbols(symbols, universe_id="US_LARGE",
                              audit=False, **inputs)
        self.assertEqual(out[0]["status"], "OBSERVE_ONLY")
        self.assertEqual(out[0]["reason"], "insufficient_paper_history")


class TestRankSymbolsDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        symbols = ["AAPL", "MSFT", "SPY", "QQQ"]
        inputs = _make_universe_data(symbols)
        out1 = us.rank_symbols(symbols, universe_id="US_LARGE",
                               audit=False, **inputs)
        out2 = us.rank_symbols(symbols, universe_id="US_LARGE",
                               audit=False, **inputs)
        self.assertEqual(out1, out2)

    def test_ranks_are_unique_and_sequential(self):
        symbols = ["AAPL", "MSFT", "SPY"]
        inputs = _make_universe_data(symbols)
        out = us.rank_symbols(symbols, universe_id="US_LARGE",
                              audit=False, **inputs)
        ranks = [r["rank"] for r in out]
        self.assertEqual(ranks, [1, 2, 3])

    def test_score_decreasing(self):
        # Construct mixed perf to ensure score variation.
        symbols = ["AAPL", "MSFT", "SPY"]
        inputs = _make_universe_data(symbols)
        inputs["paper_performance"]["AAPL"]["profit_factor"] = 2.5
        inputs["paper_performance"]["MSFT"]["profit_factor"] = 1.2
        inputs["paper_performance"]["SPY"]["profit_factor"] = 0.8
        out = us.rank_symbols(symbols, universe_id="US_LARGE",
                              audit=False, **inputs)
        scores = [r["score"] for r in out]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # Top symbol should be the one with PF=2.5
        self.assertEqual(out[0]["symbol"], "AAPL")


class TestWriteUniverseReport(unittest.TestCase):
    def test_writes_md_and_json(self):
        symbols = ["AAPL", "MSFT"]
        inputs = _make_universe_data(symbols)
        out = us.rank_symbols(symbols, universe_id="US_LARGE",
                              audit=False, **inputs)
        with tempfile.TemporaryDirectory() as td:
            md = os.path.join(td, "rank.md")
            jp = os.path.join(td, "rank.json")
            mdp, jpp = us.write_universe_report(out,
                                                 out_md_path=md,
                                                 out_json_path=jp,
                                                 universe_id="US_LARGE")
            self.assertEqual(mdp, md)
            self.assertEqual(jpp, jp)
            self.assertTrue(os.path.exists(md))
            self.assertTrue(os.path.exists(jp))
            md_body = open(md).read()
            self.assertIn("Universe Ranking (paper trading)", md_body)
            self.assertIn("AAPL", md_body)
            self.assertIn("Paper analysis only", md_body)
            data = json.loads(open(jp).read())
            self.assertEqual(data["universe_id"], "US_LARGE")
            self.assertEqual(data["n"], 2)


class TestAuditEmit(unittest.TestCase):
    def test_audit_called_with_ranking_summary(self):
        symbols = ["AAPL"]
        inputs = _make_universe_data(symbols)
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict(os.environ,
                                  {"AUDIT_TRADING_DIR": td}):
                out = us.rank_symbols(symbols, universe_id="US_LARGE",
                                      audit=True, **inputs)
                self.assertEqual(len(out), 1)
                # Audit file should exist for today
                files = os.listdir(td)
                self.assertTrue(
                    any(f.endswith(".jsonl") for f in files),
                    f"expected JSONL audit, got {files}",
                )
                # Open the file and assert content
                jsonl = next(f for f in files if f.endswith(".jsonl"))
                with open(os.path.join(td, jsonl)) as f:
                    rec = json.loads(f.readline())
                self.assertEqual(rec["type"], "universe_ranking")
                self.assertEqual(rec["source"], "evidence_analysis")
                self.assertEqual(rec["universe_id"], "US_LARGE")


class TestFailSoft(unittest.TestCase):
    def test_garbage_perf_does_not_raise(self):
        out = us.rank_symbols(
            ["AAPL"], universe_id="US_LARGE",
            paper_performance={"AAPL": "garbage"},  # type: ignore
            audit=False,
        )
        self.assertEqual(len(out), 1)
        self.assertIn(out[0]["status"], ("OBSERVE_ONLY", "NEEDS_DATA"))


if __name__ == "__main__":
    unittest.main()
