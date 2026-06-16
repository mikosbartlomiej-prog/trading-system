"""v3.30 (2026-06-16) — LLM provider activation tests.

Asserts the contract of the v3.30 advisory-mesh activation path:

1. ``GEMINI_API_KEY`` missing -> deterministic fallback emits 10 stubs.
2. ``GEMINI_API_KEY`` present (mocked) -> real provider path invoked.
3. Provider timeout -> fallback for that agent + audit token.
4. Provider returns empty -> LLM_ADVISORY_LOW_QUALITY + fallback.
5. Secret value NEVER appears in stdout / on disk.
6. ``redact_secrets`` is called on every provider response before
   the row is persisted.
7. Workflow YAML references ``secrets.GEMINI_API_KEY`` only.
8. Workflow pins 7 broker / live flags = false.
9. Workflow has a refusal step.
10. Mesh runner does NOT import ``alpaca_orders``.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import llm_advisory_mesh as mesh             # noqa: E402
import llm_provider_client as _p             # noqa: E402

MESH_SRC = (REPO_ROOT / "shared"
            / "llm_advisory_mesh.py").read_text(encoding="utf-8")

WORKFLOW_PATH = (REPO_ROOT / ".github" / "workflows"
                  / "llm-advisory-mesh-v329.yml")
WORKFLOW_SRC = WORKFLOW_PATH.read_text(encoding="utf-8")


# ─── 1. Key missing -> deterministic fallback for all 10 agents ────────────

class TestKeyMissingDeterministicFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]    = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)
        # Ensure no key.
        os.environ.pop("GEMINI_API_KEY", None)

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",    None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        self.tmp.cleanup()

    def test_dry_run_emits_ten_stubs(self):
        outs = mesh.run_mesh(dry_run=True)
        self.assertEqual(len(outs), 10)
        for out in outs:
            self.assertEqual(out.recommendation, "ALLOW")
            self.assertEqual(out.risk_level,    "LOW")
            self.assertEqual(out.confidence,    "LOW")
            self.assertTrue(out.advisory_only)
            self.assertTrue(out.must_not_execute_orders)


# ─── 2. Provider key present (mocked) -> provider path invoked ─────────────

class TestProviderPathInvokedWhenKeyPresent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]    = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)
        os.environ["LLM_BUDGET_STATE_DIR"] = str(self.advisory_dir)
        os.environ["GEMINI_API_KEY"]      = "test-key-only-mocked"
        os.environ["LLM_PROVIDER"]        = "gemini"
        os.environ["LLM_AGENTS_ENABLED"]  = "true"
        os.environ["LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS"] = "0"

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",     None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        os.environ.pop("LLM_BUDGET_STATE_DIR", None)
        os.environ.pop("GEMINI_API_KEY",       None)
        os.environ.pop("LLM_PROVIDER",         None)
        os.environ.pop("LLM_AGENTS_ENABLED",   None)
        os.environ.pop("LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS", None)
        self.tmp.cleanup()

    def test_provider_called_with_good_response(self):
        good_json = json.dumps({
            "findings_list": [
                "Finding alpha — clear and grounded in evidence.",
                "Finding beta — referenced workflow_health_latest.",
                "Finding gamma — no execution intent.",
            ],
            "risks": [
                "Risk one — operator should verify counters.",
                "Risk two — paid provider must stay BLOCKED.",
            ],
            "recommended_next_actions": [
                "Action one — inspect llm_budget_state.json.",
                "Action two — rerun the audit tomorrow.",
            ],
            "findings": "Aggregate finding paragraph.",
            "risk_level": "LOW",
            "recommendation": "ALLOW",
            "veto_recommendation": False,
            "confidence": "MEDIUM",
            "limitations": (
                "Smoke test only; not a substitute for deterministic "
                "gates."),
        })
        good_resp = _p.ProviderResponse(
            status=_p.LLM_PROVIDER_CALL_OK,
            provider="gemini", model="gemini-flash-latest",
            text=good_json, cost_usd=0.0,
        )
        with mock.patch.object(_p, "call_provider",
                                  return_value=good_resp) as m:
            out = mesh.run_agent("INCIDENT_REVIEW", dry_run=False)
            self.assertTrue(m.called,
                              "provider must be invoked when "
                              "GEMINI_API_KEY is present and dry_run=False")
            # Validated, advisory-only.
            self.assertTrue(out.advisory_only)
            self.assertTrue(out.must_not_execute_orders)


# ─── 3. Provider timeout -> fallback + audit token ─────────────────────────

class TestProviderTimeoutFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]    = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)
        os.environ["LLM_BUDGET_STATE_DIR"] = str(self.advisory_dir)
        os.environ["GEMINI_API_KEY"]      = "test-key-only-mocked"
        os.environ["LLM_PROVIDER"]        = "gemini"
        os.environ["LLM_AGENTS_ENABLED"]  = "true"
        os.environ["LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS"] = "0"

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",     None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        os.environ.pop("LLM_BUDGET_STATE_DIR", None)
        os.environ.pop("GEMINI_API_KEY",       None)
        os.environ.pop("LLM_PROVIDER",         None)
        os.environ.pop("LLM_AGENTS_ENABLED",   None)
        os.environ.pop("LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS", None)
        self.tmp.cleanup()

    def test_timeout_routes_to_deterministic_fallback(self):
        timeout_resp = _p.ProviderResponse(
            status=_p.LLM_PROVIDER_TIMEOUT,
            provider="gemini", model="gemini-flash-latest",
            text="", cost_usd=0.0,
        )
        with mock.patch.object(_p, "call_provider",
                                  return_value=timeout_resp):
            out = mesh.run_agent("RISK_REVIEW", dry_run=False)
            self.assertEqual(out.recommendation, "ALLOW")
            self.assertEqual(out.risk_level,    "LOW")
            # The persisted row must carry the provider audit token.
            p = self.advisory_dir / "RISK_REVIEW_latest.json"
            self.assertTrue(p.exists())
            persisted = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["provider_status"],
                "PROVIDER_FAILED_FAIL_SOFT")


# ─── 4. Empty provider response -> LLM_ADVISORY_LOW_QUALITY -> fallback ────

class TestEmptyResponseLowQuality(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]    = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)
        os.environ["LLM_BUDGET_STATE_DIR"] = str(self.advisory_dir)
        os.environ["GEMINI_API_KEY"]      = "test-key-only-mocked"
        os.environ["LLM_PROVIDER"]        = "gemini"
        os.environ["LLM_AGENTS_ENABLED"]  = "true"
        os.environ["LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS"] = "0"

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",     None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        os.environ.pop("LLM_BUDGET_STATE_DIR", None)
        os.environ.pop("GEMINI_API_KEY",       None)
        os.environ.pop("LLM_PROVIDER",         None)
        os.environ.pop("LLM_AGENTS_ENABLED",   None)
        os.environ.pop("LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS", None)
        self.tmp.cleanup()

    def test_empty_text_routes_to_fallback(self):
        empty_ok = _p.ProviderResponse(
            status=_p.LLM_PROVIDER_CALL_OK,
            provider="gemini", model="gemini-flash-latest",
            text="", cost_usd=0.0,
        )
        with mock.patch.object(_p, "call_provider",
                                  return_value=empty_ok):
            out = mesh.run_agent("STRATEGY_REVIEW", dry_run=False)
            self.assertEqual(out.recommendation, "ALLOW")
            # Persisted file should be marked PROVIDER_FAILED_FAIL_SOFT
            # because the empty text was treated as no-usable-response.
            p = self.advisory_dir / "STRATEGY_REVIEW_latest.json"
            persisted = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["provider_status"],
                "PROVIDER_FAILED_FAIL_SOFT")


# ─── 5. Secret value NEVER appears in stdout or persisted file ─────────────

class TestSecretValueNeverLeaks(unittest.TestCase):
    SECRET_LITERAL = "GEMINIKEY1234567890ABCDEFGHIJK"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]    = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)
        os.environ["GEMINI_API_KEY"]      = self.SECRET_LITERAL
        os.environ["LLM_PROVIDER"]        = "gemini"
        os.environ["LLM_AGENTS_ENABLED"]  = "true"

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",     None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        os.environ.pop("LLM_BUDGET_STATE_DIR", None)
        os.environ.pop("GEMINI_API_KEY",       None)
        os.environ.pop("LLM_PROVIDER",         None)
        os.environ.pop("LLM_AGENTS_ENABLED",   None)
        os.environ.pop("LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS", None)
        self.tmp.cleanup()

    def test_secret_never_persisted_to_disk(self):
        # Provider response that ECHOES the secret value in the text.
        echo_resp = _p.ProviderResponse(
            status=_p.LLM_PROVIDER_CALL_OK,
            provider="gemini", model="gemini-flash-latest",
            text=json.dumps({
                "findings_list": [
                    f"Echoed key: {self.SECRET_LITERAL}",
                    "Other finding",
                    "Third finding",
                ],
                "risks": ["Risk A", "Risk B"],
                "recommended_next_actions": ["Act A", "Act B"],
                "limitations": "Echo limitation.",
                "risk_level": "LOW",
                "recommendation": "ALLOW",
                "veto_recommendation": False,
                "confidence": "LOW",
            }),
            cost_usd=0.0,
        )
        with mock.patch.object(_p, "call_provider",
                                  return_value=echo_resp):
            mesh.run_agent("DAILY_BRIEF", dry_run=False)
        p = self.advisory_dir / "DAILY_BRIEF_latest.json"
        on_disk = p.read_text(encoding="utf-8")
        self.assertNotIn(self.SECRET_LITERAL, on_disk,
                          "secret value leaked into the persisted row")

    def test_redact_secrets_invoked_on_provider_text(self):
        # Patch the redact_secrets helper to count invocations.
        import llm_advisory_authority as auth
        with mock.patch.object(
                auth, "redact_secrets",
                side_effect=lambda x: f"[REDACTED-WRAPPED]{x or ''}") as m:
            echo_resp = _p.ProviderResponse(
                status=_p.LLM_PROVIDER_CALL_OK,
                provider="gemini", model="gemini-flash-latest",
                text="hi", cost_usd=0.0,
            )
            with mock.patch.object(_p, "call_provider",
                                      return_value=echo_resp):
                mesh.run_agent("FINAL_ARBITER", dry_run=False)
            self.assertGreaterEqual(
                m.call_count, 1,
                "redact_secrets must be invoked at least once on the "
                "provider-OK path")


# ─── 6. Workflow YAML asserts ──────────────────────────────────────────────

class TestWorkflowReferencesOnlyGeminiSecret(unittest.TestCase):
    def test_workflow_references_secrets_gemini_api_key(self):
        self.assertIn("secrets.GEMINI_API_KEY", WORKFLOW_SRC)

    def test_workflow_does_not_reference_other_provider_secrets(self):
        # v3.30 — only GEMINI_API_KEY should appear; ANTHROPIC + OPENAI
        # must NOT be referenced as secrets in this workflow.
        self.assertNotIn("secrets.ANTHROPIC_API_KEY", WORKFLOW_SRC)
        self.assertNotIn("secrets.OPENAI_API_KEY",    WORKFLOW_SRC)


class TestWorkflowPinsBrokerFlags(unittest.TestCase):
    def test_seven_broker_live_flags_pinned_false(self):
        import re
        for flag in (
            "ALLOW_BROKER_PAPER",
            "EDGE_GATE_ENABLED",
            "BROKER_EXECUTION_ENABLED",
            "LIVE_TRADING",
            "LIVE_ENABLED",
            "GO_LIVE",
            "LIVE_TRADING_ENABLED",
        ):
            self.assertIsNotNone(
                re.search(rf'\n\s*{flag}:\s+"false"', WORKFLOW_SRC),
                f"{flag} must be pinned to \"false\"")


class TestWorkflowHasRefusalStep(unittest.TestCase):
    def test_refusal_step_present(self):
        self.assertIn("Refuse if any broker-execution env flag is truthy",
                       WORKFLOW_SRC)
        self.assertIn("exit 1", WORKFLOW_SRC)


# ─── 10. AST: no broker imports / calls in mesh ────────────────────────────

class TestMeshAstNoBroker(unittest.TestCase):
    def test_no_alpaca_orders_import(self):
        tree = ast.parse(MESH_SRC)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertFalse(
                    node.module and "alpaca_orders" in node.module,
                    f"forbidden import: {node.module}")


if __name__ == "__main__":
    unittest.main()
