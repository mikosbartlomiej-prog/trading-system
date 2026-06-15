"""Tests for scripts/build_post_v324_audit_report.py — v3.25 phase 2.

Hard-safety contract verified:

* The audit module NEVER imports ``alpaca_orders`` (AST check).
* The audit module NEVER opens a socket / makes a network call
  (AST check for ``requests``/``urllib``/``http``/``socket``).
* The audit reads only local files; empty windows are handled
  gracefully and exit 0 without raising.

Behaviour verified:

* Entry-capable detection from top-level + raw_signal nested.
* Observe-only classification.
* confidence_status distribution counting (including NULL sentinel).
* Avg completeness across populated rows; None when nothing populated.
* Standing markers are written to JSON output.
* Empty ledger does not crash.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_post_v324_audit_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_post_v324_audit_report", SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


class _SyntheticLedgerMixin:
    """Helper to build an isolated ledger directory for the test."""

    def _write_jsonl(self, rows, fname="2026-06-15.jsonl"):
        d = Path(self._tmp.name) / "opportunity_ledger"
        d.mkdir(parents=True, exist_ok=True)
        path = d / fname
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        return d


class TestEntryCapableClassification(unittest.TestCase, _SyntheticLedgerMixin):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mod = _load_module()

    def test_audit_classifies_entry_capable_rows(self):
        rows = [
            {
                "timestamp": "2026-06-15T12:00:00+00:00",
                "raw_signal": {
                    "signal_state": "DETECTED",
                    "entry_capable": True,
                    "confidence_status": "OK",
                },
                "confidence_score": 0.71,
                "confidence_components": {"signal_strength": 0.8},
                "schema_version": "v3.24.0",
                "strategy": "crypto-momentum",
                "source_monitor": "crypto-monitor",
            },
            {
                "timestamp": "2026-06-15T12:01:00+00:00",
                "raw_signal": {
                    "signal_state": "REJECT",
                    "entry_capable": False,
                    "confidence_status": "OBSERVE_ONLY_SKIP",
                },
                "confidence_score": None,
                "schema_version": "v3.24.0",
                "strategy": "crypto-momentum",
                "source_monitor": "crypto-monitor",
            },
        ]
        ledger_dir = self._write_jsonl(rows)
        loaded = self.mod.load_rows(
            ledger_dir, "2026-06-15T11:35:05+00:00", max_files=7
        )
        summary = self.mod.compute_audit(
            loaded["post_rows"], "2026-06-15T11:35:05+00:00",
            used_fallback=False,
        )
        self.assertEqual(summary["entry_capable"], 1)
        self.assertEqual(summary["observe_only"], 1)
        self.assertEqual(summary["entry_capable_with_score"], 1)
        self.assertEqual(summary["entry_capable_silent_null"], 0)
        self.assertEqual(summary["verdict"], "YES_FULLY")

    def test_audit_classifies_observe_only_rows(self):
        rows = [
            {
                "timestamp": "2026-06-15T12:00:00+00:00",
                "raw_signal": {
                    "signal_state": "REJECT",
                    "entry_capable": False,
                    "confidence_status": "OBSERVE_ONLY_SKIP",
                },
                "confidence_score": None,
                "schema_version": "v3.24.0",
                "strategy": "crypto-momentum",
                "source_monitor": "crypto-monitor",
            }
            for _ in range(5)
        ]
        ledger_dir = self._write_jsonl(rows)
        loaded = self.mod.load_rows(
            ledger_dir, "2026-06-15T11:35:05+00:00", max_files=7
        )
        summary = self.mod.compute_audit(
            loaded["post_rows"], "2026-06-15T11:35:05+00:00",
            used_fallback=False,
        )
        self.assertEqual(summary["entry_capable"], 0)
        self.assertEqual(summary["observe_only"], 5)
        self.assertEqual(summary["verdict"], "NO_BUT_CRON_HASNT_FIRED_YET")


class TestStatusDistribution(unittest.TestCase, _SyntheticLedgerMixin):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mod = _load_module()

    def test_audit_counts_confidence_status_distribution(self):
        rows = [
            {
                "timestamp": "2026-06-15T12:00:00+00:00",
                "raw_signal": {"signal_state": "DETECTED",
                               "entry_capable": True,
                               "confidence_status": "OK"},
                "confidence_score": 0.8,
                "confidence_components": {"x": 1},
            },
            {
                "timestamp": "2026-06-15T12:01:00+00:00",
                "raw_signal": {"signal_state": "REJECT",
                               "entry_capable": False,
                               "confidence_status": "OBSERVE_ONLY_SKIP"},
            },
            {
                "timestamp": "2026-06-15T12:02:00+00:00",
                "raw_signal": {"signal_state": "DETECTED",
                               "entry_capable": True,
                               "confidence_status": "ERROR",
                               "confidence_error": "TYPE_ERROR"},
            },
            {
                "timestamp": "2026-06-15T12:03:00+00:00",
                "raw_signal": {},
            },
        ]
        ledger_dir = self._write_jsonl(rows)
        loaded = self.mod.load_rows(
            ledger_dir, "2026-06-15T11:35:05+00:00", max_files=7
        )
        summary = self.mod.compute_audit(
            loaded["post_rows"], "2026-06-15T11:35:05+00:00",
            used_fallback=False,
        )
        dist = summary["confidence_status_distribution"]
        self.assertEqual(dist.get("OK"), 1)
        self.assertEqual(dist.get("OBSERVE_ONLY_SKIP"), 1)
        self.assertEqual(dist.get("ERROR"), 1)
        self.assertEqual(dist.get("NULL"), 1)
        # Entry-capable with ERROR is bearing (explicit failure surfaced).
        self.assertEqual(summary["entry_capable_with_error"], 1)


class TestCompleteness(unittest.TestCase, _SyntheticLedgerMixin):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mod = _load_module()

    def test_audit_computes_completeness_avg(self):
        rows = [
            {
                "timestamp": "2026-06-15T12:00:00+00:00",
                "confidence_input_completeness": 0.4,
                "raw_signal": {"entry_capable": True},
            },
            {
                "timestamp": "2026-06-15T12:01:00+00:00",
                "raw_signal": {
                    "entry_capable": True,
                    "confidence_input_completeness": 0.8,
                },
            },
            # Row with no completeness — should be ignored from avg
            {
                "timestamp": "2026-06-15T12:02:00+00:00",
                "raw_signal": {"entry_capable": False},
            },
        ]
        ledger_dir = self._write_jsonl(rows)
        loaded = self.mod.load_rows(
            ledger_dir, "2026-06-15T11:35:05+00:00", max_files=7
        )
        summary = self.mod.compute_audit(
            loaded["post_rows"], "2026-06-15T11:35:05+00:00",
            used_fallback=False,
        )
        avg = summary["confidence_input_completeness_avg"]
        self.assertIsNotNone(avg)
        self.assertAlmostEqual(avg, 0.6, places=4)


class TestStandingMarkers(unittest.TestCase, _SyntheticLedgerMixin):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mod = _load_module()

    def test_audit_writes_standing_markers(self):
        # Empty ledger, but the summary still must contain markers.
        d = Path(self._tmp.name) / "opportunity_ledger"
        d.mkdir(parents=True, exist_ok=True)
        summary = self.mod.compute_audit(
            [], "2026-06-15T11:35:05+00:00", used_fallback=True
        )
        markers = summary["standing_markers"]
        self.assertIn("EDGE_GATE_ENABLED=false", markers)
        self.assertIn("ALLOW_BROKER_PAPER=false", markers)
        self.assertIn("LIVE_TRADING_UNSUPPORTED", markers)
        self.assertIn("NO_ORDER_PLACEMENT_BY_REPORTER", markers)
        self.assertIn("NEAR_MISS_IS_NOT_TRADE_EVIDENCE", markers)
        self.assertIn("SHADOW_IS_NOT_BROKER_PAPER", markers)
        self.assertIn("LLM_ADVISORY_ONLY", markers)


class TestHardSafetyAst(unittest.TestCase):
    """AST scans guarantee the reporter has no broker / network path."""

    def setUp(self):
        self.src = SCRIPT_PATH.read_text()
        self.tree = ast.parse(self.src)

    def _imported_modules(self):
        names: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.add(node.module.split(".")[0])
        return names

    def test_audit_never_imports_alpaca_orders(self):
        names = self._imported_modules()
        self.assertNotIn("alpaca_orders", names)
        # Strip docstrings/comments and verify no real import statement
        # for alpaca_orders remains. Documentary mentions in module
        # docstring are allowed and audited by the AST-level assertion
        # above.
        for needle in (
            "import alpaca_orders", "from alpaca_orders",
            "from shared.alpaca_orders", "from shared import alpaca_orders",
            "importlib.import_module('alpaca_orders",
            'importlib.import_module("alpaca_orders',
        ):
            self.assertNotIn(
                needle, self.src,
                msg=f"forbidden alpaca_orders import '{needle}' present"
            )
        forbidden_calls = (
            "submit_order(", "place_order(", "safe_close(",
            "place_stock_order(", "place_crypto_order(",
            "place_option_order(", "close_position(",
            "close_all_positions(",
        )
        for call in forbidden_calls:
            self.assertNotIn(
                call, self.src,
                msg=f"forbidden broker call '{call}' present"
            )

    def test_audit_never_makes_network_calls(self):
        names = self._imported_modules()
        forbidden_modules = {
            "requests", "urllib", "urllib2", "urllib3", "http",
            "socket", "ssl", "aiohttp", "httpx",
        }
        for mod in forbidden_modules:
            self.assertNotIn(
                mod, names,
                msg=f"forbidden network module '{mod}' imported"
            )
        # Catch dynamic imports too.
        for needle in ("requests.get", "requests.post", "urlopen(",
                       "socket.socket", "urllib.request"):
            self.assertNotIn(
                needle, self.src,
                msg=f"forbidden network usage '{needle}' present"
            )


class TestEmptyLedgerSafe(unittest.TestCase, _SyntheticLedgerMixin):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mod = _load_module()

    def test_audit_handles_empty_ledger_safely(self):
        # No files exist in the ledger dir.
        empty_dir = Path(self._tmp.name) / "opportunity_ledger"
        empty_dir.mkdir(parents=True, exist_ok=True)
        loaded = self.mod.load_rows(
            empty_dir, "2026-06-15T11:35:05+00:00", max_files=7
        )
        self.assertEqual(loaded["post_rows"], [])
        self.assertEqual(loaded["all_rows"], [])
        # Fallback path: compute_audit with empty list + fallback=True
        summary = self.mod.compute_audit(
            [], "2026-06-15T11:35:05+00:00", used_fallback=True,
        )
        self.assertEqual(summary["rows_total"], 0)
        self.assertEqual(summary["entry_capable"], 0)
        self.assertEqual(summary["verdict"], "NO_ROWS_TO_AUDIT")
        # Render does not raise.
        md = self.mod.render_markdown(summary)
        self.assertIn("Post-v3.24 Production Audit", md)


class TestMainExits(unittest.TestCase, _SyntheticLedgerMixin):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mod = _load_module()

    def test_main_exits_zero_on_empty(self):
        empty_dir = Path(self._tmp.name) / "opportunity_ledger"
        empty_dir.mkdir(parents=True, exist_ok=True)
        rc = self.mod.main([
            "--cutoff-iso", "2026-06-15T11:35:05+00:00",
            "--ledger-dir", str(empty_dir),
            "--no-write",
        ])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
