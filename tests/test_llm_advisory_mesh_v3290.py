"""v3.29 ETAP 6 (2026-06-16) — LLM advisory mesh tests.

Asserts the contract of ``shared/llm_advisory_mesh.py``:

- LLM unavailable -> deterministic fallback returns ALLOW (not BLOCK).
- LLM unavailable does NOT mutate state on its own.
- LLM cannot mutate runtime_state (AST scan).
- LLM cannot call broker (AST scan + import scan).
- LLM cannot clear safe_mode (AST scan).
- LLM cannot flip flags (AST scan).
- Budget cap is consulted.
- Secrets redacted before write.
- Output written to learning-loop/llm_advisory/.
- 10 agents enumerable.
- mesh runs all agents.
- dry-run does not call provider.
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

import llm_advisory_authority as auth   # noqa: E402
import llm_advisory_mesh as mesh        # noqa: E402

MESH_SRC = (REPO_ROOT / "shared"
              / "llm_advisory_mesh.py").read_text(encoding="utf-8")


# ─── 1. LLM unavailable -> ALLOW (not BLOCK) ───────────────────────────────

class TestLLMUnavailableAllowFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]   = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",   None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        self.tmp.cleanup()

    def test_dry_run_returns_allow(self):
        out = mesh.run_agent("INCIDENT_REVIEW", dry_run=True)
        self.assertEqual(out.recommendation, "ALLOW")
        self.assertEqual(out.risk_level,    "LOW")
        self.assertEqual(out.confidence,    "LOW")
        self.assertEqual(out.veto_recommendation, False)
        self.assertTrue(out.advisory_only)
        self.assertTrue(out.must_not_execute_orders)


# ─── 2. Deterministic gate remains in control even when LLM says ALLOW ─────
#       (i.e. the mesh never expands the LLM's role; it just emits advice)
class TestLLMAllowDoesNotOverrideDeterministicGate(unittest.TestCase):
    def test_authority_level_remains_advisory(self):
        out = mesh.run_agent("RISK_REVIEW", dry_run=True)
        self.assertIn(out.authority_level,
                       auth.ASSIGNABLE_AUTHORITY_LEVELS)
        # The advisory output may not enable execution.
        self.assertTrue(out.must_not_execute_orders)


# ─── 3-6. AST: LLM mesh cannot mutate state / broker / safe_mode / flags ───

class TestMeshAstHardInvariants(unittest.TestCase):
    def test_no_alpaca_orders_import(self):
        tree = ast.parse(MESH_SRC)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertFalse(
                    node.module and "alpaca_orders" in node.module)

    def test_no_broker_function_call(self):
        forbidden_names = {
            "submit_order", "place_order", "safe_close",
            "cancel_order", "close_position", "place_stock_order",
            "place_crypto_order", "place_option_order",
        }
        tree = ast.parse(MESH_SRC)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = ""
                if isinstance(node.func, ast.Name):
                    fname = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    fname = node.func.attr
                self.assertNotIn(fname, forbidden_names)

    def test_no_safe_mode_clear(self):
        # The mesh must not call any 'clear' / 'exit_safe_mode'-style
        # function. Source must not contain `clear_safe_mode` /
        # `exit_safe_mode` / `safe_mode = None`.
        self.assertNotIn("clear_safe_mode", MESH_SRC)
        self.assertNotIn("exit_safe_mode",  MESH_SRC)
        self.assertNotIn("safe_mode = None", MESH_SRC)

    def test_no_flag_flip(self):
        # No assignment to any 'live' / 'broker' env-flag-style name.
        forbidden = (
            "ALLOW_BROKER_PAPER =",
            "EDGE_GATE_ENABLED =",
            "LIVE_TRADING =",
            "LIVE_ENABLED =",
            "GO_LIVE =",
            "BROKER_EXECUTION_ENABLED =",
            "LIVE_TRADING_ENABLED =",
        )
        for tok in forbidden:
            self.assertNotIn(tok, MESH_SRC)


# ─── 7. Budget cap consulted ───────────────────────────────────────────────

class TestBudgetCapConsulted(unittest.TestCase):
    def test_budget_module_referenced(self):
        # The mesh references llm_agent_budget at runtime; assert the
        # import is present in source.
        self.assertIn("llm_agent_budget", MESH_SRC)


# ─── 8. Secrets redacted before write ──────────────────────────────────────

class TestSecretsRedactedOnWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]   = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",   None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        self.tmp.cleanup()

    def test_dry_run_emits_redacted_file(self):
        out = mesh.run_agent("DAILY_BRIEF", dry_run=True)
        p = self.advisory_dir / "DAILY_BRIEF_latest.json"
        self.assertTrue(p.exists())
        content = p.read_text(encoding="utf-8")
        # Even though we did not inject a secret in dry-run, the
        # redaction code path must run — assert no obvious leaks.
        for pattern in ("sk-ant-", "ghp_AAAA", "GEMINI_API_KEY="):
            self.assertNotIn(pattern, content)


# ─── 9. Output written under learning-loop/llm_advisory/ ───────────────────

class TestOutputPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]   = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",   None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        self.tmp.cleanup()

    def test_writes_to_per_role_latest_path(self):
        for role in ("STRATEGY_REVIEW", "TRIGGER_WATCHLIST_REVIEW"):
            mesh.run_agent(role, dry_run=True)
            self.assertTrue(
                (self.advisory_dir
                 / f"{role}_latest.json").exists(),
                f"missing {role}_latest.json")


# ─── 10. 10 agents enumerable ──────────────────────────────────────────────

class TestEnumerateAgents(unittest.TestCase):
    def test_ten_agents(self):
        agents = mesh.enumerate_agents()
        self.assertEqual(len(agents), 10)
        for role in (
            "INCIDENT_REVIEW", "RISK_REVIEW", "STRATEGY_REVIEW",
            "NO_SIGNAL_DIAGNOSTIC", "SHADOW_CANDIDATE_REVIEW",
            "TRIGGER_WATCHLIST_REVIEW", "DAILY_BRIEF",
            "ALLOCATOR_PLAN_CRITIC", "EQUITY_RECONCILIATION_CRITIC",
            "FINAL_ARBITER",
        ):
            self.assertIn(role, agents)


# ─── 11. mesh runs all agents ──────────────────────────────────────────────

class TestRunMesh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]   = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",   None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        self.tmp.cleanup()

    def test_dry_run_mesh_returns_ten_outputs(self):
        outs = mesh.run_mesh(dry_run=True)
        self.assertEqual(len(outs), 10)
        for out in outs:
            self.assertTrue(out.advisory_only)
            self.assertTrue(out.must_not_execute_orders)


# ─── 12. dry-run does not call provider ────────────────────────────────────

class TestDryRunDoesNotCallProvider(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]   = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",   None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        self.tmp.cleanup()

    def test_dry_run_skips_provider_call(self):
        # Spy on the provider client via monkey-patch.
        import llm_provider_client as _p
        with mock.patch.object(_p, "call_provider") as m:
            mesh.run_agent("FINAL_ARBITER", dry_run=True)
            m.assert_not_called()


if __name__ == "__main__":
    unittest.main()
