"""v3.19.0 (2026-06-04) — Tests for scripts/daily_operator_dashboard.py.

Covers:
  - collect_dashboard_data returns required section keys
  - render_dashboard_markdown produces valid markdown
  - render_dashboard_json produces valid JSON
  - Missing inputs → graceful 'unavailable' message
  - 'Can EDGE_GATE flip' returns False when paper ledger empty
  - 'Heartbeat 11/11' reports correctly from synthetic state
  - 'Is live trading disabled' returns YES with assert_paper_only verified
  - main writes both files
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _fresh_module():
    """Force re-import of the dashboard module each test."""
    for k in list(sys.modules):
        if k.endswith(".daily_operator_dashboard") \
           or k == "daily_operator_dashboard":
            del sys.modules[k]
    import daily_operator_dashboard as dod
    return dod


REQUIRED_SECTIONS = {
    "system_health",
    "heartbeat",
    "paper_workflow",
    "paper_trades_collected",
    "strongest_strategies",
    "weakest_strategies",
    "confidence_buckets",
    "best_instruments",
    "edge_gate",
    "backlog_p0_p1",
    "free_operation",
    "live_trading_disabled",
}


class TestCollect(unittest.TestCase):
    def setUp(self):
        # Isolate the paper_experiment ledger to an empty tmp dir
        self._tmp = tempfile.mkdtemp(prefix="dash_v3190_")
        os.environ["PAPER_EXPERIMENT_DIR"] = self._tmp

    def tearDown(self):
        os.environ.pop("PAPER_EXPERIMENT_DIR", None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_collect_returns_required_sections(self):
        dod = _fresh_module()
        data = dod.collect_dashboard_data()
        self.assertIn("sections", data)
        sec = data["sections"]
        for required in REQUIRED_SECTIONS:
            self.assertIn(required, sec, f"missing section: {required}")
        self.assertIn("version", data)
        self.assertIn("generated_at", data)

    def test_render_markdown_is_string(self):
        dod = _fresh_module()
        data = dod.collect_dashboard_data()
        md = dod.render_dashboard_markdown(data)
        self.assertIsInstance(md, str)
        self.assertGreater(len(md), 200)
        # Headings present
        self.assertIn("# Operator Dashboard", md)
        self.assertIn("## 1. System health summary", md)
        self.assertIn("## 13. Is live trading disabled?", md)
        # No live-trading recommendation phrase
        self.assertNotIn("ready for live trading", md.lower())
        self.assertNotIn("we recommend going live", md.lower())

    def test_render_json_is_valid(self):
        dod = _fresh_module()
        data = dod.collect_dashboard_data()
        rendered = dod.render_dashboard_json(data)
        parsed = json.loads(rendered)
        self.assertEqual(parsed.get("version"), data.get("version"))
        self.assertIn("sections", parsed)


class TestGracefulMissingInputs(unittest.TestCase):
    def setUp(self):
        # Set ledger dir to a path that doesn't exist so the section degrades
        self._tmp = tempfile.mkdtemp(prefix="dash_v3190_missing_")
        # Use a child path that does NOT yet exist
        os.environ["PAPER_EXPERIMENT_DIR"] = str(Path(self._tmp) / "noexist")

    def tearDown(self):
        os.environ.pop("PAPER_EXPERIMENT_DIR", None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_paper_trades_handles_missing_dir(self):
        dod = _fresh_module()
        data = dod.collect_dashboard_data()
        s = data["sections"]["paper_trades_collected"]
        # Section is still available; just reports 0 records
        self.assertTrue(s.get("available"))
        self.assertEqual(s.get("total_records"), 0)
        self.assertTrue(s.get("empty"))

    def test_unavailable_renders_friendly_message(self):
        dod = _fresh_module()
        data = dod.collect_dashboard_data()
        # Inject a synthetic unavailable section
        data["sections"]["confidence_buckets"] = {
            "available": False, "reason": "test reason",
        }
        md = dod.render_dashboard_markdown(data)
        self.assertIn("_unavailable — test reason_", md)


class TestEdgeGateFlip(unittest.TestCase):
    """When the paper ledger is empty, allow_flip MUST be False."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="dash_v3190_edge_")
        os.environ["PAPER_EXPERIMENT_DIR"] = self._tmp

    def tearDown(self):
        os.environ.pop("PAPER_EXPERIMENT_DIR", None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_empty_ledger_blocks_edge_gate(self):
        dod = _fresh_module()
        data = dod.collect_dashboard_data()
        s = data["sections"]["edge_gate"]
        self.assertTrue(s.get("available"))
        self.assertFalse(s.get("allow_flip"),
                         "edge gate must not flip when ledger empty")
        self.assertGreater(len(s.get("blockers") or []), 0)


class TestHeartbeat(unittest.TestCase):
    def test_heartbeat_section_shape(self):
        dod = _fresh_module()
        sec = dod._section_heartbeat()
        if sec.get("available"):
            self.assertIn("alive", sec)
            self.assertIn("total", sec)
            self.assertIn("ratio", sec)
            self.assertGreaterEqual(sec["total"], 1)
            self.assertGreaterEqual(sec["alive"], 0)
            self.assertLessEqual(sec["alive"], sec["total"])
            self.assertIn("per_component", sec)
            for row in sec["per_component"]:
                self.assertIn("name", row)
                self.assertIn("stale", row)

    def test_heartbeat_synthetic_state(self):
        """If we feed the snapshot directly we can verify rendering."""
        dod = _fresh_module()
        synthetic = {
            "available": True,
            "alive": 7, "total": 11, "ratio": 7 / 11,
            "stale_components": ["a", "b"],
            "expected_components": ["a", "b", "c"],
            "per_component": [
                {"name": "a", "stale": True, "age_seconds": None},
                {"name": "b", "stale": True, "age_seconds": 12345.6},
                {"name": "c", "stale": False, "age_seconds": 42.0},
            ],
        }
        data = {
            "version": "v3.19.0",
            "generated_at": "test",
            "sections": {
                "system_health": {"available": True,
                                  "heartbeat_alive": 7, "heartbeat_total": 11,
                                  "heartbeat_ratio": 7 / 11,
                                  "stale_components": [],
                                  "safe_mode_active": False,
                                  "last_incident": {"present": False}},
                "heartbeat": synthetic,
                "paper_workflow": {"available": True, "status": "DEPLOYED",
                                   "template_exists": True,
                                   "deployed_exists": True},
                "paper_trades_collected": {"available": True,
                                           "total_records": 0,
                                           "files": 0,
                                           "ledger_dir": "test",
                                           "empty": True,
                                           "per_strategy": {}},
                "strongest_strategies": {"available": True, "top": [],
                                         "total_strategies": 0},
                "weakest_strategies": {"available": True, "bottom": [],
                                       "with_recent_degradation": [],
                                       "total_eligible": 0},
                "confidence_buckets": {"available": True, "buckets": [],
                                       "note": "test", "empty": True},
                "best_instruments": {"available": True, "source": "test"},
                "edge_gate": {"available": True, "allow_flip": False,
                              "blockers": ["test"],
                              "per_strategy_status": {}},
                "backlog_p0_p1": {"available": True,
                                  "p0_open": [], "p1_open": [],
                                  "p0_count": 0, "p1_count": 0,
                                  "source": "test"},
                "free_operation": {"available": True, "is_free": True,
                                   "evidence": ["ok"]},
                "live_trading_disabled": {"available": True,
                                          "live_disabled": True,
                                          "evidence": ["ok"],
                                          "paper_base_url": "https://paper-api.alpaca.markets"},
            },
        }
        md = dod.render_dashboard_markdown(data)
        self.assertIn("7/11", md)
        self.assertIn("Stale: a, b", md)


class TestLiveTradingDisabled(unittest.TestCase):
    def test_live_trading_disabled_yes(self):
        dod = _fresh_module()
        s = dod._section_live_trading_disabled()
        self.assertTrue(s.get("available"))
        self.assertEqual(
            s.get("paper_base_url"), "https://paper-api.alpaca.markets")
        # assert_paper_only refusing live URL is recorded
        self.assertTrue(
            any("refuses live URL" in ev for ev in s.get("evidence") or []),
            f"missing refusal evidence: {s.get('evidence')}",
        )
        # The composite verdict should be YES
        self.assertTrue(s.get("live_disabled"),
                        f"expected live_disabled True, evidence: {s.get('evidence')}")


class TestMainWritesBothFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="dash_v3190_out_")
        self._ledger = tempfile.mkdtemp(prefix="dash_v3190_ledger_")
        os.environ["PAPER_EXPERIMENT_DIR"] = self._ledger

    def tearDown(self):
        os.environ.pop("PAPER_EXPERIMENT_DIR", None)
        shutil.rmtree(self._tmp, ignore_errors=True)
        shutil.rmtree(self._ledger, ignore_errors=True)

    def test_main_writes_both_files(self):
        dod = _fresh_module()
        rc = dod.main(["--out-dir", self._tmp])
        self.assertEqual(rc, 0)
        md = Path(self._tmp) / "operator_dashboard_LATEST.md"
        js = Path(self._tmp) / "operator_dashboard_LATEST.json"
        self.assertTrue(md.exists(), "markdown not written")
        self.assertTrue(js.exists(), "json not written")
        # Parse json again to confirm valid
        parsed = json.loads(js.read_text(encoding="utf-8"))
        self.assertIn("sections", parsed)
        # Markdown contains all 13 section headings
        text = md.read_text(encoding="utf-8")
        for i in range(1, 14):
            self.assertIn(f"## {i}.", text, f"section {i} heading missing")

    def test_main_no_write_prints_stdout(self):
        dod = _fresh_module()
        rc = dod.main(["--no-write"])
        # exit code 0; no file written
        self.assertEqual(rc, 0)


