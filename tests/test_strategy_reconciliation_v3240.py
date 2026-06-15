"""v3.24 (2026-06-15) — tests for scripts/reconcile_strategy_sources.py.

Covers classification of each status enum + the auto-conversion /
operator-flag list. Tests use synthetic registry/state/backtest/ledger
inputs by patching the loader functions in the reconciler module.

HARD SAFETY
-----------
- Tests NEVER call the broker.
- Tests NEVER hit the network.
- AST scan asserts the reconciler does NOT import alpaca_orders.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
for p in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_module():
    """Load scripts/reconcile_strategy_sources.py as module."""
    target = SCRIPTS_DIR / "reconcile_strategy_sources.py"
    spec = importlib.util.spec_from_file_location(
        "reconcile_strategy_sources_v324", str(target))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()
        self.as_of = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)

    def _build(self, registry, state_strats, backtest_fns, monitors,
                ledger_strats, *, backtest_reg=None):
        """Patch the loaders to return synthetic values."""
        m = self.mod
        m._load_registry = lambda repo_root=None: registry
        m._load_backtest_strategies = (
            lambda repo_root=None: set(backtest_fns))
        m._load_backtest_registry = (
            lambda repo_root=None: backtest_reg or {})
        m._scan_monitor_strategies = (
            lambda repo_root=None: monitors)
        # state.json
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            ll = tdp / "learning-loop"
            ll.mkdir()
            (ll / "state.json").write_text(
                json.dumps({"strategies": state_strats}),
                encoding="utf-8")
            ld = ll / "opportunity_ledger"
            ld.mkdir()
            # Synthesize ledger file for today.
            today = self.as_of.date().isoformat()
            lines = []
            for s in ledger_strats:
                lines.append(json.dumps({
                    "strategy": s, "timestamp":
                        self.as_of.isoformat(),
                }))
            (ld / f"{today}.jsonl").write_text(
                "\n".join(lines), encoding="utf-8")
            return m.build_reconciliation(as_of=self.as_of, repo_root=tdp)

    def test_active_runtime_source(self):
        rec = self._build(
            registry={"crypto-momentum": {
                "asset_class": "crypto",
                "signal_at": lambda i, b: None,
            }},
            state_strats={"crypto-momentum": {"enabled": True}},
            backtest_fns={"crypto-momentum"},
            monitors={"crypto-momentum": ["crypto-monitor"]},
            ledger_strats={"crypto-momentum"},
        )
        names = {r["strategy"]: r["status"] for r in rec["strategies"]}
        self.assertEqual(names["crypto-momentum"], "ACTIVE_RUNTIME_SOURCE")

    def test_active_shadow_source(self):
        rec = self._build(
            registry={"momentum-long": {
                "asset_class": "us_equity",
                "signal_at": lambda i, b: None,
            }},
            state_strats={},
            backtest_fns={"momentum-long"},
            monitors={},   # no monitor traffic
            ledger_strats=set(),
        )
        names = {r["strategy"]: r["status"] for r in rec["strategies"]}
        self.assertEqual(names["momentum-long"], "ACTIVE_SHADOW_SOURCE")

    def test_observe_only_explicit_flag(self):
        rec = self._build(
            registry={"geo-defense": {
                "asset_class": "us_equity",
                "signal_at":   None,
                "observe_only": True,
            }},
            state_strats={"geo-defense": {"enabled": True}},
            backtest_fns=set(),
            monitors={"geo-defense": ["geo-monitor"]},
            ledger_strats={"geo-defense"},
        )
        names = {r["strategy"]: r["status"] for r in rec["strategies"]}
        self.assertEqual(names["geo-defense"], "OBSERVE_ONLY")

    def test_backtest_only(self):
        rec = self._build(
            registry={},
            state_strats={},
            backtest_fns={"experimental-strat"},
            monitors={},
            ledger_strats=set(),
        )
        names = {r["strategy"]: r["status"] for r in rec["strategies"]}
        self.assertEqual(names["experimental-strat"], "BACKTEST_ONLY")

    def test_zombie_state_only(self):
        rec = self._build(
            registry={},
            state_strats={"abandoned-strat": {"enabled": True}},
            backtest_fns=set(),
            monitors={},
            ledger_strats=set(),
        )
        names = {r["strategy"]: r["status"] for r in rec["strategies"]}
        self.assertEqual(names["abandoned-strat"], "ZOMBIE_STATE_ONLY")
        # flagged for operator review
        flagged = {f["strategy"] for f in rec["operator_flags"]}
        self.assertIn("abandoned-strat", flagged)

    def test_zombie_registry_only_with_signal_at_no_flag(self):
        rec = self._build(
            registry={"shadow-only-strat": {
                "asset_class": "us_equity",
                "signal_at": lambda i, b: None,
            }},
            state_strats={},
            backtest_fns=set(),
            monitors={},
            ledger_strats=set(),
        )
        names = {r["strategy"]: r["status"] for r in rec["strategies"]}
        # With signal_at fn, classifier prefers ACTIVE_SHADOW_SOURCE
        # because the function CAN generate signals; absence of state /
        # monitor / ledger only matters when there is no signal_at.
        self.assertEqual(
            names["shadow-only-strat"], "ACTIVE_SHADOW_SOURCE")

    def test_zombie_registry_only_auto_conversion(self):
        rec = self._build(
            registry={"orphaned-registry": {
                "asset_class": "us_equity",
                "signal_at":   None,
            }},
            state_strats={},
            backtest_fns=set(),
            monitors={},
            ledger_strats=set(),
        )
        names = {r["strategy"]: r["status"] for r in rec["strategies"]}
        # Without observe_only flag AND without signal_at, classifier
        # routes to OBSERVE_ONLY (registry observe-only-by-default).
        self.assertEqual(
            names["orphaned-registry"], "OBSERVE_ONLY")

    def test_disabled_intentionally(self):
        rec = self._build(
            registry={"overbought-short": {
                "asset_class": "us_equity",
                "signal_at": lambda i, b: None,
            }},
            state_strats={"overbought-short": {"enabled": False}},
            backtest_fns={"overbought-short"},
            monitors={},
            ledger_strats=set(),
        )
        names = {r["strategy"]: r["status"] for r in rec["strategies"]}
        self.assertEqual(
            names["overbought-short"], "DISABLED_INTENTIONALLY")

    def test_active_monitor_unregistered(self):
        rec = self._build(
            registry={},
            state_strats={},
            backtest_fns=set(),
            monitors={"twitter-A-direct": ["twitter-monitor"]},
            ledger_strats={"twitter-A-direct"},
        )
        names = {r["strategy"]: r["status"] for r in rec["strategies"]}
        self.assertEqual(
            names["twitter-A-direct"], "ACTIVE_MONITOR_UNREGISTERED")

    def test_status_distribution_aggregation(self):
        # Multiple statuses in one run.
        rec = self._build(
            registry={
                "crypto-momentum": {
                    "asset_class": "crypto",
                    "signal_at": lambda i, b: None,
                },
                "geo-defense": {
                    "asset_class": "us_equity",
                    "signal_at":   None,
                    "observe_only": True,
                },
            },
            state_strats={
                "crypto-momentum": {"enabled": True},
                "geo-defense":     {"enabled": True},
                "abandoned":       {"enabled": True},
            },
            backtest_fns={"crypto-momentum"},
            monitors={"crypto-momentum": ["crypto-monitor"]},
            ledger_strats={"crypto-momentum"},
        )
        sd = rec["status_distribution"]
        self.assertEqual(sd.get("ACTIVE_RUNTIME_SOURCE", 0), 1)
        self.assertEqual(sd.get("OBSERVE_ONLY", 0), 1)
        self.assertEqual(sd.get("ZOMBIE_STATE_ONLY", 0), 1)


class TestSafety(unittest.TestCase):
    def test_reconciler_does_not_import_alpaca_orders(self):
        src = (SCRIPTS_DIR / "reconcile_strategy_sources.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        "alpaca_orders", alias.name or "")
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(
                    "alpaca_orders", node.module or "")

    def test_reconciler_does_not_make_network_calls(self):
        src = (SCRIPTS_DIR / "reconcile_strategy_sources.py").read_text(
            encoding="utf-8")
        # Only allow git subprocess; no urllib/requests/socket/http.client.
        for forbidden in ("import requests", "from requests",
                           "urllib.request", "http.client",
                           "socket.connect"):
            self.assertNotIn(
                forbidden, src,
                f"reconciler must not use {forbidden}")

    def test_reconciler_does_not_modify_state_json(self):
        src = (SCRIPTS_DIR / "reconcile_strategy_sources.py").read_text(
            encoding="utf-8")
        # No state.json write_text inside this script.
        self.assertNotIn(
            "STATE_PATH.write_text", src,
            "reconciler must not write state.json")
        self.assertNotIn(
            'open(STATE_PATH, "w")', src,
            "reconciler must not write state.json")

    def test_safety_field_in_output(self):
        m = _load_module()
        m._load_registry = lambda repo_root=None: {}
        m._load_backtest_strategies = lambda repo_root=None: set()
        m._load_backtest_registry = lambda repo_root=None: {}
        m._scan_monitor_strategies = lambda repo_root=None: {}
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "learning-loop").mkdir()
            (tdp / "learning-loop" / "state.json").write_text(
                json.dumps({"strategies": {}}), encoding="utf-8")
            (tdp / "learning-loop" / "opportunity_ledger").mkdir()
            out = m.build_reconciliation(
                as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
                repo_root=tdp,
            )
        self.assertFalse(out["safety"]["edge_gate_enabled"])
        self.assertFalse(out["safety"]["allow_broker_paper"])
        self.assertFalse(out["safety"]["live_trading_supported"])
        self.assertFalse(out["safety"]["modifies_state_json"])
        self.assertFalse(out["safety"]["modifies_registry"])


if __name__ == "__main__":
    unittest.main()
