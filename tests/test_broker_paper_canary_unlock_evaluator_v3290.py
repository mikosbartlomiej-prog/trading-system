"""v3.29 (2026-06-09) — unlock evaluator tests (gate matrix)."""

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


def _write(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")


class _SandboxedRepo(unittest.TestCase):
    """Patches REPO_ROOT in the module to a tmp dir so we can write
    synthetic artefacts without touching the real repo state."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # Mirror minimal repo layout.
        (self.tmp / "learning-loop" / "shadow_evidence").mkdir(
            parents=True, exist_ok=True)
        (self.tmp / "learning-loop" / "llm_advisory").mkdir(
            parents=True, exist_ok=True)
        (self.tmp / "learning-loop" / "broker_paper_canary").mkdir(
            parents=True, exist_ok=True)
        (self.tmp / "configs").mkdir(parents=True, exist_ok=True)
        # Copy the real config so safe_canary_enable_switch_present
        # returns the real (false) value.
        real_cfg = (REPO_ROOT / "configs"
                     / "broker_paper_canary.json")
        if real_cfg.exists():
            (self.tmp / "configs" / "broker_paper_canary.json"
             ).write_text(real_cfg.read_text(encoding="utf-8"),
                           encoding="utf-8")
        self._patcher = mock.patch(
            "broker_paper_canary_unlock.REPO_ROOT", self.tmp)
        self._patcher.start()
        # Clear OPERATOR_APPROVED + live flags.
        self._env = mock.patch.dict(os.environ, {
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY": "false",
            "ALLOW_BROKER_PAPER": "false",
            "EDGE_GATE_ENABLED":  "false",
            "BROKER_EXECUTION_ENABLED": "false",
            "LIVE_TRADING": "false", "LIVE_ENABLED": "false",
            "GO_LIVE": "false", "LIVE_TRADING_ENABLED": "false",
        }, clear=False)
        self._env.start()

    def tearDown(self):
        self._patcher.stop()
        self._env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_evidence(self, *, real=0, completed=0,
                          first_real=False, safety_overrides=None,
                          audit_bypass=0, exposure=0):
        safety = {
            "broker_order_submitted_ever": False,
            "live_trading_enabled":        False,
            "broker_paper_enabled":        False,
            "edge_gate_enabled":           False,
            "baseline_reset":              False,
            "drawdown_guard_lowered":      False,
        }
        if safety_overrides:
            safety.update(safety_overrides)
        _write(self.tmp / "learning-loop" / "shadow_evidence"
                / "evidence_counters_latest.json", {
                    "real_market_opportunities_count":    real,
                    "completed_shadow_outcomes_count":    completed,
                    "audit_bypass_findings_count":        audit_bypass,
                    "exposure_cap_breach_count":          exposure,
                    "repeated_buy_violation_count":       0,
                    "unexplained_broker_state_conflicts_count": 0,
                    "safety_invariants": safety,
                })
        _write(self.tmp / "learning-loop" / "shadow_evidence"
                / "first_real_market_record_status.json", {
                    "first_real_market_record_seen": first_real,
                })
        _write(self.tmp / "learning-loop" / "shadow_evidence"
                / "workflow_health_latest.json", {
                    "verdict": "AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET",
                })

    def _write_quality(self, status):
        _write(self.tmp / "learning-loop" / "llm_advisory"
                / "quality_review_latest.json", {
                    "quality_status": status,
                })

    def _write_alignment(self, status):
        _write(self.tmp / "learning-loop" / "llm_advisory"
                / "strategy_alignment_latest.json", {
                    "alignment_status": status,
                })


class TestNoRealRecordBlocks(_SandboxedRepo):
    def test_blocks_when_first_real_record_false(self):
        import broker_paper_canary_unlock as bp
        self._write_evidence(real=100, completed=50,
                                first_real=False)
        self._write_quality("LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self._write_alignment("LLM_STRATEGY_ALIGNMENT_PASS")
        rep = bp.evaluate_unlock_readiness()
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_REAL_MARKET_RECORD)


class TestEvidenceIncompleteBlocks(_SandboxedRepo):
    def test_blocks_below_real_threshold(self):
        import broker_paper_canary_unlock as bp
        self._write_evidence(real=49, completed=20,
                                first_real=True)
        self._write_quality("LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self._write_alignment("LLM_STRATEGY_ALIGNMENT_PASS")
        rep = bp.evaluate_unlock_readiness()
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_EVIDENCE_INCOMPLETE)

    def test_blocks_below_completed_threshold(self):
        import broker_paper_canary_unlock as bp
        self._write_evidence(real=50, completed=19,
                                first_real=True)
        self._write_quality("LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self._write_alignment("LLM_STRATEGY_ALIGNMENT_PASS")
        rep = bp.evaluate_unlock_readiness()
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_COMPLETED_OUTCOMES)


class TestAuditRiskBlocks(_SandboxedRepo):
    def test_drawdown_lowered_blocks(self):
        import broker_paper_canary_unlock as bp
        self._write_evidence(
            real=50, completed=20, first_real=True,
            safety_overrides={"drawdown_guard_lowered": True})
        self._write_quality("LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self._write_alignment("LLM_STRATEGY_ALIGNMENT_PASS")
        rep = bp.evaluate_unlock_readiness()
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_AUDIT_RISK)

    def test_audit_bypass_blocks(self):
        import broker_paper_canary_unlock as bp
        self._write_evidence(real=50, completed=20,
                                first_real=True, audit_bypass=3)
        self._write_quality("LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self._write_alignment("LLM_STRATEGY_ALIGNMENT_PASS")
        rep = bp.evaluate_unlock_readiness()
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_AUDIT_RISK)


class TestLLMQualityBlocks(_SandboxedRepo):
    def test_quality_generic_blocks(self):
        import broker_paper_canary_unlock as bp
        self._write_evidence(real=50, completed=20,
                                first_real=True)
        self._write_quality(
            "LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER")
        self._write_alignment("LLM_STRATEGY_ALIGNMENT_PASS")
        rep = bp.evaluate_unlock_readiness()
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY)


class TestLLMAlignmentBlocks(_SandboxedRepo):
    def test_alignment_fail_blocks(self):
        import broker_paper_canary_unlock as bp
        self._write_evidence(real=50, completed=20,
                                first_real=True)
        self._write_quality("LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self._write_alignment(
            "LLM_STRATEGY_ALIGNMENT_FAIL_EXECUTION_AUTHORITY")
        rep = bp.evaluate_unlock_readiness(
            require_n_acceptable_runs=1)
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_ALIGNMENT)


class TestOperatorApprovalBlocks(_SandboxedRepo):
    def test_no_operator_approval_blocks(self):
        import broker_paper_canary_unlock as bp
        self._write_evidence(real=50, completed=20,
                                first_real=True)
        self._write_quality("LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self._write_alignment("LLM_STRATEGY_ALIGNMENT_PASS")
        rep = bp.evaluate_unlock_readiness(
            require_n_acceptable_runs=1)
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_OPERATOR_APPROVAL)


class TestReadyButNoSafeEnableSwitch(_SandboxedRepo):
    def test_all_gates_plus_approval_yields_no_safe_switch_in_v329(self):
        import broker_paper_canary_unlock as bp
        self._write_evidence(real=50, completed=20,
                                first_real=True)
        self._write_quality("LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self._write_alignment("LLM_STRATEGY_ALIGNMENT_PASS")
        with mock.patch.dict(os.environ, {
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY": "true",
        }, clear=False):
            rep = bp.evaluate_unlock_readiness(
                require_n_acceptable_runs=1)
        # v3.29 ships no safe enable switch — even all-green hits
        # the explicit "READY_BUT_NO_SAFE_ENABLE_SWITCH" stop sign.
        self.assertEqual(
            rep.status,
            bp.BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH)


class TestLiveFlagAlwaysRefuses(_SandboxedRepo):
    def test_live_flag_truthy_refuses_immediately(self):
        import broker_paper_canary_unlock as bp
        # Even with all-green evidence, a truthy live flag must short
        # the evaluation.
        self._write_evidence(real=100, completed=100,
                                first_real=True)
        self._write_quality("LLM_ADVISORY_QUALITY_ACCEPTABLE")
        self._write_alignment("LLM_STRATEGY_ALIGNMENT_PASS")
        with mock.patch.dict(os.environ, {
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY": "true",
            "LIVE_TRADING": "true",
        }, clear=False):
            rep = bp.evaluate_unlock_readiness()
        self.assertEqual(rep.status, bp.LIVE_TRADING_UNSUPPORTED)


class TestEvaluatorNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "shared"
                / "broker_paper_canary_unlock.py").read_text(
            encoding="utf-8")
        for tok in (
            "alpaca_orders", "place_stock_bracket",
            "place_crypto_order", "execute_stock_signal",
            "execute_crypto_signal",
        ):
            self.assertNotIn(tok, src)


if __name__ == "__main__":
    unittest.main()
