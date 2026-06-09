"""v3.29.1 (2026-06-09) — advisory rows carry evidence_values_used."""

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


class TestPromptFooterRequiresEvidenceValues(unittest.TestCase):
    def test_footer_mentions_evidence_values_used(self):
        runner = _load_runner()
        self.assertIn("evidence_values_used",
                       runner._AGENT_PROMPT_FOOTER)
        self.assertIn("AT LEAST ONE item",
                       runner._AGENT_PROMPT_FOOTER)
        self.assertIn("'insufficient evidence because",
                       runner._AGENT_PROMPT_FOOTER)


class TestParserExtractsEvidenceValues(unittest.TestCase):
    def test_evidence_values_kept(self):
        runner = _load_runner()
        text = json.dumps({
            "recommendation":        "Do not unlock; first_real=false.",
            "rationale":             "Counters show 0/50.",
            "risks_identified":      ["data still thin"],
            "proposed_next_actions": ["await more cron ticks"],
            "confidence":            0.4,
            "veto_recommendation":   False,
            "evidence_values_used": {
                "first_real_market_record_seen": False,
                "real_market_opportunities_count": 0,
            },
        })
        out = runner._parse_provider_response_into_row_fields(text)
        self.assertIn("evidence_values_used", out)
        self.assertEqual(
            out["evidence_values_used"][
                "first_real_market_record_seen"], False)
        self.assertEqual(
            out["evidence_values_used"][
                "real_market_opportunities_count"], 0)


class TestSchemaAllowsEvidenceValuesUsed(unittest.TestCase):
    def test_schema_property_present(self):
        schema = json.loads(
            (REPO_ROOT / "learning-loop" / "llm_advisory"
             / "schema.json").read_text(encoding="utf-8"))
        self.assertIn("evidence_values_used",
                       schema["properties"])


class TestQualityGuardDowngradesNoEvidenceValues(unittest.TestCase):
    def test_no_evidence_values_yields_no_evidence_values_status(self):
        import llm_advisory_quality as q
        rows = []
        for i in range(3):
            rows.append({
                "recommendation": f"concrete-{i}",
                "rationale": "details",
                "risks_identified": ["x"],
                "proposed_next_actions": ["y"],
                "confidence": 0.5,
                "advisory_only": True,
                "may_execute": False,
                "broker_order_submitted": False,
                "affects_readiness_gate": False,
                "agent_name": f"A{i}",
                "provider_status": "PROVIDER_USED",
                "evidence_values_used": {},
            })
        rep = q.evaluate_quality(rows)
        self.assertEqual(
            rep.status,
            q.LLM_ADVISORY_QUALITY_NO_EVIDENCE_VALUES_USED)


class TestQualityGuardAcceptableWithEvidenceValues(unittest.TestCase):
    def test_concrete_with_evidence_values_passes(self):
        import llm_advisory_quality as q
        rows = []
        for i in range(3):
            rows.append({
                "recommendation": f"concrete-{i}",
                "rationale": "details",
                "risks_identified": ["x"],
                "proposed_next_actions": ["y"],
                "confidence": 0.5,
                "advisory_only": True,
                "may_execute": False,
                "broker_order_submitted": False,
                "affects_readiness_gate": False,
                "agent_name": f"A{i}",
                "provider_status": "PROVIDER_USED",
                "evidence_values_used": {
                    "first_real_market_record_seen": False},
            })
        rep = q.evaluate_quality(rows)
        self.assertEqual(rep.status,
                          q.LLM_ADVISORY_QUALITY_ACCEPTABLE)


class TestEmptyAnalysisStatus(unittest.TestCase):
    def test_all_empty_yields_empty_analysis(self):
        import llm_advisory_quality as q
        rows = []
        for i in range(3):
            rows.append({
                "recommendation": "x",
                "rationale": "y",
                "risks_identified": [],
                "proposed_next_actions": [],
                "confidence": 0.0,
                "advisory_only": True, "may_execute": False,
                "broker_order_submitted": False,
                "affects_readiness_gate": False,
                "agent_name": f"A{i}",
                "provider_status": "PROVIDER_USED",
            })
        rep = q.evaluate_quality(rows)
        self.assertEqual(rep.status,
                          q.LLM_ADVISORY_QUALITY_EMPTY_ANALYSIS)


if __name__ == "__main__":
    unittest.main()
