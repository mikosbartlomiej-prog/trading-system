"""v3.30 ETAP 9 (2026-06-16) — Daily brief truth tests.

Asserts the v3.30 banner / citation / "what changed" / operator-action
contract of ``scripts/generate_daily_operational_brief.py``:

* retry storm active → top RED banner;
* repair required (no storm) → top ORANGE banner;
* allocator blocked (other reason) → top YELLOW banner;
* allocator allowed → top GREEN status;
* LLM advisory cannot hide blockers (blockers come from
  deterministic artefacts);
* numeric claims cite an artefact path (or render
  ``CLAIM_UNSUPPORTED``);
* unverified narrative claims marked ``CLAIM_UNSUPPORTED``;
* what-changed section diffs vs yesterday;
* operator-action section non-empty when blocked;
* AST: no ``alpaca_orders`` import.
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
sys.path.insert(0, str(REPO_ROOT / "shared"))
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_daily_operational_brief.py"
SCRIPT_SRC = SCRIPT_PATH.read_text(encoding="utf-8")


def _import_module():
    if "generate_daily_operational_brief" in sys.modules:
        del sys.modules["generate_daily_operational_brief"]
    spec = importlib.util.spec_from_file_location(
        "generate_daily_operational_brief", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["generate_daily_operational_brief"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_sa(*, decision: str, blockers=(), retry_storm=False,
              p13=False, broker_repair=()) -> dict:
    return {
        "decision":  decision,
        "blockers":  list(blockers),
        "reason":   f"sa_reason:{decision}",
        "shadow_only_allowed": decision == "ALLOCATOR_ALLOWED",
        "snapshot":  {
            "retry_storm_active":            retry_storm,
            "retry_storm_count_last_hour":   2 if retry_storm else 0,
            "fresh_p13_in_window":           p13,
            "fresh_p13_count_last_hour":     1 if p13 else 0,
            "broker_repair_blocked":         list(broker_repair),
        },
    }


# ── 1. Banner classifier branches ────────────────────────────────────────────

class TestBannerClassifierBranches(unittest.TestCase):

    def test_01_retry_storm_active_red_banner(self):
        mod = _import_module()
        color, head, sub = mod._classify_banner(
            _make_sa(decision="ALLOCATOR_BLOCKED_BROKER_REPAIR",
                     retry_storm=True,
                     broker_repair=["AVAX/USD"]),
            None,
        )
        self.assertEqual(color, "RED")
        self.assertIn("AUTO_CLOSE_RETRY_STORM_ACTIVE", head)

    def test_02_repair_required_no_storm_orange_banner(self):
        mod = _import_module()
        color, head, _ = mod._classify_banner(
            _make_sa(
                decision="ALLOCATOR_BLOCKED_BROKER_REPAIR",
                blockers=["broker_repair_required:AVAX/USD"],
                broker_repair=["AVAX/USD"]),
            None,
        )
        self.assertEqual(color, "ORANGE")
        self.assertIn("BROKER_REPAIR_REQUIRED", head)

    def test_03_other_blocker_yellow_banner(self):
        mod = _import_module()
        color, head, _ = mod._classify_banner(
            _make_sa(
                decision="ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT",
                blockers=["safe_mode_consistency=INCONSISTENT_ENTERED_NOT_PERSISTED"]),
            None,
        )
        self.assertEqual(color, "YELLOW")
        self.assertIn("ALLOCATOR_BLOCKED", head)

    def test_04_allocator_allowed_green_status(self):
        mod = _import_module()
        color, head, _ = mod._classify_banner(
            _make_sa(decision="ALLOCATOR_ALLOWED"),
            None,
        )
        self.assertEqual(color, "GREEN")
        self.assertIn("ALLOCATOR_ALLOWED", head)


# ── 2. LLM advisory cannot hide blockers ─────────────────────────────────────

class TestLLMAdvisoryCannotHideBlockers(unittest.TestCase):

    def test_05_llm_advisory_never_in_blocker_list(self):
        mod = _import_module()
        sa = _make_sa(
            decision="ALLOCATOR_BLOCKED_BROKER_REPAIR",
            blockers=["broker_repair_required:AVAX/USD"],
            broker_repair=["AVAX/USD"],
        )
        flags = {"LLM_PROVIDER_MODE": "UNAVAILABLE",
                  "NEXT_OPERATOR_ACTIONS": []}
        tmpdir = tempfile.TemporaryDirectory()
        try:
            today = {
                "as_of": "2026-06-16",
                "system_activation": sa,
                "flags": flags,
                "audit_event_count_24h": 0,
            }
            with mock.patch.object(mod, "REPO_ROOT", Path(tmpdir.name)):
                text = mod.render_brief(
                    today=today, yesterday=None,
                    banner=mod._classify_banner(sa, flags),
                    dash_flags=flags,
                )
            # Blocker appears in top blockers section.
            self.assertIn("broker_repair_required:AVAX/USD", text)
            # LLM section explicitly marks itself advisory-only.
            self.assertIn("LLM advisory only", text)
            self.assertIn("does not override deterministic", text)
        finally:
            tmpdir.cleanup()


# ── 3. Numeric claims cite artefact path ─────────────────────────────────────

class TestNumericClaimsCiteSource(unittest.TestCase):

    def test_06_cite_includes_source_tag(self):
        mod = _import_module()
        out = mod._cite(42, "x/y.json::z")
        self.assertIn("42", out)
        self.assertIn("source", out)
        self.assertIn("x/y.json::z", out)

    def test_07_missing_value_renders_claim_unsupported(self):
        mod = _import_module()
        out = mod._cite(None, "missing/file.json")
        self.assertIn("CLAIM_UNSUPPORTED", out)
        self.assertIn("missing/file.json", out)


# ── 4. Unverified narrative claims explicitly flagged ────────────────────────

class TestUnverifiedClaimsFlagged(unittest.TestCase):

    def test_08_brief_marks_92_18_80_as_unsupported(self):
        mod = _import_module()
        sa = _make_sa(decision="ALLOCATOR_ALLOWED")
        tmpdir = tempfile.TemporaryDirectory()
        try:
            today = {
                "as_of": "2026-06-16",
                "system_activation": sa,
                "flags": {"LLM_PROVIDER_MODE": "UNAVAILABLE",
                            "NEXT_OPERATOR_ACTIONS": []},
                "audit_event_count_24h": 0,
            }
            with mock.patch.object(mod, "REPO_ROOT", Path(tmpdir.name)):
                text = mod.render_brief(
                    today=today, yesterday=None,
                    banner=mod._classify_banner(sa, today["flags"]),
                    dash_flags=today["flags"],
                )
            # Each claim explicitly listed as CLAIM_UNSUPPORTED.
            self.assertIn("92 % readiness", text)
            self.assertIn("CLAIM_UNSUPPORTED", text)
            self.assertIn("18 LLM agents", text)
            self.assertIn("80-day failure", text)
        finally:
            tmpdir.cleanup()


# ── 5. What-changed section diffs vs yesterday ───────────────────────────────

class TestWhatChangedSection(unittest.TestCase):

    def test_09_what_changed_diffs_decision_and_blockers(self):
        mod = _import_module()
        today = {
            "system_activation": _make_sa(
                decision="ALLOCATOR_BLOCKED_BROKER_REPAIR",
                blockers=["broker_repair_required:AVAX/USD"]),
            "flags": {"LLM_PROVIDER_MODE": "REAL_PROVIDER"},
            "audit_event_count_24h": 100,
        }
        yesterday = {
            "system_activation": _make_sa(
                decision="ALLOCATOR_BLOCKED_SAFE_MODE_INCONSISTENT",
                blockers=["safe_mode_consistency=INCONSISTENT_ENTERED_NOT_PERSISTED"]),
            "flags": {"LLM_PROVIDER_MODE": "UNAVAILABLE"},
            "audit_event_count_24h": 80,
        }
        lines = mod._what_changed(today, yesterday)
        joined = "\n".join(lines)
        self.assertIn("decision changed", joined)
        self.assertIn("Blockers added", joined)
        self.assertIn("Blockers removed", joined)
        self.assertIn("LLM provider mode changed", joined)


# ── 6. Operator-action section non-empty when blocked ────────────────────────

class TestOperatorActionsSection(unittest.TestCase):

    def test_10_operator_actions_non_empty_when_blocked(self):
        mod = _import_module()
        sa = _make_sa(
            decision="ALLOCATOR_BLOCKED_BROKER_REPAIR",
            blockers=["broker_repair_required:AVAX/USD"],
            broker_repair=["AVAX/USD"],
        )
        flags = {"NEXT_OPERATOR_ACTIONS": []}
        actions = mod._operator_actions("ORANGE", sa, flags)
        self.assertTrue(actions, "operator actions must be non-empty "
                                   "when blocked even if dashboard list "
                                   "is empty")
        # Mentions the runbook or confirmation script.
        joined = " ".join(actions)
        self.assertTrue(
            "operator_repair_confirmation" in joined.lower()
            or "OPERATOR_REPAIR_CONFIRMATION" in joined,
        )

    def test_11_operator_actions_empty_when_allowed(self):
        mod = _import_module()
        sa = _make_sa(decision="ALLOCATOR_ALLOWED")
        actions = mod._operator_actions("GREEN", sa, None)
        self.assertEqual(actions, [])


# ── 7. AST: no alpaca_orders import / no broker call ─────────────────────────

class TestAstNoAlpaca(unittest.TestCase):

    def test_12_no_alpaca_orders_import_in_brief_script(self):
        tree = ast.parse(SCRIPT_SRC)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertFalse(
                    node.module and "alpaca_orders" in node.module)

    def test_13_no_broker_function_calls(self):
        forbidden = {
            "submit_order", "place_order", "safe_close",
            "cancel_order", "close_position", "place_stock_order",
            "place_crypto_order", "place_option_order",
        }
        tree = ast.parse(SCRIPT_SRC)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = ""
                if isinstance(node.func, ast.Name):
                    fname = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    fname = node.func.attr
                self.assertNotIn(fname, forbidden)


if __name__ == "__main__":
    unittest.main()
