"""v3.19.0 (2026-06-04) — Tests for shared/evidence_source.py and the
v3.19 extensions to shared/paper_experiment.py (ETAP 3).

Covers:
  - EvidenceSource enum values
  - is_paper_only / is_triage_only correctness on enum + string
  - record_paper_trade defaults to PAPER source
  - record_paper_trade with source=BACKTEST/REPLAY routes to dedicated dirs
  - compute_strategy_metrics(source_filter=PAPER) excludes BACKTEST records
  - load_backtest_ledger / load_replay_ledger read correct paths
  - Backtest entries cannot increment paper n_closed
  - evidence_divergence detects >30% WR difference
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))


# ─── EvidenceSource enum tests ────────────────────────────────────────────────


class TestEvidenceSourceEnum(unittest.TestCase):

    def setUp(self):
        # Always reload to pick up a clean state.
        for k in list(sys.modules):
            if k == "evidence_source" or k.endswith(".evidence_source"):
                del sys.modules[k]
        import evidence_source as es
        self.es = es

    def test_enum_values(self):
        self.assertEqual(self.es.EvidenceSource.BACKTEST.value, "BACKTEST")
        self.assertEqual(self.es.EvidenceSource.REPLAY.value, "REPLAY")
        self.assertEqual(self.es.EvidenceSource.PAPER.value, "PAPER")

    def test_is_paper_only_enum(self):
        self.assertTrue(self.es.is_paper_only(self.es.EvidenceSource.PAPER))
        self.assertFalse(self.es.is_paper_only(self.es.EvidenceSource.BACKTEST))
        self.assertFalse(self.es.is_paper_only(self.es.EvidenceSource.REPLAY))

    def test_is_paper_only_string_and_none(self):
        self.assertTrue(self.es.is_paper_only("PAPER"))
        self.assertTrue(self.es.is_paper_only("paper"))
        self.assertFalse(self.es.is_paper_only("BACKTEST"))
        self.assertFalse(self.es.is_paper_only(None))
        self.assertFalse(self.es.is_paper_only(123))

    def test_is_triage_only(self):
        self.assertTrue(self.es.is_triage_only(self.es.EvidenceSource.BACKTEST))
        self.assertTrue(self.es.is_triage_only(self.es.EvidenceSource.REPLAY))
        self.assertFalse(self.es.is_triage_only(self.es.EvidenceSource.PAPER))
        self.assertTrue(self.es.is_triage_only("backtest"))
        self.assertTrue(self.es.is_triage_only("REPLAY"))
        self.assertFalse(self.es.is_triage_only("paper"))
        self.assertFalse(self.es.is_triage_only(None))

    def test_parse_source_defaults_paper(self):
        self.assertEqual(self.es.parse_source(None), self.es.EvidenceSource.PAPER)
        self.assertEqual(self.es.parse_source("garbage"),
                          self.es.EvidenceSource.PAPER)
        self.assertEqual(self.es.parse_source("BACKTEST"),
                          self.es.EvidenceSource.BACKTEST)


# ─── paper_experiment v3.19 extension tests ──────────────────────────────────


class _BaseLedgerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="ev_src_v3190_")
        self._paper_dir = os.path.join(self._tmp, "paper")
        self._backtest_dir = os.path.join(self._tmp, "backtest")
        self._replay_dir = os.path.join(self._tmp, "replay")
        os.environ["PAPER_EXPERIMENT_DIR"] = self._paper_dir
        os.environ["BACKTEST_LEDGER_DIR"] = self._backtest_dir
        os.environ["REPLAY_LEDGER_DIR"] = self._replay_dir
        for k in list(sys.modules):
            if k == "paper_experiment" or k == "shared.paper_experiment" \
               or k == "evidence_source" or k == "shared.evidence_source":
                del sys.modules[k]
        import paper_experiment as pe
        import evidence_source as es
        self.pe = pe
        self.es = es

    def tearDown(self):
        for k in ("PAPER_EXPERIMENT_DIR",
                   "BACKTEST_LEDGER_DIR",
                   "REPLAY_LEDGER_DIR"):
            os.environ.pop(k, None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _files(self, sub: str):
        return list(Path(os.path.join(self._tmp, sub)).glob("*.jsonl")) \
            if os.path.exists(os.path.join(self._tmp, sub)) else []


class TestRecordPaperTradeDefaultSource(_BaseLedgerTest):

    def test_record_default_source_is_paper(self):
        self.pe.record_paper_trade(
            strategy="momentum-long", symbol="AAPL",
            entry=100.0, exit=105.0, qty=10, side="long",
        )
        paper_files = self._files("paper")
        self.assertEqual(len(paper_files), 1)
        rec = json.loads(paper_files[0].read_text().strip().splitlines()[0])
        self.assertEqual(rec["source"], "PAPER")
        self.assertTrue(rec["paper_only"])

    def test_record_with_source_backtest_routes_to_backtest_dir(self):
        self.pe.record_paper_trade(
            strategy="momentum-long", symbol="AAPL",
            entry=100.0, exit=105.0, qty=10, side="long",
            source=self.es.EvidenceSource.BACKTEST,
        )
        paper_files = self._files("paper")
        back_files = self._files("backtest")
        self.assertEqual(len(paper_files), 0)
        self.assertEqual(len(back_files), 1)
        rec = json.loads(back_files[0].read_text().strip().splitlines()[0])
        self.assertEqual(rec["source"], "BACKTEST")
        self.assertFalse(rec["paper_only"])

    def test_record_with_source_replay_routes_to_replay_dir(self):
        self.pe.record_paper_trade(
            strategy="event-driven", symbol="QQQ",
            entry=400.0, exit=395.0, qty=5, side="long",
            source=self.es.EvidenceSource.REPLAY,
        )
        replay_files = self._files("replay")
        self.assertEqual(len(replay_files), 1)
        rec = json.loads(replay_files[0].read_text().strip().splitlines()[0])
        self.assertEqual(rec["source"], "REPLAY")
        self.assertFalse(rec["paper_only"])


class TestComputeMetricsSourceFilter(_BaseLedgerTest):

    def _write_records(self, dir_path: str, recs: list[dict]) -> None:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        iso = datetime.now(timezone.utc).date().isoformat()
        with open(Path(dir_path) / f"{iso}.jsonl", "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, sort_keys=True) + "\n")

    def _mk(self, source: str, pnl: float) -> dict:
        return {
            "paper_only":         (source == "PAPER"),
            "source":             source,
            "strategy":           "momentum-long",
            "symbol":             "AAPL",
            "side":               "long",
            "entry":              100.0,
            "exit":               110.0 if pnl > 0 else 90.0,
            "qty":                1.0,
            "fees":               0.0,
            "spread_at_entry":    0.0,
            "slippage_at_entry":  0.0,
            "regime":             "RISK_ON",
            "confidence_at_entry": 0.7,
            "gross_pnl":          pnl,
            "cost":               0.0,
            "net_pnl":            pnl,
            "closed_at":          datetime.now(timezone.utc).isoformat(),
        }

    def test_compute_metrics_default_excludes_backtest_records(self):
        # Write 5 paper losers and 5 backtest winners. The paper-default
        # metrics MUST show 5 losses, 0 wins — backtest records cannot
        # leak in.
        self._write_records(self._paper_dir,
                              [self._mk("PAPER", -10.0) for _ in range(5)])
        self._write_records(self._backtest_dir,
                              [self._mk("BACKTEST", +20.0) for _ in range(5)])
        m = self.pe.compute_strategy_metrics("momentum-long", window_days=30)
        self.assertEqual(m["n_closed"], 5)
        self.assertEqual(m["win_rate"], 0.0)
        self.assertEqual(m["source_filter"], "PAPER")

    def test_compute_metrics_with_explicit_backtest_filter(self):
        self._write_records(self._backtest_dir,
                              [self._mk("BACKTEST", +5.0) for _ in range(7)])
        m = self.pe.compute_strategy_metrics(
            "momentum-long", window_days=30,
            source_filter=self.es.EvidenceSource.BACKTEST,
        )
        self.assertEqual(m["n_closed"], 7)
        self.assertEqual(m["source_filter"], "BACKTEST")

    def test_load_backtest_ledger_reads_correct_path(self):
        self._write_records(self._backtest_dir,
                              [self._mk("BACKTEST", +1.0)])
        recs = self.pe.load_backtest_ledger(window_days=30)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["source"], "BACKTEST")

    def test_load_replay_ledger_reads_correct_path(self):
        self._write_records(self._replay_dir,
                              [self._mk("REPLAY", -2.0)])
        recs = self.pe.load_replay_ledger(window_days=30)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["source"], "REPLAY")

    def test_backtest_records_cannot_increment_paper_n_closed(self):
        # Even if a stray BACKTEST-tagged record somehow lands in the
        # PAPER directory, the source-tag filter excludes it.
        self._write_records(
            self._paper_dir,
            [self._mk("BACKTEST", +50.0) for _ in range(3)],
        )
        m = self.pe.compute_strategy_metrics("momentum-long", window_days=30)
        self.assertEqual(m["n_closed"], 0)


# ─── evidence_divergence ─────────────────────────────────────────────────────


class TestEvidenceDivergence(_BaseLedgerTest):

    def _write_records(self, dir_path: str, recs: list[dict]) -> None:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        iso = datetime.now(timezone.utc).date().isoformat()
        with open(Path(dir_path) / f"{iso}.jsonl", "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, sort_keys=True) + "\n")

    def _mk(self, source: str, pnl: float) -> dict:
        return {
            "paper_only":         (source == "PAPER"),
            "source":             source,
            "strategy":           "momentum-long",
            "symbol":             "AAPL",
            "side":               "long",
            "entry":              100.0,
            "exit":               110.0 if pnl > 0 else 90.0,
            "qty":                1.0,
            "fees":               0.0,
            "spread_at_entry":    0.0,
            "slippage_at_entry":  0.0,
            "regime":             "RISK_ON",
            "confidence_at_entry": 0.7,
            "gross_pnl":          pnl,
            "cost":               0.0,
            "net_pnl":            pnl,
            "closed_at":          datetime.now(timezone.utc).isoformat(),
        }

    def test_divergence_detects_large_wr_difference(self):
        # Paper: 10 trades, all losers (WR 0%)
        # Backtest: 10 trades, all winners (WR 100%)
        # → delta 1.00 > 0.30 → overfitting_warning
        self._write_records(self._paper_dir,
                              [self._mk("PAPER", -1.0) for _ in range(10)])
        self._write_records(self._backtest_dir,
                              [self._mk("BACKTEST", +1.0) for _ in range(10)])

        # Re-import the script module after env vars are set so it
        # uses our temp dirs.
        for k in list(sys.modules):
            if k == "evidence_triage_report":
                del sys.modules[k]
        import evidence_triage_report as etr

        rows = etr.evidence_divergence(window_days=30, threshold=0.30)
        # Find momentum-long row
        target = next(r for r in rows if r["strategy"] == "momentum-long")
        self.assertTrue(target["overfitting"])
        self.assertAlmostEqual(target["paper_wr"], 0.0)
        self.assertAlmostEqual(target["backtest_wr"], 1.0)
        self.assertAlmostEqual(abs(target["delta_paper_backtest"]), 1.0)

    def test_divergence_no_flag_when_small_difference(self):
        # Paper: 5 wins, 5 losses (WR 50%)
        # Backtest: 6 wins, 4 losses (WR 60%)
        # delta 0.10 < threshold 0.30 → no flag
        self._write_records(self._paper_dir,
                              [self._mk("PAPER", +1.0) for _ in range(5)] +
                              [self._mk("PAPER", -1.0) for _ in range(5)])
        self._write_records(self._backtest_dir,
                              [self._mk("BACKTEST", +1.0) for _ in range(6)] +
                              [self._mk("BACKTEST", -1.0) for _ in range(4)])
        for k in list(sys.modules):
            if k == "evidence_triage_report":
                del sys.modules[k]
        import evidence_triage_report as etr
        rows = etr.evidence_divergence(window_days=30, threshold=0.30)
        target = next(r for r in rows if r["strategy"] == "momentum-long")
        self.assertFalse(target["overfitting"])


if __name__ == "__main__":
    unittest.main()
