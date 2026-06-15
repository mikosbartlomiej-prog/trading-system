"""v3.23.0 — tests for ``scripts/build_real_market_evidence_status.py``."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_real_market_evidence_status as brm  # type: ignore  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def _seed(repo_root: Path, *, today_rows: list[dict],
            counters: dict, health: dict,
            as_of: datetime) -> None:
    """Seed a minimal repo skeleton in a tempdir."""
    ledger_dir = repo_root / "learning-loop" / "opportunity_ledger"
    ev_dir = repo_root / "learning-loop" / "shadow_evidence"
    _write_jsonl(
        ledger_dir / f"{as_of.date().isoformat()}.jsonl",
        today_rows,
    )
    _write_json(
        ev_dir / "evidence_counters_latest.json", counters)
    _write_json(
        ev_dir / "workflow_health_latest.json", health)


class TestBuildRealMarketEvidenceStatus(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.as_of = datetime(2026, 6, 15, 12, 0,
                              tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_empty_ledger_returns_zero_opportunities(self):
        _seed(self.repo, today_rows=[],
              counters={"real_market_opportunities_count": 0,
                          "thresholds": {"real_market_opportunities": 50}},
              health={}, as_of=self.as_of)
        out = brm.build_status(as_of=self.as_of, repo_root=self.repo)
        self.assertEqual(out["opportunities_today"], 0)
        self.assertEqual(out["shadow_eligible_count_today"], 0)
        self.assertEqual(out["days_to_n50_estimate"], "UNKNOWN")
        self.assertIn(out["current_blocker"],
                       ("WORKFLOW_NOT_FIRING", "NO_REAL_MARKET_DATA"))

    def test_shadow_eligible_requires_score_above_threshold(self):
        rows = [
            {"strategy": "momentum-long", "symbol": "AAPL",
             "risk_decision": "DETECTED", "confidence_score": 0.7,
             "raw_signal": {}},
            {"strategy": "momentum-long", "symbol": "AAPL",
             "risk_decision": "DETECTED", "confidence_score": 0.4,
             "raw_signal": {}},
            {"strategy": "momentum-long", "symbol": "AAPL",
             "risk_decision": "DETECTED", "confidence_score": None,
             "raw_signal": {}},
        ]
        _seed(self.repo, today_rows=rows,
              counters={"real_market_opportunities_count": 0,
                          "thresholds": {"real_market_opportunities": 50}},
              health={}, as_of=self.as_of)
        out = brm.build_status(as_of=self.as_of, repo_root=self.repo)
        # Only 1 row qualifies: DETECTED + 0.7 score.
        self.assertEqual(out["shadow_eligible_count_today"], 1)

    def test_by_monitor_maps_strategies_correctly(self):
        rows = [
            {"strategy": "crypto-momentum", "symbol": "BTC/USD",
             "risk_decision": "NO_SIGNAL", "raw_signal": {}},
            {"strategy": "momentum-long", "symbol": "AAPL",
             "risk_decision": "NO_SIGNAL", "raw_signal": {}},
            {"strategy": "geo-defense", "symbol": "RTX",
             "risk_decision": "NO_SIGNAL", "raw_signal": {}},
        ]
        _seed(self.repo, today_rows=rows,
              counters={}, health={}, as_of=self.as_of)
        out = brm.build_status(as_of=self.as_of, repo_root=self.repo)
        self.assertEqual(
            out["opportunities_today_by_monitor"]["crypto-monitor"], 1)
        self.assertEqual(
            out["opportunities_today_by_monitor"]["price-monitor"], 1)
        self.assertEqual(
            out["opportunities_today_by_monitor"]["geo-monitor"], 1)

    def test_confidence_bucket_distribution(self):
        rows = [
            {"strategy": "crypto-momentum", "symbol": "BTC/USD",
             "confidence_score": 0.30, "risk_decision": "REJECT",
             "raw_signal": {}},
            {"strategy": "crypto-momentum", "symbol": "BTC/USD",
             "confidence_score": 0.55, "risk_decision": "REJECT",
             "raw_signal": {}},
            {"strategy": "crypto-momentum", "symbol": "BTC/USD",
             "confidence_score": 0.70, "risk_decision": "DETECTED",
             "raw_signal": {}},
            {"strategy": "crypto-momentum", "symbol": "BTC/USD",
             "confidence_score": 0.90, "risk_decision": "DETECTED",
             "raw_signal": {}},
            {"strategy": "crypto-momentum", "symbol": "BTC/USD",
             "confidence_score": None, "risk_decision": "NO_SIGNAL",
             "raw_signal": {}},
        ]
        _seed(self.repo, today_rows=rows,
              counters={}, health={}, as_of=self.as_of)
        out = brm.build_status(as_of=self.as_of, repo_root=self.repo)
        dist = out["confidence_distribution"]
        self.assertEqual(dist["0.0-0.5"], 1)
        self.assertEqual(dist["0.5-0.65"], 1)
        self.assertEqual(dist["0.65-0.80"], 1)
        self.assertEqual(dist["0.80+"], 1)
        self.assertEqual(dist["null"], 1)

    def test_diagnostic_token_counts_propagate_from_health(self):
        _seed(self.repo, today_rows=[],
              counters={"real_market_opportunities_count": 0},
              health={
                  "diagnostic_token_counts": {"AUTH_MISSING": 13},
                  "secrets_status": "SECRETS_MISSING_OR_UNAVAILABLE",
              }, as_of=self.as_of)
        out = brm.build_status(as_of=self.as_of, repo_root=self.repo)
        self.assertEqual(
            out["data_failure_counts"], {"AUTH_MISSING": 13})
        self.assertEqual(out["current_blocker"], "AUTH_MISSING")

    def test_blocker_no_real_market_data_when_collector_skipped(self):
        _seed(self.repo, today_rows=[],
              counters={},
              health={
                  "diagnostic_token_counts": {},
                  "last_collector_status":
                      "SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA",
                  "last_workflow_run_conclusion": "success",
              }, as_of=self.as_of)
        out = brm.build_status(as_of=self.as_of, repo_root=self.repo)
        self.assertEqual(out["current_blocker"], "NO_REAL_MARKET_DATA")

    def test_days_to_n50_estimate_when_rolling_avg_positive(self):
        # Place 1 real opportunity in counters; rolling_avg = 1/3.
        # 50 remaining /  (1/3) ≈ 150 days
        _seed(self.repo, today_rows=[],
              counters={
                  "real_market_opportunities_count": 1,
                  "thresholds": {"real_market_opportunities": 50},
              },
              health={}, as_of=self.as_of)
        out = brm.build_status(as_of=self.as_of, repo_root=self.repo)
        # The rolling avg is real_count / rolling_days = 1/3 ≈ 0.333
        # 49 / 0.333 ≈ 147 days
        self.assertNotEqual(out["days_to_n50_estimate"], "UNKNOWN")
        self.assertGreater(float(out["days_to_n50_estimate"]), 100)

    def test_standing_markers_present_in_output(self):
        _seed(self.repo, today_rows=[],
              counters={}, health={}, as_of=self.as_of)
        out = brm.build_status(as_of=self.as_of, repo_root=self.repo)
        for marker in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
            "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
        ):
            self.assertIn(marker, out["standing_markers"])

    def test_render_md_contains_standing_markers(self):
        _seed(self.repo, today_rows=[],
              counters={}, health={}, as_of=self.as_of)
        out = brm.build_status(as_of=self.as_of, repo_root=self.repo)
        md = brm.render_md(out)
        for marker in brm.STANDING_MARKERS:
            self.assertIn(marker, md)

    def test_safety_flags_all_false(self):
        _seed(self.repo, today_rows=[],
              counters={}, health={}, as_of=self.as_of)
        out = brm.build_status(as_of=self.as_of, repo_root=self.repo)
        self.assertFalse(out["safety"]["edge_gate_enabled"])
        self.assertFalse(out["safety"]["allow_broker_paper"])
        self.assertFalse(out["safety"]["live_trading_supported"])
        self.assertFalse(out["safety"]["observations_count_as_opportunities"])


if __name__ == "__main__":
    unittest.main()
