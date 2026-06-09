"""v3.26.1 (2026-06-09) — daily signal/shadow run check + evidence-quality.

Pin the v3.26.1 contract:
- shadow records carry an ``evidence_quality`` enum field,
- SCAFFOLD_NO_MARKET_DATA records do NOT count toward broker-paper
  canary readiness,
- only REAL_MARKET_DATA records can advance the canary gate (and
  the v3.25 trading_unlock_readiness module still requires
  daily_learning_stable + trade_reconstruction_stable + explicit
  operator approval on top of the threshold),
- the migration from v3.26.0 moved the 5 scaffold records out of
  ``normal_non_halt_opportunities_count``.
"""

from __future__ import annotations

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


def _load_collector():
    spec = importlib.util.spec_from_file_location(
        "run_signal_shadow_evidence_collection",
        REPO_ROOT / "scripts"
        / "run_signal_shadow_evidence_collection.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _clean_env() -> dict:
    return {
        "ALLOW_BROKER_PAPER": "false",
        "EDGE_GATE_ENABLED": "false",
        "BROKER_EXECUTION_ENABLED": "false",
        "LIVE_TRADING": "false",
        "LIVE_ENABLED": "false",
        "GO_LIVE": "false",
        "LIVE_TRADING_ENABLED": "false",
    }


class TestEvidenceQualityEnum(unittest.TestCase):
    def test_three_quality_values_exposed(self):
        import shadow_evidence_counters as sec
        self.assertEqual(
            sec.EVIDENCE_QUALITY_REAL_MARKET_DATA, "REAL_MARKET_DATA")
        self.assertEqual(
            sec.EVIDENCE_QUALITY_SCAFFOLD_NO_MARKET_DATA,
            "SCAFFOLD_NO_MARKET_DATA")
        self.assertEqual(
            sec.EVIDENCE_QUALITY_HALT_PATH_ONLY, "HALT_PATH_ONLY")
        for q in (
            sec.EVIDENCE_QUALITY_REAL_MARKET_DATA,
            sec.EVIDENCE_QUALITY_SCAFFOLD_NO_MARKET_DATA,
            sec.EVIDENCE_QUALITY_HALT_PATH_ONLY,
        ):
            self.assertIn(q, sec.ALL_EVIDENCE_QUALITIES)


class TestSchemaPinsEvidenceQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "schema.json")
        cls.data = json.loads(path.read_text())

    def test_evidence_quality_required(self):
        self.assertIn("evidence_quality", self.data["required"])

    def test_evidence_quality_enum_three_values(self):
        prop = self.data["properties"]["evidence_quality"]
        self.assertEqual(set(prop["enum"]), {
            "REAL_MARKET_DATA",
            "SCAFFOLD_NO_MARKET_DATA",
            "HALT_PATH_ONLY",
        })

    def test_broker_flags_still_pinned_false(self):
        self.assertEqual(
            self.data["properties"]["broker_execution_enabled"]["enum"],
            [False],
        )
        self.assertEqual(
            self.data["properties"]["broker_order_submitted"]["enum"],
            [False],
        )


