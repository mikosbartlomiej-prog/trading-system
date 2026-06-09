"""v3.28.3 (2026-06-09) — mesh runner emits quality status + artefacts."""

from __future__ import annotations

import importlib.util as iu
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
            "LLM_ADVISORY_DIR":      str(self.tmp / "advisory"),
            "LLM_BUDGET_STATE_DIR":  str(self.tmp / "advisory"),
            "LLM_AGENTS_ENABLED":    "true",
            "LLM_PROVIDER":          "offline_mock",
            "LLM_FREE_ONLY":         "true",
            "ANTHROPIC_API_KEY":     "",
            "OPENAI_API_KEY":        "",
            "GEMINI_API_KEY":        "",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestRunEmitsQualityStatus(_Iso):
    def test_mock_provider_yields_provider_not_used_quality(self):
        runner = _load_runner()
        summary = runner.run_mesh(run_id="v3283-mock-1")
        self.assertEqual(summary["status"], "LLM_ADVISORY_MESH_RAN")
        # Mock provider → all rows carry PROVIDER_SKIPPED_DISABLED →
        # quality status PROVIDER_OUTPUT_NOT_USED.
        self.assertEqual(
            summary["quality_status"],
            "LLM_ADVISORY_QUALITY_PROVIDER_OUTPUT_NOT_USED")
        qr = summary["quality_report"]
        self.assertEqual(qr["rows_with_provider_used"], 0)
        self.assertGreaterEqual(qr["rows_with_provider_skipped"], 1)


class TestEachRowCarriesProviderStatus(_Iso):
    def test_every_row_has_provider_status(self):
        runner = _load_runner()
        summary = runner.run_mesh(run_id="v3283-mock-2")
        rows_path = Path(summary["rows_path"])
        for line in rows_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            self.assertIn("provider_status", row)
            self.assertIn(row["provider_status"], (
                "PROVIDER_USED", "PROVIDER_SKIPPED_DISABLED",
                "PROVIDER_FAILED_FAIL_SOFT",
                "PROVIDER_OUTPUT_INVALID_SCHEMA"))


class TestQualityArtifactWritten(_Iso):
    def test_quality_review_artifact_written_when_render_doc(self):
        runner = _load_runner()
        # Use --render-doc path which writes quality artifact.
        buf_path = self.tmp / "advisory" / "rows.jsonl"
        # write_quality_artifact writes to REPO_ROOT/learning-loop —
        # so test by calling it directly with a summary.
        summary = {
            "run_id":        "v3283-mock-3",
            "quality_status": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
            "quality_report": {
                "rows_seen": 5,
                "rows_with_provider_used": 5,
                "rows_with_provider_skipped": 0,
                "rows_with_provider_failed": 0,
                "generic_placeholder_count": 0,
                "empty_risks_count": 0,
                "empty_next_actions_count": 0,
                "zero_confidence_count": 0,
                "confidence_min": 0.4, "confidence_max": 0.7,
                "secret_leak_hits": 0, "unsafe_phrase_hits": 0,
                "rationale": ["acceptable"],
            },
            "next_recommended_action": "trigger another run",
        }
        try:
            runner.write_quality_artifact(summary)
            qr_path = (REPO_ROOT / "learning-loop" / "llm_advisory"
                        / "quality_review_latest.json")
            self.assertTrue(qr_path.exists())
            doc_path = (REPO_ROOT / "docs"
                         / "LLM_ADVISORY_QUALITY_REVIEW.md")
            self.assertTrue(doc_path.exists())
            # Check safety block in JSON.
            data = json.loads(qr_path.read_text(encoding="utf-8"))
            self.assertTrue(
                data["safety"]["broker_paper_canary_still_blocked"])
            self.assertTrue(
                data["safety"]["live_trading_unsupported"])
            self.assertFalse(data["safety"]["schedule_enabled"])
            self.assertFalse(
                data["safety"]["llm_pre_order_veto_honored"])
        finally:
            pass  # leave the artifact for the integration step


class TestProviderUsedRowsCounted(_Iso):
    def test_gemini_success_routed_through_parser(self):
        # Mock the provider client so call_provider returns a
        # PROVIDER_CALL_OK with a JSON response.
        runner = _load_runner()
        import llm_provider_client as p

        class _OK:
            status = p.LLM_PROVIDER_CALL_OK
            provider = "gemini"
            model = "gemini-2.5-flash-lite"
            text = json.dumps({
                "recommendation":        "VIX 14; counters 0/50.",
                "rationale":             "Bars healthy; just early.",
                "risks_identified":      ["small sample"],
                "proposed_next_actions": ["await next cron"],
                "confidence":            0.5,
                "veto_recommendation":   False,
            })
            cost_usd = 0.0
            raw = None

        with mock.patch.dict(os.environ, {
            "LLM_PROVIDER":   "gemini",
            "GEMINI_API_KEY": "fake-test-only",
            "LLM_FREE_ONLY":  "true",
        }, clear=False), \
                mock.patch.object(p, "call_provider",
                                     return_value=_OK()):
            summary = runner.run_mesh(run_id="v3283-gemini-mock")
        self.assertEqual(summary["status"], "LLM_ADVISORY_MESH_RAN")
        self.assertEqual(
            summary["quality_status"],
            "LLM_ADVISORY_QUALITY_ACCEPTABLE")
        qr = summary["quality_report"]
        self.assertGreaterEqual(qr["rows_with_provider_used"], 3)


if __name__ == "__main__":
    unittest.main()
