"""v3.28 ETAP 5 (2026-06-16) — tests for docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md.

The runbook is operator-facing text. These tests assert the standing
invariants the runbook itself promises in its footer + body:

* exists on disk,
* points at the paper account URL,
* never recommends live trading,
* contains the "what NOT to do" section,
* contains the standing markers footer,
* references the verifier script.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_RUNBOOK_PATH = _REPO_ROOT / "docs" / "RUNBOOK_AVAXUSD_P13_2026-06-16.md"


class TestRunbookAvaxV3280(unittest.TestCase):
    """The runbook is a contract document; these tests guard its content."""

    @classmethod
    def setUpClass(cls):
        cls.body = _RUNBOOK_PATH.read_text(encoding="utf-8")
        cls.body_lower = cls.body.lower()

    # 1. File must exist.
    def test_01_runbook_file_exists(self):
        self.assertTrue(_RUNBOOK_PATH.exists(),
                        f"Runbook missing at {_RUNBOOK_PATH}")
        self.assertGreater(len(self.body), 5000,
                           "Runbook body unexpectedly short")

    # 2. Paper-account URL must appear (operator must point at /paper/).
    def test_02_paper_account_url_present(self):
        self.assertIn("https://app.alpaca.markets/paper/dashboard/overview",
                      self.body)
        # URL must contain /paper/ — explicit.
        self.assertIn("/paper/", self.body)

    # 3. Runbook MUST NOT recommend live trading anywhere.
    def test_03_never_recommends_live_trading(self):
        # We look for any of the forbidden phrases NOT preceded by a
        # negation marker. The runbook can (and does) mention "enable
        # live trading" in negative form ("does not instruct ... to
        # enable live trading"); the test must not flag those.
        forbidden = [
            "enable live trading",
            "switch to live",
            "switch to live trading",
            "go live",
            "live account is correct",
            "recommend live",
        ]
        # Inspect every occurrence with a 60-character preceding window.
        for phrase in forbidden:
            start = 0
            while True:
                idx = self.body_lower.find(phrase, start)
                if idx == -1:
                    break
                window_start = max(0, idx - 60)
                preceding = self.body_lower[window_start:idx]
                has_negation = any(neg in preceding for neg in (
                    "not ", "never ", "do not", "does not", "must not",
                    "cannot", "without", "forbidden", "**not**",
                ))
                self.assertTrue(
                    has_negation,
                    f"Runbook contains forbidden recommendation {phrase!r} "
                    f"without a negation in the preceding context "
                    f"(window starts {window_start}): "
                    f"...{self.body[window_start:idx + len(phrase)]!r}"
                )
                start = idx + len(phrase)
        # The runbook MUST contain explicit "live trading is unsupported" markers.
        self.assertIn("LIVE_TRADING_UNSUPPORTED", self.body)
        self.assertIn("live trading is unsupported", self.body_lower)

    # 4. Runbook must contain a "what NOT to do" section.
    def test_04_what_not_to_do_section_present(self):
        # Section heading is "## 10. What NOT to do".
        self.assertRegex(self.body, r"##\s*10\.\s*What\s*NOT\s*to\s*do")
        # The section must enumerate the forbidden flags.
        for flag in (
            "LIVE_TRADING",
            "ALLOW_BROKER_PAPER",
            "EDGE_GATE_ENABLED",
            "BROKER_EXECUTION_ENABLED",
        ):
            self.assertIn(flag, self.body,
                          f"Runbook §10 missing forbidden-flag mention: {flag}")

    # 5. Standing markers footer must be present.
    def test_05_standing_markers_footer_present(self):
        for marker in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "NO_AUTO_BROKER_ACTION_FROM_THIS_RUNBOOK",
        ):
            self.assertIn(marker, self.body,
                          f"Runbook footer missing standing marker: {marker}")

    # 6. Verify script must be mentioned with the safe defaults.
    def test_06_mentions_verify_script(self):
        self.assertIn("scripts/verify_manual_broker_repair.py", self.body)
        # The runbook must describe the dry-run default.
        self.assertRegex(self.body, r"--dry-run", )
        self.assertRegex(self.body, r"read-only", )
        # The runbook must NOT describe the verifier as actually clearing
        # safe_mode — it can only propose.
        self.assertIn("SAFE_MODE_CLEAR_PROPOSED_OPERATOR_MUST_APPLY", self.body)


if __name__ == "__main__":
    unittest.main()
