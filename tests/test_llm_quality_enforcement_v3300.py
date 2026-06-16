"""v3.30 (2026-06-16) — LLM advisory quality enforcement tests.

Asserts the contract of ``shared/llm_advisory_quality_v3300.py``:

1. Output with 0 findings is rejected.
2. Output with 1 finding (< 3) is rejected.
3. Output with 3+ findings + 2+ risks + 2+ actions is accepted.
4. Generic-placeholder output is rejected.
5. (Replaced by a deterministic-stub list test — required by the
   v3.30 spec: ``deterministic fallback produces 3+ findings``.)
6. Deterministic fallback produces ≥3 findings (stub is non-empty).
7. LOW_QUALITY mark triggers fallback in the mesh.
8. Quality verdict reported in the audit row + journal.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import llm_advisory_quality_v3300 as qual         # noqa: E402
import llm_advisory_mesh as mesh                   # noqa: E402
import llm_provider_client as _p                   # noqa: E402


# ─── 1-3. Threshold logic ──────────────────────────────────────────────────


class TestThresholds(unittest.TestCase):

    def test_zero_findings_rejected(self):
        verdict = qual.evaluate({
            "findings_list":            [],
            "risks":                    ["r1", "r2"],
            "recommended_next_actions": ["a1", "a2"],
        }, limitations="non-empty")
        self.assertEqual(verdict.verdict, qual.LLM_ADVISORY_LOW_QUALITY)

    def test_one_finding_rejected_below_min_three(self):
        verdict = qual.evaluate({
            "findings_list":            ["solo finding"],
            "risks":                    ["r1", "r2"],
            "recommended_next_actions": ["a1", "a2"],
        }, limitations="non-empty")
        self.assertEqual(verdict.verdict, qual.LLM_ADVISORY_LOW_QUALITY)
        joined = " | ".join(verdict.rationale)
        self.assertIn("findings_count=1", joined)

    def test_three_findings_two_risks_two_actions_accepted(self):
        verdict = qual.evaluate({
            "findings_list":            ["f1", "f2", "f3"],
            "risks":                    ["r1", "r2"],
            "recommended_next_actions": ["a1", "a2"],
        }, limitations="non-empty limitations")
        self.assertEqual(verdict.verdict,
                          qual.LLM_ADVISORY_QUALITY_ACCEPTABLE)
        self.assertEqual(verdict.findings_count, 3)
        self.assertEqual(verdict.risks_count, 2)
        self.assertEqual(verdict.next_actions_count, 2)


# ─── 4. Generic-placeholder output rejected ────────────────────────────────


class TestPlaceholderRejected(unittest.TestCase):

    def test_generic_placeholders_rejected(self):
        verdict = qual.evaluate({
            "findings_list":            ["TBD", "placeholder",
                                         "lorem ipsum"],
            "risks":                    ["TBD", "placeholder"],
            "recommended_next_actions": ["TBD", "TBD"],
        }, limitations="non-empty")
        self.assertEqual(verdict.verdict, qual.LLM_ADVISORY_LOW_QUALITY)


# ─── 5. Unsupported recommendation routes to fallback (mesh-side) ──────────


class TestUnsupportedRecommendationRoutesToFallback(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]    = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)
        os.environ["LLM_BUDGET_STATE_DIR"] = str(self.advisory_dir)
        os.environ["GEMINI_API_KEY"]      = "test-key-only-mocked"
        os.environ["LLM_PROVIDER"]        = "gemini"
        os.environ["LLM_AGENTS_ENABLED"]  = "true"
        os.environ["LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS"] = "0"

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",     None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        os.environ.pop("LLM_BUDGET_STATE_DIR", None)
        os.environ.pop("GEMINI_API_KEY",       None)
        os.environ.pop("LLM_PROVIDER",         None)
        os.environ.pop("LLM_AGENTS_ENABLED",   None)
        os.environ.pop("LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS", None)
        self.tmp.cleanup()

    def test_short_findings_routes_to_fallback(self):
        # Provider returns ONLY one finding -> quality LOW_QUALITY ->
        # mesh routes to deterministic fallback (recommendation=ALLOW).
        short_text = json.dumps({
            "findings_list": ["only one finding"],
            "risks": ["only one risk"],
            "recommended_next_actions": ["only one action"],
            "findings": "single finding",
            "risk_level": "LOW",
            "recommendation": "WATCH",
            "veto_recommendation": False,
            "confidence": "LOW",
            "limitations": "tiny",
        })
        resp = _p.ProviderResponse(
            status=_p.LLM_PROVIDER_CALL_OK,
            provider="gemini", model="gemini-flash-latest",
            text=short_text, cost_usd=0.0,
        )
        with mock.patch.object(_p, "call_provider", return_value=resp):
            out = mesh.run_agent("RISK_REVIEW", dry_run=False)
        # Fallback path -> ALLOW.
        self.assertEqual(out.recommendation, "ALLOW")


# ─── 6. Deterministic fallback produces ≥3 findings ────────────────────────


class TestDeterministicFallbackNonEmpty(unittest.TestCase):

    def test_stub_provides_at_least_three_findings(self):
        stub = qual.deterministic_stub_lists("RISK_REVIEW")
        self.assertGreaterEqual(len(stub["findings_list"]),
                                  qual.MIN_FINDINGS)
        self.assertGreaterEqual(len(stub["risks_list"]),
                                  qual.MIN_RISKS)
        self.assertGreaterEqual(len(stub["next_actions_list"]),
                                  qual.MIN_NEXT_ACTIONS)
        # Limitations must be non-empty.
        self.assertGreaterEqual(
            len((stub["limitations"] or "").strip()),
            qual.MIN_LIMITATIONS_LEN)


# ─── 7. LOW_QUALITY mark triggers fallback (end-to-end persisted row) ──────


class TestLowQualityTriggersFallback(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]    = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)
        os.environ["LLM_BUDGET_STATE_DIR"] = str(self.advisory_dir)
        os.environ["GEMINI_API_KEY"]      = "test-key-only-mocked"
        os.environ["LLM_PROVIDER"]        = "gemini"
        os.environ["LLM_AGENTS_ENABLED"]  = "true"
        os.environ["LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS"] = "0"

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",     None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        os.environ.pop("LLM_BUDGET_STATE_DIR", None)
        os.environ.pop("GEMINI_API_KEY",       None)
        os.environ.pop("LLM_PROVIDER",         None)
        os.environ.pop("LLM_AGENTS_ENABLED",   None)
        os.environ.pop("LLM_AGENT_MIN_SECONDS_BETWEEN_CALLS", None)
        self.tmp.cleanup()

    def test_low_quality_recorded_in_persisted_row(self):
        # Provider returns LOW_QUALITY payload (two findings only).
        low_qual_text = json.dumps({
            "findings_list": ["f1", "f2"],   # < 3
            "risks": ["r1", "r2"],
            "recommended_next_actions": ["a1", "a2"],
            "findings": "agg",
            "risk_level": "LOW",
            "recommendation": "REVIEW",
            "veto_recommendation": False,
            "confidence": "LOW",
            "limitations": "lim",
        })
        resp = _p.ProviderResponse(
            status=_p.LLM_PROVIDER_CALL_OK,
            provider="gemini", model="gemini-flash-latest",
            text=low_qual_text, cost_usd=0.0,
        )
        with mock.patch.object(_p, "call_provider", return_value=resp):
            mesh.run_agent("INCIDENT_REVIEW", dry_run=False)
        # Persisted row must include the LOW_QUALITY verdict.
        p = self.advisory_dir / "INCIDENT_REVIEW_latest.json"
        persisted = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted["quality_verdict"],
            qual.LLM_ADVISORY_LOW_QUALITY)
        # And the row must be the deterministic fallback (ALLOW).
        self.assertEqual(persisted["recommendation"], "ALLOW")


# ─── 8. Quality verdict reported in audit (journal/autonomy/<date>.jsonl) ──


class TestQualityVerdictInJournal(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.advisory_dir = Path(self.tmp.name) / "llm_advisory"
        self.journal_dir  = Path(self.tmp.name) / "journal_autonomy"
        os.environ["LLM_ADVISORY_DIR"]    = str(self.advisory_dir)
        os.environ["AUTONOMY_JOURNAL_DIR"] = str(self.journal_dir)
        os.environ.pop("GEMINI_API_KEY", None)

    def tearDown(self):
        os.environ.pop("LLM_ADVISORY_DIR",    None)
        os.environ.pop("AUTONOMY_JOURNAL_DIR", None)
        self.tmp.cleanup()

    def test_dry_run_emits_journal_with_quality_field(self):
        mesh.run_agent("DAILY_BRIEF", dry_run=True)
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        jpath = self.journal_dir / f"{today}.jsonl"
        self.assertTrue(jpath.exists())
        lines = jpath.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(lines), 1)
        last = json.loads(lines[-1])
        self.assertIn("quality_verdict", last)
        self.assertIn("provider_status", last)
        self.assertIn(last["quality_verdict"],
                       (qual.LLM_ADVISORY_QUALITY_ACCEPTABLE,
                        qual.LLM_ADVISORY_LOW_QUALITY,
                        qual.LLM_ADVISORY_QUALITY_EMPTY))


if __name__ == "__main__":
    unittest.main()
