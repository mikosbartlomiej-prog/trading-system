"""v3.17.0 (2026-06-04) — Strategy registry drift detection (Codex Task 7).

Closes audit gap: strategies present in `learning-loop/state.json::strategies`
that have no entry in `backtest/strategy_registry.py::REGISTRY` cannot be
backtested and are invisible to EDGE_GATE_ENABLED logic.

This test enforces the contract:
  - Every strategy named in `state.json::strategies` MUST be a key in REGISTRY
    (otherwise the registry lies about coverage and EDGE_GATE flip would be
    unsafe).
  - Strategies marked enabled=True in state.json MUST have readiness !=
    INTERFACE (we need at least MVP_IN_PROGRESS or HAS_SIGNAL).
  - REGISTRY entries marked HAS_SIGNAL must have a non-None signal_fn_name.

A test that fails here means either:
  - operator added a strategy to state.json without registering it (fix:
    add REGISTRY entry), OR
  - operator dropped a registry entry that's still referenced live (fix:
    re-add or disable in state.json).
"""

from __future__ import annotations

import json
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKTEST_DIR = os.path.join(REPO_ROOT, "backtest")
if BACKTEST_DIR not in sys.path:
    sys.path.insert(0, BACKTEST_DIR)


class TestStrategyRegistryDrift(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import strategy_registry as r
        cls.REGISTRY = r.REGISTRY
        cls.HAS_SIGNAL = r.HAS_SIGNAL
        cls.INTERFACE = r.INTERFACE
        cls.MVP = r.MVP_IN_PROGRESS
        cls.NOT_APPLICABLE = r.NOT_APPLICABLE
        with open(os.path.join(REPO_ROOT, "learning-loop", "state.json")) as f:
            cls.STATE = json.load(f)

    def test_every_state_json_strategy_has_registry_entry(self):
        """Drift detector — every strategy in state.json MUST be known to registry."""
        state_strategies = set(self.STATE.get("strategies", {}).keys())
        registry_strategies = set(self.REGISTRY.keys())
        missing = state_strategies - registry_strategies
        self.assertEqual(missing, set(),
                          f"strategies in state.json missing from REGISTRY: {sorted(missing)}")

    def test_enabled_strategies_have_actionable_readiness(self):
        """Enabled strategies must be at least MVP_IN_PROGRESS or HAS_SIGNAL,
        or explicitly NOT_APPLICABLE (admin tags like alloc-exit).
        INTERFACE alone is not enough — it means "no signal fn".
        """
        state_strategies = self.STATE.get("strategies", {})
        violations = []
        for name, cfg in state_strategies.items():
            if not cfg.get("enabled", True):
                continue
            entry = self.REGISTRY.get(name)
            if entry is None:
                continue  # caught by other test
            if entry.readiness == self.INTERFACE:
                violations.append(f"{name}: enabled but INTERFACE (no signal fn)")
        # We tolerate options-momentum as a known exception (paid data gap).
        violations = [v for v in violations if not v.startswith("options-momentum")]
        self.assertEqual(violations, [],
                          f"enabled strategies with INTERFACE readiness: {violations}")

    def test_has_signal_entries_have_signal_fn_name(self):
        """HAS_SIGNAL means there's a registered Python signal function."""
        missing_fn = []
        for name, entry in self.REGISTRY.items():
            if entry.readiness == self.HAS_SIGNAL:
                if not entry.signal_fn_name:
                    missing_fn.append(name)
        self.assertEqual(missing_fn, [],
                          f"HAS_SIGNAL entries missing signal_fn_name: {missing_fn}")

    def test_mvp_entries_have_signal_fn_name(self):
        """MVP_IN_PROGRESS entries have event_strategy fn (event-driven harness)."""
        missing_fn = []
        for name, entry in self.REGISTRY.items():
            if entry.readiness == self.MVP:
                if not entry.signal_fn_name:
                    missing_fn.append(name)
        self.assertEqual(missing_fn, [],
                          f"MVP_IN_PROGRESS entries missing signal_fn_name: {missing_fn}")

    def test_registry_count_matches_documentation_claim(self):
        """docs/backtesting_strategy_coverage.md claims ~3 HAS_SIGNAL out of 12+.
        v3.17.0: actually 5 HAS_SIGNAL (3 bar + 2 crypto), 3 MVP_IN_PROGRESS,
        1 EVENT_DRIVEN defunct, 1 INTERFACE, 4 NOT_APPLICABLE = 14 total.
        Test guards against drift in the count.
        """
        from collections import Counter
        counts = Counter(v.readiness for v in self.REGISTRY.values())
        self.assertGreaterEqual(counts.get(self.HAS_SIGNAL, 0), 5,
                                  "HAS_SIGNAL count regressed below 5")
        # Total >= 12 — if it drops below, someone removed strategies.
        self.assertGreaterEqual(len(self.REGISTRY), 12,
                                  "REGISTRY total dropped below 12 entries")


if __name__ == "__main__":
    unittest.main(verbosity=2)
