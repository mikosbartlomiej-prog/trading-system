"""v3.18.0 (2026-06-04) — Tests for shared/paper_experiment.py.

Covers:
  - record_paper_trade JSONL append
  - compute_strategy_metrics determinism + fail-soft
  - aggregate metric correctness on synthetic ledgers
  - per_regime / per_confidence_bucket / per_symbol / per_time_window breakdowns
  - net_pnl_after_fees_slippage deduction
  - max_drawdown computation
  - longest_losing_streak
  - generate_edge_evidence_report renders valid markdown
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


class _BaseLedgerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="paper_exp_v3180_")
        os.environ["PAPER_EXPERIMENT_DIR"] = self._tmp
        # Reload module to pick up env
        if "paper_experiment" in sys.modules:
            del sys.modules["paper_experiment"]
        if "shared.paper_experiment" in sys.modules:
            del sys.modules["shared.paper_experiment"]
        import paper_experiment as pe   # noqa: F401
        self.pe = pe

    def tearDown(self):
        os.environ.pop("PAPER_EXPERIMENT_DIR", None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_synthetic(self, recs: list[dict]) -> None:
        """Write trades directly to today's JSONL (skipping record_paper_trade
        so we can pin closed_at + side + costs without re-parsing)."""
        d = Path(self._tmp)
        d.mkdir(parents=True, exist_ok=True)
        today_iso = datetime.now(timezone.utc).date().isoformat()
        path = d / f"{today_iso}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, sort_keys=True) + "\n")


# ─── record_paper_trade ──────────────────────────────────────────────────────

class TestRecordPaperTrade(_BaseLedgerTest):

    def test_appends_to_jsonl(self):
        self.pe.record_paper_trade(
            strategy="momentum-long",
            symbol="AAPL",
            entry=100.0,
            exit=105.0,
            qty=10,
            side="long",
            fees=1.0,
            spread_at_entry=0.5,
            slippage_at_entry=0.5,
            regime="RISK_ON",
            confidence_at_entry=0.72,
        )
        files = list(Path(self._tmp).glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        line = files[0].read_text().strip().splitlines()[0]
        rec = json.loads(line)
        self.assertEqual(rec["strategy"], "momentum-long")
        self.assertEqual(rec["symbol"], "AAPL")
        self.assertEqual(rec["paper_only"], True)
        # gross = (105 - 100) * 10 = 50
        self.assertAlmostEqual(rec["gross_pnl"], 50.0)
        # cost = 1 + 0.5 + 0.5 = 2
        self.assertAlmostEqual(rec["cost"], 2.0)
        # net = 50 - 2 = 48
        self.assertAlmostEqual(rec["net_pnl"], 48.0)

    def test_short_trade_pnl(self):
        self.pe.record_paper_trade(
            strategy="overbought-short",
            symbol="MSTR",
            entry=200.0,
            exit=180.0,
            qty=5,
            side="short",
            fees=0.0,
        )
        files = list(Path(self._tmp).glob("*.jsonl"))
        rec = json.loads(files[0].read_text().strip())
        # Short: (entry - exit) * qty = (200 - 180) * 5 = 100
        self.assertAlmostEqual(rec["gross_pnl"], 100.0)
        self.assertAlmostEqual(rec["net_pnl"], 100.0)

    def test_record_never_raises_on_bad_inputs(self):
        # Should NOT raise; should clamp / drop.
        self.pe.record_paper_trade(
            strategy=None,                        # type: ignore
            symbol=None,                          # type: ignore
            entry="not-a-number",                 # type: ignore
            exit=None,                            # type: ignore
            qty="bad",                            # type: ignore
            side=42,                              # type: ignore
        )
        files = list(Path(self._tmp).glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        rec = json.loads(files[0].read_text().strip())
        self.assertEqual(rec["strategy"], "unknown")
        self.assertEqual(rec["entry"], 0.0)
        self.assertEqual(rec["qty"], 0.0)


# ─── compute_strategy_metrics ────────────────────────────────────────────────

class TestComputeMetrics(_BaseLedgerTest):

    def test_unknown_strategy_returns_zeros(self):
        m = self.pe.compute_strategy_metrics("does-not-exist", window_days=180)
        self.assertEqual(m["n_closed"], 0)
        self.assertEqual(m["win_rate"], 0.0)
        self.assertEqual(m["profit_factor"], 0.0)
        self.assertEqual(m["expectancy"], 0.0)

    def test_fail_soft_on_missing_dir(self):
        # Point at a non-existent directory.
        os.environ["PAPER_EXPERIMENT_DIR"] = os.path.join(self._tmp, "nope")
        if "paper_experiment" in sys.modules:
            del sys.modules["paper_experiment"]
        import paper_experiment as pe
        m = pe.compute_strategy_metrics("anything")
        self.assertEqual(m["n_closed"], 0)

    def _make_recs(self, n_winners: int, n_losers: int,
                   win_amt: float = 100.0, loss_amt: float = 50.0,
                   strategy: str = "S",
                   symbol: str = "X",
                   regime: str = "RISK_ON",
                   conf: float = 0.7) -> list[dict]:
        now = datetime.now(timezone.utc)
        recs: list[dict] = []
        t = 0
        for _ in range(n_winners):
            recs.append({
                "paper_only": True,
                "strategy":   strategy,
                "symbol":     symbol,
                "side":       "long",
                "entry":      100.0,
                "exit":       100.0 + win_amt,
                "qty":        1.0,
                "gross_pnl":  win_amt,
                "cost":       0.0,
                "net_pnl":    win_amt,
                "regime":     regime,
                "confidence_at_entry": conf,
                "closed_at":  (now + timedelta(seconds=t)).isoformat(),
            })
            t += 1
        for _ in range(n_losers):
            recs.append({
                "paper_only": True,
                "strategy":   strategy,
                "symbol":     symbol,
                "side":       "long",
                "entry":      100.0,
                "exit":       100.0 - loss_amt,
                "qty":        1.0,
                "gross_pnl":  -loss_amt,
                "cost":       0.0,
                "net_pnl":    -loss_amt,
                "regime":     regime,
                "confidence_at_entry": conf,
                "closed_at":  (now + timedelta(seconds=t)).isoformat(),
            })
            t += 1
        return recs

    def test_win_rate_profit_factor_expectancy_50_trade_ledger(self):
        # 30 winners @ +100, 20 losers @ -50 → WR 60%, PF=(30*100)/(20*50)=3
        recs = self._make_recs(n_winners=30, n_losers=20,
                                win_amt=100.0, loss_amt=50.0)
        self._write_synthetic(recs)
        m = self.pe.compute_strategy_metrics("S")
        self.assertEqual(m["n_closed"], 50)
        self.assertAlmostEqual(m["win_rate"], 0.6, places=4)
        self.assertAlmostEqual(m["profit_factor"], 3.0, places=2)
        # expectancy = 0.6*100 + 0.4*(-50) = 60 - 20 = 40
        self.assertAlmostEqual(m["expectancy"], 40.0, places=4)
        self.assertAlmostEqual(m["avg_win"], 100.0, places=4)
        self.assertAlmostEqual(m["avg_loss"], -50.0, places=4)
        self.assertAlmostEqual(m["net_pnl_after_fees_slippage"],
                                30*100 - 20*50, places=4)

    def test_per_regime_breakdown(self):
        recs = self._make_recs(10, 5, regime="RISK_ON") + \
               self._make_recs(5, 5, regime="RISK_OFF")
        self._write_synthetic(recs)
        m = self.pe.compute_strategy_metrics("S")
        self.assertIn("RISK_ON", m["per_regime"])
        self.assertIn("RISK_OFF", m["per_regime"])
        self.assertEqual(m["per_regime"]["RISK_ON"]["n_closed"], 15)
        self.assertEqual(m["per_regime"]["RISK_OFF"]["n_closed"], 10)

    def test_per_confidence_bucket_breakdown(self):
        recs = self._make_recs(3, 2, conf=0.40) + \
               self._make_recs(4, 1, conf=0.60) + \
               self._make_recs(6, 0, conf=0.85)
        self._write_synthetic(recs)
        m = self.pe.compute_strategy_metrics("S")
        self.assertIn("low",  m["per_confidence_bucket"])
        self.assertIn("mid",  m["per_confidence_bucket"])
        self.assertIn("high", m["per_confidence_bucket"])
        self.assertEqual(m["per_confidence_bucket"]["low"]["n_closed"],  5)
        self.assertEqual(m["per_confidence_bucket"]["mid"]["n_closed"],  5)
        self.assertEqual(m["per_confidence_bucket"]["high"]["n_closed"], 6)

    def test_per_symbol_breakdown(self):
        recs = self._make_recs(5, 5, symbol="AAPL") + \
               self._make_recs(2, 8, symbol="MSTR")
        self._write_synthetic(recs)
        m = self.pe.compute_strategy_metrics("S")
        self.assertEqual(m["per_symbol"]["AAPL"]["n_closed"], 10)
        self.assertEqual(m["per_symbol"]["MSTR"]["n_closed"], 10)

    def test_net_pnl_deducts_costs(self):
        # 10 winners @ +100 with cost 5 each → gross 1000, costs 50, net 950
        now = datetime.now(timezone.utc)
        recs = []
        for i in range(10):
            recs.append({
                "paper_only": True,
                "strategy":   "S",
                "symbol":     "X",
                "side":       "long",
                "entry":      100.0,
                "exit":       200.0,
                "qty":        1.0,
                "gross_pnl":  100.0,
                "cost":       5.0,
                "net_pnl":    95.0,
                "closed_at":  (now + timedelta(seconds=i)).isoformat(),
            })
        self._write_synthetic(recs)
        m = self.pe.compute_strategy_metrics("S")
        self.assertAlmostEqual(m["gross_pnl"], 1000.0)
        self.assertAlmostEqual(m["total_costs"], 50.0)
        self.assertAlmostEqual(m["net_pnl_after_fees_slippage"], 950.0)

    def test_max_drawdown_computation(self):
        # +100 +100 +100 -200 -200 → cumulative 100,200,300,100,-100
        # peak 300, trough -100 → drawdown from 300 to -100 = 400/300=1.33,
        # but our metric is (peak - cumulative)/peak when peak > 0
        # at -100: (300 - (-100))/300 = 1.333…
        now = datetime.now(timezone.utc)
        nets = [100, 100, 100, -200, -200]
        recs = []
        for i, p in enumerate(nets):
            recs.append({
                "paper_only": True, "strategy": "S", "symbol": "X",
                "side": "long", "entry": 100.0, "exit": 100.0 + p,
                "qty": 1.0,
                "gross_pnl": float(p),
                "cost": 0.0, "net_pnl": float(p),
                "closed_at": (now + timedelta(seconds=i)).isoformat(),
            })
        self._write_synthetic(recs)
        m = self.pe.compute_strategy_metrics("S")
        # Peak 300, trough -100, max_dd > 1.0 (cap allowed; we just check
        # that it's computed and > 1.3 to confirm formula path used)
        self.assertGreater(m["max_drawdown"], 1.3)

    def test_longest_losing_streak(self):
        # +1 -1 -1 -1 +1 -1 -1 → longest streak = 3
        now = datetime.now(timezone.utc)
        seq = [1, -1, -1, -1, 1, -1, -1]
        recs = []
        for i, p in enumerate(seq):
            recs.append({
                "paper_only": True, "strategy": "S", "symbol": "X",
                "side": "long", "entry": 100.0, "exit": 100.0 + p,
                "qty": 1.0,
                "gross_pnl": float(p),
                "cost": 0.0, "net_pnl": float(p),
                "closed_at": (now + timedelta(seconds=i)).isoformat(),
            })
        self._write_synthetic(recs)
        m = self.pe.compute_strategy_metrics("S")
        self.assertEqual(m["longest_losing_streak"], 3)

    def test_last_20_win_rate(self):
        # 20 trades, all losses → last_20_wr = 0.0
        now = datetime.now(timezone.utc)
        recs = []
        for i in range(20):
            recs.append({
                "paper_only": True, "strategy": "S", "symbol": "X",
                "side": "long", "entry": 100.0, "exit": 90.0,
                "qty": 1.0, "gross_pnl": -10.0, "cost": 0.0,
                "net_pnl": -10.0,
                "closed_at": (now + timedelta(seconds=i)).isoformat(),
            })
        self._write_synthetic(recs)
        m = self.pe.compute_strategy_metrics("S")
        self.assertEqual(m["last_20_win_rate"], 0.0)


# ─── generate_edge_evidence_report ───────────────────────────────────────────

class TestEdgeEvidenceReport(_BaseLedgerTest):

    def test_writes_valid_markdown(self):
        # Empty ledger — report should still render.
        md = self.pe.generate_edge_evidence_report(window_days=180)
        self.assertIn("# Edge Evidence Report (paper trading)", md)
        self.assertIn("Paper trading only", md)
        self.assertIn("OBSERVE_ONLY", md)  # statuses legend
        self.assertNotIn("LIVE_APPROVED", md)
        self.assertNotIn("ready for live", md.lower())

    def test_report_written_to_path(self):
        out_path = Path(self._tmp) / "report.md"
        self.pe.generate_edge_evidence_report(
            out_path=str(out_path), window_days=180)
        self.assertTrue(out_path.exists())
        text = out_path.read_text()
        self.assertIn("Edge Evidence Report", text)

    def test_report_includes_strategy_row_when_metrics_present(self):
        # Sized so PAPER_ENABLED kicks in (n=30, PF=1)
        now = datetime.now(timezone.utc)
        recs = []
        # 30 trades, 50% WR, +/-50 PnL → PF=1.0, net=0
        for i in range(15):
            recs.append({
                "paper_only": True, "strategy": "momentum-long",
                "symbol": "AAPL",
                "side": "long", "entry": 100.0, "exit": 150.0,
                "qty": 1.0, "gross_pnl": 50.0,
                "cost": 0.0, "net_pnl": 50.0,
                "regime": "RISK_ON",
                "confidence_at_entry": 0.70,
                "closed_at": (now + timedelta(seconds=i)).isoformat(),
            })
        for i in range(15, 30):
            recs.append({
                "paper_only": True, "strategy": "momentum-long",
                "symbol": "AAPL",
                "side": "long", "entry": 100.0, "exit": 50.0,
                "qty": 1.0, "gross_pnl": -50.0,
                "cost": 0.0, "net_pnl": -50.0,
                "regime": "RISK_ON",
                "confidence_at_entry": 0.70,
                "closed_at": (now + timedelta(seconds=i)).isoformat(),
            })
        self._write_synthetic(recs)
        md = self.pe.generate_edge_evidence_report(window_days=180)
        self.assertIn("momentum-long", md)
        # 30 trades in window — should show up in the n_closed column
        self.assertRegex(md, r"momentum-long.*\|\s*30\s*\|")


# ─── Determinism + Bonus ─────────────────────────────────────────────────────

class TestDeterminism(_BaseLedgerTest):

    def test_metrics_deterministic_across_invocations(self):
        now = datetime.now(timezone.utc)
        recs = []
        for i in range(20):
            recs.append({
                "paper_only": True, "strategy": "S", "symbol": "X",
                "side": "long", "entry": 100.0,
                "exit": 100.0 + (10 if i % 2 == 0 else -7),
                "qty": 1.0,
                "gross_pnl": (10.0 if i % 2 == 0 else -7.0),
                "cost": 0.0,
                "net_pnl": (10.0 if i % 2 == 0 else -7.0),
                "closed_at": (now + timedelta(seconds=i)).isoformat(),
            })
        self._write_synthetic(recs)
        m1 = self.pe.compute_strategy_metrics("S")
        m2 = self.pe.compute_strategy_metrics("S")
        # Drop per_regime / per_symbol etc. which may have dict iteration
        # noise on Py3.6 (not 3.7+, but defensive); compare leaf fields.
        for key in ("n_closed", "win_rate", "profit_factor", "expectancy",
                    "avg_win", "avg_loss", "max_drawdown",
                    "longest_losing_streak",
                    "net_pnl_after_fees_slippage", "gross_pnl",
                    "total_costs", "last_20_win_rate"):
            self.assertEqual(m1[key], m2[key], f"key {key} non-deterministic")


if __name__ == "__main__":
    unittest.main()
