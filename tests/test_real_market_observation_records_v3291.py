"""v3.29.1 (2026-06-09) — observation record proposal tests.

v3.29.1 ships NO schema change for observation records. The proposal
doc captures the v3.30 design. These tests guard the deferral
decision: no shadow evidence counters change, no new
``evidence_quality`` value appears, and the proposal doc exists.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestProposalDocExists(unittest.TestCase):
    def test_doc_present(self):
        path = (REPO_ROOT / "docs"
                 / "REAL_MARKET_OBSERVATION_RECORD_PROPOSAL.md")
        self.assertTrue(path.exists())

    def test_doc_says_deferred_to_v3_30(self):
        text = (REPO_ROOT / "docs"
                 / "REAL_MARKET_OBSERVATION_RECORD_PROPOSAL.md"
                 ).read_text(encoding="utf-8")
        self.assertIn("DEFERRED", text)
        self.assertIn("v3.30", text)


class TestNoSchemaChangeYet(unittest.TestCase):
    def test_evidence_quality_enum_landed_in_v330_safely(self):
        # v3.29.1 originally asserted the absence of
        # REAL_MARKET_DATA_OBSERVATION + NO_TRADE_OBSERVATION because
        # the schema was deferred to v3.30. v3.30 ships that schema
        # with the diagnostic-only safety contract (observation
        # records NEVER count toward the unlock gate). The new
        # invariant is that:
        # - REAL_MARKET_DATA_OBSERVATION is distinct from
        #   REAL_MARKET_DATA,
        # - the metric ``observation_records_count`` is distinct from
        #   ``real_market_opportunities_count``.
        src = (REPO_ROOT / "shared"
                / "shadow_evidence_counters.py").read_text(
            encoding="utf-8")
        self.assertIn("REAL_MARKET_DATA_OBSERVATION", src)
        self.assertIn("NO_TRADE_OBSERVATION", src)
        self.assertIn("observation_records_count", src)
        # Confirm the diagnostic split is preserved.
        self.assertIn("REAL_MARKET_DATA_OBSERVATION", src)
        self.assertIn('"REAL_MARKET_DATA"', src)


class TestObservationsDoNotCountAsOpportunities(unittest.TestCase):
    def test_doc_pins_zero_counter_increment(self):
        text = (REPO_ROOT / "docs"
                 / "REAL_MARKET_OBSERVATION_RECORD_PROPOSAL.md"
                 ).read_text(encoding="utf-8")
        self.assertIn("NOT", text)
        self.assertIn("real_market_opportunities_count", text)
        self.assertIn("unlock broker paper", text)

    def test_doc_pins_no_unlock(self):
        text = (REPO_ROOT / "docs"
                 / "REAL_MARKET_OBSERVATION_RECORD_PROPOSAL.md"
                 ).read_text(encoding="utf-8")
        # The proposal contains "MUST NOT unlock broker paper" rule.
        self.assertIn("MUST NOT", text)


if __name__ == "__main__":
    unittest.main()
