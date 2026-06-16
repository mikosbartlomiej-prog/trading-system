"""v3.29 ETAP 6 (2026-06-16) — LLM authority model tests.

Asserts the contract of ``shared/llm_advisory_authority.py``:

- 10 advisory roles enumerated.
- L5_EXECUTE_FORBIDDEN is sentinel; never assignable.
- LLMAdvisoryOutput rejects unknown agent_name / forbidden output /
  advisory_only != True / must_not_execute_orders != True.
- assert_no_execution_intent raises on forbidden output token.
- redact_secrets masks sk-... / gh_... / GEMINI_API_KEY=...
- AST gate: module never imports alpaca_orders.
- AST gate: module never calls a broker function.
- validate_output works for both LLMAdvisoryOutput and dict.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import llm_advisory_authority as auth  # noqa: E402


# ─── 1. ADVISORY_ROLES has 10 entries ──────────────────────────────────────

class TestAdvisoryRoles(unittest.TestCase):
    def test_ten_advisory_roles(self):
        self.assertEqual(len(auth.ADVISORY_ROLES), 10)
        for role in (
            "INCIDENT_REVIEW", "RISK_REVIEW", "STRATEGY_REVIEW",
            "NO_SIGNAL_DIAGNOSTIC", "SHADOW_CANDIDATE_REVIEW",
            "TRIGGER_WATCHLIST_REVIEW", "DAILY_BRIEF",
            "ALLOCATOR_PLAN_CRITIC", "EQUITY_RECONCILIATION_CRITIC",
            "FINAL_ARBITER",
        ):
            self.assertIn(role, auth.ADVISORY_ROLES)


# ─── 2. FORBIDDEN_OUTPUTS contains required tokens ─────────────────────────

class TestForbiddenOutputs(unittest.TestCase):
    def test_required_forbidden_tokens(self):
        for tok in (
            "EXECUTE_ORDER", "PLACE_ORDER", "CLEAR_SAFE_MODE",
            "FLIP_BROKER_FLAG", "MUTATE_THRESHOLD",
            "PROMOTE_VARIANT", "OVERRIDE_GATE",
        ):
            self.assertIn(tok, auth.FORBIDDEN_OUTPUTS)


# ─── 3. LLMAdvisoryOutput rejections ───────────────────────────────────────

def _good_output(**kw):
    base = dict(
        agent_name="INCIDENT_REVIEW",
        authority_level=auth.AUTHORITY_LEVEL_ADVISORY,
        input_artifacts=("journal/autonomy/2026-06-16.jsonl",),
        findings="quiet day",
        risk_level="LOW",
        recommendation="ALLOW",
        veto_recommendation=False,
        confidence="LOW",
        limitations="advisory-only",
    )
    base.update(kw)
    return auth.LLMAdvisoryOutput(**base)


class TestRejectsUnknownAgentName(unittest.TestCase):
    def test_unknown_agent_name_rejected(self):
        with self.assertRaises(ValueError):
            _good_output(agent_name="EXECUTE_ALL_THE_TRADES")


class TestRejectsForbiddenOutputToken(unittest.TestCase):
    def test_forbidden_token_in_findings_rejected(self):
        with self.assertRaises(ValueError):
            _good_output(findings="I will EXECUTE_ORDER now")


class TestRejectsAdvisoryOnlyFalse(unittest.TestCase):
    def test_advisory_only_must_be_true(self):
        with self.assertRaises(ValueError):
            _good_output(advisory_only=False)


class TestRejectsMustNotExecuteOrdersFalse(unittest.TestCase):
    def test_must_not_execute_orders_must_be_true(self):
        with self.assertRaises(ValueError):
            _good_output(must_not_execute_orders=False)


# ─── 4. assert_no_execution_intent raises on forbidden ─────────────────────

class TestAssertNoExecutionIntent(unittest.TestCase):
    def test_raises_on_forbidden_in_dict(self):
        payload = {
            "agent_name":              "INCIDENT_REVIEW",
            "authority_level":         auth.AUTHORITY_LEVEL_ADVISORY,
            "input_artifacts":         [],
            "findings":                "we should CLEAR_SAFE_MODE now",
            "risk_level":              "LOW",
            "recommendation":          "ALLOW",
            "veto_recommendation":     False,
            "confidence":              "LOW",
            "limitations":             "n/a",
            "must_not_execute_orders": True,
            "advisory_only":           True,
        }
        with self.assertRaises(ValueError):
            auth.assert_no_execution_intent(payload)

    def test_does_not_raise_on_clean_payload(self):
        out = _good_output()
        auth.assert_no_execution_intent(out)


# ─── 5. redact_secrets ─────────────────────────────────────────────────────

class TestRedactSecrets(unittest.TestCase):
    def test_redacts_sk_pattern(self):
        s = "my key is sk-ant-AAAAAAAAAAAAAAAAAA hello"
        out = auth.redact_secrets(s)
        self.assertNotIn("sk-ant-AAAA", out)
        self.assertIn("[REDACTED]", out)

    def test_redacts_openai_sk_pattern(self):
        s = "my key is sk-ABCDEFGHIJK1234567890 done"
        out = auth.redact_secrets(s)
        self.assertNotIn("sk-ABCDEFGHIJK", out)
        self.assertIn("[REDACTED]", out)

    def test_redacts_gemini_api_key_kv(self):
        s = "config: GEMINI_API_KEY=abcdef12345xyz789 end"
        out = auth.redact_secrets(s)
        self.assertIn("GEMINI_API_KEY=[REDACTED]", out)
        self.assertNotIn("abcdef12345xyz789", out)

    def test_redacts_github_pat(self):
        s = "set token to ghp_AAAAAAAAAAAAAAAAAAAA done"
        out = auth.redact_secrets(s)
        self.assertNotIn("ghp_AAAAAAAA", out)
        self.assertIn("[REDACTED]", out)


# ─── 6. AST gates — no broker imports / calls ──────────────────────────────

class TestNoBrokerImport(unittest.TestCase):
    def test_no_alpaca_orders_import(self):
        src = (REPO_ROOT / "shared"
                / "llm_advisory_authority.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertFalse(
                    node.module and "alpaca_orders" in node.module)

    def test_no_broker_function_call(self):
        src = (REPO_ROOT / "shared"
                / "llm_advisory_authority.py").read_text(
            encoding="utf-8")
        forbidden_names = {
            "submit_order", "place_order", "safe_close",
            "cancel_order", "close_position", "place_stock_order",
            "place_crypto_order", "place_option_order",
        }
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = ""
                if isinstance(node.func, ast.Name):
                    fname = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    fname = node.func.attr
                self.assertNotIn(fname, forbidden_names)


# ─── 7. Module never mutates state ─────────────────────────────────────────

class TestModuleNeverMutatesState(unittest.TestCase):
    def test_no_write_calls_to_runtime_state(self):
        # The authority module is pure validation — it must not write
        # to any state file. Cheap heuristic: no `open(...).write(`
        # call.
        src = (REPO_ROOT / "shared"
                / "llm_advisory_authority.py").read_text(
            encoding="utf-8")
        self.assertNotIn("runtime_state", src.lower())
        self.assertNotIn("write_text", src)
        self.assertNotIn("open(", src)
        self.assertNotIn("os.replace", src)


# ─── 8. validate_output accepts/rejects ────────────────────────────────────

class TestValidateOutputAccepts(unittest.TestCase):
    def test_accepts_good_output(self):
        out = _good_output()
        errs = auth.validate_output(out)
        self.assertEqual(errs, [])

    def test_accepts_good_dict(self):
        payload = {
            "agent_name":              "DAILY_BRIEF",
            "authority_level":         auth.AUTHORITY_LEVEL_ADVISORY,
            "input_artifacts":         ["briefs/2026-06-16.md"],
            "findings":                "quiet",
            "risk_level":              "LOW",
            "recommendation":          "ALLOW",
            "veto_recommendation":     False,
            "confidence":              "LOW",
            "limitations":             "advisory-only",
            "must_not_execute_orders": True,
            "advisory_only":           True,
        }
        errs = auth.validate_output(payload)
        self.assertEqual(errs, [])


class TestValidateOutputRejects(unittest.TestCase):
    def test_rejects_missing_field(self):
        payload = {"agent_name": "DAILY_BRIEF"}
        errs = auth.validate_output(payload)
        self.assertTrue(any("missing required field" in e for e in errs))

    def test_rejects_forbidden_in_dict(self):
        payload = {
            "agent_name":              "DAILY_BRIEF",
            "authority_level":         auth.AUTHORITY_LEVEL_ADVISORY,
            "input_artifacts":         ["x"],
            "findings":                "EXECUTE_ORDER now",
            "risk_level":              "LOW",
            "recommendation":          "ALLOW",
            "veto_recommendation":     False,
            "confidence":              "LOW",
            "limitations":             "",
            "must_not_execute_orders": True,
            "advisory_only":           True,
        }
        errs = auth.validate_output(payload)
        self.assertTrue(any("forbidden output token" in e
                                 for e in errs))


# ─── 9. Authority levels limited to L0/L1 ──────────────────────────────────

class TestAuthorityLevelsLimited(unittest.TestCase):
    def test_only_l0_l1_assignable(self):
        self.assertEqual(
            auth.ASSIGNABLE_AUTHORITY_LEVELS,
            frozenset({auth.AUTHORITY_LEVEL_ADVISORY,
                        auth.AUTHORITY_LEVEL_VETO_RECOMMEND}),
        )

    def test_l5_sentinel_rejected(self):
        with self.assertRaises(ValueError):
            _good_output(
                authority_level=auth.AUTHORITY_LEVEL_EXECUTE_FORBIDDEN)

    def test_unknown_authority_level_rejected(self):
        with self.assertRaises(ValueError):
            _good_output(authority_level="L99_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
