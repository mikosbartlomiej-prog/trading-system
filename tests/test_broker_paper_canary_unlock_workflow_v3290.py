"""v3.29 (2026-06-09) — unlock evaluator workflow YAML tests."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WF_PATH   = (REPO_ROOT / ".github" / "workflows"
              / "broker-paper-canary-unlock-evaluator.yml")
MESH_WF   = (REPO_ROOT / ".github" / "workflows"
              / "llm-advisory-mesh.yml")


class TestWorkflowExists(unittest.TestCase):
    def test_exists(self):
        self.assertTrue(WF_PATH.exists())


class TestWorkflowHasNoBrokerSecrets(unittest.TestCase):
    def test_no_alpaca_secrets(self):
        text = WF_PATH.read_text(encoding="utf-8")
        for tok in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY",
                     "paper-api.alpaca.markets"):
            self.assertNotIn(tok, text)


class TestWorkflowBrokerFlagsPinnedFalse(unittest.TestCase):
    def test_seven_flags_pinned_false(self):
        text = WF_PATH.read_text(encoding="utf-8")
        for v in ("ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
                   "BROKER_EXECUTION_ENABLED",
                   "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
                   "LIVE_TRADING_ENABLED"):
            self.assertRegex(text, rf"{v}:\s*\"false\"")


class TestWorkflowReadOnlyEvaluation(unittest.TestCase):
    def test_calls_evaluate_only(self):
        text = WF_PATH.read_text(encoding="utf-8")
        self.assertIn("--evaluate-only", text)

    def test_path_allow_list(self):
        text = WF_PATH.read_text(encoding="utf-8")
        for needed in (
            "learning-loop/broker_paper_canary/",
            "docs/BROKER_PAPER_CANARY_UNLOCK_STATUS.md",
            "docs/BROKER_PAPER_CANARY_UNLOCK_CONTRACT.md",
            "docs/LLM_STRATEGY_ALIGNMENT.md",
            "learning-loop/llm_advisory/strategy_alignment_latest.json",
        ):
            self.assertIn(needed, text)


class TestMeshWorkflowGeminiSmokeStep(unittest.TestCase):
    def test_mesh_workflow_has_smoke_step(self):
        text = MESH_WF.read_text(encoding="utf-8")
        self.assertIn("smoke_test_gemini_provider", text)
        self.assertIn("GEMINI_SMOKE_OK", text)

    def test_mesh_workflow_has_model_override_input(self):
        text = MESH_WF.read_text(encoding="utf-8")
        self.assertIn("model_override:", text)


class TestUnlockEvaluatorScriptExists(unittest.TestCase):
    def test_script_present(self):
        path = (REPO_ROOT / "scripts"
                 / "evaluate_broker_paper_canary_unlock.py")
        self.assertTrue(path.exists())


class TestWorkflowDoesNotReferenceBrokerModule(unittest.TestCase):
    def test_no_broker_tokens_in_workflow(self):
        text = WF_PATH.read_text(encoding="utf-8")
        for tok in ("alpaca_orders", "place_stock_bracket",
                     "place_crypto_order", "submit_order",
                     "safe_close"):
            self.assertNotIn(tok, text)


if __name__ == "__main__":
    unittest.main()
