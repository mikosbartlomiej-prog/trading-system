"""v3.23.0 (2026-06-15) — Agent 3C — Monitor emission status reporter tests.

Verify the per-monitor emission status reporter:

  * Returns a structured report with every monitor in scope.
  * Reads the opportunity_ledger and attributes rows via the
    ``STRATEGY_TO_MONITOR`` map (and the ``twitter-*`` prefix rule).
  * Detects the ``emit_signal_opportunity`` / ``emit_monitor_signal``
    marker correctly.
  * Picks the right verdict per row (ACTIVE / WIRED_BUT_NOT_FIRING /
    DORMANT / NOT_APPLICABLE).
  * Writes the artefacts to the right paths (JSON + Markdown).
  * Never references any broker function (HARD SAFETY guard).

Run:
    python3 -m unittest tests.test_monitor_emission_status_v3230 -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "build_monitor_emission_status.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_monitor_emission_status_v3230", str(_SCRIPT_PATH)
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestMonitorEmissionStatusReporter(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()

    # ── 1. Structure ─────────────────────────────────────────────────────
    def test_evaluate_returns_required_top_level_keys(self) -> None:
        report = self.mod.evaluate(now=datetime(2026, 6, 15, tzinfo=timezone.utc))
        for k in ("generated_at_iso", "window_days", "summary",
                  "monitors", "safety", "standing_markers", "version"):
            self.assertIn(k, report, f"missing top-level key: {k}")
        self.assertEqual(report["version"], "v3.23.0")
        # All 10 monitors must be present.
        self.assertEqual(len(report["monitors"]), 10)
        monitor_names = {row["monitor"] for row in report["monitors"]}
        for expected in (
            "price-monitor", "options-monitor", "crypto-monitor",
            "defense-monitor", "twitter-monitor", "reddit-monitor",
            "geo-monitor", "politician-monitor", "exit-monitor",
            "options-exit-monitor",
        ):
            self.assertIn(expected, monitor_names)

    # ── 2. Attribution map ───────────────────────────────────────────────
    def test_strategy_to_monitor_map_covers_known_strategies(self) -> None:
        m = self.mod.STRATEGY_TO_MONITOR
        for strategy, expected_monitor in (
            ("crypto-momentum", "crypto-monitor"),
            ("crypto-breakdown", "crypto-monitor"),
            ("crypto-oversold-bounce", "crypto-monitor"),
            ("momentum-long", "price-monitor"),
            ("leveraged-etf", "price-monitor"),
            ("options-momentum", "options-monitor"),
            ("defense-news", "defense-monitor"),
            ("reddit-sentiment", "reddit-monitor"),
            ("geo-news", "geo-monitor"),
            ("politician-djt", "politician-monitor"),
            ("politician-tracker", "politician-monitor"),
        ):
            self.assertEqual(m.get(strategy), expected_monitor,
                             f"strategy {strategy} should map to {expected_monitor}")

    def test_twitter_prefix_attribution_dynamic(self) -> None:
        # twitter-* prefixes are not in the static map; the helper applies
        # a prefix rule.
        self.assertEqual(self.mod._attribute_monitor("twitter-gov_us"),
                         "twitter-monitor")
        self.assertEqual(self.mod._attribute_monitor("twitter-macro_v3"),
                         "twitter-monitor")
        # Unknown strategy stays unattributed (returns None).
        self.assertIsNone(self.mod._attribute_monitor("totally-made-up"))
        self.assertIsNone(self.mod._attribute_monitor(""))

    # ── 3. Emit marker detection ─────────────────────────────────────────
    def test_emit_marker_detection(self) -> None:
        has_marker = self.mod._emit_marker_in_source
        self.assertTrue(has_marker("foo = emit_signal_opportunity(...)"))
        self.assertTrue(has_marker("from helper import emit_monitor_signal"))
        self.assertFalse(has_marker("notify_signal(payload)"))
        self.assertFalse(has_marker(""))

    # ── 4. Verdict logic ─────────────────────────────────────────────────
    def test_verdict_logic(self) -> None:
        v = self.mod._verdict
        # ACTIVE: wired + rows
        self.assertEqual(v("crypto-monitor", True, 100), "ACTIVE")
        # WIRED_BUT_NOT_FIRING: wired + zero rows + not in NOT_APPLICABLE set
        self.assertEqual(v("price-monitor", True, 0), "WIRED_BUT_NOT_FIRING")
        # DORMANT: not wired + zero rows + not in NOT_APPLICABLE set
        self.assertEqual(v("price-monitor", False, 0), "DORMANT")
        # NOT_APPLICABLE: exit/dispatch lane with zero rows
        self.assertEqual(v("exit-monitor", True, 0), "NOT_APPLICABLE")
        self.assertEqual(v("options-exit-monitor", True, 0), "NOT_APPLICABLE")
        # exit-monitor with rows still goes to ACTIVE
        self.assertEqual(v("exit-monitor", True, 5), "ACTIVE")

    # ── 5. Markdown rendering ────────────────────────────────────────────
    def test_render_markdown_contains_standing_markers(self) -> None:
        report = self.mod.evaluate(now=datetime(2026, 6, 15, tzinfo=timezone.utc))
        md = self.mod._render_markdown(report, head_sha="abc1234")
        for marker in (
            "EDGE_GATE_ENABLED = false",
            "ALLOW_BROKER_PAPER = false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
        ):
            self.assertIn(marker, md, f"markdown missing standing marker: {marker}")
        self.assertIn("HEAD: `abc1234`", md)

    # ── 6. Source code hard-safety scan (AST-based) ──────────────────────
    def test_reporter_source_does_not_import_or_call_broker_apis(self) -> None:
        """AST scan: walks imports + calls, ignores docstring mentions.

        Substrings like ``alpaca_orders`` may legitimately appear inside
        the module docstring (where we explicitly promise NOT to import
        it). The hard-safety guarantee is that no AST-level import or
        call references a broker entry point. We check both.
        """
        import ast
        src = _SCRIPT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        forbidden_modules = {
            "alpaca_orders",
            "shared.alpaca_orders",
            "broker_paper_adapter",
            "shared.broker_paper_adapter",
        }
        forbidden_calls = {
            "submit_order",
            "place_order",
            "place_stock_order",
            "place_crypto_order",
            "place_option_order",
            "safe_close",
            "close_position",
            "close_all_positions",
        }
        for node in ast.walk(tree):
            # Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name, forbidden_modules,
                                     f"reporter imports forbidden module: {alias.name}")
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertNotIn(mod, forbidden_modules,
                                 f"reporter imports forbidden module: {mod}")
            # Calls
            if isinstance(node, ast.Call):
                fn = node.func
                name: str = ""
                if isinstance(fn, ast.Name):
                    name = fn.id
                elif isinstance(fn, ast.Attribute):
                    name = fn.attr
                if name in forbidden_calls:
                    self.fail(f"reporter calls forbidden broker function: {name}")

    # ── 7. Artefact write ────────────────────────────────────────────────
    def test_write_artefacts_creates_json_and_md(self) -> None:
        report = self.mod.evaluate(now=datetime(2026, 6, 15, tzinfo=timezone.utc))
        with tempfile.TemporaryDirectory() as td:
            # Redirect the writer to a temp repo root.
            with mock.patch.object(self.mod, "_REPO_ROOT", Path(td)):
                self.mod._write_artefacts(report)
                json_p = Path(td) / "learning-loop" / "shadow_evidence" / \
                    "monitor_emission_status_latest.json"
                md_p = Path(td) / "docs" / "MONITOR_EMISSION_STATUS.md"
                self.assertTrue(json_p.exists())
                self.assertTrue(md_p.exists())
                data = json.loads(json_p.read_text(encoding="utf-8"))
                self.assertEqual(data["version"], "v3.23.0")


if __name__ == "__main__":
    unittest.main()
