"""v3.27.0 — Tests for extended source separation in
``scripts/build_confidence_precalibration_readiness.py``.

Hard-safety invariants verified here:
- Replay rows NEVER count as production positives.
- Near-miss rows NEVER count as production positives.
- Fixture rows NEVER count as production positives.
- Verdict NEVER recommends calibration without outcomes.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_confidence_precalibration_readiness as bp  # noqa: E402


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_replay_artefact(tmp: Path, candidate_count: int) -> Path:
    """Write a minimal replay_discovery_latest.json with N candidates."""
    candidate_records = []
    for i in range(candidate_count):
        candidate_records.append({
            "action":            "BUY",
            "asset_class":       "us_equity",
            "entry_price":       100.0 + i,
            "evidence_source":   "REPLAY",
            "idx":               i,
            "is_paper_trade":    False,
            "is_real_market":    False,
            "is_signal_observation": False,
            "replay_version":    "v3.26.0",
            "rsi":               55.0,
            "snapshot_source":   "backfill_snapshots",
            "stop_loss":         95.0,
            "strategy":          "momentum-long",
            "symbol":            "AAPL",
            "take_profit":       110.0,
        })
    artefact = {
        "as_of":            "2026-06-15T00:00:00+00:00",
        "rows": [{
            "asset_class":         "us_equity",
            "candidates":          candidate_count,
            "candidate_records":   candidate_records,
            "diagnostic":          "OK",
            "near_misses":         0,
            "strategy":            "momentum-long",
            "symbol":              "AAPL",
            "threshold_crosses":   0,
        }],
    }
    p = tmp / "replay_discovery_latest.json"
    p.write_text(json.dumps(artefact), encoding="utf-8")
    return p


def _make_near_miss_jsonl(tmp_dir: Path, n_rows: int,
                          date_str: str = "2026-06-15") -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    p = tmp_dir / f"{date_str}.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for i in range(n_rows):
            fh.write(json.dumps({
                "ts":          f"2026-06-15T0{i % 9}:00:00+00:00",
                "strategy_id": "momentum-long",
                "symbol":      "AAPL",
                "metric_name": "rsi",
                "current_value": 48.0 + i,
                "threshold":   50.0,
                "distance":    -(2.0 - (i % 2)),
                "abs_distance": 2.0 - (i % 2),
                "is_paper_trade": False,
                "is_signal":   False,
            }) + "\n")
    return p


def _make_ledger_jsonl(
    tmp_dir: Path,
    *,
    n_positive_rows: int = 0,
    n_fixture_rows: int = 0,
    date_str: str = "2026-06-15",
) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    p = tmp_dir / f"{date_str}.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        # Production positive rows
        for i in range(n_positive_rows):
            fh.write(json.dumps({
                "confidence_score":   0.55 + i * 0.01,
                "confidence_components": {
                    "data_quality":      0.7,
                    "signal_strength":   0.6 + i * 0.01,
                    "regime_alignment":  0.5,
                    "system_health":     0.8,
                    "risk_state":        0.6,
                    "structural_filter": 0.5,
                    "confirmation":      0.5,
                    "operational":       0.5,
                },
                "builder_completeness": 0.8,
                "confidence_decision":  "ALERT_ONLY",
                "signal_id":            f"prod-momentum-AAPL-{i:03d}",
            }) + "\n")
        # Fixture rows (must be EXCLUDED from production count)
        for i in range(n_fixture_rows):
            fh.write(json.dumps({
                "confidence_score":   0.50,
                "confidence_components": {
                    "data_quality":      0.5,
                    "signal_strength":   0.5,
                    "regime_alignment":  0.5,
                    "system_health":     0.5,
                    "risk_state":        0.5,
                    "structural_filter": 0.5,
                    "confirmation":      0.5,
                    "operational":       0.5,
                },
                "builder_completeness": 0.5,
                "confidence_decision":  "ALERT_ONLY",
                "evidence_source":      "FIXTURE",
                "signal_id":            f"test-fixture-AAPL-{i:03d}",
            }) + "\n")
    return p


def _patch_paths_to_tmp(tmp: Path) -> dict:
    """Monkeypatch v3.27 input paths to test fixtures."""
    patches = {
        "REPLAY_DISCOVERY_PATH": tmp / "replay_discovery_latest.json",
        "NEAR_MISS_DIR_V327":    tmp / "near_miss",
        "SHADOW_EVIDENCE_DIR":   tmp / "shadow_evidence",
        "LEDGER_DIR":            tmp / "ledger",
    }
    return patches


def _run_build_with_paths(*, tmp: Path, as_of: datetime) -> dict:
    """Re-runs ``build_report`` with v3.27 paths patched to tmp."""
    patches = _patch_paths_to_tmp(tmp)
    with mock.patch.object(bp, "REPLAY_DISCOVERY_PATH",
                            patches["REPLAY_DISCOVERY_PATH"]), \
         mock.patch.object(bp, "NEAR_MISS_DIR_V327",
                            patches["NEAR_MISS_DIR_V327"]), \
         mock.patch.object(bp, "SHADOW_EVIDENCE_DIR",
                            patches["SHADOW_EVIDENCE_DIR"]):
        return bp.build_report(
            as_of=as_of,
            days=7,
            base_dir=patches["LEDGER_DIR"],
        )


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestSeparationCounts(unittest.TestCase):
    AS_OF = datetime(2026, 6, 15, tzinfo=timezone.utc)

    def test_production_positive_rows_counted_separately(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_ledger_jsonl(tdp / "ledger", n_positive_rows=5)
            rep = _run_build_with_paths(tmp=tdp, as_of=self.AS_OF)
            sep = rep["source_separation"]
            self.assertEqual(sep["production_positive_rows"], 5)
            self.assertEqual(sep["replay_positive_rows"], 0)
            self.assertEqual(sep["near_miss_rows"], 0)
            self.assertEqual(sep["fixture_only_rows"], 0)

    def test_replay_positive_rows_counted_separately(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_replay_artefact(tdp, candidate_count=7)
            rep = _run_build_with_paths(tmp=tdp, as_of=self.AS_OF)
            sep = rep["source_separation"]
            # Replay counted, production stays zero.
            self.assertEqual(sep["replay_positive_rows"], 7)
            self.assertEqual(sep["production_positive_rows"], 0)
            # Replay rows DO NOT inflate production count.
            self.assertEqual(sep["fixture_only_rows"], 0)

    def test_near_miss_rows_counted_separately(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_near_miss_jsonl(tdp / "near_miss", n_rows=12)
            rep = _run_build_with_paths(tmp=tdp, as_of=self.AS_OF)
            sep = rep["source_separation"]
            self.assertEqual(sep["near_miss_rows"], 12)
            self.assertEqual(sep["production_positive_rows"], 0)
            self.assertEqual(sep["replay_positive_rows"], 0)

    def test_fixture_only_rows_excluded_from_production_count(self):
        """Fixture-tagged rows MUST NOT inflate production positives."""
        with TemporaryDirectory() as td:
            tdp = Path(td)
            # 3 real production + 4 fixture rows
            _make_ledger_jsonl(
                tdp / "ledger",
                n_positive_rows=3,
                n_fixture_rows=4,
            )
            rep = _run_build_with_paths(tmp=tdp, as_of=self.AS_OF)
            sep = rep["source_separation"]
            self.assertEqual(sep["fixture_only_rows"], 4)
            self.assertEqual(sep["production_positive_rows"], 3)


class TestSeparationVerdicts(unittest.TestCase):
    AS_OF = datetime(2026, 6, 15, tzinfo=timezone.utc)

    def test_verdict_NOT_READY_NO_POSITIVE_ROWS_when_all_zero(self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            # Nothing seeded anywhere.
            rep = _run_build_with_paths(tmp=tdp, as_of=self.AS_OF)
            sep = rep["source_separation"]
            self.assertEqual(
                sep["verdict_v327"],
                "NOT_READY_NO_POSITIVE_ROWS",
            )
            # Standing markers explicit on this point.
            self.assertIn(
                "REPLAY_ROW_NEVER_COUNTS_AS_PRODUCTION_POSITIVE",
                rep["standing_markers"],
            )

    def test_verdict_READY_FOR_COMPONENT_VARIANCE_REVIEW_when_replay_present(
            self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_replay_artefact(tdp, candidate_count=29)
            _make_near_miss_jsonl(tdp / "near_miss", n_rows=50)
            rep = _run_build_with_paths(tmp=tdp, as_of=self.AS_OF)
            sep = rep["source_separation"]
            self.assertEqual(
                sep["verdict_v327"],
                "READY_FOR_COMPONENT_VARIANCE_REVIEW",
            )
            self.assertEqual(sep["production_positive_rows"], 0)
            # Reason MUST explicitly forbid calibration.
            self.assertIn("MUST NOT", sep["verdict_v327_reason"])

    def test_verdict_NOT_READY_NO_OUTCOMES_when_production_present_no_outcomes(
            self):
        with TemporaryDirectory() as td:
            tdp = Path(td)
            _make_ledger_jsonl(tdp / "ledger", n_positive_rows=10)
            # Shadow evidence dir EMPTY => no outcomes.
            rep = _run_build_with_paths(tmp=tdp, as_of=self.AS_OF)
            sep = rep["source_separation"]
            self.assertEqual(sep["production_positive_rows"], 10)
            self.assertFalse(sep["outcomes_available"])
            self.assertEqual(
                sep["verdict_v327"],
                "NOT_READY_NO_OUTCOMES",
            )
            self.assertIn(
                "calibration", sep["verdict_v327_reason"].lower())


class TestStandingMarkersAndSafety(unittest.TestCase):
    def test_safety_block_includes_v327_separation_flags(self):
        with TemporaryDirectory() as td:
            rep = _run_build_with_paths(
                tmp=Path(td),
                as_of=datetime(2026, 6, 15, tzinfo=timezone.utc),
            )
            safety = rep["safety"]
            self.assertFalse(safety["replay_counted_as_production"])
            self.assertFalse(safety["near_miss_counted_as_production"])
            self.assertFalse(safety["fixture_counted_as_production"])
            self.assertFalse(
                safety["calibration_recommended_without_outcomes"])


if __name__ == "__main__":
    unittest.main()
