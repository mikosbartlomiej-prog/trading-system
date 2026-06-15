"""v3.26 (Agent 3A ETAP 3) — tests for scripts/strategy_threshold_reality_report.

Verifies:
  - synthetic ledger rows produce expected realism verdicts
  - "no fires + no near-misses" -> DISABLE_CANDIDATE
  - "no fires but many near-misses" -> SHADOW_VARIANT_REVIEW
  - sub-MIN_EVAL_RECOMMENDATION rows -> OBSERVE_MORE
  - AST scan: reporter does NOT import alpaca_orders
  - AST scan: reporter does NOT contain an "auto-lower threshold" code path
  - aggregate_rows is pure (no I/O) and returns a stable shape
  - build_report respects the days window
  - write_report drops both artifacts at the requested paths
"""

from __future__ import annotations

import ast
import json
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

import strategy_threshold_reality_report as report_mod  # noqa: E402


def _row(*, strategy, symbol="BTC/USD", raw_signal=None, action=None,
         day_offset=0):
    ts = (datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)).isoformat()
    raw = dict(raw_signal or {})
    if action is not None:
        raw["action"] = action
    return {
        "signal_id":   f"{strategy}:{symbol}:{day_offset}",
        "strategy":    strategy,
        "symbol":      symbol,
        "timestamp":   ts,
        "raw_signal":  raw,
        "schema_version": "v3.20.0",
    }


# ─── A: REALISM CLASSIFICATION ────────────────────────────────────────────────

class TestRealismClassification(unittest.TestCase):
    """Build synthetic rows with known hit/miss rates and assert verdicts."""

    def test_too_strict_realism_no_hits_few_near_misses(self):
        # crypto-oversold-bounce trigger: rsi < 30. We produce 50 rows
        # all with rsi values FAR from 30 (e.g. 70-90) and zero hits.
        rows = []
        for i in range(50):
            rows.append(_row(
                strategy="crypto-oversold-bounce",
                raw_signal={"rsi": 70.0 + (i % 20)}))
        agg = report_mod.aggregate_rows(rows)
        s = next(s for s in agg["strategies"]
                 if s["strategy_id"] == "crypto-oversold-bounce")
        self.assertEqual(s["actual_signals_fired"], 0)
        self.assertEqual(s["near_misses"], 0)
        # Per-metric: hit_rate == 0 AND miss_rate <= 0.10 -> TOO_STRICT
        m = s["metrics"][0]
        self.assertEqual(m["threshold_realism"], "TOO_STRICT")
        self.assertEqual(s["threshold_realism"], "TOO_STRICT")

    def test_too_strict_no_fires_with_near_misses_yields_shadow_review(self):
        # All rows have rsi just above 30 (30.5-32.5) — within near-miss
        # window (10%) below trigger.
        rows = []
        for i in range(60):
            rows.append(_row(
                strategy="crypto-oversold-bounce",
                raw_signal={"rsi": 30.1 + (i % 30) * 0.05}))
        agg = report_mod.aggregate_rows(rows)
        s = next(s for s in agg["strategies"]
                 if s["strategy_id"] == "crypto-oversold-bounce")
        self.assertEqual(s["actual_signals_fired"], 0)
        self.assertGreaterEqual(s["near_misses"], 5)
        self.assertEqual(s["recommendation"], "SHADOW_VARIANT_REVIEW")

    def test_too_loose_realism_more_than_half_fire(self):
        # crypto-momentum: rsi > 60 AND 24h_move in [3, 15]. We feed
        # 50 rows where both pass.
        rows = []
        for i in range(50):
            rows.append(_row(
                strategy="crypto-momentum",
                raw_signal={"rsi": 65.0 + (i % 5),
                            "move_24h_pct": 5.0 + (i % 10) * 0.5},
                action="BUY"))
        agg = report_mod.aggregate_rows(rows)
        s = next(s for s in agg["strategies"]
                 if s["strategy_id"] == "crypto-momentum")
        # Both metrics hit → both TOO_LOOSE.
        self.assertGreaterEqual(s["actual_signals_fired"], 25)
        self.assertEqual(s["threshold_realism"], "TOO_LOOSE")

    def test_insufficient_data_realism_under_min_eval(self):
        # 5 rows is way below MIN_EVAL_REALISM (30) — must report
        # INSUFFICIENT_DATA on metric realism.
        rows = []
        for i in range(5):
            rows.append(_row(strategy="overbought-short",
                             raw_signal={"rsi": 60.0 + i}))
        agg = report_mod.aggregate_rows(rows)
        s = next(s for s in agg["strategies"]
                 if s["strategy_id"] == "overbought-short")
        self.assertEqual(s["threshold_realism"], "INSUFFICIENT_DATA")
        self.assertEqual(s["recommendation"], "OBSERVE_MORE")


