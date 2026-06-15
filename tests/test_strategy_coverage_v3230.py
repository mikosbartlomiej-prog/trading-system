"""v3.23.0 — tests for ``scripts/build_strategy_coverage_report.py``."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_strategy_coverage_report as bsc  # type: ignore  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def _seed(repo_root: Path, *, rows: list[dict],
            state_strategies: dict, as_of: datetime) -> None:
    ledger_dir = repo_root / "learning-loop" / "opportunity_ledger"
    _write_jsonl(
        ledger_dir / f"{as_of.date().isoformat()}.jsonl", rows)
    _write_json(
        repo_root / "learning-loop" / "state.json",
        {"strategies": state_strategies})


class TestBuildStrategyCoverageReport(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.as_of = datetime(2026, 6, 15, 12, 0,
                              tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_zombie_when_only_in_state(self):
        # Strategy only in state, not in registry, no ledger activity.
        with mock.patch.object(bsc, "_load_registry", return_value={}):
            _seed(self.repo,
                   rows=[],
                   state_strategies={
                       "alloc-exit": {"enabled": True,
                                       "trades_lifetime": 0}},
                   as_of=self.as_of)
            cov = bsc.build_coverage(
                as_of=self.as_of, repo_root=self.repo)
        # registry empty + in state -> ZOMBIE
        rows = {r["strategy"]: r for r in cov["strategies"]}
        self.assertEqual(rows["alloc-exit"]["status"], "ZOMBIE")

    def test_observe_only_for_registry_observe_strategies(self):
        with mock.patch.object(bsc, "_load_registry", return_value={
            "geo-defense": {"asset_class": "us_equity",
                             "signal_at": None,
                             "observe_only": True},
            "options-momentum": {"asset_class": "us_option",
                                  "signal_at": None,
                                  "observe_only": True},
        }):
            _seed(self.repo,
                   rows=[],
                   state_strategies={
                       "geo-defense": {"enabled": True,
                                        "trades_lifetime": 0},
                       "options-momentum": {"enabled": True,
                                              "trades_lifetime": 0},
                   },
                   as_of=self.as_of)
            cov = bsc.build_coverage(
                as_of=self.as_of, repo_root=self.repo)
        rows = {r["strategy"]: r for r in cov["strategies"]}
        self.assertEqual(rows["geo-defense"]["status"], "OBSERVE_ONLY")
        self.assertEqual(
            rows["options-momentum"]["status"], "OBSERVE_ONLY")

    def test_active_when_signals_present(self):
        with mock.patch.object(bsc, "_load_registry", return_value={
            "crypto-momentum": {"asset_class": "crypto",
                                 "signal_at": lambda i, b: None},
        }):
            _seed(self.repo,
                   rows=[
                       {"strategy": "crypto-momentum",
                        "symbol": "BTC/USD",
                        "risk_decision": "DETECTED",
                        "confidence_score": 0.7},
                   ],
                   state_strategies={
                       "crypto-momentum": {"enabled": True,
                                            "trades_lifetime": 50}},
                   as_of=self.as_of)
            cov = bsc.build_coverage(
                as_of=self.as_of, repo_root=self.repo)
        rows = {r["strategy"]: r for r in cov["strategies"]}
        self.assertEqual(rows["crypto-momentum"]["status"], "ACTIVE")
        self.assertEqual(
            rows["crypto-momentum"]["signals_count_7d"], 1)
        self.assertEqual(
            rows["crypto-momentum"]["shadow_eligible_7d"], 1)

    def test_dormant_when_only_no_signal_and_rejects(self):
        with mock.patch.object(bsc, "_load_registry", return_value={
            "crypto-momentum": {"asset_class": "crypto",
                                 "signal_at": lambda i, b: None},
        }):
            _seed(self.repo,
                   rows=[
                       {"strategy": "crypto-momentum",
                        "symbol": "BTC/USD",
                        "risk_decision": "NO_SIGNAL"},
                       {"strategy": "crypto-momentum",
                        "symbol": "BTC/USD",
                        "risk_decision": "REJECT"},
                   ],
                   state_strategies={
                       "crypto-momentum": {"enabled": True,
                                            "trades_lifetime": 50}},
                   as_of=self.as_of)
            cov = bsc.build_coverage(
                as_of=self.as_of, repo_root=self.repo)
        rows = {r["strategy"]: r for r in cov["strategies"]}
        self.assertEqual(rows["crypto-momentum"]["status"], "DORMANT")

    def test_paid_data_flag_for_options_momentum(self):
        with mock.patch.object(bsc, "_load_registry", return_value={
            "options-momentum": {"asset_class": "us_option",
                                  "signal_at": None,
                                  "observe_only": True},
        }):
            _seed(self.repo, rows=[],
                   state_strategies={
                       "options-momentum": {"enabled": True,
                                              "trades_lifetime": 0}},
                   as_of=self.as_of)
            cov = bsc.build_coverage(
                as_of=self.as_of, repo_root=self.repo)
        rows = {r["strategy"]: r for r in cov["strategies"]}
        self.assertTrue(rows["options-momentum"]["requires_paid_data"])

    def test_monitor_source_correctly_resolved(self):
        with mock.patch.object(bsc, "_load_registry", return_value={
            "momentum-long": {"asset_class": "us_equity",
                               "signal_at": lambda i, b: None},
        }):
            _seed(self.repo, rows=[],
                   state_strategies={
                       "momentum-long": {"enabled": True,
                                          "trades_lifetime": 0}},
                   as_of=self.as_of)
            cov = bsc.build_coverage(
                as_of=self.as_of, repo_root=self.repo)
        rows = {r["strategy"]: r for r in cov["strategies"]}
        self.assertEqual(
            rows["momentum-long"]["monitor_source"], "price-monitor")

    def test_status_distribution_aggregated(self):
        with mock.patch.object(bsc, "_load_registry", return_value={
            "crypto-momentum": {"asset_class": "crypto",
                                 "signal_at": lambda i, b: None},
            "geo-defense": {"asset_class": "us_equity",
                             "signal_at": None,
                             "observe_only": True},
        }):
            _seed(self.repo,
                   rows=[
                       {"strategy": "crypto-momentum",
                        "symbol": "BTC/USD",
                        "risk_decision": "DETECTED",
                        "confidence_score": 0.7},
                       {"strategy": "alloc-exit",
                        "symbol": "AAPL",
                        "risk_decision": "DETECTED"},
                   ],
                   state_strategies={
                       "crypto-momentum": {"enabled": True,
                                            "trades_lifetime": 50},
                       "geo-defense": {"enabled": True,
                                        "trades_lifetime": 0},
                   },
                   as_of=self.as_of)
            cov = bsc.build_coverage(
                as_of=self.as_of, repo_root=self.repo)
        dist = cov["status_distribution"]
        self.assertEqual(dist.get("ACTIVE", 0), 1)
        self.assertEqual(dist.get("OBSERVE_ONLY", 0), 1)
        # alloc-exit only in ledger, neither in state nor registry -> ZOMBIE
        self.assertEqual(dist.get("ZOMBIE", 0), 1)

    def test_standing_markers_and_safety(self):
        with mock.patch.object(bsc, "_load_registry", return_value={}):
            _seed(self.repo, rows=[], state_strategies={},
                   as_of=self.as_of)
            cov = bsc.build_coverage(
                as_of=self.as_of, repo_root=self.repo)
        for marker in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
            "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
        ):
            self.assertIn(marker, cov["standing_markers"])
        md = bsc.render_md(cov)
        for marker in bsc.STANDING_MARKERS:
            self.assertIn(marker, md)
        self.assertFalse(cov["safety"]["edge_gate_enabled"])
        self.assertFalse(cov["safety"]["allow_broker_paper"])
        self.assertFalse(cov["safety"]["live_trading_supported"])


if __name__ == "__main__":
    unittest.main()
