"""v3.27.2 (2026-06-09) — first_real_market_record_status.json tests."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_monitor():
    import importlib.util as iu
    spec = iu.spec_from_file_location(
        "monitor_automated_shadow_progress",
        REPO_ROOT / "scripts"
        / "monitor_automated_shadow_progress.py",
    )
    mod = iu.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestStatusFalseWhenNoRealRecord(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "learning-loop" / "shadow_evidence").mkdir(
            parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_records_at_all_yields_false(self):
        # No records_*.jsonl exist.
        payload = self.mod.build_first_real_record_status(
            repo_root=self.tmp,
            progress_status=self.mod.AUTOMATED_EVIDENCE_REQUIRES_MORE_RUNS,
            rationale=["bootstrap"],
            history=[],
        )
        self.assertFalse(payload["first_real_market_record_seen"])
        self.assertIsNone(payload["first_real_market_record_at"])
        self.assertIsNone(payload["first_real_market_symbol"])
        self.assertIsNone(payload["first_real_market_strategy"])

    def test_only_scaffold_records_yields_false(self):
        # Scaffold records do NOT advance the first-real flag.
        recs = (self.tmp / "learning-loop" / "shadow_evidence"
                  / "records_2026-06-09.jsonl")
        recs.write_text(json.dumps({
            "evidence_quality": "SCAFFOLD_NO_MARKET_DATA",
            "symbol": "SPY", "strategy": "momentum-long",
            "timestamp_iso": "2026-06-09T13:35:00+00:00",
        }) + "\n", encoding="utf-8")
        payload = self.mod.build_first_real_record_status(
            repo_root=self.tmp,
            progress_status=self.mod.AUTOMATED_EVIDENCE_HEALTHY_BUT_NO_SIGNALS_YET,
            rationale=["healthy"],
            history=[],
        )
        self.assertFalse(payload["first_real_market_record_seen"])

    def test_only_halt_path_records_yields_false(self):
        recs = (self.tmp / "learning-loop" / "shadow_evidence"
                  / "records_2026-06-09.jsonl")
        recs.write_text(json.dumps({
            "evidence_quality": "HALT_PATH_ONLY",
            "symbol": "QQQ", "strategy": "crypto-momentum",
            "timestamp_iso": "2026-06-09T13:35:00+00:00",
        }) + "\n", encoding="utf-8")
        payload = self.mod.build_first_real_record_status(
            repo_root=self.tmp,
            progress_status=self.mod.AUTOMATED_EVIDENCE_REQUIRES_MORE_RUNS,
            rationale=["bootstrap"],
            history=[],
        )
        self.assertFalse(payload["first_real_market_record_seen"])


class TestStatusTrueWhenRealRecordPresent(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "learning-loop" / "shadow_evidence").mkdir(
            parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_real_record_flips_status_true(self):
        recs = (self.tmp / "learning-loop" / "shadow_evidence"
                  / "records_2026-06-10.jsonl")
        recs.write_text(json.dumps({
            "evidence_quality": "REAL_MARKET_DATA",
            "symbol": "SPY", "strategy": "momentum-long",
            "timestamp_iso": "2026-06-10T13:35:42+00:00",
            "broker_order_submitted": False,
            "broker_execution_enabled": False,
        }) + "\n", encoding="utf-8")
        payload = self.mod.build_first_real_record_status(
            repo_root=self.tmp,
            progress_status=self.mod.AUTOMATED_EVIDENCE_PROGRESSING,
            rationale=["first real record landed"],
            history=[],
        )
        self.assertTrue(payload["first_real_market_record_seen"])
        self.assertEqual(payload["first_real_market_symbol"], "SPY")
        self.assertEqual(payload["first_real_market_strategy"],
                          "momentum-long")
        self.assertEqual(payload["first_real_market_record_at"],
                          "2026-06-10T13:35:42+00:00")

    def test_mixed_records_pick_first_real(self):
        # Scaffold first in time, real second — real wins for "first".
        recs1 = (self.tmp / "learning-loop" / "shadow_evidence"
                   / "records_2026-06-09.jsonl")
        recs1.write_text(json.dumps({
            "evidence_quality": "SCAFFOLD_NO_MARKET_DATA",
            "symbol": "QQQ", "strategy": "momentum-long",
            "timestamp_iso": "2026-06-09T13:35:00+00:00",
        }) + "\n" + json.dumps({
            "evidence_quality": "REAL_MARKET_DATA",
            "symbol": "AMD", "strategy": "momentum-long",
            "timestamp_iso": "2026-06-09T14:35:00+00:00",
        }) + "\n", encoding="utf-8")
        payload = self.mod.build_first_real_record_status(
            repo_root=self.tmp,
            progress_status=self.mod.AUTOMATED_EVIDENCE_PROGRESSING,
            rationale=["mixed"],
            history=[],
        )
        self.assertTrue(payload["first_real_market_record_seen"])
        self.assertEqual(payload["first_real_market_symbol"], "AMD")


class TestStatusPayloadShape(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()

    def test_required_fields_present(self):
        payload = self.mod.build_first_real_record_status(
            repo_root=Path(tempfile.mkdtemp()),
            progress_status=self.mod.AUTOMATED_EVIDENCE_REQUIRES_MORE_RUNS,
            rationale=["bootstrap"],
            history=[],
        )
        for k in (
            "version",
            "generated_at_iso",
            "first_real_market_record_seen",
            "first_real_market_record_at",
            "first_real_market_symbol",
            "first_real_market_strategy",
            "current_waiting_reason",
            "current_waiting_rationale",
            "diagnostic_dominant_token",
            "runs_observed",
            "successful_runs_observed",
            "next_expected_automation_window",
            "safety",
            "standing_markers",
        ):
            self.assertIn(k, payload, f"missing field: {k}")

    def test_standing_markers_always_present(self):
        payload = self.mod.build_first_real_record_status(
            repo_root=Path(tempfile.mkdtemp()),
            progress_status=self.mod.AUTOMATED_EVIDENCE_PROGRESSING,
            rationale=["x"],
            history=[],
        )
        self.assertIn("BROKER_PAPER_CANARY_STILL_BLOCKED",
                       payload["standing_markers"])
        self.assertIn("LIVE_TRADING_UNSUPPORTED",
                       payload["standing_markers"])
        self.assertTrue(
            payload["safety"]["broker_paper_canary_still_blocked"])
        self.assertTrue(
            payload["safety"]["live_trading_unsupported"])


class TestStatusArtifactWritten(unittest.TestCase):
    def test_artifact_exists_on_disk_after_smoke(self):
        # The on-repo artifact was created during the v3.27.2 smoke
        # run; verify the file exists and is well-formed JSON.
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "first_real_market_record_status.json")
        self.assertTrue(path.exists(),
                          f"missing status artifact: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("first_real_market_record_seen", data)
        self.assertIn("BROKER_PAPER_CANARY_STILL_BLOCKED",
                       data["standing_markers"])
        # The smoke artifact MUST NOT claim a real record exists
        # until one actually lands on disk.
        records_files = list(
            (REPO_ROOT / "learning-loop" / "shadow_evidence")
            .glob("records_*.jsonl"))
        any_real = False
        for p in records_files:
            text = p.read_text(encoding="utf-8")
            if '"evidence_quality": "REAL_MARKET_DATA"' in text:
                any_real = True
                break
        # If no real record on disk, status must say so.
        if not any_real:
            self.assertFalse(data["first_real_market_record_seen"])


class TestBrokerInvariants(unittest.TestCase):
    def test_status_artifact_carries_safety_block(self):
        path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                 / "first_real_market_record_status.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(
            data["safety"]["broker_paper_canary_still_blocked"])
        self.assertTrue(
            data["safety"]["live_trading_unsupported"])


if __name__ == "__main__":
    unittest.main()
