"""v3.30 (2026-06-09) — shadow strategy candidates safety contract.

v3.30 deliberately does NOT expand the deterministic strategy
registry (that work was deferred to avoid regressions across the
existing v3.27.x suite). This test pins that the existing registry
still contains the baseline candidates AND that observation emission
is wired into the per-symbol collector loop — so universe expansion
yields observation records even when no opportunity fires.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestExistingStrategyRegistryStable(unittest.TestCase):

    def test_registry_contains_baseline_candidates(self):
        import shadow_opportunity_generator as gen
        reg = gen._strategy_registry()
        names = set(reg.keys())
        self.assertIn("momentum-long", names)
        self.assertIn("crypto-momentum", names)

    def test_22_bar_atr_floor_preserved(self):
        src = (REPO_ROOT / "shared"
                / "shadow_opportunity_generator.py").read_text(
            encoding="utf-8")
        self.assertIn("< 22", src,
                       "22-bar ATR-window floor must be preserved")


class TestCollectorEmitsObservationRecords(unittest.TestCase):

    def test_collector_imports_observation_records(self):
        path = (REPO_ROOT / "scripts"
                 / "run_signal_shadow_evidence_collection.py")
        src = path.read_text(encoding="utf-8")
        self.assertIn("observation_records", src,
                       "collector must import observation_records")
        self.assertIn("METRIC_OBSERVATION_RECORDS", src,
                       "collector must bump observation counter")
        self.assertIn("REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL",
                       src,
                       "collector must map the diagnostic token")

    def test_collector_never_calls_submit_order(self):
        path = (REPO_ROOT / "scripts"
                 / "run_signal_shadow_evidence_collection.py")
        src = path.read_text(encoding="utf-8")
        for forbidden in ("submit_order(", "place_order(",
                            "safe_close("):
            self.assertNotIn(forbidden, src,
                              f"collector must NOT contain {forbidden}")


if __name__ == "__main__":
    unittest.main()
