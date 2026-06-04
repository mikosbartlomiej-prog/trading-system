"""v3.19.0 (2026-06-04) — Tests for shared/confidence_calibration.py
(ETAP 4 — Confidence Calibration).

Covers:
  - bucket_for boundary values
  - compute_calibration_metrics returns empty stats for unknown buckets
  - Perfect monotonic ledger → is_calibrated=True
  - High-bucket WR < mid-bucket WR → is_calibrated=False
  - Overstatement detection (high conf has low WR)
  - Underuse detection (low conf has high WR)
  - calibration_drift = 0 for identical data
  - calibration_drift > 0 for diverging data
  - generate_calibration_report writes valid Markdown + JSON
  - Bucket with n < 10 is excluded from monotonicity check
  - Fail-soft on malformed inputs
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


class _BaseTest(unittest.TestCase):
    def setUp(self):
        for k in list(sys.modules):
            if k == "confidence_calibration" \
               or k.endswith(".confidence_calibration"):
                del sys.modules[k]
        import confidence_calibration as cc
        self.cc = cc


# ─── bucket_for ──────────────────────────────────────────────────────────────


class TestBucketFor(_BaseTest):

    def test_boundary_values(self):
        self.assertEqual(self.cc.bucket_for(0.00), "very_low")
        self.assertEqual(self.cc.bucket_for(0.39), "very_low")
        self.assertEqual(self.cc.bucket_for(0.40), "low")
        self.assertEqual(self.cc.bucket_for(0.499), "low")
        self.assertEqual(self.cc.bucket_for(0.50), "mid")
        self.assertEqual(self.cc.bucket_for(0.649), "mid")
        self.assertEqual(self.cc.bucket_for(0.65), "high")
        self.assertEqual(self.cc.bucket_for(0.749), "high")
        self.assertEqual(self.cc.bucket_for(0.75), "very_high")
        self.assertEqual(self.cc.bucket_for(0.849), "very_high")
        self.assertEqual(self.cc.bucket_for(0.85), "extreme")
        self.assertEqual(self.cc.bucket_for(1.00), "extreme")

    def test_invalid_inputs_default_very_low(self):
        self.assertEqual(self.cc.bucket_for(None), "very_low")
        self.assertEqual(self.cc.bucket_for("nope"), "very_low")
        self.assertEqual(self.cc.bucket_for(-0.5), "very_low")
        self.assertEqual(self.cc.bucket_for(float("nan")), "very_low")


# ─── compute_calibration_metrics ─────────────────────────────────────────────


def _trade(conf: float, pnl: float, *, entry: float = 100.0,
           qty: float = 1.0) -> dict:
    return {
        "confidence_at_entry": conf,
        "net_pnl":             pnl,
        "entry":               entry,
        "qty":                 qty,
    }


class TestComputeCalibrationMetrics(_BaseTest):

    def test_empty_returns_zero_stats(self):
        out = self.cc.compute_calibration_metrics([])
        self.assertEqual(out["n_total"], 0)
        for name in [b[2] for b in self.cc.CONFIDENCE_BUCKETS]:
            self.assertEqual(out["buckets"][name]["n"], 0)
            self.assertTrue(out["buckets"][name]["sparse"])

    def test_perfectly_monotonic_ledger(self):
        recs: list[dict] = []
        # very_low: WR ~ 10% (1 win, 9 losses) × 10 trades
        recs += [_trade(0.10, +1.0)] + [_trade(0.20, -1.0)] * 9
        # low: WR ~ 30% (3 wins, 7 losses)
        recs += [_trade(0.42, +1.0)] * 3 + [_trade(0.45, -1.0)] * 7
        # mid: WR ~ 50%
        recs += [_trade(0.55, +1.0)] * 5 + [_trade(0.55, -1.0)] * 5
        # high: WR ~ 70%
        recs += [_trade(0.70, +1.0)] * 7 + [_trade(0.70, -1.0)] * 3
        # very_high: WR ~ 85%
        recs += [_trade(0.80, +1.0)] * 17 + [_trade(0.80, -1.0)] * 3
        # extreme: WR ~ 90%
        recs += [_trade(0.90, +1.0)] * 18 + [_trade(0.90, -1.0)] * 2

        cal = self.cc.compute_calibration_metrics(recs)
        ok, why = self.cc.is_calibrated(cal, min_n_per_bucket=10)
        self.assertTrue(ok, f"expected calibrated, got: {why}")

    def test_high_bucket_wr_below_mid_wr_uncalibrated(self):
        recs: list[dict] = []
        # mid (n=10, WR 70%)
        recs += [_trade(0.55, +1.0)] * 7 + [_trade(0.55, -1.0)] * 3
        # high (n=10, WR 30%)  ← lower than mid → uncalibrated
        recs += [_trade(0.70, +1.0)] * 3 + [_trade(0.70, -1.0)] * 7
        cal = self.cc.compute_calibration_metrics(recs)
        ok, why = self.cc.is_calibrated(cal, min_n_per_bucket=10)
        self.assertFalse(ok)
        self.assertIn("high", why)

    def test_n_below_min_excluded_from_monotonicity(self):
        # Two buckets with n=10 each (calibrated), plus one tiny bucket
        # with n=3 that *looks bad* — must be ignored.
        recs: list[dict] = []
        recs += [_trade(0.55, +1.0)] * 6 + [_trade(0.55, -1.0)] * 4  # mid WR60%
        recs += [_trade(0.70, +1.0)] * 8 + [_trade(0.70, -1.0)] * 2  # high WR80%
        # extreme has 3 losers — too small to count
        recs += [_trade(0.90, -1.0)] * 3
        cal = self.cc.compute_calibration_metrics(recs)
        ok, _ = self.cc.is_calibrated(cal, min_n_per_bucket=10)
        self.assertTrue(ok)


# ─── detect_overstatement / detect_underuse ──────────────────────────────────


class TestDetectors(_BaseTest):

    def test_overstatement_when_high_has_low_wr(self):
        recs: list[dict] = []
        recs += [_trade(0.70, +1.0)] * 2 + [_trade(0.70, -1.0)] * 8  # high WR20%
        cal = self.cc.compute_calibration_metrics(recs)
        over = self.cc.detect_overstatement(cal)
        self.assertIn("high", over)

    def test_overstatement_when_lower_beats_higher(self):
        recs: list[dict] = []
        recs += [_trade(0.55, +1.0)] * 9 + [_trade(0.55, -1.0)]      # mid WR90%
        recs += [_trade(0.80, +1.0)] * 6 + [_trade(0.80, -1.0)] * 4  # very_high 60%
        cal = self.cc.compute_calibration_metrics(recs)
        over = self.cc.detect_overstatement(cal)
        self.assertIn("very_high", over)

    def test_underuse_when_low_bucket_wins(self):
        recs: list[dict] = []
        recs += [_trade(0.30, +1.0)] * 8 + [_trade(0.30, -1.0)] * 2  # very_low WR80%
        cal = self.cc.compute_calibration_metrics(recs)
        under = self.cc.detect_underuse(cal)
        self.assertIn("very_low", under)

    def test_no_overstatement_when_all_good(self):
        recs: list[dict] = []
        recs += [_trade(0.70, +1.0)] * 8 + [_trade(0.70, -1.0)] * 2
        cal = self.cc.compute_calibration_metrics(recs)
        self.assertEqual(self.cc.detect_overstatement(cal), [])


# ─── calibration_drift ───────────────────────────────────────────────────────


class TestCalibrationDrift(_BaseTest):

    def test_drift_zero_for_identical_data(self):
        recs = ([_trade(0.55, +1.0)] * 6 + [_trade(0.55, -1.0)] * 4 +
                [_trade(0.80, +1.0)] * 8 + [_trade(0.80, -1.0)] * 2)
        a = self.cc.compute_calibration_metrics(recs)
        b = self.cc.compute_calibration_metrics(recs)
        self.assertEqual(self.cc.calibration_drift(a, b), 0.0)

    def test_drift_positive_when_wr_changes(self):
        recs_a = [_trade(0.70, +1.0)] * 8 + [_trade(0.70, -1.0)] * 2
        recs_b = [_trade(0.70, +1.0)] * 2 + [_trade(0.70, -1.0)] * 8
        a = self.cc.compute_calibration_metrics(recs_a)
        b = self.cc.compute_calibration_metrics(recs_b)
        self.assertGreater(self.cc.calibration_drift(a, b), 0.0)

    def test_drift_safe_on_none(self):
        self.assertEqual(self.cc.calibration_drift(None, None), 0.0)
        self.assertEqual(self.cc.calibration_drift({}, {}), 0.0)


# ─── generate_calibration_report ─────────────────────────────────────────────


class TestGenerateCalibrationReport(_BaseTest):

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="calib_v3190_")
        # Set up a tiny PAPER ledger for the loader to read.
        self._paper_dir = os.path.join(self._tmp, "paper")
        os.makedirs(self._paper_dir, exist_ok=True)
        from datetime import datetime, timezone
        iso = datetime.now(timezone.utc).date().isoformat()
        recs = ([_trade(0.55, +1.0)] * 6 + [_trade(0.55, -1.0)] * 4 +
                [_trade(0.80, +1.0)] * 8 + [_trade(0.80, -1.0)] * 2)
        with open(os.path.join(self._paper_dir, f"{iso}.jsonl"), "w",
                   encoding="utf-8") as f:
            for r in recs:
                rec = {
                    "paper_only":         True,
                    "source":             "PAPER",
                    "strategy":           "synthetic",
                    "symbol":             "X",
                    "side":               "long",
                    "entry":              100.0,
                    "exit":               101.0,
                    "qty":                1.0,
                    "confidence_at_entry": r["confidence_at_entry"],
                    "net_pnl":            r["net_pnl"],
                    "closed_at":          (
                        datetime.now(timezone.utc).isoformat()
                    ),
                }
                f.write(json.dumps(rec, sort_keys=True) + "\n")
        os.environ["PAPER_EXPERIMENT_DIR"] = self._paper_dir
        # Force re-import after env set
        for k in list(sys.modules):
            if k in ("paper_experiment", "shared.paper_experiment",
                      "confidence_calibration",
                      "shared.confidence_calibration"):
                del sys.modules[k]
        import confidence_calibration as cc2
        self.cc = cc2
        os.environ["AUDIT_TRADING_DIR"] = os.path.join(self._tmp, "audit")

    def tearDown(self):
        os.environ.pop("PAPER_EXPERIMENT_DIR", None)
        os.environ.pop("AUDIT_TRADING_DIR", None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_generate_writes_markdown_and_json(self):
        md_path = os.path.join(self._tmp, "report.md")
        js_path = os.path.join(self._tmp, "report.json")
        out_md, out_js = self.cc.generate_calibration_report(
            out_md_path=md_path, out_json_path=js_path,
            window_days=30, min_n_per_bucket=10,
        )
        self.assertTrue(os.path.exists(out_md))
        self.assertTrue(os.path.exists(out_js))
        body = Path(out_md).read_text(encoding="utf-8")
        self.assertIn("Confidence Calibration Report", body)
        self.assertIn("Bucket", body)
        payload = json.loads(Path(out_js).read_text(encoding="utf-8"))
        self.assertIn("calibration", payload)
        self.assertIn("calibrated", payload)
        # Audit JSONL was written
        audit_files = list(Path(os.environ["AUDIT_TRADING_DIR"])
                            .glob("*.jsonl"))
        self.assertTrue(len(audit_files) >= 1)
        line = audit_files[0].read_text().strip().splitlines()[-1]
        evt = json.loads(line)
        self.assertEqual(evt["kind"], "confidence_calibration")
        self.assertIn("calibrated", evt)


# ─── Fail-soft on malformed inputs ───────────────────────────────────────────


class TestFailSoft(_BaseTest):

    def test_records_missing_confidence_are_dropped(self):
        recs = [
            {"net_pnl": +1.0},                             # no confidence
            {"confidence_at_entry": 0.6, "net_pnl": +1.0},
        ]
        cal = self.cc.compute_calibration_metrics(recs)
        self.assertEqual(cal["n_total"], 1)

    def test_is_calibrated_on_non_dict(self):
        ok, why = self.cc.is_calibrated(None)
        self.assertFalse(ok)
        ok, why = self.cc.is_calibrated([])
        self.assertFalse(ok)

    def test_detect_overstatement_on_garbage(self):
        self.assertEqual(self.cc.detect_overstatement(None), [])
        self.assertEqual(self.cc.detect_overstatement({}), [])

    def test_detect_underuse_on_garbage(self):
        self.assertEqual(self.cc.detect_underuse(None), [])
        self.assertEqual(self.cc.detect_underuse({}), [])


if __name__ == "__main__":
    unittest.main()
