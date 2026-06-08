"""v3.26.0 (2026-06-09) — shadow evidence counter tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import shadow_evidence_counters as sec


class TestCountersStructure(unittest.TestCase):
    def test_default_counters_all_zero(self):
        c = sec.EvidenceCounters()
        for name in sec.ALL_METRICS:
            self.assertEqual(
                getattr(c, name), 0,
                f"default {name} must be 0",
            )

    def test_all_metrics_list_present(self):
        for required in (
            "normal_non_halt_opportunities_count",
            "completed_shadow_outcomes_count",
            "halt_path_opportunities_count",
            "would_block_by_crypto_exposure_count",
            "would_block_by_drawdown_guard_count",
            "would_block_by_recent_loss_cooldown_count",
            "exposure_cap_breach_count",
            "repeated_buy_violation_count",
            "audit_bypass_findings_count",
            "unexplained_broker_state_conflicts_count",
        ):
            self.assertIn(required, sec.ALL_METRICS)

    def test_thresholds_default_50_and_20(self):
        self.assertEqual(sec.THRESHOLD_NORMAL_OPPORTUNITIES, 50)
        self.assertEqual(sec.THRESHOLD_SHADOW_OUTCOMES, 20)

    def test_default_safety_invariants_safe(self):
        c = sec.EvidenceCounters()
        self.assertFalse(
            c.safety_invariants["broker_order_submitted_ever"])
        self.assertFalse(c.safety_invariants["live_trading_enabled"])
        self.assertFalse(c.safety_invariants["broker_paper_enabled"])
        self.assertFalse(c.safety_invariants["edge_gate_enabled"])
        self.assertFalse(c.safety_invariants["baseline_reset"])
        self.assertFalse(c.safety_invariants["drawdown_guard_lowered"])


class TestMonotonicIncrement(unittest.TestCase):
    def test_increment_by_one(self):
        c = sec.EvidenceCounters()
        sec.increment(c, sec.METRIC_NORMAL_NON_HALT_OPPORTUNITIES)
        self.assertEqual(c.normal_non_halt_opportunities_count, 1)

    def test_increment_by_more(self):
        c = sec.EvidenceCounters()
        sec.increment(c, sec.METRIC_COMPLETED_SHADOW_OUTCOMES, by=5)
        self.assertEqual(c.completed_shadow_outcomes_count, 5)

    def test_increment_clamps_negative_to_noop(self):
        c = sec.EvidenceCounters()
        sec.increment(c, sec.METRIC_NORMAL_NON_HALT_OPPORTUNITIES,
                       by=-3)
        self.assertEqual(c.normal_non_halt_opportunities_count, 0)
        sec.increment(c, sec.METRIC_NORMAL_NON_HALT_OPPORTUNITIES,
                       by=0)
        self.assertEqual(c.normal_non_halt_opportunities_count, 0)

    def test_unknown_metric_raises(self):
        c = sec.EvidenceCounters()
        with self.assertRaises(KeyError):
            sec.increment(c, "not_a_metric")


class TestPersistRoundTrip(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c = sec.EvidenceCounters()
            sec.increment(c, sec.METRIC_NORMAL_NON_HALT_OPPORTUNITIES,
                           by=3)
            sec.increment(c, sec.METRIC_COMPLETED_SHADOW_OUTCOMES,
                           by=1)
            path = sec.save_counters(c, repo_root=root)
            self.assertTrue(path.exists())
            data = json.loads(path.read_text())
            self.assertEqual(
                data["normal_non_halt_opportunities_count"], 3)
            self.assertEqual(
                data["completed_shadow_outcomes_count"], 1)
            # Round-trip via load.
            c2 = sec.load_counters(root)
            self.assertEqual(
                c2.normal_non_halt_opportunities_count, 3)
            self.assertEqual(c2.completed_shadow_outcomes_count, 1)

    def test_load_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = sec.load_counters(Path(tmp))
            self.assertEqual(
                c.normal_non_halt_opportunities_count, 0)

    def test_save_refuses_if_broker_order_submitted_ever_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = sec.EvidenceCounters()
            c.safety_invariants["broker_order_submitted_ever"] = True
            with self.assertRaises(RuntimeError):
                sec.save_counters(c, repo_root=Path(tmp))

    def test_save_refuses_if_live_trading_enabled_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = sec.EvidenceCounters()
            c.safety_invariants["live_trading_enabled"] = True
            with self.assertRaises(RuntimeError):
                sec.save_counters(c, repo_root=Path(tmp))

    def test_save_refuses_if_broker_paper_enabled_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = sec.EvidenceCounters()
            c.safety_invariants["broker_paper_enabled"] = True
            with self.assertRaises(RuntimeError):
                sec.save_counters(c, repo_root=Path(tmp))


class TestProgressTowardBrokerPaper(unittest.TestCase):
    def test_initial_progress_is_zero_over_50_and_20(self):
        c = sec.EvidenceCounters()
        p = sec.progress_summary(c)
        self.assertEqual(p["normal_opportunities"], "0/50")
        self.assertEqual(p["completed_shadow_outcomes"], "0/20")
        self.assertFalse(p["broker_paper_canary_ready"])
        self.assertFalse(p["live_trading_supported"])

    def test_progress_increments_toward_target(self):
        c = sec.EvidenceCounters()
        sec.increment(c, sec.METRIC_NORMAL_NON_HALT_OPPORTUNITIES,
                       by=10)
        sec.increment(c, sec.METRIC_COMPLETED_SHADOW_OUTCOMES, by=2)
        p = sec.progress_summary(c)
        self.assertEqual(p["normal_opportunities"], "10/50")
        self.assertEqual(p["completed_shadow_outcomes"], "2/20")


class TestThresholdsFedToUnlockReadiness(unittest.TestCase):
    """The counter thresholds must MATCH the v3.25 unlock readiness
    thresholds so the two modules agree on broker-paper criteria."""

    def test_thresholds_match_unlock_readiness_constants(self):
        from trading_unlock_readiness import (
            BROKER_PAPER_MIN_NORMAL_OPPORTUNITIES,
            BROKER_PAPER_MIN_SHADOW_OUTCOMES,
        )
        self.assertEqual(
            sec.THRESHOLD_NORMAL_OPPORTUNITIES,
            BROKER_PAPER_MIN_NORMAL_OPPORTUNITIES,
        )
        self.assertEqual(
            sec.THRESHOLD_SHADOW_OUTCOMES,
            BROKER_PAPER_MIN_SHADOW_OUTCOMES,
        )


class TestRealRepoCountersFilePresent(unittest.TestCase):
    """The initial counters file we committed must exist and have the
    expected zero-state shape."""

    def test_real_counters_file_exists(self):
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "evidence_counters_latest.json")
        self.assertTrue(path.exists(), f"counters file missing: {path}")

    def test_real_counters_initial_zeros(self):
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "evidence_counters_latest.json")
        data = json.loads(path.read_text())
        for metric in sec.ALL_METRICS:
            self.assertEqual(
                data.get(metric), 0,
                f"{metric} must start at 0 (got {data.get(metric)})",
            )


class TestSchemaShipped(unittest.TestCase):
    def test_schema_file_present(self):
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "schema.json")
        self.assertTrue(path.exists(), f"schema file missing: {path}")

    def test_schema_pins_broker_flags_to_false(self):
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "schema.json")
        data = json.loads(path.read_text())
        be = data["properties"]["broker_execution_enabled"]
        os_ = data["properties"]["broker_order_submitted"]
        self.assertEqual(be["enum"], [False])
        self.assertEqual(os_["enum"], [False])

    def test_schema_includes_required_fields(self):
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "schema.json")
        data = json.loads(path.read_text())
        required = set(data["required"])
        for f in (
            "timestamp", "symbol", "asset_class", "strategy",
            "decision_type", "side", "would_trade", "would_block",
            "block_reasons", "sizing_preview",
            "exposure_policy_result", "drawdown_guard_state",
            "broker_execution_enabled", "broker_order_submitted",
            "outcome_tracking_status", "audit_trace_id",
        ):
            self.assertIn(f, required)


class TestInvariantConstants(unittest.TestCase):
    def test_invariants_true(self):
        self.assertTrue(sec.NEVER_SUBMITS_ORDERS)
        self.assertTrue(sec.NEVER_PROMOTES_BROKER_PAPER)
        self.assertTrue(sec.COUNTERS_ARE_MONOTONIC)


if __name__ == "__main__":
    unittest.main()
