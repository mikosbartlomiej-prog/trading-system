"""v3.30 (2026-06-09) — unlock evaluator reaches
``BROKER_PAPER_CANARY_UNLOCK_READY_PRE_EXECUTOR_ONLY`` when every
deterministic gate passes AND the canary executor is in
``preflight_only`` mode AND order placement is not implemented.

This pins the v3.30 maximum-readiness terminal status. The status
maps directly to the spec's expected final state:

    *all gates green; canary still does NOT trade.*
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


class _SandboxedRepo(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for sub in (
            "learning-loop/shadow_evidence",
            "learning-loop/llm_advisory",
            "learning-loop/broker_paper_canary",
            "configs",
        ):
            (self.tmp / sub).mkdir(parents=True, exist_ok=True)
        # Copy the real canary config so the v3.30 config is loaded.
        real_cfg = (REPO_ROOT / "configs"
                     / "broker_paper_canary.json")
        (self.tmp / "configs" / "broker_paper_canary.json"
         ).write_text(real_cfg.read_text(encoding="utf-8"),
                       encoding="utf-8")
        self._patcher = mock.patch(
            "broker_paper_canary_unlock.REPO_ROOT", self.tmp)
        self._patcher.start()
        # Approve the operator so we reach the post-approval branch.
        self._env = mock.patch.dict(os.environ, {
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY": "true",
            "ALLOW_BROKER_PAPER": "false",
            "EDGE_GATE_ENABLED":  "false",
            "BROKER_EXECUTION_ENABLED": "false",
            "LIVE_TRADING": "false", "LIVE_ENABLED": "false",
            "GO_LIVE": "false", "LIVE_TRADING_ENABLED": "false",
        }, clear=False)
        self._env.start()

        # Synthesise green evidence + quality + alignment.
        _write(self.tmp / "learning-loop" / "shadow_evidence"
                / "evidence_counters_latest.json", {
                    "real_market_opportunities_count":   60,
                    "completed_shadow_outcomes_count":   25,
                    "audit_bypass_findings_count":       0,
                    "exposure_cap_breach_count":         0,
                    "repeated_buy_violation_count":      0,
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
                    "first_real_market_record_seen": True,
                })
        _write(self.tmp / "learning-loop" / "shadow_evidence"
                / "workflow_health_latest.json", {
                    "verdict":
                        "AUTOMATED_PIPELINE_HEALTHY",
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
        # Write an acceptable-quality history row so the count >= 1
        # gate passes.
        hist = (self.tmp / "learning-loop" / "llm_advisory"
                  / "quality_history.jsonl")
        hist.write_text(json.dumps({
            "run_id": "v3300-test-run-1",
            "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
            "accepted_for_unlock_counting": True,
            "rows_seen": 5,
            "rows_with_provider_used": 5,
            "empty_risks_count": 1,
            "empty_next_actions_count": 1,
            "zero_confidence_count": 1,
            "secret_leak_hits": 0,
            "unsafe_phrase_hits": 0,
        }) + "\n", encoding="utf-8")

    def tearDown(self):
        self._patcher.stop()
        self._env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestPreExecutorOnlyStatus(_SandboxedRepo):

    def test_reaches_pre_executor_only_status_with_v330_config(self):
        import broker_paper_canary_unlock as bp
        rep = bp.evaluate_unlock_readiness(
            require_n_acceptable_runs=1)
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_READY_PRE_EXECUTOR_ONLY,
            f"v3.30 expected PRE_EXECUTOR_ONLY; got {rep.status}; "
            f"gates={rep.gates}",
        )
        self.assertEqual(rep.stage,
                          bp.STAGE_2_BROKER_PAPER_CANARY_READY)
        # Sanity: the v3.30 config fields are wired into gates.
        self.assertEqual(rep.gates["canary_executor_mode"],
                          "preflight_only")
        self.assertFalse(rep.gates[
            "canary_order_placement_implemented"])
        self.assertTrue(rep.gates["safe_enable_switch_present"])

    def test_full_unlock_ready_requires_order_placement_implemented(self):
        import broker_paper_canary_unlock as bp
        cfg = self.tmp / "configs" / "broker_paper_canary.json"
        d = json.loads(cfg.read_text(encoding="utf-8"))
        d["canary_executor_mode"] = "full_executor"
        d["canary_order_placement_implemented"] = True
        cfg.write_text(json.dumps(d), encoding="utf-8")
        rep = bp.evaluate_unlock_readiness(
            require_n_acceptable_runs=1)
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_READY,
            "with both flags set to full+implemented, the evaluator "
            "should advance to BROKER_PAPER_CANARY_UNLOCK_READY")


if __name__ == "__main__":
    unittest.main()
