"""v3.29 ETAP 8 (2026-06-16) — Discovery + shadow stack activation tests.

Asserts:
- All v3.29 reporters are listed in daily-reporters.yml
- shadow_simulator REFUSES when master gate blocks
- shadow_simulator ALLOWS when master gate is SHADOW_ONLY-or-better
- Discovery workflows pin 7 broker / live flags false
- Discovery workflows never call broker
- AST: no alpaca_orders import in new code
- llm-advisory-mesh.yml exists
- daily-operational-brief.yml exists
- Standing markers present in reporter output
- No live URL in any of the new modules / scripts.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


# Mandatory broker / live flag list per spec
_BROKER_LIVE_FLAGS = (
    "ALLOW_BROKER_PAPER",
    "EDGE_GATE_ENABLED",
    "BROKER_EXECUTION_ENABLED",
    "LIVE_TRADING",
    "LIVE_ENABLED",
    "GO_LIVE",
    "LIVE_TRADING_ENABLED",
)

# Files whose AST must be free of any alpaca_orders import / broker URL.
_NEW_FILES_NO_ALPACA = (
    "shared/system_activation_gate.py",
    "scripts/build_system_activation_status.py",
    "scripts/generate_daily_operational_brief.py",
    "scripts/audit_geo_monitor_health.py",
    "scripts/audit_llm_provider_health.py",
)


class TestDailyReportersWorkflow(unittest.TestCase):
    """daily-reporters.yml must include v3.29 reporters + pin flags."""

    @classmethod
    def setUpClass(cls):
        cls.wf_path = _REPO_ROOT / ".github" / "workflows" / "daily-reporters.yml"
        cls.text = cls.wf_path.read_text(encoding="utf-8")

    def test_v329_reporters_listed(self):
        for tok in (
            "check_safe_mode_consistency.py",
            "backfill_broker_repair_from_incidents.py",
            "build_system_activation_status.py",
            "build_shadow_candidate_queue.py",
            "build_trigger_watchlist.py",
            "universe_opportunity_review.py",
        ):
            self.assertIn(tok, self.text,
                          f"daily-reporters.yml is missing {tok}")

    def test_pins_seven_broker_live_flags(self):
        for f in _BROKER_LIVE_FLAGS:
            self.assertIn(f, self.text,
                          f"daily-reporters.yml does not pin {f}")
        self.assertIn("REFUSED:", self.text,
                      "daily-reporters.yml has no refusal step")

    def test_contents_write_permission(self):
        self.assertIn("contents: write", self.text)


class TestLLMAdvisoryMeshWorkflow(unittest.TestCase):
    def test_workflow_exists(self):
        p = _REPO_ROOT / ".github" / "workflows" / "llm-advisory-mesh.yml"
        self.assertTrue(p.exists())
        text = p.read_text(encoding="utf-8")
        for f in _BROKER_LIVE_FLAGS:
            self.assertIn(f, text)
        self.assertIn("REFUSED:", text)


class TestDailyOperationalBriefWorkflow(unittest.TestCase):
    def test_workflow_exists_and_pins_flags(self):
        p = _REPO_ROOT / ".github" / "workflows" / "daily-operational-brief.yml"
        self.assertTrue(p.exists(),
                        "daily-operational-brief.yml is missing")
        text = p.read_text(encoding="utf-8")
        for f in _BROKER_LIVE_FLAGS:
            self.assertIn(f, text)
        self.assertIn("REFUSED:", text)
        self.assertIn("contents: write", text)


class TestShadowSimulatorMasterGate(unittest.TestCase):
    """shadow_simulator must read system_activation_gate.evaluate()."""

    def test_imports_master_gate(self):
        text = (_REPO_ROOT / "shared" / "shadow_simulator.py").read_text(
            encoding="utf-8")
        self.assertIn("system_activation_gate", text,
                       "shadow_simulator missing master-gate import")
        self.assertIn("SHADOW_PERMITTED_DECISIONS", text)

    def test_refuses_when_master_gate_blocks(self):
        """Patch the master gate to return a BLOCKING decision."""
        from shadow_simulator import maybe_simulate_from_row
        try:
            from system_activation_gate import (
                SystemActivationDecision, SystemActivationResult,
            )
        except ImportError:
            from shared.system_activation_gate import (  # type: ignore
                SystemActivationDecision, SystemActivationResult,
            )

        blocked = SystemActivationResult(
            decision=SystemActivationDecision.ALLOCATOR_BLOCKED_SAFE_MODE,
            blockers=("safe_mode_active",),
            enabled_subsystems=(),
            llm_status="unknown",
            snapshot={},
            audit_row={},
            reason="test_block",
        )

        try:
            import system_activation_gate as _mod  # type: ignore
        except ImportError:
            import shared.system_activation_gate as _mod  # type: ignore

        row = {
            "signal_id":   "s-1",
            "symbol":      "AAPL",
            "strategy":    "test",
            "side":        "long",
            "asset_class": "us_equity",
            "raw_signal":  {
                "price":   100.0,
                "action":  "BUY",
                "intended_price": 100.0,
            },
        }
        # Production workflow pins SHADOW_SIMULATOR_REQUIRE_MASTER_GATE
        # true. The guard is opt-in so legacy unit tests keep their
        # semantics. Patch eligibility to ELIGIBLE so the row gets to
        # the master-gate check at all.
        try:
            import shadow_eligibility as _se
        except ImportError:
            import shared.shadow_eligibility as _se  # type: ignore
        eligible_verdict = type(
            "V", (), {
                "decision":       _se.ShadowEligibilityDecision.ELIGIBLE,
                "canary_verdict": "CANARY_PREFLIGHT_DRY_RUN_OK",
            })()
        env = {
            "SHADOW_SIMULATOR_REQUIRE_MASTER_GATE": "true",
            **{f: "false" for f in _BROKER_LIVE_FLAGS},
        }
        with patch.object(_mod, "evaluate", return_value=blocked), \
             patch.object(_se, "evaluate_shadow_eligibility",
                          return_value=eligible_verdict):
            fill = maybe_simulate_from_row(row, env=env)
            self.assertIsNotNone(fill,
                "expected an audit REJECTED_BY_GATE row, not None")
            self.assertEqual(fill.fill_status, "REJECTED_BY_GATE")
            self.assertEqual(fill.rejection_reason,
                             "REFUSED_SHADOW_DUE_TO_SYSTEM_GATE")

    def test_allows_when_master_gate_is_allocator_allowed(self):
        """Patch the master gate to ALLOCATOR_ALLOWED and eligibility to ELIGIBLE."""
        from shadow_simulator import maybe_simulate_from_row, FILL_FILLED
        try:
            from system_activation_gate import (
                SystemActivationDecision, SystemActivationResult,
            )
        except ImportError:
            from shared.system_activation_gate import (  # type: ignore
                SystemActivationDecision, SystemActivationResult,
            )
        try:
            import shadow_eligibility as _se
        except ImportError:
            import shared.shadow_eligibility as _se  # type: ignore

        allowed = SystemActivationResult(
            decision=SystemActivationDecision.SYSTEM_ACTIVE_SHADOW_ONLY,
            blockers=(),
            enabled_subsystems=("shadow_simulator",),
            llm_status="unknown",
            snapshot={},
            audit_row={},
            reason="ok",
        )

        try:
            import system_activation_gate as _gate_mod  # type: ignore
        except ImportError:
            import shared.system_activation_gate as _gate_mod  # type: ignore

        # ELIGIBLE verdict for the eligibility function.
        eligible_verdict = type(
            "V", (), {
                "decision":       _se.ShadowEligibilityDecision.ELIGIBLE,
                "canary_verdict": "CANARY_PREFLIGHT_DRY_RUN_OK",
            })()

        row = {
            "signal_id":   "s-2",
            "symbol":      "AAPL",
            "strategy":    "test",
            "side":        "long",
            "asset_class": "us_equity",
            "raw_signal":  {
                "price": 100.0,
                "action": "BUY",
                "intended_price": 100.0,
            },
        }
        env = {
            "SHADOW_SIMULATOR_REQUIRE_MASTER_GATE": "true",
            **{f: "false" for f in _BROKER_LIVE_FLAGS},
        }
        with patch.object(_gate_mod, "evaluate", return_value=allowed), \
             patch.object(_se, "evaluate_shadow_eligibility",
                          return_value=eligible_verdict):
            fill = maybe_simulate_from_row(
                row, market_snapshot={"price": 100.0}, env=env)
        self.assertIsNotNone(fill)
        self.assertEqual(fill.fill_status, FILL_FILLED)


class TestNoAlpacaImportInNewCode(unittest.TestCase):
    """AST scan: no new module may import alpaca_orders."""

    def test_no_alpaca_imports(self):
        for rel in _NEW_FILES_NO_ALPACA:
            p = _REPO_ROOT / rel
            if not p.exists():
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    name = node.module or ""
                    self.assertNotIn("alpaca_orders", name,
                                     f"{rel} imports {name}")
                if isinstance(node, ast.Import):
                    for n in node.names:
                        self.assertNotIn("alpaca_orders", n.name or "",
                                          f"{rel} imports {n.name}")


class TestNoLiveURL(unittest.TestCase):
    """Static scan: no new module may reference live (non-paper) URL."""

    def test_no_live_url(self):
        for rel in _NEW_FILES_NO_ALPACA:
            p = _REPO_ROOT / rel
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("api.alpaca.markets", text,
                              f"{rel} references live API URL")


class TestDiscoveryWorkflowsNeverCallBroker(unittest.TestCase):
    """Discovery / brief workflows must never invoke broker SDK."""

    def test_workflows_no_broker_install(self):
        workflows = [
            ".github/workflows/daily-reporters.yml",
            ".github/workflows/daily-operational-brief.yml",
        ]
        for rel in workflows:
            p = _REPO_ROOT / rel
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("pip install alpaca", text)
            self.assertNotIn("alpaca-trade-api", text)
            self.assertNotIn("submit_order", text)


class TestStandingMarkers(unittest.TestCase):
    """build_system_activation_status emits standing markers."""

    def test_standing_markers_in_output(self):
        spec = importlib.util.spec_from_file_location(
            "build_system_activation_status",
            _REPO_ROOT / "scripts" / "build_system_activation_status.py")
        m = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(m)
        # The module exposes STANDING_MARKERS module-level constant.
        self.assertTrue(hasattr(m, "STANDING_MARKERS"))
        markers = m.STANDING_MARKERS
        self.assertIn("EDGE_GATE_ENABLED=false", markers)
        self.assertIn("ALLOW_BROKER_PAPER=false", markers)
        self.assertIn("LIVE_TRADING_UNSUPPORTED", markers)
        self.assertIn("NO_ORDER_PLACEMENT", markers)


if __name__ == "__main__":
    unittest.main()