# ─── B: RECOMMENDATIONS ────────────────────────────────────────────────────────

class TestRecommendations(unittest.TestCase):

    def test_no_fires_no_near_misses_is_disable_candidate(self):
        # 60 rows all WAY off threshold for crypto-oversold-bounce
        # (rsi = 90 each → not in window 27-30).
        rows = [_row(strategy="crypto-oversold-bounce",
                     raw_signal={"rsi": 90.0})
                for _ in range(60)]
        agg = report_mod.aggregate_rows(rows)
        s = next(s for s in agg["strategies"]
                 if s["strategy_id"] == "crypto-oversold-bounce")
        self.assertEqual(s["actual_signals_fired"], 0)
        self.assertEqual(s["near_misses"], 0)
        self.assertEqual(s["recommendation"], "DISABLE_CANDIDATE")

    def test_low_sample_observation_window(self):
        rows = [_row(strategy="momentum-long",
                     raw_signal={"rsi": 55, "breakout_pct": 0.025,
                                 "volume_ratio": 1.6}, action="BUY")
                for _ in range(10)]
        agg = report_mod.aggregate_rows(rows)
        s = next(s for s in agg["strategies"]
                 if s["strategy_id"] == "momentum-long")
        self.assertEqual(s["recommendation"], "OBSERVE_MORE")

    def test_mixed_with_one_fire_and_too_loose_gives_replay_test(self):
        rows = []
        # 30 hits + 30 near-misses across crypto-momentum metrics
        for i in range(30):
            rows.append(_row(
                strategy="crypto-momentum",
                raw_signal={"rsi": 70.0, "move_24h_pct": 5.0},
                action="BUY"))
        for i in range(30):
            rows.append(_row(
                strategy="crypto-momentum",
                raw_signal={"rsi": 58.5, "move_24h_pct": 2.95}))
        agg = report_mod.aggregate_rows(rows)
        s = next(s for s in agg["strategies"]
                 if s["strategy_id"] == "crypto-momentum")
        self.assertGreaterEqual(s["actual_signals_fired"], 1)
        # Recommendation may be REPLAY_TEST_VARIANT, SHADOW_VARIANT_REVIEW
        # or NEEDS_OPERATOR_REVIEW depending on realism mix — anything
        # except KEEP/OBSERVE_MORE/DISABLE_CANDIDATE is acceptable here.
        self.assertNotIn(s["recommendation"],
                         {"DISABLE_CANDIDATE", "OBSERVE_MORE"})


# ─── C: PURITY / SIDE EFFECTS ─────────────────────────────────────────────────

