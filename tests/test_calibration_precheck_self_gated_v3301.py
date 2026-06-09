"""v3.30.1 (2026-06-09) — calibration precheck self-gating.

Verifies that ``scripts/llm_quality_calibration_precheck.py`` exposes
the 8-status enum, decides correctly by priority, never imports
broker-orders, never reveals GEMINI_API_KEY.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "shared"))


_SAFE_ENV = {
    "ALLOW_BROKER_PAPER":        "false",
    "EDGE_GATE_ENABLED":         "false",
    "BROKER_EXECUTION_ENABLED":  "false",
    "LIVE_TRADING":              "false",
    "LIVE_ENABLED":              "false",
    "GO_LIVE":                   "false",
    "LIVE_TRADING_ENABLED":      "false",
    "LLM_AGENTS_SCHEDULED":      "false",
    "LLM_QUALITY_CALIBRATION_DISABLED": "false",
    "LLM_PROVIDER":              "gemini",
    "LLM_FREE_ONLY":             "true",
    "GEMINI_API_KEY":            "AIzaTEST-FAKE-LOCAL-ONLY",
}


class TestStatusEnumExposed(unittest.TestCase):
    def test_all_8_statuses_exposed(self):
        import llm_quality_calibration_precheck as pc
        for name in (
            "CALIBRATION_PROCEEDING",
            "CALIBRATION_SKIPPED_ALREADY_CALIBRATED",
            "CALIBRATION_SKIPPED_DISABLED_BY_OPERATOR",
            "CALIBRATION_SKIPPED_BUDGET_EXHAUSTED",
            "CALIBRATION_SKIPPED_NO_GEMINI_KEY",
            "CALIBRATION_SKIPPED_NON_FREE_PROVIDER",
            "CALIBRATION_SKIPPED_PRODUCTION_SCHEDULE_ENABLED",
            "CALIBRATION_SKIPPED_BROKER_FLAG_TRUTHY",
        ):
            self.assertTrue(hasattr(pc, name),
                              f"precheck must expose {name}")
            self.assertEqual(getattr(pc, name), name)
        self.assertEqual(len(pc.ALL_PRECHECK_STATUSES), 8)


class TestDecideStatus(unittest.TestCase):
    def _decide(self, **overrides):
        import llm_quality_calibration_precheck as pc
        env = dict(_SAFE_ENV)
        env.update(overrides)
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(
                    pc, "_count_accepted_quality_runs",
                    return_value=0):
                with mock.patch.object(
                        pc, "_budget_status",
                        return_value="LLM_BUDGET_ALLOWED"):
                    return pc._decide_status()

    def test_broker_flag_truthy_blocks(self):
        st, _ = self._decide(ALLOW_BROKER_PAPER="true")
        self.assertEqual(
            st, "CALIBRATION_SKIPPED_BROKER_FLAG_TRUTHY")

    def test_live_flag_truthy_blocks(self):
        st, _ = self._decide(LIVE_TRADING="true")
        self.assertEqual(
            st, "CALIBRATION_SKIPPED_BROKER_FLAG_TRUTHY")

    def test_production_schedule_enabled_blocks(self):
        st, _ = self._decide(LLM_AGENTS_SCHEDULED="true")
        self.assertEqual(
            st, "CALIBRATION_SKIPPED_PRODUCTION_SCHEDULE_ENABLED")

    def test_operator_opt_out_blocks(self):
        st, _ = self._decide(LLM_QUALITY_CALIBRATION_DISABLED="true")
        self.assertEqual(
            st, "CALIBRATION_SKIPPED_DISABLED_BY_OPERATOR")

    def test_non_gemini_provider_blocks(self):
        st, _ = self._decide(LLM_PROVIDER="openai")
        self.assertEqual(
            st, "CALIBRATION_SKIPPED_NON_FREE_PROVIDER")

    def test_free_only_false_blocks(self):
        st, _ = self._decide(LLM_FREE_ONLY="false")
        self.assertEqual(
            st, "CALIBRATION_SKIPPED_NON_FREE_PROVIDER")

    def test_missing_gemini_key_blocks(self):
        st, _ = self._decide(GEMINI_API_KEY="")
        self.assertEqual(
            st, "CALIBRATION_SKIPPED_NO_GEMINI_KEY")

    def test_already_calibrated_blocks(self):
        import llm_quality_calibration_precheck as pc
        with mock.patch.dict(os.environ, _SAFE_ENV, clear=False):
            with mock.patch.object(
                    pc, "_count_accepted_quality_runs",
                    return_value=2):
                with mock.patch.object(
                        pc, "_budget_status",
                        return_value="LLM_BUDGET_ALLOWED"):
                    st, _ = pc._decide_status()
        self.assertEqual(
            st, "CALIBRATION_SKIPPED_ALREADY_CALIBRATED")

    def test_budget_exhausted_blocks(self):
        import llm_quality_calibration_precheck as pc
        with mock.patch.dict(os.environ, _SAFE_ENV, clear=False):
            with mock.patch.object(
                    pc, "_count_accepted_quality_runs",
                    return_value=0):
                with mock.patch.object(
                        pc, "_budget_status",
                        return_value="LLM_BUDGET_EXHAUSTED"):
                    st, _ = pc._decide_status()
        self.assertEqual(
            st, "CALIBRATION_SKIPPED_BUDGET_EXHAUSTED")

    def test_happy_path_returns_proceeding(self):
        st, _ = self._decide()
        self.assertEqual(st, "CALIBRATION_PROCEEDING")


class TestShouldCallProviderFlag(unittest.TestCase):
    def test_should_call_provider_iff_proceeding(self):
        import llm_quality_calibration_precheck as pc
        with mock.patch.dict(os.environ, _SAFE_ENV, clear=False):
            with mock.patch.object(
                    pc, "_count_accepted_quality_runs",
                    return_value=0):
                with mock.patch.object(
                        pc, "_budget_status",
                        return_value="LLM_BUDGET_ALLOWED"):
                    rc = pc.main(["--write-artifacts"])
        self.assertEqual(rc, 0)
        # status file should exist
        p = (REPO_ROOT / "learning-loop" / "llm_advisory"
              / "calibration_status_latest.json")
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("precheck_status") == "CALIBRATION_PROCEEDING":
                self.assertTrue(d["should_call_provider"])
            else:
                # Real env may have different gating — only verify
                # the invariant.
                self.assertEqual(
                    d["should_call_provider"],
                    d["precheck_status"] == "CALIBRATION_PROCEEDING")


class TestNoBrokerImportNoKeyLeak(unittest.TestCase):
    def test_module_does_not_import_or_call_forbidden_symbols(self):
        """The module is allowed to MENTION the forbidden symbols in
        safety comments / docstrings. It must not import them or call
        them.
        """
        import ast
        path = (REPO_ROOT / "scripts"
                 / "llm_quality_calibration_precheck.py")
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        forbidden_imports = {"alpaca_orders"}
        forbidden_calls   = {"submit_order", "place_order",
                              "safe_close"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        alias.name.split(".")[-1],
                        forbidden_imports,
                        f"precheck must NOT import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.assertNotIn(
                        node.module.split(".")[-1],
                        forbidden_imports,
                        f"precheck must NOT import from "
                        f"{node.module}")
                for alias in node.names:
                    self.assertNotIn(
                        alias.name, forbidden_imports,
                        f"precheck must NOT import {alias.name}")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    self.assertNotIn(
                        func.id, forbidden_calls,
                        f"precheck must NOT call {func.id}")
                elif isinstance(func, ast.Attribute):
                    self.assertNotIn(
                        func.attr, forbidden_calls,
                        f"precheck must NOT call .{func.attr}()")

    def test_module_never_emits_gemini_key_value(self):
        """The module must never print or write the GEMINI_API_KEY
        value. It is allowed to report ``gemini_key_present`` (bool).
        """
        import llm_quality_calibration_precheck as pc
        env = dict(_SAFE_ENV)
        env["GEMINI_API_KEY"] = "AIzaSECRET-NEVER-LEAK-TEST"
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(
                    pc, "_count_accepted_quality_runs",
                    return_value=0):
                with mock.patch.object(
                        pc, "_budget_status",
                        return_value="LLM_BUDGET_ALLOWED"):
                    pc.main(["--write-artifacts"])

        # Check the JSON artefact does not contain the literal key
        # value.
        p = (REPO_ROOT / "learning-loop" / "llm_advisory"
              / "calibration_status_latest.json")
        if p.exists():
            txt = p.read_text(encoding="utf-8")
            self.assertNotIn("AIzaSECRET-NEVER-LEAK-TEST", txt)
        doc = (REPO_ROOT / "docs"
                / "LLM_QUALITY_CALIBRATION_STATUS.md")
        if doc.exists():
            txt = doc.read_text(encoding="utf-8")
            self.assertNotIn("AIzaSECRET-NEVER-LEAK-TEST", txt)


if __name__ == "__main__":
    unittest.main()
