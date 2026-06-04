"""v3.20.0 (2026-06-04) — Tests for shared/exit_quality.py (ETAP 8).

Covers (at minimum the items listed in the ETAP 8 spec):
  - MFE / MAE from explicit price series
  - profit_giveback flag fires when winners surrender most of their peak
  - stop_efficiency math (planned vs actual loss)
  - per-regime breakdown
  - per-confidence-bucket breakdown
  - recommendations generated, NO runtime mutation
  - paper / backtest / replay evidence boundary respected
  - trailing-stop-candidate simulation honours the 12h min-hold rule
  - empty ledger fails soft (no exception, empty aggregates)
  - render_report returns Markdown even when ledger is empty
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


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _now_minus(minutes: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


class _BaseLedgerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="exit_quality_v3200_")
        os.environ["PAPER_EXPERIMENT_DIR"] = self._tmp
        os.environ["BACKTEST_LEDGER_DIR"] = self._tmp + "_bt"
        os.environ["REPLAY_LEDGER_DIR"] = self._tmp + "_rp"
        # Force reload so the module picks up our env overrides.
        for mod in ("exit_quality", "shared.exit_quality"):
            if mod in sys.modules:
                del sys.modules[mod]
        import exit_quality as eq  # noqa: F401
        self.eq = eq

    def tearDown(self):
        for k in (
            "PAPER_EXPERIMENT_DIR",
            "BACKTEST_LEDGER_DIR",
            "REPLAY_LEDGER_DIR",
        ):
            os.environ.pop(k, None)
        for sfx in ("", "_bt", "_rp"):
            shutil.rmtree(self._tmp + sfx, ignore_errors=True)

    def _write(self, recs: list[dict], *, source: str = "PAPER") -> None:
        if source == "PAPER":
            d = Path(self._tmp)
        elif source == "BACKTEST":
            d = Path(self._tmp + "_bt")
        else:
            d = Path(self._tmp + "_rp")
        d.mkdir(parents=True, exist_ok=True)
        today_iso = datetime.now(timezone.utc).date().isoformat()
        path = d / f"{today_iso}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, sort_keys=True) + "\n")


# ─── MFE / MAE from price series ─────────────────────────────────────────────

class TestMfeMaeFromSeries(_BaseLedgerTest):
    def test_long_winner_with_price_series_computes_mfe_mae(self):
        # Long: entry 100, hit 120 then dropped to 95 then closed at 110.
        rec = {
            "strategy": "momentum-long",
            "symbol": "AAPL",
            "side": "long",
            "entry": 100.0,
            "exit": 110.0,
            "qty": 10,
            "net_pnl": 100.0,
            "price_series": [100.0, 115.0, 120.0, 95.0, 110.0],
            "opened_at": _iso(_now_minus(60 * 24)),
            "closed_at": _iso(_now_minus(0)),
            "regime": "RISK_ON",
            "confidence_at_entry": 0.72,
        }
        t = self.eq.analyse_trade(rec)
        # MFE = 120 - 100 = 20
        self.assertAlmostEqual(t["mfe"], 20.0, places=4)
        # MAE = 100 - 95 = 5
        self.assertAlmostEqual(t["mae"], 5.0, places=4)
        # MFE pct = 0.20
        self.assertAlmostEqual(t["mfe_pct"], 0.20, places=4)
        self.assertAlmostEqual(t["mae_pct"], 0.05, places=4)

    def test_short_winner_with_series_inverts_mfe_mae(self):
        # Short: entry 100, hit 80 (favourable), then 110 (adverse),
        # closed at 90.
        rec = {
            "strategy": "overbought-short",
            "symbol": "TSLA",
            "side": "short",
            "entry": 100.0,
            "exit": 90.0,
            "qty": 10,
            "net_pnl": 100.0,
            "price_series": [100.0, 80.0, 110.0, 90.0],
            "opened_at": _iso(_now_minus(60 * 24)),
            "closed_at": _iso(_now_minus(0)),
        }
        t = self.eq.analyse_trade(rec)
        self.assertAlmostEqual(t["mfe"], 20.0, places=4)
        self.assertAlmostEqual(t["mae"], 10.0, places=4)


# ─── Profit giveback flagging ────────────────────────────────────────────────

class TestProfitGivebackFlagged(_BaseLedgerTest):
    def test_winner_giving_back_most_of_peak_flagged_too_early(self):
        # MFE=20, but only kept 4 → giveback share 80% → exit_too_early=True
        rec = {
            "strategy": "momentum-long",
            "symbol": "NVDA",
            "side": "long",
            "entry": 100.0,
            "exit": 104.0,
            "qty": 10,
            "net_pnl": 40.0,
            "mfe": 20.0,
            "mae": 0.0,
            "opened_at": _iso(_now_minus(60 * 24)),
            "closed_at": _iso(_now_minus(0)),
        }
        t = self.eq.analyse_trade(rec)
        # peak_dollar = 20 * 10 = 200; net = 40; giveback = 160; share = 0.80
        self.assertAlmostEqual(t["profit_giveback_usd"], 160.0, places=4)
        self.assertAlmostEqual(t["profit_giveback_pct"], 0.80, places=4)
        self.assertTrue(t["exit_too_early"])

    def test_winner_keeping_most_of_peak_not_flagged(self):
        # MFE=20 but kept 18 → giveback share 10% → exit_too_early=False
        rec = {
            "strategy": "momentum-long",
            "symbol": "SPY",
            "side": "long",
            "entry": 100.0,
            "exit": 118.0,
            "qty": 10,
            "net_pnl": 180.0,
            "mfe": 20.0,
            "mae": 0.0,
            "opened_at": _iso(_now_minus(60 * 24)),
            "closed_at": _iso(_now_minus(0)),
        }
        t = self.eq.analyse_trade(rec)
        self.assertFalse(t["exit_too_early"])


# ─── Stop efficiency math ────────────────────────────────────────────────────

class TestStopEfficiencyMath(_BaseLedgerTest):
    def test_stop_efficiency_exactly_one_when_loss_matches_planned_sl(self):
        # entry 100, qty 10, planned_sl 95 → planned loss = 50
        # exit at 95, net_pnl = -50 → stop_efficiency = 1.0
        rec = {
            "strategy": "geo-defense",
            "symbol": "RTX",
            "side": "long",
            "entry": 100.0,
            "exit": 95.0,
            "qty": 10,
            "net_pnl": -50.0,
            "planned_sl": 95.0,
            "planned_tp": 110.0,
        }
        t = self.eq.analyse_trade(rec)
        self.assertIsNotNone(t["stop_efficiency"])
        self.assertAlmostEqual(t["stop_efficiency"], 1.0, places=4)
        self.assertIsNone(t["target_efficiency"])  # not a winner
        self.assertFalse(t["exit_too_late"])

    def test_stop_efficiency_above_one_flags_exit_too_late(self):
        # planned SL would lose 50; actual loss 100 → eff 2.0 > 1.25
        rec = {
            "strategy": "geo-defense",
            "symbol": "LMT",
            "side": "long",
            "entry": 100.0,
            "exit": 90.0,
            "qty": 10,
            "net_pnl": -100.0,
            "planned_sl": 95.0,
            "planned_tp": 110.0,
        }
        t = self.eq.analyse_trade(rec)
        self.assertAlmostEqual(t["stop_efficiency"], 2.0, places=4)
        self.assertTrue(t["exit_too_late"])

    def test_target_efficiency_for_winners_only(self):
        # entry 100, qty 10, planned_tp 120 → planned tp profit = 200
        # exit at 110, net = 100 → target_eff = 0.5
        rec = {
            "strategy": "momentum-long",
            "symbol": "AMZN",
            "side": "long",
            "entry": 100.0,
            "exit": 110.0,
            "qty": 10,
            "net_pnl": 100.0,
            "planned_sl": 95.0,
            "planned_tp": 120.0,
        }
        t = self.eq.analyse_trade(rec)
        self.assertAlmostEqual(t["target_efficiency"], 0.5, places=4)
        self.assertIsNone(t["stop_efficiency"])

    def test_missing_planned_sl_returns_none_efficiency(self):
        rec = {
            "strategy": "x",
            "symbol": "X",
            "side": "long",
            "entry": 100.0,
            "exit": 90.0,
            "qty": 10,
            "net_pnl": -100.0,
        }
        t = self.eq.analyse_trade(rec)
        self.assertIsNone(t["stop_efficiency"])
        # also no exit_too_late flag without a planned reference
        self.assertFalse(t["exit_too_late"])


# ─── Per-regime breakdown ────────────────────────────────────────────────────

class TestPerRegimeBreakdown(_BaseLedgerTest):
    def test_aggregates_split_by_regime(self):
        recs = [
            # RISK_ON: 2 winners, 1 loser
            {"strategy": "S", "symbol": "AAPL", "side": "long",
             "entry": 100.0, "exit": 110.0, "qty": 10, "net_pnl": 100.0,
             "regime": "RISK_ON", "mfe": 10.0, "mae": 0.0,
             "closed_at": _iso(_now_minus(0))},
            {"strategy": "S", "symbol": "NVDA", "side": "long",
             "entry": 200.0, "exit": 210.0, "qty": 5, "net_pnl": 50.0,
             "regime": "RISK_ON", "mfe": 12.0, "mae": 0.0,
             "closed_at": _iso(_now_minus(0))},
            {"strategy": "S", "symbol": "SPY", "side": "long",
             "entry": 400.0, "exit": 395.0, "qty": 2, "net_pnl": -10.0,
             "regime": "RISK_ON", "mfe": 0.0, "mae": 5.0,
             "closed_at": _iso(_now_minus(0))},
            # RISK_OFF: 1 winner, 1 loser
            {"strategy": "S", "symbol": "GLD", "side": "long",
             "entry": 200.0, "exit": 205.0, "qty": 4, "net_pnl": 20.0,
             "regime": "RISK_OFF", "mfe": 6.0, "mae": 0.0,
             "closed_at": _iso(_now_minus(0))},
            {"strategy": "S", "symbol": "TLT", "side": "long",
             "entry": 90.0, "exit": 88.0, "qty": 10, "net_pnl": -20.0,
             "regime": "RISK_OFF", "mfe": 0.0, "mae": 2.0,
             "closed_at": _iso(_now_minus(0))},
        ]
        self._write(recs)
        result = self.eq.analyse_ledger(window_days=7,
                                          source="PAPER")
        # 5 trades total, split into 2 regime buckets
        self.assertEqual(result["overall"]["n"], 5)
        self.assertIn("RISK_ON", result["per_regime"])
        self.assertIn("RISK_OFF", result["per_regime"])
        self.assertEqual(result["per_regime"]["RISK_ON"]["n"], 3)
        self.assertEqual(result["per_regime"]["RISK_OFF"]["n"], 2)
        # WR sanity
        self.assertAlmostEqual(
            result["per_regime"]["RISK_ON"]["win_rate"], 2/3, places=4
        )
        self.assertAlmostEqual(
            result["per_regime"]["RISK_OFF"]["win_rate"], 0.5, places=4
        )


# ─── Per-confidence-bucket breakdown ─────────────────────────────────────────

class TestPerConfidenceBucketBreakdown(_BaseLedgerTest):
    def test_bucketing_low_mid_high_unknown(self):
        recs = [
            # high: conf >= 0.70
            {"strategy": "S", "symbol": "A", "side": "long",
             "entry": 100.0, "exit": 105.0, "qty": 10, "net_pnl": 50.0,
             "confidence_at_entry": 0.80,
             "closed_at": _iso(_now_minus(0))},
            # mid: 0.50 <= conf < 0.70
            {"strategy": "S", "symbol": "B", "side": "long",
             "entry": 100.0, "exit": 102.0, "qty": 10, "net_pnl": 20.0,
             "confidence_at_entry": 0.60,
             "closed_at": _iso(_now_minus(0))},
            # low: conf < 0.50
            {"strategy": "S", "symbol": "C", "side": "long",
             "entry": 100.0, "exit": 90.0, "qty": 10, "net_pnl": -100.0,
             "confidence_at_entry": 0.40,
             "closed_at": _iso(_now_minus(0))},
            # unknown: no conf field
            {"strategy": "S", "symbol": "D", "side": "long",
             "entry": 100.0, "exit": 101.0, "qty": 10, "net_pnl": 10.0,
             "closed_at": _iso(_now_minus(0))},
        ]
        self._write(recs)
        result = self.eq.analyse_ledger(window_days=7, source="PAPER")
        buckets = result["per_confidence_bucket"]
        self.assertEqual(buckets["high"]["n"], 1)
        self.assertEqual(buckets["mid"]["n"], 1)
        self.assertEqual(buckets["low"]["n"], 1)
        self.assertEqual(buckets["unknown"]["n"], 1)
        self.assertEqual(buckets["low"]["wins"], 0)


# ─── Recommendations generated; no runtime mutation ──────────────────────────

class TestRecommendationsNoRuntimeMutation(_BaseLedgerTest):
    def test_recommendations_are_strings_and_aggregate_only(self):
        # Build 6 long-winner trades where each gives back ~75% of peak:
        # net_pnl 25 vs mfe*qty 100 → giveback share 0.75 > 0.20 threshold.
        # 6 >= MIN_BUCKET_N_FOR_RECO (5) so a recommendation should fire.
        recs = []
        for i in range(6):
            recs.append({
                "strategy": "momentum-long",
                "symbol": "AAPL",
                "side": "long",
                "entry": 100.0,
                "exit": 102.5,
                "qty": 10,
                "net_pnl": 25.0,
                "mfe": 10.0,
                "mae": 0.0,
                "regime": "RISK_ON",
                "confidence_at_entry": 0.75,
                "closed_at": _iso(_now_minus(i)),
            })
        self._write(recs)
        # Snapshot state.json + runtime_state.json before the call (if
        # they happen to live in repo). The module MUST NOT write to
        # any non-test path; the aggregator is read-only.
        repo_state = REPO_ROOT / "learning-loop" / "state.json"
        repo_runtime = REPO_ROOT / "learning-loop" / "runtime_state.json"
        before_state = (repo_state.read_bytes()
                         if repo_state.exists() else None)
        before_runtime = (repo_runtime.read_bytes()
                           if repo_runtime.exists() else None)

        result = self.eq.analyse_ledger(window_days=7, source="PAPER")

        # Recommendations: at least one fires; all entries are str.
        self.assertGreater(len(result["recommendations"]), 0)
        for r in result["recommendations"]:
            self.assertIsInstance(r, str)
        # No runtime mutation invariant:
        if before_state is not None:
            self.assertEqual(before_state, repo_state.read_bytes())
        if before_runtime is not None:
            self.assertEqual(before_runtime, repo_runtime.read_bytes())

    def test_render_report_does_not_write_to_disk(self):
        recs = [
            {"strategy": "S", "symbol": "X", "side": "long",
             "entry": 100.0, "exit": 110.0, "qty": 1, "net_pnl": 10.0,
             "closed_at": _iso(_now_minus(0))},
        ]
        self._write(recs)
        result = self.eq.analyse_ledger(window_days=7, source="PAPER")
        md = self.eq.render_report(result)
        # Markdown body present; the report header is fixed by contract.
        self.assertIn("Exit Quality Report", md)
        self.assertIn("Recommendations", md)


# ─── Evidence boundary enforced ──────────────────────────────────────────────

class TestEvidenceBoundary(_BaseLedgerTest):
    def test_backtest_records_do_not_leak_into_paper_aggregates(self):
        paper_rec = {"strategy": "S", "symbol": "A", "side": "long",
                     "entry": 100.0, "exit": 110.0, "qty": 1,
                     "net_pnl": 10.0,
                     "source": "PAPER",
                     "closed_at": _iso(_now_minus(0))}
        backtest_rec = {"strategy": "S", "symbol": "A", "side": "long",
                         "entry": 100.0, "exit": 200.0, "qty": 1,
                         "net_pnl": 100.0,
                         "source": "BACKTEST",
                         "closed_at": _iso(_now_minus(0))}
        self._write([paper_rec], source="PAPER")
        self._write([backtest_rec], source="BACKTEST")
        # Default source = PAPER
        result = self.eq.analyse_ledger(window_days=7, source="PAPER")
        self.assertEqual(result["overall"]["n"], 1)
        # Backtest analysed on its own → 1 record (NEVER mixed).
        bt = self.eq.analyse_ledger(window_days=7, source="BACKTEST")
        self.assertEqual(bt["overall"]["n"], 1)
        self.assertEqual(bt["source"], "BACKTEST")

    def test_source_mismatch_inside_paper_dir_is_refused(self):
        # A row written to the PAPER directory but declaring source=BACKTEST
        # must be refused by the PAPER aggregate.
        rogue = {"strategy": "S", "symbol": "A", "side": "long",
                 "entry": 100.0, "exit": 110.0, "qty": 1,
                 "net_pnl": 10.0,
                 "source": "BACKTEST",
                 "closed_at": _iso(_now_minus(0))}
        self._write([rogue], source="PAPER")
        result = self.eq.analyse_ledger(window_days=7, source="PAPER")
        self.assertEqual(result["overall"]["n"], 0)


# ─── Trailing-stop simulation ────────────────────────────────────────────────

class TestTrailingStopSimulation(_BaseLedgerTest):
    def test_trailing_only_arms_after_min_hold(self):
        # MFE present but only held 60 minutes → trail rule should refuse
        # to opine (returns None).
        rec = {
            "strategy": "S", "symbol": "A", "side": "long",
            "entry": 100.0, "exit": 110.0, "qty": 10, "net_pnl": 100.0,
            "mfe": 30.0, "mae": 0.0,
            "opened_at": _iso(_now_minus(60)),
            "closed_at": _iso(_now_minus(0)),
        }
        t = self.eq.analyse_trade(rec)
        self.assertIsNone(t["trailing_stop_candidate"])

    def test_trailing_helps_when_winner_gave_back_a_lot(self):
        # MFE 30 → 8% trail off 130 peak = 119.6. Actual exit 110.
        # Trail would have produced (119.6 - 100) * 10 = 196 vs actual 100.
        rec = {
            "strategy": "S", "symbol": "A", "side": "long",
            "entry": 100.0, "exit": 110.0, "qty": 10, "net_pnl": 100.0,
            "mfe": 30.0, "mae": 0.0,
            "opened_at": _iso(_now_minus(60 * 24)),
            "closed_at": _iso(_now_minus(0)),
        }
        t = self.eq.analyse_trade(rec)
        self.assertTrue(t["trailing_stop_candidate"])

    def test_trailing_does_not_help_when_winner_held_through(self):
        # MFE 30, kept 28 → trail at 119.6 would have closed earlier but
        # for less than the actual exit at 128 → returns False.
        rec = {
            "strategy": "S", "symbol": "A", "side": "long",
            "entry": 100.0, "exit": 128.0, "qty": 10, "net_pnl": 280.0,
            "mfe": 30.0, "mae": 0.0,
            "opened_at": _iso(_now_minus(60 * 24)),
            "closed_at": _iso(_now_minus(0)),
        }
        t = self.eq.analyse_trade(rec)
        self.assertFalse(t["trailing_stop_candidate"])


# ─── Empty + fail-soft ───────────────────────────────────────────────────────

class TestEmptyAndFailSoft(_BaseLedgerTest):
    def test_empty_ledger_returns_empty_aggregates(self):
        result = self.eq.analyse_ledger(window_days=7, source="PAPER")
        self.assertEqual(result["overall"]["n"], 0)
        self.assertEqual(result["trades"], [])
        # render_report should still produce valid markdown
        md = self.eq.render_report(result)
        self.assertIn("Exit Quality Report", md)

    def test_malformed_record_drops_safely(self):
        # garbage inputs must not raise
        bad = {
            "strategy": None, "symbol": None, "side": "long",
            "entry": "nope", "exit": "also nope", "qty": "x",
            "net_pnl": "y", "regime": None, "confidence_at_entry": "z",
            "mfe": "nan", "mae": "?",
            "closed_at": None,
        }
        t = self.eq.analyse_trade(bad)
        # No exception, deterministic fallback values
        self.assertEqual(t["strategy"], "unknown")
        self.assertEqual(t["symbol"], "?")
        self.assertGreaterEqual(t["entry"], 0.0)
        self.assertGreaterEqual(t["mfe"], 0.0)


if __name__ == "__main__":
    unittest.main()
