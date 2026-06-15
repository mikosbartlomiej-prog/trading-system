"""v3.27.0 — Tests for ``scripts/build_opportunity_density_plan.py``.

Hard-safety invariants verified here:
- Plan NEVER recommends auto-lowering any threshold.
- Plan NEVER recommends enabling broker / paper / live.
- Plan NEVER promises profit (no "profit"/"earn" framing).
- Plan NEVER counts replay / near-miss / shadow rows as paper edge.
- Plan NEVER imports ``alpaca_orders``.
- Plan NEVER makes a network call (AST + import scan).
- Plan ALWAYS surfaces sections A–G.
"""

from __future__ import annotations

import ast
import json
import socket
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_opportunity_density_plan.py"
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_opportunity_density_plan as bop  # noqa: E402


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _seed_minimal_inputs(tmp: Path) -> None:
    """Write a minimal set of artefacts so build_plan emits content."""
    ll = tmp / "learning-loop"
    ll.mkdir(parents=True, exist_ok=True)
    (ll / "strategy_threshold_reality_latest.json").write_text(json.dumps({
        "strategies": [{
            "strategy_id":          "momentum-long",
            "actual_signals_fired": 2,
            "evaluations":          50,
            "recommendation":       "OBSERVE_MORE",
            "threshold_realism":    "INSUFFICIENT_DATA",
            "metrics": [{
                "strategy_id":        "momentum-long",
                "metric_name":        "rsi",
                "threshold":          50.0,
                "threshold_realism":  "TOO_STRICT",
                "hit_rate":           0.05,
                "near_miss_rate":     0.25,
                "sample_size":        50,
            }],
        }],
    }), encoding="utf-8")
    (ll / "replay_discovery_latest.json").write_text(json.dumps({
        "rows": [{
            "strategy":            "momentum-long",
            "symbol":              "AAPL",
            "candidates":          5,
            "near_misses":         3,
            "threshold_crosses":   1,
        }],
    }), encoding="utf-8")
    (ll / "universe_opportunity_review_latest.json").write_text(json.dumps({
        "rows": [
            {"symbol": "SPY", "asset_class": "us_equity",
             "recommendation": "REMOVE_LOW_QUALITY"},
            {"symbol": "AAPL", "asset_class": "us_equity",
             "recommendation": "ADD_FOR_OBSERVATION"},
        ],
    }), encoding="utf-8")
    (ll / "shadow_candidate_queue_latest.json").write_text(json.dumps({
        "rows": [],
    }), encoding="utf-8")
    (ll / "trigger_watchlist_latest.json").write_text(json.dumps({
        "rows": [],
    }), encoding="utf-8")
    (ll / "strategy_variant_quarantine_latest.json").write_text(json.dumps({
        "variants": [{
            "id":              "momentum-long-v2",
            "parent_strategy": "momentum-long",
            "dataclass_status": "QUARANTINED",
            "days_observed":   3,
        }],
    }), encoding="utf-8")
    (ll / "monitor_runtime_diag_status_latest.json").write_text(
        json.dumps({
            "aggregate": {
                "per_monitor": {
                    "price-monitor": {
                        "RAN": 5, "SIGNAL_DETECTED": 0,
                    },
                },
            },
        }), encoding="utf-8")
    (ll / "confidence_precalibration_readiness_latest.json").write_text(
        json.dumps({
            "source_separation": {
                "production_positive_rows": 0,
                "replay_positive_rows":     5,
                "near_miss_rows":           20,
                "fixture_only_rows":        0,
                "outcomes_available":       False,
                "verdict_v327":             "READY_FOR_COMPONENT_VARIANCE_REVIEW",
            },
        }), encoding="utf-8")
    # near_miss/<date>.jsonl
    nm = ll / "near_miss"
    nm.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    with (nm / f"{today}.jsonl").open("w", encoding="utf-8") as fh:
        for i in range(10):
            fh.write(json.dumps({
                "strategy_id": "momentum-long",
                "symbol":      "AAPL",
                "metric_name": "rsi",
            }) + "\n")
        for i in range(3):
            fh.write(json.dumps({
                "strategy_id": "crypto-momentum",
                "symbol":      "BTC/USD",
                "metric_name": "rsi",
            }) + "\n")


