"""v3.28.3 (2026-06-09) — per-agent prompt + provider-response parsing tests."""

from __future__ import annotations

import importlib.util as iu
import json
import sys
import unittest
from pathlib import Path

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


class TestPromptBuilder(unittest.TestCase):
    def test_per_agent_prompt_is_evidence_grounded(self):
        runner = _load_runner()
        evidence = {
            "counters_latest": {
                "real_market_opportunities_count": 0,
                "completed_shadow_outcomes_count": 0,
            },
            "workflow_health_latest": {
                "verdict": "AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET",
            },
        }
        p = runner._build_prompt("MARKET_REGIME_AGENT", evidence)
        # Per-agent template appears.
        self.assertIn("MARKET_REGIME_AGENT", p)
        # Evidence values appear verbatim.
        self.assertIn("real_market_opportunities_count", p)
        self.assertIn("AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET", p)
        # Schema contract sentinel.
        self.assertIn("Return ONLY one JSON object", p)
        # Safety paragraph.
        self.assertIn("CANNOT execute", p)
        self.assertIn("insufficient evidence", p)

    def test_unknown_agent_falls_back_to_generic_l2_template(self):
        runner = _load_runner()
        p = runner._build_prompt("MADE_UP_AGENT", {})
        self.assertIn("L2 advisory agent", p)
        self.assertIn("Return ONLY one JSON object", p)


class TestProviderResponseParser(unittest.TestCase):
    def test_json_response_extracts_all_fields(self):
        runner = _load_runner()
        text = json.dumps({
            "recommendation":        "VIX 14; regime risk-on.",
            "rationale":             "Counters say 0/50; bars healthy.",
            "risks_identified":      ["data still thin"],
            "proposed_next_actions": ["await more cron ticks"],
            "confidence":            0.6,
            "veto_recommendation":   False,
        })
        out = runner._parse_provider_response_into_row_fields(text)
        self.assertEqual(out["recommendation"],
                          "VIX 14; regime risk-on.")
        self.assertEqual(out["risks_identified"], ["data still thin"])
        self.assertEqual(out["proposed_next_actions"],
                          ["await more cron ticks"])
        self.assertAlmostEqual(out["confidence"], 0.6)
        self.assertFalse(out["veto_recommendation"])

    def test_fenced_json_response_parsed(self):
        runner = _load_runner()
        text = "```json\n{\"recommendation\": \"X\", \"confidence\": 0.5}\n```"
        out = runner._parse_provider_response_into_row_fields(text)
        self.assertEqual(out["recommendation"], "X")
        self.assertAlmostEqual(out["confidence"], 0.5)

    def test_prose_response_kept_as_recommendation(self):
        runner = _load_runner()
        out = runner._parse_provider_response_into_row_fields(
            "Markets calm today; nothing to add.")
        self.assertIn("Markets calm", out["recommendation"])
        # Defaults stay safe.
        self.assertEqual(out["risks_identified"], [])
        self.assertEqual(out["proposed_next_actions"], [])
        self.assertEqual(out["confidence"], 0.0)
        self.assertFalse(out["veto_recommendation"])

    def test_empty_response_returns_insufficient_marker(self):
        runner = _load_runner()
        out = runner._parse_provider_response_into_row_fields("")
        self.assertIn("insufficient", out["recommendation"].lower())

    def test_confidence_clamped_to_unit_interval(self):
        runner = _load_runner()
        text = json.dumps({"recommendation": "x", "confidence": 99.0})
        out = runner._parse_provider_response_into_row_fields(text)
        self.assertEqual(out["confidence"], 1.0)
        text = json.dumps({"recommendation": "x", "confidence": -1.0})
        out = runner._parse_provider_response_into_row_fields(text)
        self.assertEqual(out["confidence"], 0.0)

    def test_risks_and_actions_capped(self):
        runner = _load_runner()
        text = json.dumps({
            "recommendation":        "x",
            "rationale":             "y",
            "risks_identified":      [f"r{i}" for i in range(20)],
            "proposed_next_actions": [f"a{i}" for i in range(20)],
        })
        out = runner._parse_provider_response_into_row_fields(text)
        self.assertLessEqual(len(out["risks_identified"]), 6)
        self.assertLessEqual(len(out["proposed_next_actions"]), 6)


class TestEvidenceSummaryPerAgent(unittest.TestCase):
    def test_data_quality_agent_sees_health_history(self):
        runner = _load_runner()
        evidence = {
            "workflow_health_history": [
                {"workflow_run_id": "1"}, {"workflow_run_id": "2"}],
            "first_real_record": {"first_real_market_record_seen": False},
        }
        snippet = runner._evidence_summary_for_agent(
            "DATA_QUALITY_AGENT", evidence)
        self.assertIn("workflow_health_history", snippet)
        self.assertIn("first_real_record", snippet)


if __name__ == "__main__":
    unittest.main()
