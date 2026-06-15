"""v3.23.0 — tests for ``scripts/build_confidence_reality_check.py``."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_confidence_reality_check as bcr  # type: ignore  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def _seed(repo_root: Path, *, rows: list[dict], state: dict | None,
            as_of: datetime) -> None:
    ledger_dir = repo_root / "learning-loop" / "opportunity_ledger"
    _write_jsonl(
        ledger_dir / f"{as_of.date().isoformat()}.jsonl", rows)
    if state is not None:
        _write_json(
            repo_root / "learning-loop" / "state.json", state)


class TestBuildConfidenceRealityCheck(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.as_of = datetime(2026, 6, 15, 12, 0,
                              tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_empty_ledger_returns_zero_population(self):
        _seed(self.repo, rows=[], state=None, as_of=self.as_of)
        check = bcr.build_check(as_of=self.as_of, repo_root=self.repo)
        self.assertEqual(check["rows_total_7d"], 0)
        self.assertEqual(
            check["rows_with_confidence_score_nonnull"], 0)
        self.assertEqual(
            check["rows_with_confidence_components_nonempty"], 0)

    def test_all_null_score_marks_everything_default(self):
        rows = [
            {"confidence_score": None, "confidence_components": {}},
            {"confidence_score": None, "confidence_components": {}},
            {"confidence_score": None, "confidence_components": {}},
        ]
        _seed(self.repo, rows=rows, state=None, as_of=self.as_of)
        check = bcr.build_check(as_of=self.as_of, repo_root=self.repo)
        self.assertEqual(check["rows_total_7d"], 3)
        self.assertEqual(
            check["rows_with_confidence_score_nonnull"], 0)
        # No data => every component listed as "always default".
        self.assertEqual(
            sorted(check["components_always_default"]),
            sorted(bcr.EXPECTED_COMPONENTS))
        self.assertEqual(check["components_with_real_data"], [])

    def test_real_variance_in_some_components(self):
        rows = [
            {"confidence_score": 0.72,
             "confidence_components": {
                 "data_quality": 0.9, "signal_strength": 0.8,
                 "regime_alignment": 0.5, "system_health": 0.5,
                 "risk_state": 0.5, "sample_size": 0.5,
                 "track_record": 0.5, "calibration": 0.5}},
            {"confidence_score": 0.62,
             "confidence_components": {
                 "data_quality": 0.8, "signal_strength": 0.6,
                 "regime_alignment": 0.5, "system_health": 0.5,
                 "risk_state": 0.5, "sample_size": 0.5,
                 "track_record": 0.5, "calibration": 0.5}},
        ]
        _seed(self.repo, rows=rows, state=None, as_of=self.as_of)
        check = bcr.build_check(as_of=self.as_of, repo_root=self.repo)
        # data_quality + signal_strength have variance.
        self.assertIn("data_quality", check["components_with_real_data"])
        self.assertIn("signal_strength", check["components_with_real_data"])
        # The five others are constant at 0.5 -> always default.
        for c in ("regime_alignment", "system_health", "risk_state",
                    "sample_size", "track_record", "calibration"):
            self.assertIn(c, check["components_always_default"])

    def test_verdict_distribution_from_scores(self):
        rows = [
            {"confidence_score": 0.30},  # BLOCK
            {"confidence_score": 0.55},  # ALERT_ONLY
            {"confidence_score": 0.70},  # ALLOW
            {"confidence_score": None},  # unknown
        ]
        _seed(self.repo, rows=rows, state=None, as_of=self.as_of)
        check = bcr.build_check(as_of=self.as_of, repo_root=self.repo)
        vd = check["confidence_verdict_distribution"]
        self.assertEqual(vd.get("BLOCK", 0), 1)
        self.assertEqual(vd.get("ALERT_ONLY", 0), 1)
        self.assertEqual(vd.get("ALLOW", 0), 1)
        self.assertEqual(vd.get("unknown", 0), 1)

    def test_low_sample_strategies_from_state(self):
        state = {
            "strategies": {
                "momentum-long": {"trades_lifetime": 0, "enabled": True},
                "crypto-momentum": {"trades_lifetime": 5,
                                     "enabled": True},
                "geo-defense": {"trades_lifetime": 25, "enabled": True},
            }
        }
        _seed(self.repo, rows=[], state=state, as_of=self.as_of)
        check = bcr.build_check(as_of=self.as_of, repo_root=self.repo)
        self.assertEqual(check["low_sample_strategy_count"], 2)
        self.assertIn("momentum-long", check["low_sample_strategies"])
        self.assertIn("crypto-momentum", check["low_sample_strategies"])
        self.assertNotIn("geo-defense", check["low_sample_strategies"])

    def test_calibrated_yet_when_dir_has_files(self):
        # Empty dir -> not calibrated.
        cal_dir = self.repo / "learning-loop" / "shadow_evidence" / \
            "confidence_calibration"
        cal_dir.mkdir(parents=True, exist_ok=True)
        _seed(self.repo, rows=[], state=None, as_of=self.as_of)
        check = bcr.build_check(as_of=self.as_of, repo_root=self.repo)
        self.assertFalse(check["calibrated_yet"])
        # Add a non-empty file -> calibrated.
        (cal_dir / "2026-06-15.json").write_text("{}", encoding="utf-8")
        check2 = bcr.build_check(as_of=self.as_of, repo_root=self.repo)
        self.assertTrue(check2["calibrated_yet"])

    def test_standing_markers_present(self):
        _seed(self.repo, rows=[], state=None, as_of=self.as_of)
        check = bcr.build_check(as_of=self.as_of, repo_root=self.repo)
        for marker in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
            "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
        ):
            self.assertIn(marker, check["standing_markers"])
        md = bcr.render_md(check)
        for marker in bcr.STANDING_MARKERS:
            self.assertIn(marker, md)

    def test_safety_flags_all_false(self):
        _seed(self.repo, rows=[], state=None, as_of=self.as_of)
        check = bcr.build_check(as_of=self.as_of, repo_root=self.repo)
        self.assertFalse(check["safety"]["edge_gate_enabled"])
        self.assertFalse(check["safety"]["allow_broker_paper"])
        self.assertFalse(check["safety"]["live_trading_supported"])


if __name__ == "__main__":
    unittest.main()