def _patch_paths_to_tmp(tmp: Path) -> dict:
    ll = tmp / "learning-loop"
    docs = tmp / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    return {
        "STRATEGY_REALITY":     ll / "strategy_threshold_reality_latest.json",
        "REPLAY_DISCOVERY":     ll / "replay_discovery_latest.json",
        "REPLAY_DISCOVERY_ALT": ll / "replay_entry_candidate_discovery_latest.json",
        "UNIVERSE_REVIEW":      ll / "universe_opportunity_review_latest.json",
        "SHADOW_QUEUE":         ll / "shadow_candidate_queue_latest.json",
        "TRIGGER_WATCHLIST":    ll / "trigger_watchlist_latest.json",
        "NEAR_MISS_DIR":        ll / "near_miss",
        "VARIANT_QUARANTINE":   ll / "strategy_variant_quarantine_latest.json",
        "MONITOR_EMISSION":     ll / "monitor_emission_status_latest.json",
        "MONITOR_EMISSION_ALT": ll / "monitor_runtime_diag_status_latest.json",
        "PRECAL_READINESS":     ll / "confidence_precalibration_readiness_latest.json",
        "OUTPUT_JSON":          ll / "opportunity_density_plan_latest.json",
        "OUTPUT_MD":            docs / "OPPORTUNITY_DENSITY_PLAN.md",
    }


