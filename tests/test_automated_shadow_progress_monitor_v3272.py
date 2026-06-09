"""v3.27.2 (2026-06-09) — progress monitor rule-matrix tests."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

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


def _entry(*, run_id, conclusion="success",
           diag=None, real_count=0, completed=0,
           generated_at_iso=None):
    return {
        "appended_at_iso":     "2026-06-09T13:35:00+00:00",
        "generated_at_iso":    (generated_at_iso
                                  or f"2026-06-09T13:{run_id:02d}:00+00:00"),
        "workflow_run_id":     str(run_id),
        "workflow_conclusion": conclusion,
        "collector_status":    "SHADOW_COLLECTION_PROCEEDING",
        "resolver_status":     "RESOLVED",
        "secrets_status":      "SECRETS_AVAILABLE",
        "verdict":             "AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET",
        "diagnostic_token_counts": dict(diag or {}),
        "counters_snapshot": {
            "real_market_opportunities_count": real_count,
            "completed_shadow_outcomes_count": completed,
        },
        "standing_markers": [
            "BROKER_PAPER_CANARY_STILL_BLOCKED",
            "LIVE_TRADING_UNSUPPORTED",
        ],
        "safety": {
            "broker_paper_canary_still_blocked": True,
            "live_trading_unsupported":          True,
        },
    }


# ────────────────────────────────────────────────────────────────────────────
# Rule 7 — REQUIRES_MORE_RUNS
# ────────────────────────────────────────────────────────────────────────────

class TestRequiresMoreRuns(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()

    def test_empty_history_returns_requires_more_runs(self):
        s, _ = self.mod.evaluate_progress([])
        self.assertEqual(
            s, "AUTOMATED_EVIDENCE_REQUIRES_MORE_RUNS")

    def test_one_success_run_returns_requires_more_runs(self):
        hist = [_entry(run_id=1, diag={
            "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 5})]
        s, _ = self.mod.evaluate_progress(hist)
        self.assertEqual(
            s, "AUTOMATED_EVIDENCE_REQUIRES_MORE_RUNS")


# ────────────────────────────────────────────────────────────────────────────
# Rule 1 — PROGRESSING
# ────────────────────────────────────────────────────────────────────────────

class TestProgressing(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()

    def test_real_count_increase_returns_progressing(self):
        hist = [
            _entry(run_id=1, real_count=0,
                    diag={"REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 5}),
            _entry(run_id=2, real_count=2,
                    diag={"REAL_MARKET_SIGNAL_RECORDS_EMITTED": 2,
                          "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 3}),
        ]
        s, _ = self.mod.evaluate_progress(hist)
        self.assertEqual(s, "AUTOMATED_EVIDENCE_PROGRESSING")

    def test_real_signal_emitted_token_returns_progressing(self):
        # Even without an opportunities-count increase, an explicit
        # REAL_MARKET_SIGNAL_RECORDS_EMITTED on the latest run marks
        # progress.
        hist = [
            _entry(run_id=1, real_count=0, diag={"MARKET_CLOSED_OR_NO_BARS": 3}),
            _entry(run_id=2, real_count=0,
                    diag={"REAL_MARKET_SIGNAL_RECORDS_EMITTED": 1,
                          "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 5}),
        ]
        s, _ = self.mod.evaluate_progress(hist)
        self.assertEqual(s, "AUTOMATED_EVIDENCE_PROGRESSING")


# ────────────────────────────────────────────────────────────────────────────
# Rules 2-3 — auth + provider error
# ────────────────────────────────────────────────────────────────────────────

class TestStuckAuth(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()

    def test_auth_failed_in_2_consecutive_runs_returns_stuck_auth(self):
        hist = [
            _entry(run_id=1, diag={"MARKET_DATA_AUTH_FAILED": 5}),
            _entry(run_id=2, diag={"MARKET_DATA_AUTH_FAILED": 8}),
        ]
        s, _ = self.mod.evaluate_progress(hist)
        self.assertEqual(s, "AUTOMATED_EVIDENCE_STUCK_AUTH")

    def test_auth_failed_only_once_does_not_block(self):
        hist = [
            _entry(run_id=1, diag={"MARKET_DATA_AUTH_FAILED": 5}),
            _entry(run_id=2,
                    diag={"REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 8}),
        ]
        s, _ = self.mod.evaluate_progress(hist)
        self.assertNotEqual(s, "AUTOMATED_EVIDENCE_STUCK_AUTH")


class TestStuckProviderError(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()

    def test_provider_error_in_2_consecutive_runs(self):
        hist = [
            _entry(run_id=1, diag={"MARKET_DATA_PROVIDER_ERROR": 4}),
            _entry(run_id=2, diag={"MARKET_DATA_PROVIDER_ERROR": 3}),
        ]
        s, _ = self.mod.evaluate_progress(hist)
        self.assertEqual(s, "AUTOMATED_EVIDENCE_STUCK_PROVIDER_ERROR")


# ────────────────────────────────────────────────────────────────────────────
# Rule 4 — insufficient bars
# ────────────────────────────────────────────────────────────────────────────

class TestStuckInsufficientBars(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()

    def test_insufficient_bars_dominant_in_2_runs(self):
        hist = [
            _entry(run_id=1,
                    diag={"INSUFFICIENT_BARS_FOR_SIGNAL": 6,
                          "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 1}),
            _entry(run_id=2,
                    diag={"INSUFFICIENT_BARS_FOR_SIGNAL": 7,
                          "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 0}),
        ]
        s, _ = self.mod.evaluate_progress(hist)
        self.assertEqual(
            s, "AUTOMATED_EVIDENCE_STUCK_INSUFFICIENT_BARS")


# ────────────────────────────────────────────────────────────────────────────
# Rule 5 — market closed outside vs inside session
# ────────────────────────────────────────────────────────────────────────────

class TestMarketClosedOutsideSession(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()

    def test_market_closed_outside_session_is_not_failure(self):
        hist = [
            _entry(run_id=1, diag={"MARKET_CLOSED_OR_NO_BARS": 7}),
            _entry(run_id=2, diag={"MARKET_CLOSED_OR_NO_BARS": 7}),
        ]
        # Saturday 21:00 UTC — definitely outside session.
        s, _ = self.mod.evaluate_progress(
            hist,
            now=datetime(2026, 6, 6, 21, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            s, "AUTOMATED_EVIDENCE_HEALTHY_BUT_NO_SIGNALS_YET")

    def test_market_closed_inside_session_returns_stuck(self):
        hist = [
            _entry(run_id=1, diag={"MARKET_CLOSED_OR_NO_BARS": 7}),
            _entry(run_id=2, diag={"MARKET_CLOSED_OR_NO_BARS": 7}),
        ]
        # Monday 14:00 UTC — inside US session.
        s, _ = self.mod.evaluate_progress(
            hist,
            now=datetime(2026, 6, 8, 14, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            s, "AUTOMATED_EVIDENCE_STUCK_NO_MARKET_DATA")


# ────────────────────────────────────────────────────────────────────────────
# Rule 6 — generator too restrictive (3-run threshold)
# ────────────────────────────────────────────────────────────────────────────

class TestStuckGeneratorTooRestrictive(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()

    def test_no_signal_dominant_2_runs_NOT_yet_stuck(self):
        # 2 runs of pure REAL_BUT_NO_SIGNAL is not enough to flag
        # generator restrictiveness; the threshold is 3.
        hist = [
            _entry(run_id=1,
                    diag={"REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 10}),
            _entry(run_id=2,
                    diag={"REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 10}),
        ]
        s, _ = self.mod.evaluate_progress(hist)
        self.assertNotEqual(
            s, "AUTOMATED_EVIDENCE_STUCK_GENERATOR_TOO_RESTRICTIVE")

    def test_no_signal_dominant_3_runs_marks_too_restrictive(self):
        hist = [
            _entry(run_id=i,
                    diag={"REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 10})
            for i in (1, 2, 3)
        ]
        s, _ = self.mod.evaluate_progress(hist)
        self.assertEqual(
            s, "AUTOMATED_EVIDENCE_STUCK_GENERATOR_TOO_RESTRICTIVE")


# ────────────────────────────────────────────────────────────────────────────
# Rule 8 — healthy fall-through
# ────────────────────────────────────────────────────────────────────────────

class TestHealthyFallthrough(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()

    def test_two_quiet_runs_returns_healthy_but_no_signals_yet(self):
        # 2 successful runs with non-error diag and no count growth
        # but no token meets a stuck threshold.
        hist = [
            _entry(run_id=1,
                    diag={"MARKET_CLOSED_OR_NO_BARS": 7}),
            _entry(run_id=2,
                    diag={"REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL": 7}),
        ]
        s, _ = self.mod.evaluate_progress(
            hist,
            now=datetime(2026, 6, 6, 22, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            s, "AUTOMATED_EVIDENCE_HEALTHY_BUT_NO_SIGNALS_YET")


# ────────────────────────────────────────────────────────────────────────────
# Failed workflow runs are excluded from trend analysis
# ────────────────────────────────────────────────────────────────────────────

class TestFailedRunsExcluded(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()

    def test_failed_runs_do_not_count_toward_thresholds(self):
        hist = [
            _entry(run_id=1, conclusion="failure",
                    diag={"MARKET_DATA_AUTH_FAILED": 5}),
            _entry(run_id=2, conclusion="failure",
                    diag={"MARKET_DATA_AUTH_FAILED": 5}),
        ]
        # 0 successful runs → REQUIRES_MORE_RUNS, NOT STUCK_AUTH.
        s, _ = self.mod.evaluate_progress(hist)
        self.assertEqual(
            s, "AUTOMATED_EVIDENCE_REQUIRES_MORE_RUNS")


# ────────────────────────────────────────────────────────────────────────────
# Safety: standing markers / never imports broker / never advances canary
# ────────────────────────────────────────────────────────────────────────────

class TestSafety(unittest.TestCase):
    def setUp(self):
        self.mod = _load_monitor()

    def test_all_statuses_enumerated(self):
        for tok in (
            "AUTOMATED_EVIDENCE_PROGRESSING",
            "AUTOMATED_EVIDENCE_HEALTHY_BUT_NO_SIGNALS_YET",
            "AUTOMATED_EVIDENCE_STUCK_NO_MARKET_DATA",
            "AUTOMATED_EVIDENCE_STUCK_INSUFFICIENT_BARS",
            "AUTOMATED_EVIDENCE_STUCK_AUTH",
            "AUTOMATED_EVIDENCE_STUCK_PROVIDER_ERROR",
            "AUTOMATED_EVIDENCE_STUCK_GENERATOR_TOO_RESTRICTIVE",
            "AUTOMATED_EVIDENCE_REQUIRES_MORE_RUNS",
        ):
            self.assertIn(
                getattr(self.mod, tok),
                self.mod.ALL_PROGRESS_STATUSES,
            )

    def test_standing_markers_constant(self):
        self.assertEqual(self.mod.BROKER_PAPER_CANARY_STILL_BLOCKED,
                          "BROKER_PAPER_CANARY_STILL_BLOCKED")
        self.assertEqual(self.mod.LIVE_TRADING_UNSUPPORTED,
                          "LIVE_TRADING_UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
