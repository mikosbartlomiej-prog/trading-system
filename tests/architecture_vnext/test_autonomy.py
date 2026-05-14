"""autonomy contract — decisions, paper-only, forbidden-string scan."""
import os
import sys
import unittest

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

import autonomy


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class TestPaperOnly(unittest.TestCase):
    def test_paper_endpoint_ok(self):
        autonomy.assert_paper_only("https://paper-api.alpaca.markets")
        autonomy.assert_paper_only("https://paper-api.alpaca.markets/")  # trailing slash
        autonomy.assert_paper_only(None)  # library default → ok

    def test_live_endpoint_rejected(self):
        with self.assertRaises(autonomy.PaperOnlyViolation):
            autonomy.assert_paper_only("https://api.alpaca.markets")

    def test_random_endpoint_rejected(self):
        with self.assertRaises(autonomy.PaperOnlyViolation):
            autonomy.assert_paper_only("https://evil.example.com")

    def test_non_string_rejected(self):
        with self.assertRaises(autonomy.PaperOnlyViolation):
            autonomy.assert_paper_only(42)


class TestForbiddenStrings(unittest.TestCase):
    def test_approval_needed_raises(self):
        with self.assertRaises(autonomy.ForbiddenStateError):
            autonomy.assert_no_forbidden_strings("approval needed", where="test")

    def test_waiting_for_human_raises(self):
        with self.assertRaises(autonomy.ForbiddenStateError):
            autonomy.assert_no_forbidden_strings("waiting for human", where="test")

    def test_manual_confirm_required_raises(self):
        with self.assertRaises(autonomy.ForbiddenStateError):
            autonomy.assert_no_forbidden_strings("manual confirmation required", "test")

    def test_clean_string_ok(self):
        autonomy.assert_no_forbidden_strings("trade APPROVED", "test")
        autonomy.assert_no_forbidden_strings("rejected by gate", "test")


class TestDecisionRecord(unittest.TestCase):
    def test_unknown_decision_type_rejected(self):
        with self.assertRaises(ValueError):
            autonomy.make_decision("FROBNICATE", "?", "?", "test")

    def test_decision_with_forbidden_reason_rejected(self):
        with self.assertRaises(autonomy.ForbiddenStateError):
            autonomy.make_decision(
                "REJECT_ENTRY", "REJECT",
                reason="please approve manually",
                actor="test",
            )

    def test_decision_hash_stable(self):
        d1 = autonomy.make_decision("APPROVE_ENTRY", "APPROVE", "rsi ok", "t",
                                     inputs={"a": 1, "b": 2})
        d2 = autonomy.make_decision("APPROVE_ENTRY", "APPROVE", "rsi ok", "t",
                                     inputs={"b": 2, "a": 1})  # different order
        self.assertEqual(d1.deterministic_inputs_hash,
                          d2.deterministic_inputs_hash)

    def test_decision_serialises_to_jsonl(self):
        d = autonomy.make_decision(
            "EMERGENCY_CLOSE", "CLOSED", "hard loss",
            actor="emergency_engine",
            affected_symbols=["AAPL"], reversible=False,
        )
        line = d.to_jsonl()
        self.assertIn("EMERGENCY_CLOSE", line)
        self.assertIn("AAPL", line)
        self.assertTrue(line.startswith("{"))
        self.assertTrue(line.endswith("}"))


class TestRepoForbiddenScan(unittest.TestCase):
    """No forbidden approval wording in trading code paths."""

    def test_no_forbidden_strings_in_trading_code(self):
        findings = autonomy.scan_repo_for_forbidden(REPO_ROOT)
        # docs/ and tests/architecture_vnext/ are excluded — they may
        # legitimately reference the FORBIDDEN strings to document the rule.
        # Anything else is a real violation.
        msg = "\n".join(f"{f['file']}:{f['line']} [{f['pattern']}] {f['snippet']}"
                       for f in findings)
        self.assertEqual(findings, [], f"Found forbidden wording:\n{msg}")


if __name__ == "__main__":
    unittest.main()
