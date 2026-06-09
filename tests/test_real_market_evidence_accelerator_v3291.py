"""v3.29.1 (2026-06-09) — real-market evidence accelerator tests."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "learning-loop" / "shadow_evidence").mkdir(
            parents=True, exist_ok=True)
        self.patcher = mock.patch(
            "real_market_evidence_accelerator.REPO_ROOT", self.tmp)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _w(self, rel, payload):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8")

    def _wjsonl(self, rel, rows):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, sort_keys=True) + "\n")


class TestInsufficientRunsBlocks(_Sandbox):
    def test_zero_runs_blocks(self):
        import real_market_evidence_accelerator as a
        rep = a.evaluate_acceleration()
        self.assertEqual(
            rep.status,
            a.REAL_MARKET_EVIDENCE_BLOCKED_INSUFFICIENT_RUNS)


class TestAuthFailedDominates(_Sandbox):
    def test_auth_failed_blocks_auth(self):
        import real_market_evidence_accelerator as a
        self._wjsonl(
            "learning-loop/shadow_evidence/workflow_health_history.jsonl",
            [
                {"workflow_conclusion": "success",
                 "diagnostic_token_counts": {
                     "MARKET_DATA_AUTH_FAILED": 10}},
                {"workflow_conclusion": "success",
                 "diagnostic_token_counts": {
                     "MARKET_DATA_AUTH_FAILED": 8}},
            ])
        rep = a.evaluate_acceleration()
        self.assertEqual(
            rep.status,
            a.REAL_MARKET_EVIDENCE_BLOCKED_AUTH_FAILED)


class TestGeneratorTooRestrictiveDominates(_Sandbox):
    def test_no_signal_dominates(self):
        import real_market_evidence_accelerator as a
        self._wjsonl(
            "learning-loop/shadow_evidence/workflow_health_history.jsonl",
            [
                {"workflow_conclusion": "success",
                 "diagnostic_token_counts": {
                     "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 12}},
                {"workflow_conclusion": "success",
                 "diagnostic_token_counts": {
                     "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 13}},
            ])
        rep = a.evaluate_acceleration()
        self.assertEqual(
            rep.status,
            a.REAL_MARKET_EVIDENCE_BLOCKED_GENERATOR_RESTRICTIVE)
        self.assertIn(
            "ADD_DETERMINISTIC_SHADOW_STRATEGY_CANDIDATES",
            rep.recommended_actions)


class TestNeverIncrementsCounters(unittest.TestCase):
    def test_source_never_writes_counters(self):
        # Read-only access to counter NAMES is fine (the analyzer
        # reads evidence_counters_latest.json). Mutation patterns
        # are the forbidden bit.
        src = (REPO_ROOT / "shared"
                / "real_market_evidence_accelerator.py").read_text(
            encoding="utf-8")
        for bad in (
            "real_market_opportunities_count += 1",
            "real_market_opportunities_count = ",
            "completed_shadow_outcomes_count += 1",
            "completed_shadow_outcomes_count = ",
            ".write_text(json.dumps({\"real_market_opportunities_count\":",
            "evidence_counters_latest.json\", \"w",
        ):
            self.assertNotIn(
                bad, src,
                f"accelerator must never mutate counters: {bad!r}")


class TestForbiddenActionsListed(unittest.TestCase):
    def test_forbidden_enum_includes_critical_actions(self):
        import real_market_evidence_accelerator as a
        for tok in (
            "LOWER_SAFETY_THRESHOLDS_TO_CREATE_FAKE_SIGNALS",
            "COUNT_NO_SIGNAL_AS_OPPORTUNITY",
            "COUNT_SCAFFOLD_OR_HALT_AS_REAL_MARKET",
            "USE_LLM_OUTPUT_AS_EVIDENCE",
            "PLACE_BROKER_ORDERS",
            "ENABLE_BROKER_PAPER",
        ):
            self.assertIn(tok, a.FORBIDDEN_ACTIONS)


class TestNoBrokerImports(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "shared"
                / "real_market_evidence_accelerator.py").read_text(encoding="utf-8")
        for tok in ("alpaca_orders", "place_stock_bracket",
                     "submit_order", "place_order", "safe_close"):
            self.assertNotIn(tok, src)


if __name__ == "__main__":
    unittest.main()
