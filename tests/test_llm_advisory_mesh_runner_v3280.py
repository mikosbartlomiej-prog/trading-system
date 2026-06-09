"""v3.28 (2026-06-09) — mesh runner tests."""

from __future__ import annotations

import importlib.util as iu
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _load_runner():
    spec = iu.spec_from_file_location(
        "run_llm_advisory_mesh",
        REPO_ROOT / "scripts" / "run_llm_advisory_mesh.py")
    mod = iu.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _Iso(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {
            "LLM_ADVISORY_DIR":  str(self.tmp / "advisory"),
            "LLM_BUDGET_STATE_DIR": str(self.tmp / "advisory"),
            "LLM_AGENTS_ENABLED": "false",
            "LLM_PROVIDER": "offline_mock",
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestDefaultDisabled(_Iso):
    def test_default_returns_skipped_disabled(self):
        runner = _load_runner()
        summary = runner.run_mesh(run_id="r-default")
        self.assertEqual(
            summary["status"],
            "LLM_ADVISORY_MESH_SKIPPED_DISABLED")
        self.assertEqual(summary["rows_written"], 0)


class TestEnabledMockWritesRows(_Iso):
    def test_enabled_mock_writes_rows(self):
        runner = _load_runner()
        with mock.patch.dict(os.environ, {"LLM_AGENTS_ENABLED": "true"},
                                clear=False):
            summary = runner.run_mesh(run_id="r-mock")
        self.assertEqual(summary["status"], "LLM_ADVISORY_MESH_RAN")
        # Budget defaults to 20 daily / 5 per-run; runner bails out
        # at the per-run cap (5).
        self.assertGreaterEqual(summary["rows_written"], 1)
        self.assertLessEqual(summary["rows_written"], 5)


class TestRefusesOnBrokerFlag(_Iso):
    def test_refuses_when_allow_broker_paper_truthy(self):
        runner = _load_runner()
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"ALLOW_BROKER_PAPER": "true"},
                                clear=False):
            with redirect_stdout(buf):
                rc = runner.main([])
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED_ALLOW_BROKER_PAPER_IS_TRUTHY",
                       buf.getvalue())


class TestRunnerDoesNotMutateRiskOrCounters(_Iso):
    def test_runner_does_not_open_risk_config(self):
        # Source-level guard.
        src = (REPO_ROOT / "scripts"
                / "run_llm_advisory_mesh.py").read_text(encoding="utf-8")
        for path in (
            "aggressive_profile.json",
            "evidence_counters_latest.json\", \"w",
            "trading_unlock_readiness",
        ):
            # Reading is fine; writing is forbidden. Crude check —
            # the runner never opens for write under these paths.
            self.assertNotIn(f'open("config/{path}", "w"', src)


class TestRunnerNeverImportsBrokerOrders(unittest.TestCase):
    def test_source_clean(self):
        src = (REPO_ROOT / "scripts"
                / "run_llm_advisory_mesh.py").read_text(encoding="utf-8")
        for tok in (
            "alpaca_orders", "safe_close",
            "place_stock_bracket", "place_crypto_order",
            "execute_stock_signal", "execute_crypto_signal",
            "submit_order", "place_order",
        ):
            self.assertNotIn(tok, src, f"forbidden: {tok}")


class TestSchemaValidationDropsInvalidRows(_Iso):
    def test_invalid_row_dropped(self):
        runner = _load_runner()
        bad = {"timestamp": "x"}  # missing nearly everything
        err = runner._validate_advisory_row(bad)
        self.assertIsNotNone(err)

    def test_row_with_advisory_only_false_rejected(self):
        runner = _load_runner()
        # Build a row that violates the advisory_only pin.
        from llm_advisory_registry import FORBIDDEN_ACTIONS  # type: ignore
        bad = {
            "timestamp": "x", "run_id": "x", "agent_name": "x",
            "authority_level": "x", "process_stage": "x",
            "advisory_only": False, "may_execute": False,
            "may_modify_risk": False,
            "may_unlock_broker_paper": False,
            "broker_order_submitted": False,
            "broker_execution_enabled": False,
            "affects_readiness_gate": False,
            "evidence_refs": [], "input_summary": "x",
            "recommendation": "x", "veto_recommendation": False,
            "confidence": 0.0, "rationale": "x",
            "risks_identified": [], "proposed_next_actions": [],
            "forbidden_actions_confirmed": list(FORBIDDEN_ACTIONS),
        }
        err = runner._validate_advisory_row(bad)
        self.assertIn("advisory_only", err)


if __name__ == "__main__":
    unittest.main()