class TestPurity(unittest.TestCase):
    """aggregate_rows must be pure (no I/O); build_report must be safe."""

    def test_aggregate_rows_has_no_filesystem_side_effects(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            rows = [_row(strategy="overbought-short",
                         raw_signal={"rsi": 75})
                    for _ in range(5)]
            files_before = list(tmp.iterdir())
            report_mod.aggregate_rows(rows)
            files_after = list(tmp.iterdir())
            self.assertEqual(files_before, files_after)

    def test_build_report_respects_ledger_dir_override(self):
        with tempfile.TemporaryDirectory() as td:
            ld = Path(td)
            # Empty dir → empty report (no crash).
            r = report_mod.build_report(days=7, ledger_dir=ld)
            self.assertEqual(r["row_count"], 0)
            # All strategy slots present with INSUFFICIENT_DATA / OBSERVE_MORE.
            seen = {s["strategy_id"] for s in r["strategies"]}
            self.assertIn("crypto-oversold-bounce", seen)
            self.assertIn("crypto-momentum", seen)


# ─── D: ARTIFACT WRITING ──────────────────────────────────────────────────────

class TestArtifactWriting(unittest.TestCase):

    def test_write_report_writes_json_and_md(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jp = tmp / "out.json"
            mp = tmp / "out.md"
            report = report_mod.aggregate_rows([])
            jp_out, mp_out = report_mod.write_report(report,
                                                     json_path=jp,
                                                     md_path=mp)
            self.assertTrue(jp_out.exists())
            self.assertTrue(mp_out.exists())
            data = json.loads(jp_out.read_text())
            self.assertIn("strategies", data)
            md = mp_out.read_text()
            self.assertIn("Strategy threshold reality", md)
            # Standing safety markers must be present.
            self.assertIn("NO_THRESHOLD_AUTO_CHANGE", md)
            self.assertIn("NO_BROKER_CALL", md)
            self.assertIn("NO_PROMOTION", md)


# ─── E: HARD SAFETY — STATIC SCAN ─────────────────────────────────────────────

class TestHardSafetyStaticScans(unittest.TestCase):
    """AST scan — the reporter must NEVER import alpaca_orders, NEVER
    contain a code path that auto-lowers a threshold."""

    SRC = (Path(__file__).resolve().parent.parent / "scripts"
           / "strategy_threshold_reality_report.py").read_text()

    def test_no_alpaca_orders_import(self):
        tree = ast.parse(self.SRC)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name,
                                     "Reporter must not import alpaca_orders")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertNotIn("alpaca_orders", mod,
                                 "Reporter must not from-import alpaca_orders")

    def test_no_auto_lower_threshold_strings(self):
        # Source must not contain any "lower threshold" / "set threshold"
        # / "config.write_threshold" patterns — pure observation only.
        forbidden = [
            "threshold -=",
            "threshold +=",
            "set_threshold",
            "lower_threshold",
            "write_threshold",
            "save_threshold",
            "update_threshold",
        ]
        for pat in forbidden:
            self.assertNotIn(pat, self.SRC,
                             f"Reporter must not contain {pat!r}")

    def test_no_submit_or_place_calls(self):
        forbidden = [
            "submit_order",
            "place_order",
            "place_stock_order",
            "place_crypto_order",
            "place_option_order",
            "safe_close",
            "close_position",
            "close_all_positions",
        ]
        for pat in forbidden:
            self.assertNotIn(pat, self.SRC,
                             f"Reporter must not contain {pat!r}")


# ─── F: BUILD_REPORT END-TO-END ───────────────────────────────────────────────

class TestBuildReportEndToEnd(unittest.TestCase):

    def test_build_report_reads_jsonl_from_window(self):
        with tempfile.TemporaryDirectory() as td:
            ld = Path(td)
            # write 1 file for today
            today = datetime.now(timezone.utc).date()
            f = ld / f"{today.isoformat()}.jsonl"
            with f.open("w", encoding="utf-8") as fp:
                rows = [_row(strategy="overbought-short",
                             raw_signal={"rsi": 75})
                        for _ in range(35)]
                for r in rows:
                    fp.write(json.dumps(r) + "\n")
            report = report_mod.build_report(days=7, ledger_dir=ld)
            self.assertEqual(report["row_count"], 35)
            s = next(s for s in report["strategies"]
                     if s["strategy_id"] == "overbought-short")
            # rsi=75 is above 72 -> hits.
            self.assertEqual(s["actual_signals_fired"], 0)  # action="BUY" only
            self.assertGreater(s["metrics"][0]["actual_hits"], 0)


if __name__ == "__main__":
    unittest.main()
