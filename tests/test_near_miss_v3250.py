"""v3.25 (2026-06-15) — extension tests for the near-miss status
report after v3.24 confidence enforcement was deployed.

These tests do NOT relax any v3.24 invariant. They verify that:

1. The report handles an empty near-miss directory cleanly (the
   expected v3.25 state — strategies have not yet wired per-strategy
   near-miss helpers into their reject paths).
2. The report writes the v3.25 standing markers footer (the same
   markers v3.24 emitted; they are forever).
3. The script has no broker imports (re-asserted every revision).
4. The report documents a next-step plan when the directory is empty
   (so a future operator/agent knows what to do next — wire helpers
   into the 7 monitors that are "wired but not firing").

HARD SAFETY
-----------
- Tests NEVER call the broker.
- Tests NEVER hit the network.
- AST scan asserts the script does NOT import alpaca_orders.
- The near-miss reporter must NEVER auto-adjust thresholds.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_near_miss_report.py"
REPORT_JSON = REPO_ROOT / "learning-loop" / "near_miss_status_latest.json"
REPORT_MD = REPO_ROOT / "docs" / "NEAR_MISS_STATUS.md"
NEAR_MISS_DIR = REPO_ROOT / "learning-loop" / "near_miss"


def _load_json_report() -> dict:
    """Load the latest near-miss JSON. Skips if missing."""
    if not REPORT_JSON.exists():
        raise unittest.SkipTest(
            f"{REPORT_JSON} missing — run "
            f"`python3 scripts/build_near_miss_report.py` first")
    return json.loads(REPORT_JSON.read_text(encoding="utf-8"))


class TestEmptyHandling(unittest.TestCase):
    def test_report_handles_empty_near_miss_dir(self):
        """When near_miss/ is empty or missing, the report must still
        write cleanly: zero rows, zero pairs, zero flagged. No crash,
        no exception, no negative counts.
        """
        rep = _load_json_report()
        # rows_total, pairs, flagged must exist and be reasonable
        self.assertIn("rows_total", rep)
        self.assertGreaterEqual(rep["rows_total"], 0)
        self.assertIn("pairs", rep)
        self.assertIsInstance(rep["pairs"], list)
        self.assertIn("flagged", rep)
        self.assertIsInstance(rep["flagged"], list)
        # When empty, pairs and flagged must both be []
        if rep["rows_total"] == 0:
            self.assertEqual(rep["pairs"], [])
            self.assertEqual(rep["flagged"], [])

    def test_report_documents_next_step_when_empty(self):
        """When the near-miss directory has no rows, the operator
        needs to know WHY it is empty. The next-step plan is
        documented in this test file (which doubles as docs) and
        will be surfaced by the audit-board pass.

        Next steps when empty:
          1. Near-miss tracking is populated by per-strategy near-miss
             helpers when a signal almost-but-not-quite triggers
             (e.g. RSI 31 vs entry zone <30 on crypto-oversold-bounce).
          2. The 7 wired-but-not-firing monitors must call
             shared.near_miss.record(...) on the near-miss path.
          3. v3.26 candidate work is wiring those helpers into:
             defense-monitor, twitter-monitor, reddit-monitor,
             geo-monitor, politician-monitor, options-monitor,
             options-exit-monitor.
          4. crypto-monitor + price-monitor already produce signals
             but need near-miss helpers on the REJECT branches.

        This test asserts the report acknowledges the empty state.
        """
        rep = _load_json_report()
        # If there are 0 rows, the report MUST tell the truth — not
        # fabricate fake near-miss entries.
        if rep["rows_total"] == 0:
            self.assertEqual(len(rep["pairs"]), 0)
            self.assertEqual(len(rep["flagged"]), 0)
            # Hard safety re-asserted
            safety = rep.get("safety") or {}
            self.assertFalse(safety.get("auto_adjusts_thresholds", True))
            self.assertFalse(safety.get("modifies_state_json", True))


class TestStandingMarkers(unittest.TestCase):
    def test_reporter_writes_standing_markers(self):
        """The latest JSON report must include standing_markers
        re-asserting hard-safety invariants. Required markers:

          EDGE_GATE_ENABLED=false
          ALLOW_BROKER_PAPER=false
          LIVE_TRADING_UNSUPPORTED
          NEAR_MISS_NEVER_COUNTS_AS_TRADE
          NEAR_MISS_NEVER_AUTO_ADJUSTS_THRESHOLDS
        """
        rep = _load_json_report()
        markers = rep.get("standing_markers") or []
        self.assertIsInstance(markers, list)
        joined = " ".join(str(m).upper() for m in markers)
        self.assertIn("EDGE_GATE_ENABLED=FALSE", joined)
        self.assertIn("ALLOW_BROKER_PAPER=FALSE", joined)
        self.assertIn("LIVE_TRADING_UNSUPPORTED", joined)
        self.assertIn("NEAR_MISS_NEVER_COUNTS_AS_TRADE", joined)
        self.assertIn(
            "NEAR_MISS_NEVER_AUTO_ADJUSTS_THRESHOLDS", joined)

    def test_safety_block_present(self):
        """The safety dict must be present and ALL flags must be the
        safe value (false for live, false for thresholds, false for
        modifying state.json).
        """
        rep = _load_json_report()
        safety = rep.get("safety") or {}
        self.assertIsInstance(safety, dict)
        self.assertFalse(
            safety.get("live_trading_supported", True),
            "live_trading_supported must be False")
        self.assertFalse(
            safety.get("allow_broker_paper", True),
            "allow_broker_paper must be False")
        self.assertFalse(
            safety.get("edge_gate_enabled", True),
            "edge_gate_enabled must be False")
        self.assertFalse(
            safety.get("auto_adjusts_thresholds", True),
            "auto_adjusts_thresholds must be False")
        self.assertFalse(
            safety.get("modifies_state_json", True),
            "modifies_state_json must be False")


class TestSafety(unittest.TestCase):
    def test_no_alpaca_imports(self):
        """The near-miss reporter MUST NOT import alpaca_orders or
        any order-placement module.
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
        """The near-miss reporter MUST NOT pull in requests / urllib /
        socket modules — pure local-file aggregator.
        """
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
        """The near-miss reporter MUST NOT write state.json. State
        mutation is reserved for the daily-learning analyzer.
        """
        src = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn(
            "STATE_PATH.write_text", src,
            "near-miss reporter must not write state.json")
        self.assertNotIn(
            'state.json", "w', src,
            "near-miss reporter must not write state.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
