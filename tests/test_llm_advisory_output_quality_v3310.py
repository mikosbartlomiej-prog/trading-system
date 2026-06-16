"""v3.31 (2026-06-16) — LLM advisory output quality report tests.

Hard safety:
- AST proof: NO broker import
- standing markers present in payload + doc
- empty agents -> EMPTY/LOW_QUALITY aggregate (never fail-open)
- deterministic fallback meets 3/2/2 minimum
- aggregate verdict computed correctly
- handles missing agent file gracefully
- 10 agents enumerated by default
- quality verdict written to JSON
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "shared"))

import build_llm_advisory_output_quality_report as mod  # noqa: E402


def _row_low_quality(agent_name: str) -> dict:
    """An agent row with 0 findings/risks/actions (LOW_QUALITY-ish)."""
    return {
        "agent_name":      agent_name,
        "advisory_only":   True,
        "must_not_execute_orders": True,
        "findings":        "",
        "risks_list":      [],
        "next_actions_list": [],
        "findings_list":   [],
        "limitations":     "",
        "provider_status": "PROVIDER_FAILED_FAIL_SOFT",
        "quality_verdict": "LLM_ADVISORY_QUALITY_EMPTY",
    }


def _row_useful(agent_name: str) -> dict:
    """An agent row meeting v3.30 thresholds."""
    return {
        "agent_name":      agent_name,
        "advisory_only":   True,
        "must_not_execute_orders": True,
        "findings_list":   ["a", "b", "c"],
        "risks_list":      ["r1", "r2"],
        "next_actions_list": ["n1", "n2"],
        "findings":        "a;b;c",
        "limitations":     "we relied on stub data",
        "provider_status": "PROVIDER_USED",
        "quality_verdict": "LLM_ADVISORY_QUALITY_ACCEPTABLE",
    }


def _write_agents(base_dir: Path, agents: dict[str, dict]) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    for name, row in agents.items():
        (base_dir / f"{name}_latest.json").write_text(
            json.dumps(row, indent=2, sort_keys=True),
            encoding="utf-8")


class TestZeroFindingsIsLowQuality(unittest.TestCase):
    def test_zero_findings_routes_to_low_quality(self):
        tmp = tempfile.TemporaryDirectory()
        bd = Path(tmp.name)
        agents = {a: _row_low_quality(a)
                  for a in mod.DEFAULT_AGENTS}
        _write_agents(bd, agents)
        payload = mod.build_report(base_dir=bd)
        # Every agent rated EMPTY (since fields are all 0).
        self.assertEqual(payload["pass_count"], 0)
        # Aggregate = EMPTY when every agent is EMPTY.
        self.assertEqual(payload["aggregate_verdict"], mod.VERDICT_EMPTY)
        tmp.cleanup()


class TestThresholdsMet(unittest.TestCase):
    def test_3_findings_2_risks_2_actions_is_useful(self):
        tmp = tempfile.TemporaryDirectory()
        bd = Path(tmp.name)
        agents = {a: _row_useful(a) for a in mod.DEFAULT_AGENTS}
        _write_agents(bd, agents)
        payload = mod.build_report(base_dir=bd)
        self.assertEqual(payload["pass_count"],
                          len(mod.DEFAULT_AGENTS))
        self.assertEqual(payload["aggregate_verdict"],
                          mod.VERDICT_USEFUL)
        tmp.cleanup()


class TestDeterministicFallbackMeetsThreshold(unittest.TestCase):
    def test_deterministic_stub_meets_v3300_thresholds(self):
        """The deterministic fallback produced by the v3.30 stub
        generator MUST score USEFUL when persisted."""
        try:
            from shared.llm_advisory_quality_v3300 import (
                deterministic_stub_lists)
        except ImportError:
            from llm_advisory_quality_v3300 import (
                deterministic_stub_lists)
        # Construct an agent row that mirrors what the v3.29 mesh
        # writes when in deterministic-fallback mode.
        stub = deterministic_stub_lists("RISK_REVIEW")
        row = {
            "agent_name":         "RISK_REVIEW",
            "advisory_only":      True,
            "must_not_execute_orders": True,
            "findings_list":      list(stub["findings_list"]),
            "risks_list":         list(stub["risks_list"]),
            "next_actions_list":  list(stub["next_actions_list"]),
            "limitations":        stub["limitations"],
            "provider_status":    "PROVIDER_NOT_INVOKED",
        }
        tmp = tempfile.TemporaryDirectory()
        bd = Path(tmp.name)
        # Use only ONE agent for clarity.
        _write_agents(bd, {"RISK_REVIEW": row})
        payload = mod.build_report(
            agents=("RISK_REVIEW",), base_dir=bd)
        self.assertEqual(payload["pass_count"], 1)
        self.assertEqual(payload["aggregate_verdict"],
                          mod.VERDICT_USEFUL)
        tmp.cleanup()


class TestAggregateMixedIsLowQuality(unittest.TestCase):
    def test_mixed_useful_and_low_quality_is_low_quality(self):
        tmp = tempfile.TemporaryDirectory()
        bd = Path(tmp.name)
        agents = {}
        for i, a in enumerate(mod.DEFAULT_AGENTS):
            if i < 5:
                agents[a] = _row_useful(a)
            else:
                agents[a] = _row_low_quality(a)
        _write_agents(bd, agents)
        payload = mod.build_report(base_dir=bd)
        self.assertEqual(
            payload["aggregate_verdict"], mod.VERDICT_LOW_QUALITY)
        tmp.cleanup()


class TestNoBrokerImportAst(unittest.TestCase):
    def test_module_does_not_import_alpaca_orders(self):
        src = (REPO_ROOT / "scripts"
                / "build_llm_advisory_output_quality_report.py"
                ).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn("alpaca_orders", n.name)
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    self.assertNotIn("alpaca_orders", node.module)


class TestStandingMarkersPresent(unittest.TestCase):
    def test_standing_markers_in_payload_and_doc(self):
        tmp = tempfile.TemporaryDirectory()
        bd = Path(tmp.name)
        _write_agents(bd, {a: _row_useful(a)
                            for a in mod.DEFAULT_AGENTS})
        payload = mod.build_report(base_dir=bd)
        for m in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "LLM_ADVISORY_ONLY",
        ):
            self.assertIn(m, payload["standing_markers"])
        doc = mod.render_doc(payload)
        for m in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "LLM_ADVISORY_ONLY",
        ):
            self.assertIn(m, doc)
        tmp.cleanup()


class TestNeverFailOpen(unittest.TestCase):
    def test_empty_base_dir_returns_empty_verdict(self):
        # When the base directory is empty, aggregate = EMPTY (NOT
        # USEFUL), so the report can never tell the operator that
        # everything is fine when nothing has actually been written.
        tmp = tempfile.TemporaryDirectory()
        bd = Path(tmp.name)
        payload = mod.build_report(base_dir=bd)
        self.assertEqual(payload["aggregate_verdict"],
                          mod.VERDICT_EMPTY)
        self.assertEqual(
            payload["missing_file_count"], len(mod.DEFAULT_AGENTS))
        tmp.cleanup()


class TestMissingAgentHandledGracefully(unittest.TestCase):
    def test_missing_one_agent_does_not_raise(self):
        tmp = tempfile.TemporaryDirectory()
        bd = Path(tmp.name)
        # Only write 9 agents; one is missing.
        agents = {a: _row_useful(a)
                  for a in mod.DEFAULT_AGENTS[:9]}
        _write_agents(bd, agents)
        payload = mod.build_report(base_dir=bd)
        self.assertEqual(payload["missing_file_count"], 1)
        # One missing -> aggregate = LOW_QUALITY (not USEFUL).
        self.assertEqual(payload["aggregate_verdict"],
                          mod.VERDICT_LOW_QUALITY)
        tmp.cleanup()


class TestTenAgentsEnumerated(unittest.TestCase):
    def test_default_agents_count_is_10(self):
        self.assertEqual(len(mod.DEFAULT_AGENTS), 10)


class TestVerdictWrittenToJson(unittest.TestCase):
    def test_payload_json_has_verdict_field(self):
        tmp = tempfile.TemporaryDirectory()
        bd = Path(tmp.name)
        _write_agents(bd, {a: _row_useful(a)
                            for a in mod.DEFAULT_AGENTS})
        payload = mod.build_report(base_dir=bd)
        # Serialise + parse to confirm the verdict survives.
        s = json.dumps(payload, sort_keys=True)
        raw = json.loads(s)
        self.assertIn("aggregate_verdict", raw)
        self.assertIn("per_agent", raw)
        self.assertTrue(all("verdict" in a for a in raw["per_agent"]))
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
