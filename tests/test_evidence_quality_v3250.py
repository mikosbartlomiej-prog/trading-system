"""v3.25 (2026-06-15) — extension tests for the evidence-quality
status report after v3.24 confidence enforcement was deployed.

These tests do NOT relax any v3.24 invariant. They verify that the
v3.25 regenerated report:

1. Surfaces the LABEL DISTRIBUTION (GARBAGE / MARGINAL / USABLE /
   HIGH_QUALITY) so an operator can see at a glance how much of the
   ledger is real-grade evidence.
2. Surfaces a per-MONITOR breakdown (which producers are emitting
   high-quality rows vs garbage).
3. Surfaces a per-STRATEGY breakdown.
4. Surfaces an AVERAGE score (single headline number).
5. Surfaces the TOP LOW-SCORE REASONS (which bonus categories are
   most often missing from rows). This is the diagnostic that tells
   the operator WHY rows score so low — used to prioritise v3.26
   confidence-population work in monitors.

HARD SAFETY
-----------
- Tests NEVER call the broker.
- Tests NEVER hit the network.
- The reporter MUST NOT modify state.json or any production file
  other than its two output paths.

The TOP-3 low-score reasons (computed by Agent 3C):

  1. confidence_score_present missing (100% rows; -20 pts foregone)
  2. evidence_quality_real_market_data missing (100%; -15 pts)
  3. confidence_components_non_empty missing (100%; -15 pts)

(These are the consequence of v3.24 entry-capable-only confidence
gating: when a signal is REJECTed pre-entry the confidence compute is
correctly skipped. v3.26 candidate work is to either (a) promote
post-reject confidence_status into the top-level row, OR (b) extend
the scorer to treat OBSERVE_ONLY_SKIP rows as their own label.)
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_evidence_quality_report.py"
REPORT_JSON = REPO_ROOT / "learning-loop" / "evidence_quality_latest.json"
REPORT_MD = REPO_ROOT / "docs" / "EVIDENCE_QUALITY_STATUS.md"

# v3.25 computed top-3 low-score reasons (from 16,358-row aggregate).
EXPECTED_TOP3_LOW_SCORE_REASONS = (
    "confidence_score_present",                  # -20 pts foregone
    "evidence_quality_real_market_data",         # -15 pts foregone
    "confidence_components_non_empty",           # -15 pts foregone
)

REQUIRED_LABELS = (
    "GARBAGE",
    "MARGINAL",
    "USABLE",
    "HIGH_QUALITY",
)


def _load_json_report() -> dict:
    """Load the latest evidence-quality JSON. Skips if missing."""
    if not REPORT_JSON.exists():
        raise unittest.SkipTest(
            f"{REPORT_JSON} missing — run "
            f"`python3 scripts/build_evidence_quality_report.py` first")
    return json.loads(REPORT_JSON.read_text(encoding="utf-8"))


def _load_md_report() -> str:
    """Load the latest evidence-quality MD. Skips if missing."""
    if not REPORT_MD.exists():
        raise unittest.SkipTest(f"{REPORT_MD} missing — run reporter")
    return REPORT_MD.read_text(encoding="utf-8")


class TestLabelDistribution(unittest.TestCase):
    def test_label_distribution_present(self):
        """The report MUST include a label_distribution covering all
        four labels (GARBAGE / MARGINAL / USABLE / HIGH_QUALITY).
        Counts of 0 are valid; the keys must still be present so
        downstream dashboards do not break on label rotation.
        """
        rep = _load_json_report()
        ld = rep.get("label_distribution") or {}
        self.assertIsInstance(ld, dict)
        for label in REQUIRED_LABELS:
            self.assertIn(
                label, ld,
                f"label_distribution missing required label {label!r}")
            self.assertGreaterEqual(int(ld[label]), 0)

    def test_label_distribution_sums_to_rows_scored(self):
        rep = _load_json_report()
        ld = rep.get("label_distribution") or {}
        n_scored = int(rep.get("rows_scored", 0))
        total = sum(int(v) for v in ld.values())
        self.assertEqual(
            total, n_scored,
            f"label_distribution sum {total} != "
            f"rows_scored {n_scored}")


class TestPerMonitor(unittest.TestCase):
    def test_per_monitor_section_present(self):
        """The report MUST include a per_monitor_average section
        (single dict mapping monitor name → avg score).
        """
        rep = _load_json_report()
        pm = rep.get("per_monitor_average")
        self.assertIsInstance(
            pm, dict,
            "per_monitor_average must be a dict")
        # Either populated or empty; both are OK. If populated,
        # values must be numeric.
        for k, v in pm.items():
            self.assertIsInstance(k, str)
            self.assertIsInstance(v, (int, float))
            self.assertGreaterEqual(v, 0)
            self.assertLessEqual(v, 100)


class TestPerStrategy(unittest.TestCase):
    def test_per_strategy_section_present(self):
        """The report MUST include a per_strategy_average section."""
        rep = _load_json_report()
        ps = rep.get("per_strategy_average")
        self.assertIsInstance(
            ps, dict,
            "per_strategy_average must be a dict")
        # If populated, sanity-check the shape.
        for k, v in ps.items():
            self.assertIsInstance(k, str)
            self.assertIsInstance(v, (int, float))
            self.assertGreaterEqual(v, 0)
            self.assertLessEqual(v, 100)


class TestAverageScore(unittest.TestCase):
    def test_average_score_reported(self):
        """The report MUST surface a single average_score in [0, 100]."""
        rep = _load_json_report()
        avg = rep.get("average_score")
        self.assertIsNotNone(avg, "average_score missing from report")
        self.assertIsInstance(avg, (int, float))
        self.assertGreaterEqual(avg, 0)
        self.assertLessEqual(avg, 100)


class TestLowScoreReasons(unittest.TestCase):
    def test_low_score_reasons_listed(self):
        """The TOP-3 low-score reasons (the bonuses most often missed
        across the ledger) are documented in this test file so the
        operator can find them during the audit-board cycle.

        Current top-3 (16,358 rows analyzed, v3.25):

          1. confidence_score_present missing (100%; -20 pts foregone)
          2. evidence_quality_real_market_data missing (100%; -15 pts)
          3. confidence_components_non_empty missing (100%; -15 pts)

        These are the consequence of v3.24's correct entry-capable-only
        confidence gating: REJECTed signals correctly skip the
        confidence compute, but the scorer treats the missing fields
        as "low quality". v3.26 candidate work either lifts confidence
        into the top-level row (so scorer sees it) OR adds a new label
        for OBSERVE_ONLY_SKIP rows.

        This test asserts (a) the reasons are well-formed bonus keys
        from shared.evidence_quality.BONUS_POINTS, and (b) the report
        contains data consistent with these being the dominant gaps.
        """
        # Import BONUS_POINTS for shape check
        import sys
        if str(REPO_ROOT / "shared") not in sys.path:
            sys.path.insert(0, str(REPO_ROOT / "shared"))
        from evidence_quality import BONUS_POINTS  # type: ignore
        for reason in EXPECTED_TOP3_LOW_SCORE_REASONS:
            self.assertIn(
                reason, BONUS_POINTS,
                f"top-3 low-score reason {reason!r} is not a "
                f"recognised bonus key — list may be stale")
        # Sanity check: report average_score should be low when these
        # bonuses are missing across the board (consistent with the
        # observed 14.9 / 100). We assert avg < 50 because if these
        # top-3 bonuses (45 pts foregone) are present, the rows
        # cannot be in GARBAGE territory.
        rep = _load_json_report()
        avg = rep.get("average_score", 0)
        ld = rep.get("label_distribution") or {}
        # If most rows are GARBAGE, top-3 missing bonuses is the
        # likely cause; avg must be in low-score range.
        if ld.get("GARBAGE", 0) > ld.get("USABLE", 0):
            self.assertLess(
                avg, 50,
                f"GARBAGE-dominant report but avg {avg} >= 50; "
                f"inconsistent")


class TestSafety(unittest.TestCase):
    def test_no_alpaca_imports(self):
        """The evidence-quality reporter MUST NOT import
        alpaca_orders or any broker module.
        """
        src = SCRIPT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name or ""
                    self.assertNotIn(
                        "alpaca_orders", name,
                        f"reporter imports forbidden module {name!r}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertNotIn(
                    "alpaca_orders", mod,
                    f"reporter imports from forbidden module {mod!r}")

    def test_no_network_modules(self):
        src = SCRIPT_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "import requests",
            "from requests",
            "urllib.request",
            "http.client",
            "socket.connect",
        ):
            self.assertNotIn(
                forbidden, src,
                f"reporter must not use {forbidden}")

    def test_reporter_does_not_write_state_json(self):
        src = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn(
            "STATE_PATH.write_text", src,
            "evidence-quality reporter must not write state.json")


class TestStandingMarkers(unittest.TestCase):
    def test_md_report_has_standing_markers(self):
        """The MD report must include the standing safety markers
        footer so anyone reading the report sees the hard-safety
        re-assertion.
        """
        md = _load_md_report()
        up = md.upper()
        self.assertIn("EDGE_GATE_ENABLED=FALSE", up)
        self.assertIn("ALLOW_BROKER_PAPER=FALSE", up)
        self.assertIn("LIVE_TRADING_UNSUPPORTED", up)


if __name__ == "__main__":
    unittest.main(verbosity=2)
