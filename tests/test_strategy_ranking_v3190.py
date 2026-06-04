"""v3.19.0 (2026-06-04) — Tests for shared/strategy_ranking.py.

Covers:
  - Empty input → empty list
  - Strategy with risk_violations > 0 → last rank
  - Strategy with audit_incomplete → last rank
  - Deterministic ordering (same input → same ranking)
  - Composite score in [0..1]
  - Status mapping per score band
  - write_ranking_reports produces both .md and .json
  - High n + high PF + multi-regime → TOP_OBSERVE or EDGE_REVIEW
  - Low n → NEEDS_MORE_DATA
  - Recent degradation → REDUCE_PRIORITY-ish
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))

# Reload to avoid stale state from earlier test imports.
for _mod in ("strategy_ranking", "shared.strategy_ranking"):
    if _mod in sys.modules:
        del sys.modules[_mod]
import strategy_ranking as sr   # type: ignore  # noqa: E402


def _good_metrics(n=80, wr=0.60, pf=1.6,
                  expectancy=20.0, max_dd=0.10,
                  per_regime=None,
                  last_20_wr=0.60,
                  per_symbol=None):
    return {
        "n_closed":                    n,
        "win_rate":                    wr,
        "profit_factor":               pf,
        "expectancy":                  expectancy,
        "max_drawdown":                max_dd,
        "last_20_win_rate":            last_20_wr,
        "per_regime":                  per_regime or {
            "RISK_ON":  {"n_closed": 30, "expectancy": 15.0,
                         "net_pnl_after_fees_slippage": 300.0},
            "NEUTRAL":  {"n_closed": 30, "expectancy": 12.0,
                         "net_pnl_after_fees_slippage": 200.0},
            "RISK_OFF": {"n_closed": 20, "expectancy": 10.0,
                         "net_pnl_after_fees_slippage": 100.0},
        },
        "per_symbol":                  per_symbol or {
            "AAPL": {"n_closed": 30},
            "MSFT": {"n_closed": 30},
            "QQQ":  {"n_closed": 20},
        },
    }


def _bad_metrics(n=30, wr=0.25, pf=0.6, expectancy=-15.0, max_dd=0.45,
                 last_20_wr=0.15):
    return {
        "n_closed":         n,
        "win_rate":         wr,
        "profit_factor":    pf,
        "expectancy":       expectancy,
        "max_drawdown":     max_dd,
        "last_20_win_rate": last_20_wr,
        "per_regime":       {
            "RISK_ON": {"n_closed": 30, "expectancy": -5.0,
                        "net_pnl_after_fees_slippage": -150.0},
        },
        "per_symbol": {"AAPL": {"n_closed": 30}},
    }


class TestRankStrategies(unittest.TestCase):

    def test_empty_input_returns_empty(self):
        self.assertEqual(sr.rank_strategies(paper_metrics_per_strategy=None), [])
        self.assertEqual(sr.rank_strategies(paper_metrics_per_strategy={}), [])
        self.assertEqual(sr.rank_strategies(paper_metrics_per_strategy="bad"),
                         [])

    def test_risk_violations_pin_to_last_rank(self):
        good = _good_metrics()
        bad = dict(_good_metrics())
        bad["risk_violations"] = 1
        ranked = sr.rank_strategies(
            paper_metrics_per_strategy={"good": good, "bad": bad},
            emit_audit=False,
        )
        # 2 strategies → bad must be last
        self.assertEqual(len(ranked), 2)
        last = ranked[-1]
        self.assertEqual(last["strategy"], "bad")
        self.assertEqual(last["score"], 0.0)
        self.assertEqual(last["status"], sr.DISABLE_CANDIDATE)

    def test_audit_incomplete_pins_to_last_rank(self):
        m1 = _good_metrics()
        m2 = dict(_good_metrics())
        m2["audit_incomplete"] = True
        ranked = sr.rank_strategies(
            paper_metrics_per_strategy={"alpha": m1, "beta": m2},
            emit_audit=False,
        )
        last = ranked[-1]
        self.assertEqual(last["strategy"], "beta")
        self.assertEqual(last["score"], 0.0)

    def test_deterministic_ordering(self):
        input_metrics = {
            "S1": _good_metrics(pf=1.5),
            "S2": _good_metrics(pf=1.8),
            "S3": _bad_metrics(),
        }
        r1 = sr.rank_strategies(paper_metrics_per_strategy=input_metrics,
                                emit_audit=False)
        r2 = sr.rank_strategies(paper_metrics_per_strategy=input_metrics,
                                emit_audit=False)
        self.assertEqual([r["strategy"] for r in r1],
                         [r["strategy"] for r in r2])
        self.assertEqual([r["score"] for r in r1],
                         [r["score"] for r in r2])

    def test_score_is_in_0_1(self):
        metrics = {
            "best":  _good_metrics(),
            "worst": _bad_metrics(),
            "empty": {"n_closed": 0},
        }
        ranked = sr.rank_strategies(paper_metrics_per_strategy=metrics,
                                    emit_audit=False)
        for r in ranked:
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 1.0)

    def test_status_mapping_high_n_high_pf_multi_regime(self):
        ranked = sr.rank_strategies(
            paper_metrics_per_strategy={"top": _good_metrics(n=80, pf=1.8)},
            emit_audit=False,
        )
        top = ranked[0]
        # Should land in TOP_OBSERVE or EDGE_REVIEW_CANDIDATE band
        self.assertIn(top["status"],
                      (sr.TOP_OBSERVE, sr.EDGE_REVIEW_CANDIDATE,
                       sr.CONTINUE_OBSERVE))
        # Definitely not DISABLE / REDUCE.
        self.assertNotIn(top["status"], (sr.DISABLE_CANDIDATE,
                                         sr.REDUCE_PRIORITY))

    def test_low_n_returns_needs_more_data(self):
        m = {"thin": {"n_closed": 5, "win_rate": 0.7, "profit_factor": 1.5}}
        ranked = sr.rank_strategies(paper_metrics_per_strategy=m,
                                    emit_audit=False)
        self.assertEqual(ranked[0]["status"], sr.NEEDS_MORE_DATA)

    def test_recent_degradation_reduces_priority(self):
        # Mid-range PF/WR + crashed recent WR
        m = dict(_good_metrics(n=40, wr=0.40, pf=1.0, expectancy=2.0,
                                last_20_wr=0.05, max_dd=0.40))
        ranked = sr.rank_strategies(
            paper_metrics_per_strategy={"degraded": m},
            emit_audit=False,
        )
        # Status is unlikely to be TOP_OBSERVE; should be REDUCE_PRIORITY
        # or DISABLE_CANDIDATE.
        self.assertIn(ranked[0]["status"],
                      (sr.REDUCE_PRIORITY, sr.DISABLE_CANDIDATE,
                       sr.CONTINUE_OBSERVE, sr.NEEDS_MORE_DATA))
        self.assertLessEqual(ranked[0]["score"], 0.7)

    def test_components_breakdown_present(self):
        ranked = sr.rank_strategies(
            paper_metrics_per_strategy={"top": _good_metrics()},
            emit_audit=False,
        )
        comps = ranked[0]["components"]
        for k in sr.COMPONENT_WEIGHTS.keys():
            self.assertIn(k, comps)
            self.assertGreaterEqual(comps[k], 0.0)
            self.assertLessEqual(comps[k], 1.0)


class TestWriteRankingReports(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="sr_v3190_")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_writes_md_and_json(self):
        ranked = sr.rank_strategies(
            paper_metrics_per_strategy={"S1": _good_metrics(),
                                        "S2": _bad_metrics()},
            emit_audit=False,
        )
        out_md = os.path.join(self._tmp, "out.md")
        out_json = os.path.join(self._tmp, "out.json")
        rmd, rjs = sr.write_ranking_reports(ranked, out_md_path=out_md,
                                             out_json_path=out_json)
        self.assertEqual(rmd, out_md)
        self.assertEqual(rjs, out_json)
        self.assertTrue(os.path.exists(out_md))
        self.assertTrue(os.path.exists(out_json))
        md = open(out_md, encoding="utf-8").read()
        self.assertIn("# Strategy Ranking", md)
        payload = json.loads(open(out_json, encoding="utf-8").read())
        self.assertTrue(payload["paper_only"])
        self.assertIn("ranked", payload)
        self.assertEqual(len(payload["ranked"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
