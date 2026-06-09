"""v3.30 (2026-06-09) — observation records must never unlock.

Confirms that synthesising 1000 observation records cannot push
``real_market_opportunities_count`` past the unlock threshold, and
that the unlock evaluator never advances to
``BROKER_PAPER_CANARY_UNLOCK_READY*`` based on observations alone.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


class TestObservationsDoNotIncrementUnlockGate(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "learning-loop" / "shadow_evidence").mkdir(
            parents=True, exist_ok=True)
        (self.tmp / "learning-loop" / "shadow_evidence"
         / "observations").mkdir(parents=True, exist_ok=True)
        (self.tmp / "learning-loop" / "llm_advisory").mkdir(
            parents=True, exist_ok=True)
        (self.tmp / "configs").mkdir(parents=True, exist_ok=True)
        real_cfg = (REPO_ROOT / "configs"
                     / "broker_paper_canary.json")
        (self.tmp / "configs" / "broker_paper_canary.json"
         ).write_text(real_cfg.read_text(encoding="utf-8"),
                       encoding="utf-8")
        self._patcher = mock.patch(
            "broker_paper_canary_unlock.REPO_ROOT", self.tmp)
        self._patcher.start()
        self._env = mock.patch.dict(os.environ, {
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY": "true",
            "ALLOW_BROKER_PAPER": "false",
            "EDGE_GATE_ENABLED":  "false",
            "BROKER_EXECUTION_ENABLED": "false",
            "LIVE_TRADING": "false", "LIVE_ENABLED": "false",
            "GO_LIVE": "false", "LIVE_TRADING_ENABLED": "false",
        }, clear=False)
        self._env.start()
        # Write evidence with zero real opportunities + huge synthetic
        # observation count.
        _write(self.tmp / "learning-loop" / "shadow_evidence"
                / "evidence_counters_latest.json", {
                    "real_market_opportunities_count":          0,
                    "observation_records_count":                1000,
                    "real_market_no_signal_observations_count": 950,
                    "completed_shadow_outcomes_count":          0,
                    "audit_bypass_findings_count":              0,
                    "exposure_cap_breach_count":                0,
                    "repeated_buy_violation_count":             0,
                    "unexplained_broker_state_conflicts_count": 0,
                    "safety_invariants": {
                        "broker_order_submitted_ever": False,
                        "live_trading_enabled":        False,
                        "broker_paper_enabled":        False,
                        "edge_gate_enabled":           False,
                        "baseline_reset":              False,
                        "drawdown_guard_lowered":      False,
                    },
                })
        _write(self.tmp / "learning-loop" / "shadow_evidence"
                / "first_real_market_record_status.json", {
                    "first_real_market_record_seen": False,
                })
        _write(self.tmp / "learning-loop" / "shadow_evidence"
                / "workflow_health_latest.json", {
                    "verdict":
                        "AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET",
                })
        _write(self.tmp / "learning-loop" / "llm_advisory"
                / "quality_review_latest.json", {
                    "quality_status":
                        "LLM_ADVISORY_QUALITY_ACCEPTABLE",
                    "quality_report": {
                        "status":
                            "LLM_ADVISORY_QUALITY_ACCEPTABLE",
                        "rows_seen": 5,
                        "rows_with_provider_used": 5,
                        "empty_risks_count": 1,
                        "empty_next_actions_count": 1,
                        "zero_confidence_count": 1,
                        "secret_leak_hits": 0,
                        "unsafe_phrase_hits": 0,
                    },
                })
        _write(self.tmp / "learning-loop" / "llm_advisory"
                / "strategy_alignment_latest.json", {
                    "alignment_status": "LLM_STRATEGY_ALIGNMENT_PASS",
                })

    def tearDown(self):
        self._patcher.stop()
        self._env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_observations_do_not_set_first_real_market_record(self):
        import broker_paper_canary_unlock as bp
        rep = bp.evaluate_unlock_readiness(
            require_n_acceptable_runs=1)
        self.assertIn(
            rep.status,
            (bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_REAL_MARKET_RECORD,
             bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_EVIDENCE_INCOMPLETE,
             bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_COMPLETED_OUTCOMES,
            ))

    def test_observations_do_not_increment_real_opportunities(self):
        import broker_paper_canary_unlock as bp
        rep = bp.evaluate_unlock_readiness(
            require_n_acceptable_runs=1)
        self.assertEqual(rep.gates[
            "real_market_opportunities_count"], 0)
        # observation_records_count exists in evidence but does NOT
        # appear under the readiness gates.
        self.assertNotIn(
            "observation_records_count", rep.gates)


class TestObservationCountersAreDistinctMetrics(unittest.TestCase):

    def test_counters_module_exposes_distinct_metric_names(self):
        import shadow_evidence_counters as sec
        self.assertIn(sec.METRIC_OBSERVATION_RECORDS,
                       sec.ALL_METRICS)
        self.assertIn(sec.METRIC_REAL_MARKET_NO_SIGNAL_OBSERVATIONS,
                       sec.ALL_METRICS)
        self.assertNotEqual(
            sec.METRIC_OBSERVATION_RECORDS,
            sec.METRIC_REAL_MARKET_OPPORTUNITIES,
            "observation_records must NOT alias the real-opportunities "
            "metric — observations do not count toward unlock",
        )
        self.assertEqual(sec.EVIDENCE_QUALITY_REAL_MARKET_DATA_OBSERVATION,
                          "REAL_MARKET_DATA_OBSERVATION")
        self.assertNotEqual(sec.EVIDENCE_QUALITY_REAL_MARKET_DATA_OBSERVATION,
                              sec.EVIDENCE_QUALITY_REAL_MARKET_DATA)


if __name__ == "__main__":
    unittest.main()
