"""v3.25 — Tests for `scripts/gate_distribution_report.py`.

Covers:
  * Top blockers section present (overall)
  * Per-strategy section present
  * Per-monitor section present
  * Shadow eligibility distribution section present (v3.25 explicit)
  * Actionable next-fix section present (v3.25 explicit)

HARD SAFETY
-----------
Tests construct ledger fixtures in a tmpdir and never touch the real
opportunity_ledger or broker layer. Reporter is exercised end-to-end
via ``build_distribution`` + ``render_md``.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "gate_distribution_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "gate_distribution_report", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _make_rows():
    """Build a small fixture: one APPROVE row with NULL conf, two REJECT,
    one DETECTED with conf=0.62 (eligible), one OBSERVE_ONLY_SKIP."""
    today = datetime.now(timezone.utc).date().isoformat()
    rows = [
        {
            "strategy":  "crypto-momentum",
            "symbol":    "BTC/USD",
            "timestamp": f"{today}T08:00:00Z",
            "risk_decision": "APPROVE",
            "confidence_score": None,
            "raw_signal": {"signal_state": "DETECTED"},
            "rejection_reasons": [],
        },
        {
            "strategy":  "crypto-momentum",
            "symbol":    "ETH/USD",
            "timestamp": f"{today}T08:05:00Z",
            "risk_decision": "REJECT",
            "confidence_score": None,
            "raw_signal": {"signal_state": "REJECT",
                           "blocking_reason": "predator_bracket"},
            "rejection_reasons": ["predator_bracket"],
        },
        {
            "strategy":  "crypto-momentum",
            "symbol":    "SOL/USD",
            "timestamp": f"{today}T08:10:00Z",
            "risk_decision": "REJECT",
            "confidence_score": None,
            "raw_signal": {"signal_state": "REJECT",
                           "blocking_reason": "predator_bracket"},
            "rejection_reasons": ["predator_bracket"],
        },
        {
            "strategy":  "crypto-momentum",
            "symbol":    "BTC/USD",
            "timestamp": f"{today}T08:15:00Z",
            "risk_decision": "DETECTED",
            "confidence_score": 0.62,
            "confidence_components": {"data_quality": 0.8},
            "raw_signal": {"signal_state": "DETECTED",
                           "confidence_status": "OK",
                           "confidence_decision": "ALLOW"},
            "rejection_reasons": [],
        },
        {
            "strategy":  "crypto-momentum",
            "symbol":    "BTC/USD",
            "timestamp": f"{today}T08:20:00Z",
            "risk_decision": "REJECT",
            "confidence_score": None,
            "raw_signal": {"signal_state": "REJECT",
                           "confidence_status": "OBSERVE_ONLY_SKIP"},
            "rejection_reasons": ["predator_bracket"],
        },
    ]
    return rows, today


class TestGateDistributionV3250(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()
        self.tmpdir = Path(tempfile.mkdtemp(prefix="gd_v325_"))
        self.ledger_dir = self.tmpdir / "learning-loop" / "opportunity_ledger"
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        rows, today = _make_rows()
        ledger_file = self.ledger_dir / f"{today}.jsonl"
        with ledger_file.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _build(self):
        as_of = datetime.now(timezone.utc)
        return self.mod.build_distribution(
            as_of=as_of,
            repo_root=self.tmpdir,
            days=7,
        )

    # ------------------------------------------------------------------
    # T1 — top blockers overall section present
    # ------------------------------------------------------------------
    def test_top_blockers_section_present(self):
        rep = self._build()
        md = self.mod.render_md(rep)
        self.assertIn("## Top 3 blockers overall", md)
        self.assertIn("Blocker", md)
        self.assertIn("predator_bracket", md)

    # ------------------------------------------------------------------
    # T2 — per-strategy section present
    # ------------------------------------------------------------------
    def test_per_strategy_section_present(self):
        rep = self._build()
        md = self.mod.render_md(rep)
        self.assertIn("## Top blocker per strategy", md)
        self.assertIn("crypto-momentum", md)

    # ------------------------------------------------------------------
    # T3 — per-monitor section present
    # ------------------------------------------------------------------
    def test_per_monitor_section_present(self):
        rep = self._build()
        md = self.mod.render_md(rep)
        self.assertIn("## Top blocker per monitor", md)
        self.assertIn("crypto-monitor", md)

    # ------------------------------------------------------------------
    # T4 — shadow eligibility distribution section present (v3.25)
    # ------------------------------------------------------------------
    def test_shadow_eligibility_section_present(self):
        rep = self._build()
        md = self.mod.render_md(rep)
        self.assertIn("## Shadow eligibility distribution", md)
        dist = rep.get("shadow_eligibility_distribution") or {}
        # Fixture has: 1 eligible (DETECTED + conf 0.62), 1 conf_null
        # (APPROVE + conf None), 3 risk_blocked (REJECTs).
        self.assertEqual(dist.get("eligible", 0), 1)
        self.assertEqual(dist.get("conf_null", 0), 1)
        self.assertEqual(dist.get("risk_blocked", 0), 3)
        self.assertEqual(rep["shadow_eligible_count"], 1)
        # Buckets must appear in rendered markdown.
        self.assertIn("eligible", md)
        self.assertIn("risk_blocked", md)

    # ------------------------------------------------------------------
    # T5 — actionable next-fix advice section present (v3.25)
    # ------------------------------------------------------------------
    def test_actionable_next_fix_present(self):
        rep = self._build()
        md = self.mod.render_md(rep)
        self.assertIn("## Actionable next-fix advice", md)
        actionable = rep.get("actionable_next_fix") or []
        self.assertTrue(actionable, "actionable list must be non-empty")
        # Must contain at least one of the recognised priorities.
        priorities = {a["priority"] for a in actionable}
        self.assertTrue(
            priorities & {"P1", "P2", "P3", "INFO"},
            f"actionable should use known priorities, got {priorities}",
        )
        # Markdown must show priority + hint columns.
        self.assertIn("Priority", md)
        self.assertIn("Hint", md)

    # ------------------------------------------------------------------
    # T6 — Reporter never imports broker layer (AST safety)
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
    # T7 — Hint phrasing must not recommend lowering thresholds
    # ------------------------------------------------------------------
    def test_actionable_does_not_recommend_lowering(self):
        rep = self._build()
        actionable = rep.get("actionable_next_fix") or []
        forbidden_phrases = ("lower the", "reduce the threshold",
                             "lower threshold", "decrease threshold")
        for a in actionable:
            hint = (a.get("hint") or "").lower()
            for phrase in forbidden_phrases:
                self.assertNotIn(
                    phrase, hint,
                    f"actionable hint must not recommend lowering: {hint!r}")


if __name__ == "__main__":
    unittest.main()
