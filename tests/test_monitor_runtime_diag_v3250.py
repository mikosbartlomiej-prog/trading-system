"""v3.25 — Tests for `scripts/build_monitor_runtime_diagnostics_report.py`.

Covers:
  * synthesized fallback view when ``monitor_runtime_diag/`` is empty
  * native aggregation when JSONL diag rows ARE present
  * per-monitor table coverage (10 monitors expected)
  * v3.25 SYNTHESIZED_VIEW marker stamped in markdown
  * AST-level safety: reporter never imports ``alpaca_orders``

HARD SAFETY
-----------
Tests run entirely on tmpdir fixtures, never hit the network, never
import the broker layer, and never touch real state.json.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_monitor_runtime_diagnostics_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_monitor_runtime_diagnostics_report", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestMonitorRuntimeDiagV3250(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()
        # Hold a tmpdir so paths point into a sandbox.
        self.tmpdir = Path(tempfile.mkdtemp(prefix="diag_v325_"))
        self.diag_dir = self.tmpdir / "learning-loop" / "monitor_runtime_diag"
        self.ledger_dir = self.tmpdir / "learning-loop" / "opportunity_ledger"
        self.diag_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    # T1 — synthesized view used when diag dir empty
    # ------------------------------------------------------------------
    def test_synthesized_view_when_diag_dir_empty(self):
        # Place a single ledger row so synthesis has content.
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        row = {
            "strategy":  "crypto-momentum",
            "symbol":    "BTC/USD",
            "timestamp": f"{today}T12:00:00Z",
            "raw_signal": {"signal_state": "DETECTED"},
        }
        ledger_file = self.ledger_dir / f"{today}.jsonl"
        ledger_file.write_text(json.dumps(row) + "\n", encoding="utf-8")

        with mock.patch.object(self.mod, "LEDGER_DIR", self.ledger_dir):
            agg = self.mod._synthesize_from_ledger(days=7)

        self.assertTrue(agg.get("synthesized"))
        self.assertEqual(agg["total_rows"], 1)
        # crypto-momentum should map to crypto-monitor.
        self.assertIn("crypto-monitor", agg["per_monitor"])
        cm = agg["per_monitor"]["crypto-monitor"]
        self.assertEqual(cm["RAN"], 1)
        self.assertEqual(cm["EMIT_ATTEMPTED"], 1)
        self.assertEqual(cm["EMIT_SUCCESS"], 1)
        self.assertEqual(cm["SIGNAL_DETECTED"], 1)
        self.assertEqual(cm["INPUT_EMPTY"], 0)  # not inferrable from ledger

    # ------------------------------------------------------------------
    # T2 — native view when JSONL diag rows ARE present
    # ------------------------------------------------------------------
    def test_actual_view_when_diag_dir_populated(self):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        diag_file = self.diag_dir / f"{today}.jsonl"
        diag_file.write_text(
            json.dumps({
                "monitor":   "crypto-monitor",
                "token":     "RAN",
                "timestamp": f"{today}T08:00:00Z",
            }) + "\n"
            + json.dumps({
                "monitor":   "crypto-monitor",
                "token":     "EMIT_SUCCESS",
                "timestamp": f"{today}T08:00:01Z",
            }) + "\n",
            encoding="utf-8")

        with mock.patch.object(self.mod, "DIAG_DIR", self.diag_dir):
            files = self.mod._iter_diag_files(days=7)
            agg = self.mod._aggregate(files)

        self.assertFalse(agg.get("synthesized", False))
        self.assertEqual(agg["total_rows"], 2)
        cm = agg["per_monitor"]["crypto-monitor"]
        self.assertEqual(cm["RAN"], 1)
        self.assertEqual(cm["EMIT_SUCCESS"], 1)

    # ------------------------------------------------------------------
    # T3 — per-monitor table includes all 10 expected monitors
    # ------------------------------------------------------------------
    def test_per_monitor_table_includes_all_10_monitors(self):
        known = self.mod.KNOWN_MONITORS
        self.assertEqual(len(known), 10)
        expected = {
            "crypto-monitor", "price-monitor", "options-monitor",
            "options-exit-monitor", "exit-monitor",
            "defense-monitor", "twitter-monitor", "reddit-monitor",
            "geo-monitor", "politician-monitor",
        }
        self.assertEqual(set(known), expected)

        # Render markdown with empty aggregate — all 10 must appear.
        agg = {
            "files_scanned":   [],
            "total_rows":      0,
            "earliest_record": None,
            "latest_record":   None,
            "per_monitor":     {},
            "synthesized":     True,
        }
        md = self.mod._render_markdown(agg)
        for m in known:
            self.assertIn(f"`{m}`", md)

    # ------------------------------------------------------------------
    # T4 — v3.25 SYNTHESIZED_VIEW marker stamped in markdown
    # ------------------------------------------------------------------
    def test_reporter_writes_v325_marker(self):
        agg = {
            "files_scanned":   [],
            "total_rows":      5,
            "earliest_record": None,
            "latest_record":   None,
            "per_monitor":     {"crypto-monitor": {
                "RAN": 5, "INPUT_EMPTY": 0, "NO_SIGNAL": 3,
                "SIGNAL_DETECTED": 2, "EMIT_ATTEMPTED": 5,
                "EMIT_SUCCESS": 5, "EMIT_FAILED": 0, "UNKNOWN": 0,
            }},
            "synthesized":     True,
        }
        md = self.mod._render_markdown(agg)
        self.assertIn("v3.25 SYNTHESIZED_VIEW", md)
        self.assertIn("synthesized", md.lower())

    # ------------------------------------------------------------------
    # T5 — Reporter never imports broker layer (AST safety)
    # ------------------------------------------------------------------
    def test_no_alpaca_imports(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {
            "alpaca_orders", "place_stock_order", "place_crypto_order",
            "place_option_order", "submit_order", "safe_close",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn(
                        n.name.split(".")[-1], forbidden,
                        f"reporter must not import {n.name}")
            elif isinstance(node, ast.ImportFrom):
                mod_name = (node.module or "").split(".")[-1]
                self.assertNotIn(
                    mod_name, forbidden,
                    f"reporter must not import-from {node.module}")
                for n in node.names:
                    self.assertNotIn(
                        n.name, forbidden,
                        f"reporter must not import {n.name}")

    # ------------------------------------------------------------------
    # T6 — Status column classification logic
    # ------------------------------------------------------------------
    def test_status_column_classification(self):
        agg = {
            "files_scanned":   [],
            "total_rows":      100,
            "earliest_record": None,
            "latest_record":   None,
            "per_monitor": {
                "crypto-monitor":   {"RAN": 100, "EMIT_SUCCESS": 100,
                                     "EMIT_FAILED": 0, "INPUT_EMPTY": 0,
                                     "NO_SIGNAL": 90, "SIGNAL_DETECTED": 10,
                                     "EMIT_ATTEMPTED": 100, "UNKNOWN": 0},
                "price-monitor":    {"RAN": 5, "EMIT_SUCCESS": 0,
                                     "EMIT_FAILED": 5, "INPUT_EMPTY": 0,
                                     "NO_SIGNAL": 0, "SIGNAL_DETECTED": 0,
                                     "EMIT_ATTEMPTED": 5, "UNKNOWN": 0},
            },
            "synthesized":     True,
        }
        md = self.mod._render_markdown(agg)
        # Active monitor with successful emits.
        self.assertIn("| `crypto-monitor` |", md)
        self.assertIn("`ACTIVE`", md)
        # Degraded monitor.
        self.assertIn("| `price-monitor` |", md)
        self.assertIn("`DEGRADED`", md)
        # Silent monitor (e.g. exit-monitor).
        self.assertIn("`SILENT`", md)

    # ------------------------------------------------------------------
    # T7 — main() falls back to synthesized when diag dir empty
    # ------------------------------------------------------------------
    def test_main_falls_back_to_synthesized_when_empty(self):
        # Empty diag dir + populated ledger -> synthesized payload.
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        row = {
            "strategy":  "crypto-momentum",
            "symbol":    "BTC/USD",
            "timestamp": f"{today}T12:00:00Z",
            "raw_signal": {"signal_state": "DETECTED"},
        }
        (self.ledger_dir / f"{today}.jsonl").write_text(
            json.dumps(row) + "\n", encoding="utf-8")

        docs_out = self.tmpdir / "docs" / "MONITOR_RUNTIME_DIAGNOSTICS.md"
        json_out = self.tmpdir / "learning-loop" / "monitor_runtime_diag_status_latest.json"

        with mock.patch.object(self.mod, "DIAG_DIR", self.diag_dir), \
             mock.patch.object(self.mod, "LEDGER_DIR", self.ledger_dir), \
             mock.patch.object(self.mod, "DOCS_OUT", docs_out), \
             mock.patch.object(self.mod, "JSON_OUT", json_out):
            rc = self.mod.main()

        self.assertEqual(rc, 0)
        payload = json.loads(json_out.read_text(encoding="utf-8"))
        self.assertEqual(payload["view_mode"], "synthesized")
        self.assertEqual(payload["builder_version"], "v3.25.0")
        self.assertEqual(payload["hard_safety"]["broker_call"], False)


if __name__ == "__main__":
    unittest.main()
