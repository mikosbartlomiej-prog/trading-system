"""v3.21.0 (2026-06-04) — Tests for shared/evidence_throughput.py.

The Evidence Throughput Monitor is the read-only aggregator that
reports per-strategy growth across opportunity / shadow / paper /
counterfactual evidence streams. These tests cover the spec's required
statuses + the do-not-cross contract (no real orders, no mixing of
evidence sources, fail-soft on missing files).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _Base(unittest.TestCase):
    """Re-import the module each test so env overrides take effect."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.opportunity = self.root / "opp"
        self.shadow = self.root / "shadow"
        self.paper = self.root / "paper"
        self.counterfactual = self.root / "cf"
        for d in (self.opportunity, self.shadow, self.paper,
                  self.counterfactual):
            d.mkdir(parents=True, exist_ok=True)

        os.environ["OPPORTUNITY_LEDGER_DIR"] = str(self.opportunity)
        os.environ["SHADOW_LEDGER_DIR"] = str(self.shadow)
        os.environ["PAPER_EXPERIMENT_DIR"] = str(self.paper)
        os.environ["AUDIT_TRADING_DIR"] = str(self.counterfactual)

        for k in list(sys.modules):
            if k.endswith(".evidence_throughput") \
               or k == "evidence_throughput":
                del sys.modules[k]
        import evidence_throughput as mod
        self.m = mod

    def tearDown(self):
        for k in (
            "OPPORTUNITY_LEDGER_DIR",
            "SHADOW_LEDGER_DIR",
            "PAPER_EXPERIMENT_DIR",
            "AUDIT_TRADING_DIR",
        ):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    # ─── JSONL helpers ────────────────────────────────────────────────

    def _write_jsonl(self, directory: Path, date: str,
                     records: list[dict]) -> None:
        path = directory / f"{date}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, default=str, sort_keys=True) + "\n")

    def _today_iso(self, now: datetime, days_back: int = 0) -> str:
        return (now - timedelta(days=days_back)).date().isoformat()


class TestEmptyLedgers(_Base):
    """All directories empty -> NO_EVIDENCE_FLOW + safe report."""

    def test_empty_directories_return_empty_report(self):
        now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
        rep = self.m.compute_throughput(now=now, days_window=14)
        self.assertEqual(len(rep.strategies), 0)
        self.assertEqual(rep.raw_signal_total, 0)
        self.assertEqual(rep.shadow_total, 0)
        self.assertEqual(rep.broker_total, 0)
        self.assertEqual(rep.counterfactual_total, 0)

    def test_classify_empty_strategy_returns_no_evidence_flow(self):
        s = self.m.StrategyThroughput(strategy="ghost")
        s.finalize(
            now=datetime.now(timezone.utc),
            window_days=14,
        )
        self.assertEqual(s.status, self.m.NO_EVIDENCE_FLOW)


class TestTooSlowToReachN50(_Base):
    """Low broker growth rate -> TOO_SLOW_TO_REACH_N50."""

    def test_one_broker_sample_in_14d_is_too_slow(self):
        now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
        date = self._today_iso(now, 1)
        # One paper fill in 14 days -> growth ~ 0.07 / day, ETA ~ 700d.
        self._write_jsonl(self.paper, date, [{
            "strategy": "slow-strat",
            "symbol": "AAPL",
            "regime": "RISK_ON",
            "evidence_source": "PAPER",
            "net_pnl": 12.0,
            "closed_at": f"{date}T15:30:00+00:00",
            "confidence_score": 0.72,
        }])
        # Opportunity ledger entries too, so it isn't classified as
        # "needs more symbols / regimes" before TOO_SLOW kicks in.
        opp_records = []
        for i in range(2):
            opp_records.append({
                "strategy": "slow-strat",
                "symbol": "AAPL" if i % 2 == 0 else "MSFT",
                "market_regime": "RISK_ON" if i == 0 else "NEUTRAL",
                "confidence_score": 0.7,
                "risk_decision": "ALLOW",
                "timestamp": f"{date}T10:00:00+00:00",
            })
        self._write_jsonl(self.opportunity, date, opp_records)

        rep = self.m.compute_throughput(now=now, days_window=14)
        s = rep.strategies["slow-strat"]
        self.assertEqual(s.broker_paper_fills, 1)
        self.assertEqual(s.status, self.m.TOO_SLOW_TO_REACH_N50)


class TestHealthyShadowFlow(_Base):
    """Good shadow growth across symbols + regimes -> HEALTHY_SHADOW_FLOW."""

    def test_shadow_growth_one_per_day_with_diverse_symbols(self):
        now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
        # 14 shadow fills (1/day) across 3 symbols + 2 regimes.
        for i in range(14):
            date = self._today_iso(now, i)
            symbol = ["AAPL", "MSFT", "GOOGL"][i % 3]
            regime = "RISK_ON" if i % 2 == 0 else "NEUTRAL"
            self._write_jsonl(self.shadow, date, [{
                "strategy": "shadow-good",
                "symbol": symbol,
                "market_regime": regime,
                "confidence_score": 0.7,
                "ts": f"{date}T15:30:00+00:00",
            }])

        rep = self.m.compute_throughput(now=now, days_window=14)
        s = rep.strategies["shadow-good"]
        self.assertEqual(s.shadow_paper_fills, 14)
        self.assertGreaterEqual(s.shadow_growth_rate, 1.0)
        self.assertGreaterEqual(s.symbol_coverage, 3)
        self.assertGreaterEqual(s.regime_coverage, 2)
        self.assertEqual(s.status, self.m.HEALTHY_SHADOW_FLOW)