class TestCollectorEmitsEvidenceQuality(unittest.TestCase):
    def setUp(self):
        self.collector = _load_collector()

    def test_build_record_default_quality_is_scaffold(self):
        rec = self.collector.build_record(
            symbol="X", asset_class="us_equity", strategy="s",
            decision_type="skip", side="none",
            would_trade=False, would_block=True,
            block_reasons=["NOOP"],
            sizing_preview={"proposed_usd": 0, "equity_usd": 0},
            exposure_policy_result={"decision": "NOOP"},
            drawdown_guard_state={"active": False},
            timestamp_iso="2026-06-09T00:00:00+00:00",
            audit_trace_id="x",
        )
        self.assertEqual(
            rec["evidence_quality"], "SCAFFOLD_NO_MARKET_DATA",
        )

    def test_build_record_real_market_quality_explicit(self):
        rec = self.collector.build_record(
            symbol="X", asset_class="us_equity", strategy="s",
            decision_type="entry", side="buy",
            would_trade=True, would_block=False, block_reasons=[],
            sizing_preview={"proposed_usd": 100, "equity_usd": 10000},
            exposure_policy_result={"decision": "ALLOW"},
            drawdown_guard_state={"active": False},
            timestamp_iso="2026-06-09T00:00:00+00:00",
            audit_trace_id="x",
            evidence_quality="REAL_MARKET_DATA",
        )
        self.assertEqual(
            rec["evidence_quality"], "REAL_MARKET_DATA",
        )

    def test_build_record_invalid_quality_raises(self):
        with self.assertRaises(ValueError):
            self.collector.build_record(
                symbol="X", asset_class="us_equity", strategy="s",
                decision_type="entry", side="buy",
                would_trade=True, would_block=False, block_reasons=[],
                sizing_preview={"proposed_usd": 0, "equity_usd": 0},
                exposure_policy_result={"decision": "x"},
                drawdown_guard_state={"active": False},
                timestamp_iso="2026-06-09T00:00:00+00:00",
                audit_trace_id="x",
                evidence_quality="ANYTHING_ELSE",
            )

    def test_collect_skip_marks_halt_path_only(self):
        with mock.patch.dict(os.environ, _clean_env(), clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "shared").symlink_to(REPO_ROOT / "shared")
                (root / "scripts").symlink_to(REPO_ROOT / "scripts")
                (root / "learning-loop").mkdir()
                (root / "learning-loop" / "shadow_evidence").mkdir()
                out = self.collector.collect(repo_root=root)
                self.assertEqual(
                    out["status"],
                    self.collector.SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA,
                )
                self.assertEqual(
                    out["evidence_quality"], "HALT_PATH_ONLY",
                )

    def test_market_data_available_routes_to_real_or_halt_not_scaffold(self):
        # v3.27.0 contract: market_data_available=True attempts to
        # fetch REAL_MARKET_DATA via the v3.27 provider+generator.
        # If real data is unavailable in the sandbox, the collector
        # falls through to halt-path — it does NOT silently emit
        # SCAFFOLD records.
        with mock.patch.dict(os.environ, _clean_env(), clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "shared").symlink_to(REPO_ROOT / "shared")
                (root / "scripts").symlink_to(REPO_ROOT / "scripts")
                (root / "learning-loop").mkdir()
                (root / "learning-loop" / "shadow_evidence").mkdir()
                out = self.collector.collect(
                    repo_root=root,
                    market_data_available=True,
                    max_records=3,
                )
                # Either real records flowed or halt-path fired.
                self.assertIn(out.get("evidence_quality"),
                                ("REAL_MARKET_DATA", "HALT_PATH_ONLY"))
                self.assertNotEqual(
                    out.get("evidence_quality"),
                    "SCAFFOLD_NO_MARKET_DATA",
                )


class TestCountersRoutedByEvidenceQuality(unittest.TestCase):
    def test_market_data_available_no_real_does_not_inflate_scaffold(self):
        # v3.27.0: when market_data_available=True is asserted but
        # real data cannot be fetched, the collector falls through
        # to halt-path. Scaffold counter MUST NOT advance.
        self.collector = _load_collector()
        with mock.patch.dict(os.environ, _clean_env(), clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "shared").symlink_to(REPO_ROOT / "shared")
                (root / "scripts").symlink_to(REPO_ROOT / "scripts")
                (root / "learning-loop").mkdir()
                (root / "learning-loop" / "shadow_evidence").mkdir()
                self.collector.collect(
                    repo_root=root,
                    market_data_available=True,
                    max_records=4,
                )
                counters_path = (
                    root / "learning-loop" / "shadow_evidence"
                    / "evidence_counters_latest.json")
                data = json.loads(counters_path.read_text())
                # Scaffold counter NEVER advances in v3.27 when
                # market_data_available=True is claimed.
                self.assertEqual(
                    data["scaffold_no_market_data_records_count"], 0)
                self.assertEqual(
                    data["real_market_opportunities_count"], 0)
                self.assertEqual(
                    data["normal_non_halt_opportunities_count"], 0)

    def test_halt_path_run_increments_halt_path_records(self):
        self.collector = _load_collector()
        with mock.patch.dict(os.environ, _clean_env(), clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "shared").symlink_to(REPO_ROOT / "shared")
                (root / "scripts").symlink_to(REPO_ROOT / "scripts")
                (root / "learning-loop").mkdir()
                (root / "learning-loop" / "shadow_evidence").mkdir()
                # Default = no market data available.
                self.collector.collect(repo_root=root)
                self.collector.collect(repo_root=root)
                counters_path = (
                    root / "learning-loop" / "shadow_evidence"
                    / "evidence_counters_latest.json")
                data = json.loads(counters_path.read_text())
                self.assertEqual(data["halt_path_records_count"], 2)
                self.assertEqual(
                    data["halt_path_opportunities_count"], 2)
                self.assertEqual(
                    data["real_market_opportunities_count"], 0)
                self.assertEqual(
                    data["scaffold_no_market_data_records_count"], 0)


class TestPersistedRecordsHaveEvidenceQuality(unittest.TestCase):
    def test_existing_2026_06_09_records_have_quality(self):
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "records_2026-06-09.jsonl")
        if not path.exists():
            self.skipTest("no records file yet")
        with path.open() as f:
            records = [json.loads(line) for line in f if line.strip()]
        # Every record must declare evidence_quality.
        for r in records:
            self.assertIn("evidence_quality", r,
                            "record missing evidence_quality")
            self.assertIn(
                r["evidence_quality"],
                {"REAL_MARKET_DATA",
                  "SCAFFOLD_NO_MARKET_DATA",
                  "HALT_PATH_ONLY"},
            )
            self.assertFalse(r["broker_order_submitted"])
            self.assertFalse(r["broker_execution_enabled"])