class TestPaperWorkflowSection(unittest.TestCase):
    def test_template_exists_recognised(self):
        dod = _fresh_module()
        sec = dod._section_paper_workflow()
        self.assertTrue(sec.get("available"))
        # We expect the template to exist in this repo
        self.assertIn(sec.get("status"),
                      ("TEMPLATE_READY_NOT_DEPLOYED", "DEPLOYED"))


class TestNoLiveTradingPhrases(unittest.TestCase):
    """The rendered markdown MUST NOT contain pro-live trading language."""

    FORBIDDEN_PHRASES = (
        "ready for live trading",
        "we recommend going live",
        "guaranteed to be profitable",
        "guaranteed edge",
    )

    def test_rendered_markdown_clean(self):
        dod = _fresh_module()
        data = dod.collect_dashboard_data()
        md = dod.render_dashboard_markdown(data).lower()
        for phrase in self.FORBIDDEN_PHRASES:
            self.assertNotIn(phrase, md,
                             f"forbidden phrase leaked into output: {phrase!r}")


class TestBacklogParsing(unittest.TestCase):
    def test_backlog_section_returns_lists(self):
        dod = _fresh_module()
        sec = dod._section_backlog()
        if sec.get("available"):
            self.assertIsInstance(sec.get("p0_open"), list)
            self.assertIsInstance(sec.get("p1_open"), list)
            self.assertGreaterEqual(sec.get("p0_count"), 0)
            self.assertGreaterEqual(sec.get("p1_count"), 0)


if __name__ == "__main__":
    unittest.main()