class TestNeedsMoreRegimeCoverage(_Base):
    """Shadow fills but only one regime -> NEEDS_MORE_REGIME_COVERAGE."""

    def test_one_regime_blocks_healthy_status(self):
        now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
        date = self._today_iso(now)
        # 6 shadow fills across 2 symbols but always RISK_ON.
        for i in range(6):
            symbol = "AAPL" if i % 2 == 0 else "MSFT"
            self._write_jsonl(self.shadow, date, [{
                "strategy": "one-regime",
                "symbol": symbol,
                "market_regime": "RISK_ON",
                "confidence_score": 0.7,
                "ts": f"{date}T13:30:00+00:00",
            }])

        rep = self.m.compute_throughput(now=now, days_window=14)
        s = rep.strategies["one-regime"]
        self.assertEqual(s.regime_coverage, 1)
        self.assertGreaterEqual(s.symbol_coverage, 2)
        self.assertEqual(s.status, self.m.NEEDS_MORE_REGIME_COVERAGE)


class TestNeedsMoreSymbols(_Base):
    """Shadow fills but only one symbol across multiple regimes."""

    def test_one_symbol_blocks_healthy_status(self):
        now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
        date = self._today_iso(now)
        for i in range(8):
            regime = "RISK_ON" if i % 2 == 0 else "NEUTRAL"
            self._write_jsonl(self.shadow, date, [{
                "strategy": "one-symbol",
                "symbol": "AAPL",
                "market_regime": regime,
                "confidence_score": 0.7,
                "ts": f"{date}T13:30:00+00:00",
            }])

        rep = self.m.compute_throughput(now=now, days_window=14)
        s = rep.strategies["one-symbol"]
        self.assertEqual(s.symbol_coverage, 1)
        self.assertGreaterEqual(s.regime_coverage, 2)
        self.assertEqual(s.status, self.m.NEEDS_MORE_SYMBOLS)


class TestNoMixingOfEvidenceSources(_Base):
    """Counterfactual records must not roll up into broker totals."""

    def test_counterfactual_audit_does_not_inflate_broker_count(self):
        now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
        date = self._today_iso(now)
        # 20 counterfactual outcomes in the audit JSONL stream.
        cf_records = []
        for i in range(20):
            cf_records.append({
                "decision": "V320_COUNTERFACTUAL_COMPUTED",
                "event_type": "V320_COUNTERFACTUAL_COMPUTED",
                "actor": "counterfactual_outcomes",
                "ts": f"{date}T10:00:0{i % 10}+00:00",
                "payload": {
                    "signal_id": f"cf-{i}",
                    "strategy": "cf-only",
                    "symbol": "AAPL",
                    "outcome": "PROFITABLE",
                },
            })
        # Plus an unrelated audit line that must be ignored.
        cf_records.append({
            "decision": "V320_OPPORTUNITY_RECORDED",
            "ts": f"{date}T11:00:00+00:00",
            "payload": {"strategy": "cf-only"},
        })
        self._write_jsonl(self.counterfactual, date, cf_records)

        rep = self.m.compute_throughput(now=now, days_window=14)
        s = rep.strategies["cf-only"]
        self.assertEqual(s.counterfactual_outcomes, 20)
        # Crucial invariant: counterfactual outcomes never count as
        # broker_paper fills.
        self.assertEqual(s.broker_paper_fills, 0)
        self.assertEqual(rep.broker_total, 0)
        self.assertEqual(rep.counterfactual_total, 20)


class TestReadOnlyContract(_Base):
    """The module must NEVER write back to the source ledgers."""

    def test_compute_throughput_does_not_modify_input_files(self):
        now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
        date = self._today_iso(now)
        path = self.opportunity / f"{date}.jsonl"
        self._write_jsonl(self.opportunity, date, [{
            "strategy": "ro-strat",
            "symbol": "AAPL",
            "market_regime": "RISK_ON",
            "risk_decision": "ALLOW",
            "confidence_score": 0.7,
            "timestamp": f"{date}T10:00:00+00:00",
        }])
        before = path.read_text(encoding="utf-8")
        self.m.compute_throughput(now=now, days_window=14)
        after = path.read_text(encoding="utf-8")
        self.assertEqual(before, after)


class TestFailSoftOnMissingFiles(_Base):
    """Missing input file must NEVER raise."""

    def test_missing_directories_return_empty_report(self):
        # Point environment at directories that do not exist.
        os.environ["OPPORTUNITY_LEDGER_DIR"] = str(self.root / "no-such-opp")
        os.environ["SHADOW_LEDGER_DIR"] = str(self.root / "no-such-shadow")
        os.environ["PAPER_EXPERIMENT_DIR"] = str(self.root / "no-such-paper")
        os.environ["AUDIT_TRADING_DIR"] = str(self.root / "no-such-cf")
        for k in list(sys.modules):
            if k.endswith(".evidence_throughput") \
               or k == "evidence_throughput":
                del sys.modules[k]
        import evidence_throughput as mod
        rep = mod.compute_throughput(
            now=datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc),
            days_window=14,
        )
        self.assertEqual(rep.raw_signal_total, 0)


if __name__ == "__main__":
    unittest.main()