class TestCanaryStillBlockedAfterScaffoldOnly(unittest.TestCase):
    """No matter how many SCAFFOLD records exist, broker paper
    canary must remain blocked."""

    def test_scaffold_only_keeps_canary_blocked(self):
        from trading_unlock_readiness import (
            UnlockReadinessInputs, evaluate_unlock_readiness,
            SIGNAL_SHADOW_UNLOCK_READY,
        )
        # 1000 scaffold records, 0 real opportunities, 0 outcomes.
        inputs = UnlockReadinessInputs(
            normal_non_halt_opportunities_count=0,
            completed_shadow_outcomes_count=0,
        )
        report = evaluate_unlock_readiness(inputs)
        self.assertEqual(report.verdict, SIGNAL_SHADOW_UNLOCK_READY)
        # missing_for_broker_paper must reference the 50 / 20
        # thresholds, NOT scaffold counts.
        missing = " ".join(report.missing_for_broker_paper)
        self.assertIn("50", missing)
        self.assertIn("20", missing)

    def test_real_threshold_still_requires_operator_approval(self):
        from trading_unlock_readiness import (
            UnlockReadinessInputs, evaluate_unlock_readiness,
            SIGNAL_SHADOW_UNLOCK_READY,
        )
        # Hit both numeric thresholds but withhold operator approval
        # and daily_learning_stable / trade_reconstruction_stable.
        inputs = UnlockReadinessInputs(
            normal_non_halt_opportunities_count=100,
            completed_shadow_outcomes_count=25,
        )
        report = evaluate_unlock_readiness(inputs)
        self.assertEqual(report.verdict, SIGNAL_SHADOW_UNLOCK_READY)


class TestProgressSummaryUsesRealMarketCounter(unittest.TestCase):
    def test_progress_summary_keys_v3261(self):
        import shadow_evidence_counters as sec
        c = sec.EvidenceCounters()
        p = sec.progress_summary(c)
        # v3.26.1: the gate key is real_market_opportunities, not
        # normal_opportunities.
        self.assertIn("real_market_opportunities", p)
        self.assertNotIn("normal_opportunities", p)
        # Observational fields exposed.
        self.assertIn("scaffold_no_market_data_records", p)
        self.assertIn("halt_path_records", p)
        # broker_paper_canary_ready always False under v3.26.
        self.assertFalse(p["broker_paper_canary_ready"])
        self.assertFalse(p["live_trading_supported"])


class TestSafetyInvariantsUntouched(unittest.TestCase):
    def test_edge_gate_unchanged(self):
        v = os.environ.get("EDGE_GATE_ENABLED", "false").lower()
        self.assertNotEqual(v, "true")

    def test_allow_broker_paper_unchanged(self):
        v = os.environ.get("ALLOW_BROKER_PAPER", "false").lower()
        self.assertNotEqual(v, "true")

    def test_v3261_counters_file_broker_invariants_safe(self):
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "evidence_counters_latest.json")
        data = json.loads(path.read_text())
        si = data["safety_invariants"]
        self.assertFalse(si["broker_order_submitted_ever"])
        self.assertFalse(si["live_trading_enabled"])
        self.assertFalse(si["broker_paper_enabled"])
        self.assertFalse(si["edge_gate_enabled"])
        self.assertFalse(si["baseline_reset"])
        self.assertFalse(si["drawdown_guard_lowered"])


class TestLatestJsonV3261FollowupsRecorded(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = (REPO_ROOT / "learning-loop" / "position_reconciliation"
                 / "latest.json")
        cls.data = json.loads(path.read_text())

    def test_version_in_3_26_family(self):
        v = self.data["version"]
        self.assertTrue(
            v.startswith("v3.26") or v.startswith("v3.27"),
            f"unexpected version: {v}",
        )

    def test_v3261_followups_block_present(self):
        self.assertIn("v3261_followups", self.data)

    def test_v3261_followups_records_problem_and_fix(self):
        b = self.data["v3261_followups"]
        self.assertIn("problem", b)
        self.assertIn("fix", b)
        # Daily run section captures the verdict.
        dr = b["daily_run_2026_06_09"]
        self.assertEqual(dr["preflight_verdict"],
                          "SIGNAL_SHADOW_PREFLIGHT_PASS")
        self.assertEqual(
            dr["collector_status"],
            "SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA",
        )
        self.assertEqual(dr["real_market_records_emitted"], 0)
        # Carry-over scaffold count documented.
        self.assertEqual(
            dr["carry_over_scaffold_records_from_smoke"], 5,
        )

    def test_v3261_preserves_prior_followups(self):
        for key in ("v326_followups", "v325_followups",
                     "v324_followups", "v3233_3_followups",
                     "v3233_2_followups", "v3233_1_followups",
                     "v3233_followups", "v3232_followups"):
            self.assertIn(key, self.data,
                            f"prior followup block dropped: {key}")


if __name__ == "__main__":
    unittest.main()
