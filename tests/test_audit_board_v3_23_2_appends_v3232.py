"""v3.23.2 (2026-06-08) — Audit board prompt appends.

Confirms that the Multi-Agent Audit Board shared-context prompt
(`agents/prompts/00_shared_context.md`) has been extended with the
v3.23.2 coverage section and Final Arbiter escalation triggers.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_CONTEXT = REPO_ROOT / "agents" / "prompts" / "00_shared_context.md"


class TestSharedContextV3232Section(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SHARED_CONTEXT.read_text(encoding="utf-8")

    def test_file_exists(self):
        self.assertTrue(SHARED_CONTEXT.exists())

    def test_v3232_coverage_section_present(self):
        self.assertIn("## v3.23.2 coverage (added 2026-06-08)", self.text)

    def test_references_new_modules(self):
        for marker in (
            "shared/audit_bypass_detector.py",
            "shared/amd_close_source_search.py",
            "manual_order_history_remaining_2026-06-04.json",
            "OPERATOR_ORDER_HISTORY_EXTRACTION_CHECKLIST.md",
            "compute_partial_attribution",
        ):
            self.assertIn(marker, self.text,
                            f"expected reference: {marker}")

    def test_lists_4_new_drawdown_attribution_statuses(self):
        for s in (
            "DRAWDOWN_ATTRIBUTION_COMPLETE",
            "DRAWDOWN_ATTRIBUTION_PARTIAL",
            "DRAWDOWN_ATTRIBUTION_REQUIRES_ORDER_HISTORY",
            "DRAWDOWN_ATTRIBUTION_CONFLICT",
        ):
            self.assertIn(s, self.text)

    def test_lists_6_audit_bypass_classifications(self):
        for c in (
            "SAFE_CLOSE_WRAPPED",
            "AUDIT_EQUIVALENT_WRAPPED",
            "READ_ONLY",
            "ORDER_SUBMITTER_BYPASS",
            "LEGACY_DANGEROUS",
            "UNKNOWN_REQUIRES_REVIEW",
        ):
            self.assertIn(c, self.text)

    def test_lists_3_audit_bypass_invariants(self):
        for inv in (
            "NO_DIRECT_MARKET_SELL_WITHOUT_AUDIT",
            "NO_SELL_TO_CLOSE_WITHOUT_SAFE_CLOSE_OR_EQUIVALENT_AUDIT",
            "ACCESS_KEY_ORDER_PATH_MUST_EMIT_AUDIT",
        ):
            self.assertIn(inv, self.text)

    def test_lists_amd_close_source_classifications(self):
        for c in (
            "AMD_CLOSE_SOURCE_IDENTIFIED",
            "AMD_CLOSE_SOURCE_NOT_FOUND_LOCAL_LOGS_REQUIRE_GH_ACTIONS_OR_API_HISTORY",
        ):
            self.assertIn(c, self.text)

    def test_arbiter_v3232_escalation_section_present(self):
        self.assertIn(
            "### Final Arbiter v3.23.2 escalation triggers (P0)",
            self.text,
        )


class TestArbiterEscalationTriggersV3232(unittest.TestCase):
    """The Final Arbiter must escalate (block + NEEDS_FIXES) on at
    least 8 v3.23.2-specific conditions in addition to all v3.23 ones."""

    @classmethod
    def setUpClass(cls):
        text = SHARED_CONTEXT.read_text(encoding="utf-8")
        # Slice from the v3.23.2 escalation section start.
        marker = "### Final Arbiter v3.23.2 escalation triggers (P0)"
        if marker in text:
            cls.section = text.split(marker, 1)[1].split("---", 1)[0]
        else:
            cls.section = ""

    def test_section_not_empty(self):
        self.assertTrue(self.section)

    def test_amd_audit_gap_trigger_present(self):
        self.assertIn(
            "MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT",
            self.section,
        )

    def test_placeholder_invention_trigger_present(self):
        self.assertIn("invented fill prices", self.section)

    def test_bypass_or_legacy_outside_allow_list_trigger_present(self):
        self.assertIn("ORDER_SUBMITTER_BYPASS", self.section)
        self.assertIn("LEGACY_DANGEROUS", self.section)
        self.assertIn("ALLOW_LIST", self.section)

    def test_attribution_misuse_trigger_present(self):
        self.assertIn("DRAWDOWN_ATTRIBUTION_COMPLETE", self.section)
        self.assertIn("compute_partial_attribution", self.section)

    def test_amd_strong_match_forge_trigger_present(self):
        self.assertIn("STRONG", self.section)

    def test_baseline_reset_trigger_present(self):
        self.assertIn("starting_equity", self.section)
        # tolerate line-wrap between words
        compact = " ".join(self.section.split())
        self.assertIn("reset silently", compact)

    def test_data_quality_flip_trigger_present(self):
        self.assertIn("data_quality", self.section)

    def test_legacy_script_reintroduction_trigger_present(self):
        self.assertIn("emergency_close_", self.section)

    def test_at_least_nine_escalation_triggers_listed(self):
        # Each trigger is its own bullet starting with "- "
        bullets = [
            ln for ln in self.section.splitlines()
            if ln.strip().startswith("- ")
        ]
        self.assertGreaterEqual(len(bullets), 8,
                                  "Expected ≥8 v3.23.2 escalation triggers; "
                                  f"got {len(bullets)}")


if __name__ == "__main__":
    unittest.main()
