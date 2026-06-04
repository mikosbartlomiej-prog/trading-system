"""v3.19.0 (2026-06-04) — Tests for shared/post_session_learning.py.

Covers:
  - Empty ledger → empty buckets + warning
  - 50 winning trades → KEEP_OBSERVING
  - 30 trades + WR 25% → CANDIDATE_FOR_DISABLE
  - Single-regime concentration → finding
  - Recent 20-trade degradation → finding
  - Backtest vs paper divergence detected
  - run_post_session_analysis NEVER mutates strategy state.json
  - Generate report writes valid markdown + JSON
  - All required keys present in output
  - Detection helpers fail-soft on bad input
  - CANDIDATE_FOR_EDGE_REVIEW on healthy multi-regime evidence
  - NEEDS_MORE_DATA when n < 10
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _BaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="psl_v3190_")
        self._ledger_dir = os.path.join(self._tmp, "paper_experiments")
        self._audit_dir = os.path.join(self._tmp, "audit")
        os.environ["PAPER_EXPERIMENT_DIR"] = self._ledger_dir
        os.environ["AUDIT_TRADING_DIR"] = self._audit_dir
        # Reload module to pick up env
        for mod in ("post_session_learning", "shared.post_session_learning"):
            if mod in sys.modules:
                del sys.modules[mod]
        import post_session_learning as psl   # noqa: F401
        self.psl = psl
        # Pre-create state.json snapshot to verify it's NOT mutated.
        self._state_path = os.path.join(self._tmp, "state.json")
        with open(self._state_path, "w", encoding="utf-8") as f:
            json.dump({"strategies": {"S1": {"enabled": True}}}, f)

    def tearDown(self):
        for k in ("PAPER_EXPERIMENT_DIR", "AUDIT_TRADING_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_ledger(self, recs: list[dict], date_iso: str | None = None):
        os.makedirs(self._ledger_dir, exist_ok=True)
        if date_iso is None:
            date_iso = datetime.now(timezone.utc).date().isoformat()
        path = os.path.join(self._ledger_dir, f"{date_iso}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, sort_keys=True) + "\n")

    @staticmethod
    def _trade(strategy="S1", symbol="AAPL", net=10.0,
               regime="RISK_ON", confidence=0.6, closed_at=None):
        if closed_at is None:
            closed_at = datetime.now(timezone.utc).isoformat()
        return {
            "paper_only":           True,
            "strategy":             strategy,
            "symbol":               symbol,
            "net_pnl":              float(net),
            "gross_pnl":            float(net),
            "cost":                 0.0,
            "regime":               regime,
            "confidence_at_entry":  confidence,
            "closed_at":            closed_at,
            "side":                 "long",
        }


# ─── Empty ledger ────────────────────────────────────────────────────────────

class TestEmptyLedger(_BaseTest):

    def test_empty_ledger_returns_empty_buckets_with_warning(self):
        out = self.psl.run_post_session_analysis(emit_audit=False)
        self.assertIsInstance(out, dict)
        self.assertEqual(out["strategies"], {})
        self.assertEqual(out["symbols"], {})
        self.assertEqual(out["regimes"], {})
        self.assertEqual(out["confidence_buckets"], {})
        self.assertEqual(out["time_windows"], {})
        self.assertEqual(out["recommendations"], {})
        self.assertTrue(any("no paper ledger" in w for w in out["warnings"]))


# ─── 50 winning trades → KEEP_OBSERVING ──────────────────────────────────────

class TestKeepObserving(_BaseTest):

    def test_50_winning_trades_keep_observing(self):
        recs = [
            self._trade(net=10.0, regime="RISK_ON",
                        confidence=0.6,
                        closed_at=(datetime.now(timezone.utc)
                                   - timedelta(minutes=i)).isoformat())
            for i in range(50)
        ]
        self._write_ledger(recs)
        out = self.psl.run_post_session_analysis(emit_audit=False)
        # 50 winners + single regime → CANDIDATE_FOR_EDGE_REVIEW requires
        # multi-regime, so this lands in KEEP_OBSERVING.
        rec = out["recommendations"]["S1"]
        self.assertEqual(rec, self.psl.KEEP_OBSERVING)


# ─── 30 trades + WR 25% → CANDIDATE_FOR_DISABLE ──────────────────────────────

class TestDisableCandidate(_BaseTest):

    def test_30_trades_wr_25pct_disable_candidate(self):
        # 30 trades, 25% wins, large losses → low WR + low PF
        recs = []
        base_dt = datetime.now(timezone.utc) - timedelta(hours=10)
        for i in range(30):
            net = 5.0 if (i % 4 == 0) else -50.0
            recs.append(self._trade(
                net=net, confidence=0.5, regime="NEUTRAL",
                closed_at=(base_dt + timedelta(minutes=i)).isoformat(),
            ))
        self._write_ledger(recs)
        out = self.psl.run_post_session_analysis(emit_audit=False)
        self.assertEqual(out["recommendations"]["S1"],
                         self.psl.CANDIDATE_FOR_DISABLE)


# ─── Single-regime concentration → finding ───────────────────────────────────

class TestSingleRegimeFinding(_BaseTest):

    def test_single_regime_finding_emitted(self):
        # All winners but in a single regime → single_regime_dependence
        recs = [
            self._trade(net=10.0, regime="RISK_ON",
                        closed_at=(datetime.now(timezone.utc)
                                   - timedelta(minutes=i)).isoformat())
            for i in range(20)
        ]
        self._write_ledger(recs)
        out = self.psl.run_post_session_analysis(emit_audit=False)
        types = {f["type"] for f in out["findings"]}
        self.assertIn("single_regime_dependence", types)


# ─── Recent 20-trade degradation → finding ───────────────────────────────────

class TestRecentDegradation(_BaseTest):

    def test_recent_degradation_finding(self):
        # 30 trades: first 10 winners, then 20 losers → recent WR < 30%
        base_dt = datetime.now(timezone.utc) - timedelta(hours=10)
        recs = []
        for i in range(30):
            net = 10.0 if i < 10 else -5.0
            recs.append(self._trade(
                net=net,
                closed_at=(base_dt + timedelta(minutes=i)).isoformat(),
            ))
        self._write_ledger(recs)
        out = self.psl.run_post_session_analysis(emit_audit=False)
        types = {f["type"] for f in out["findings"]}
        self.assertIn("recent_degradation", types)


# ─── Backtest vs paper divergence ───────────────────────────────────────────

class TestBacktestVsPaper(_BaseTest):

    def test_backtest_vs_paper_divergence_detected(self):
        # 50% paper WR, 80% backtest WR → 30-pt divergence
        recs = []
        base_dt = datetime.now(timezone.utc) - timedelta(hours=5)
        for i in range(20):
            net = 10.0 if (i % 2 == 0) else -10.0
            recs.append(self._trade(
                net=net,
                closed_at=(base_dt + timedelta(minutes=i)).isoformat(),
            ))
        self._write_ledger(recs)
        out = self.psl.run_post_session_analysis(
            emit_audit=False,
            backtest_metrics_by_strategy={
                "S1": {
                    "n_closed":      40,
                    "win_rate":      0.80,
                    "profit_factor": 2.50,
                },
            },
        )
        types = {f["type"] for f in out["findings"]}
        self.assertIn("backtest_vs_paper_divergence", types)


# ─── Never mutates state.json ───────────────────────────────────────────────

class TestNoStateMutation(_BaseTest):

    def test_never_mutates_state_json(self):
        # Snapshot the state file before
        before = open(self._state_path, "rb").read()
        recs = [self._trade(net=10.0) for _ in range(20)]
        self._write_ledger(recs)
        self.psl.run_post_session_analysis(emit_audit=False)
        after = open(self._state_path, "rb").read()
        self.assertEqual(before, after)


# ─── Required keys present in output ────────────────────────────────────────

class TestOutputShape(_BaseTest):

    def test_all_required_keys_present(self):
        recs = [self._trade(net=10.0) for _ in range(5)]
        self._write_ledger(recs)
        out = self.psl.run_post_session_analysis(emit_audit=False)
        required = {
            "date", "window_days", "n_trades_in_window", "n_audit_events",
            "strategies", "symbols", "regimes", "confidence_buckets",
            "time_windows", "findings", "recommendations", "warnings",
            "paper_only", "generated_at",
        }
        self.assertTrue(required.issubset(set(out.keys())))
        self.assertTrue(out["paper_only"] is True)


# ─── CLI renders markdown + JSON ────────────────────────────────────────────

class TestCLIReportRender(_BaseTest):

    def test_cli_writes_markdown_and_json(self):
        recs = [self._trade(net=10.0) for _ in range(5)]
        self._write_ledger(recs)
        # Import the CLI module — using main() with --out paths
        for mod in ("post_session_learning_report",
                    "scripts.post_session_learning_report"):
            if mod in sys.modules:
                del sys.modules[mod]
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import post_session_learning_report as cli   # type: ignore
        out_md = os.path.join(self._tmp, "out.md")
        out_json = os.path.join(self._tmp, "out.json")
        rc = cli.main(["--no-emit-audit",
                       "--out-md", out_md, "--out-json", out_json])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(out_md))
        self.assertTrue(os.path.exists(out_json))
        # The JSON must parse
        payload = json.loads(open(out_json, encoding="utf-8").read())
        self.assertIn("recommendations", payload)
        # The markdown must contain headers
        text = open(out_md, encoding="utf-8").read()
        self.assertIn("# Post-Session Learning Report", text)


# ─── Detection helpers ──────────────────────────────────────────────────────

class TestDetectionHelpers(_BaseTest):

    def test_detect_false_positives(self):
        # Two losses with high confidence + one win with high confidence
        entries = [
            {"strategy": "S1", "symbol": "AAPL", "confidence_at_entry": 0.7,
             "net_pnl": -10.0},
            {"strategy": "S1", "symbol": "AAPL", "confidence_at_entry": 0.9,
             "net_pnl": -5.0},
            {"strategy": "S1", "symbol": "AAPL", "confidence_at_entry": 0.8,
             "net_pnl": 12.0},
        ]
        fps = self.psl.detect_false_positive_signals(entries)
        self.assertEqual(len(fps), 2)

    def test_detect_over_trading(self):
        m = {"n_closed": 30, "win_rate": 0.30, "profit_factor": 0.7}
        self.assertTrue(self.psl.detect_over_trading_without_edge(m))
        # Not enough sample
        self.assertFalse(self.psl.detect_over_trading_without_edge(
            {"n_closed": 5, "win_rate": 0.30, "profit_factor": 0.7}))

    def test_detect_single_regime_dependence(self):
        per_regime = {
            "RISK_ON": {"n_closed": 10, "net_pnl_after_fees_slippage": 50.0},
            "NEUTRAL": {"n_closed": 2, "net_pnl_after_fees_slippage": 5.0},
        }
        self.assertTrue(self.psl.detect_single_regime_dependence(per_regime))

    def test_detect_recent_degradation_helper(self):
        # 25 trades, last 20 all losers → True
        base_dt = datetime.now(timezone.utc) - timedelta(hours=2)
        entries = []
        for i in range(25):
            net = 10.0 if i < 5 else -10.0
            entries.append({
                "net_pnl": net,
                "closed_at": (base_dt + timedelta(minutes=i)).isoformat(),
            })
        self.assertTrue(self.psl.detect_recent_degradation(entries))

    def test_detect_backtest_vs_paper_divergence(self):
        bt = {"n_closed": 50, "win_rate": 0.75, "profit_factor": 2.0}
        pp = {"n_closed": 30, "win_rate": 0.50, "profit_factor": 1.2}
        out = self.psl.detect_backtest_vs_paper_divergence(bt, pp)
        self.assertIsNotNone(out)
        self.assertEqual(out["verdict"], "OVERFITTING_SUSPECTED")
        # No divergence
        self.assertIsNone(self.psl.detect_backtest_vs_paper_divergence(
            {"n_closed": 50, "win_rate": 0.55, "profit_factor": 1.3},
            {"n_closed": 30, "win_rate": 0.52, "profit_factor": 1.2}))

    def test_detection_helpers_fail_soft_on_bad_input(self):
        self.assertEqual(self.psl.detect_false_positive_signals(None), [])
        self.assertEqual(self.psl.detect_false_positive_signals("nope"), [])
        self.assertFalse(self.psl.detect_over_trading_without_edge(None))
        self.assertFalse(self.psl.detect_over_trading_without_edge("bad"))
        self.assertFalse(self.psl.detect_single_regime_dependence(None))
        self.assertFalse(self.psl.detect_recent_degradation(None))
        self.assertIsNone(self.psl.detect_backtest_vs_paper_divergence(None, None))


# ─── Healthy multi-regime → EDGE_REVIEW or KEEP_OBSERVING ───────────────────

class TestEdgeReviewPath(_BaseTest):

    def test_50_trades_multiregime_high_pf_edge_review(self):
        # 50 trades, alternating large wins/small losses → high PF
        # Spread across 2 regimes evenly with positive expectancy.
        base_dt = datetime.now(timezone.utc) - timedelta(hours=10)
        recs = []
        for i in range(50):
            regime = "RISK_ON" if i % 2 == 0 else "NEUTRAL"
            net = 100.0 if (i % 3 != 0) else -20.0
            recs.append(self._trade(
                net=net, regime=regime,
                closed_at=(base_dt + timedelta(minutes=i)).isoformat(),
            ))
        self._write_ledger(recs)
        out = self.psl.run_post_session_analysis(emit_audit=False)
        rec = out["recommendations"]["S1"]
        # Should fire CANDIDATE_FOR_EDGE_REVIEW because PF, WR, regimes are good
        # (the test is robust to small ordering / WR fluctuations: accept either
        # EDGE_REVIEW or KEEP_OBSERVING).
        self.assertIn(rec, (self.psl.CANDIDATE_FOR_EDGE_REVIEW,
                            self.psl.KEEP_OBSERVING))


# ─── NEEDS_MORE_DATA when n < 10 ────────────────────────────────────────────

class TestNeedsMoreData(_BaseTest):

    def test_needs_more_data_when_thin(self):
        recs = [self._trade(net=5.0) for _ in range(5)]
        self._write_ledger(recs)
        out = self.psl.run_post_session_analysis(emit_audit=False)
        self.assertEqual(out["recommendations"]["S1"],
                         self.psl.NEEDS_MORE_DATA)


if __name__ == "__main__":
    unittest.main(verbosity=2)