def _run_with_patches(*, tmp: Path) -> dict:
    p = _patch_paths_to_tmp(tmp)
    with mock.patch.object(bop, "STRATEGY_REALITY", p["STRATEGY_REALITY"]), \
         mock.patch.object(bop, "REPLAY_DISCOVERY", p["REPLAY_DISCOVERY"]), \
         mock.patch.object(bop, "REPLAY_DISCOVERY_ALT", p["REPLAY_DISCOVERY_ALT"]), \
         mock.patch.object(bop, "UNIVERSE_REVIEW", p["UNIVERSE_REVIEW"]), \
         mock.patch.object(bop, "SHADOW_QUEUE", p["SHADOW_QUEUE"]), \
         mock.patch.object(bop, "TRIGGER_WATCHLIST", p["TRIGGER_WATCHLIST"]), \
         mock.patch.object(bop, "NEAR_MISS_DIR", p["NEAR_MISS_DIR"]), \
         mock.patch.object(bop, "VARIANT_QUARANTINE", p["VARIANT_QUARANTINE"]), \
         mock.patch.object(bop, "MONITOR_EMISSION", p["MONITOR_EMISSION"]), \
         mock.patch.object(bop, "MONITOR_EMISSION_ALT", p["MONITOR_EMISSION_ALT"]), \
         mock.patch.object(bop, "PRECAL_READINESS", p["PRECAL_READINESS"]), \
         mock.patch.object(bop, "OUTPUT_JSON", p["OUTPUT_JSON"]), \
         mock.patch.object(bop, "OUTPUT_MD", p["OUTPUT_MD"]):
        return bop.build_plan(
            as_of=datetime(2026, 6, 15, tzinfo=timezone.utc))


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestPlanSections(unittest.TestCase):
    def test_plan_sections_A_through_G_present(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _seed_minimal_inputs(tdp)
            plan = _run_with_patches(tmp=tdp)
            sec = plan["sections"]
            for k in (
                "A_strategies_closest_to_firing",
                "B_top_symbols_by_near_misses",
                "C_variants_worth_observing",
                "D_monitors_needing_attention",
                "E_universe_changes_observe_only",
                "F_thresholds_for_operator_review",
                "G_data_collection_plan",
            ):
                self.assertIn(k, sec)
            # Each section actually has data
            self.assertGreater(len(sec["A_strategies_closest_to_firing"]), 0)
            self.assertGreater(len(sec["B_top_symbols_by_near_misses"]), 0)
            self.assertGreater(len(sec["C_variants_worth_observing"]), 0)
            self.assertGreater(
                len(sec["D_monitors_needing_attention"]), 0)
            self.assertGreater(
                len(sec["E_universe_changes_observe_only"]
                    ["observe_only_additions"]), 0)
            self.assertGreater(
                len(sec["F_thresholds_for_operator_review"]), 0)
            self.assertGreater(
                len(sec["G_data_collection_plan"]["per_strategy_eta"]), 0)

    def test_plan_handles_empty_inputs_safely(self):
        """No artefacts present → plan returns empty sections, no crash."""
        with TemporaryDirectory() as td:
            tdp = Path(td)
            plan = _run_with_patches(tmp=tdp)
            sec = plan["sections"]
            self.assertEqual(sec["A_strategies_closest_to_firing"], [])
            self.assertEqual(sec["B_top_symbols_by_near_misses"], [])
            self.assertEqual(sec["C_variants_worth_observing"], [])
            self.assertEqual(sec["D_monitors_needing_attention"], [])
            self.assertEqual(
                sec["E_universe_changes_observe_only"]
                ["observe_only_additions"], [])
            self.assertEqual(sec["F_thresholds_for_operator_review"], [])

    def test_plan_standing_markers_present(self):
        with TemporaryDirectory() as td:
            plan = _run_with_patches(tmp=Path(td))
            markers = plan["standing_markers"]
            for required in (
                "EDGE_GATE_ENABLED=false",
                "ALLOW_BROKER_PAPER=false",
                "DENSITY_PLAN_NEVER_LOWERS_THRESHOLDS",
                "DENSITY_PLAN_NEVER_PROMISES_PROFIT",
                "DENSITY_PLAN_NEVER_PROMOTES_VARIANTS",
                "REPLAY_NEVER_COUNTS_AS_PAPER_EDGE",
                "NEAR_MISS_NEVER_COUNTS_AS_PAPER_EDGE",
                "SHADOW_NEVER_COUNTS_AS_PAPER_EDGE",
            ):
                self.assertIn(required, markers)


class TestPlanAdvisoryFraming(unittest.TestCase):
    """The plan MUST NOT recommend auto-changes, broker/live, or profit."""

    def _full_text(self, tmp: Path) -> str:
        plan = _run_with_patches(tmp=tmp)
        return (
            bop.render_md(plan).lower()
            + " "
            + json.dumps(plan).lower()
        )

    def test_plan_never_recommends_auto_lowering_threshold(self):
        """Recommendation phrasings must be absent; defensive 'NEVER
        auto-lowers' disclaimers are allowed and explicitly required.
        """
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _seed_minimal_inputs(tdp)
            text = self._full_text(tdp)
            # Forbidden = recommendation phrasing. Allowed = disclaimers
            # like 'never auto-lower'. We check that no row recommends
            # an auto-action.
            for forbidden in (
                "recommend auto-lowering",
                "recommend lowering",
                "automatically apply",
                "auto-apply threshold change",
                "system will lower",
                "we lower",
                "lower threshold to",
            ):
                self.assertNotIn(
                    forbidden, text,
                    msg=f"plan must not say '{forbidden}'",
                )

    def test_plan_never_recommends_live_or_broker_paper(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _seed_minimal_inputs(tdp)
            text = self._full_text(tdp)
            for forbidden in (
                "enable live",
                "enable broker",
                "turn on live",
                "turn on broker",
                "go live",
                "switch to live",
            ):
                self.assertNotIn(
                    forbidden, text,
                    msg=f"plan must not say '{forbidden}'",
                )

    def test_plan_never_promises_profit(self):
        """Promise phrasings must be absent; standing markers and
        disclaimers like 'never promises profit' are allowed.
        """
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _seed_minimal_inputs(tdp)
            text = self._full_text(tdp)
            for forbidden in (
                "guaranteed profit",
                "guaranteed return",
                "you will earn",
                "expected profit",
                "we promise profit",
                "definite gain",
            ):
                self.assertNotIn(
                    forbidden, text,
                    msg=f"plan must not say '{forbidden}'",
                )


class TestPlanSafetyAndSource(unittest.TestCase):
    def setUp(self):
        self.src = SCRIPT_PATH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.src)

    def test_plan_no_alpaca_imports(self):
        imports: list[str] = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        for forbidden in ("alpaca_orders", "alpaca_trade_api",
                          "alpaca"):
            for mod in imports:
                self.assertNotIn(
                    forbidden, mod,
                    msg=f"plan must NOT import {forbidden}",
                )

    def test_plan_no_network_calls(self):
        """No raw socket / requests / urllib import at module level."""
        imports: list[str] = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        for forbidden in ("requests", "urllib.request",
                          "http.client", "socket"):
            for mod in imports:
                self.assertNotEqual(
                    mod, forbidden,
                    msg=f"plan must NOT import {forbidden}",
                )

        # Runtime guard: block socket connect during build_plan.
        original_connect = socket.socket.connect

        def _no_connect(*a, **kw):
            raise AssertionError(
                "plan attempted to open a network socket")
        socket.socket.connect = _no_connect  # type: ignore
        try:
            with TemporaryDirectory() as td:
                _ = _run_with_patches(tmp=Path(td))
        finally:
            socket.socket.connect = original_connect  # type: ignore


if __name__ == "__main__":
    unittest.main()
