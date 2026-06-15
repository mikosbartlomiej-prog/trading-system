"""v3.24 ETAP 7 tests — shadow_eligibility evaluator.

Every decision branch is exercised. Pure unit tests; no network, no
broker imports, no file I/O.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import sys
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

from shadow_eligibility import (  # type: ignore  # noqa: E402
    ALLOWED_CANARY_VERDICTS,
    ALLOWED_RISK_DECISIONS,
    BLOCK_RISK_DECISIONS,
    CONFIDENCE_FLOOR,
    DATA_FAILURE_DIAGNOSTIC_TOKENS,
    DRAWDOWN_GUARD_SUBSTRINGS,
    NO_SIGNAL_RISK_DECISIONS,
    ShadowEligibilityDecision,
    ShadowEligibilityResult,
    evaluate_shadow_eligibility,
)


def _ok_row(**overrides):
    """A row that passes every gate by default. Tests override one
    field at a time to exercise each rejection branch.
    """
    row = {
        "signal_id":    "sig-1",
        "symbol":       "AAPL",
        "strategy":     "price-momentum-long",
        "risk_decision": "APPROVE",
        "confidence_score": 0.80,
        "confidence_components": {"signal_strength": 0.9},
        "raw_signal": {
            "diagnostic_token":         None,
            "canary_preflight_verdict": "CANARY_PREFLIGHT_DRY_RUN_OK",
            "observe_only":             False,
            "action":                   "BUY",
        },
    }
    row.update(overrides)
    return row


class TestEligibleHappyPath(unittest.TestCase):

    def test_eligible_when_all_gates_pass(self):
        r = evaluate_shadow_eligibility(_ok_row())
        self.assertEqual(r.decision, ShadowEligibilityDecision.ELIGIBLE)
        self.assertTrue(r.eligible)
        self.assertEqual(r.canary_verdict, "CANARY_PREFLIGHT_DRY_RUN_OK")
        self.assertEqual(r.risk_decision, "APPROVE")

    def test_eligible_with_detected_risk(self):
        row = _ok_row()
        row["risk_decision"] = "DETECTED"
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(r.decision, ShadowEligibilityDecision.ELIGIBLE)

    def test_eligible_with_alternate_canary_verdict(self):
        row = _ok_row()
        row["raw_signal"]["canary_preflight_verdict"] = (
            "CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED")
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(r.decision, ShadowEligibilityDecision.ELIGIBLE)


class TestRejectionBranches(unittest.TestCase):

    def test_observe_only_true_blocks(self):
        row = _ok_row()
        row["raw_signal"]["observe_only"] = True
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_OBSERVE_ONLY,
        )
        self.assertFalse(r.eligible)

    def test_observe_only_via_confidence_status_blocks(self):
        row = _ok_row()
        row["raw_signal"]["confidence_status"] = "OBSERVE_ONLY_SKIP"
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_OBSERVE_ONLY,
        )

    def test_confidence_null_blocks(self):
        row = _ok_row(confidence_score=None)
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_NO_CONFIDENCE,
        )
        self.assertIsNone(r.confidence_score)

    def test_confidence_below_floor_blocks(self):
        row = _ok_row(confidence_score=CONFIDENCE_FLOOR - 0.01)
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_CONFIDENCE_LOW,
        )

    def test_confidence_at_floor_is_eligible(self):
        # Boundary: == CONFIDENCE_FLOOR must be ELIGIBLE.
        row = _ok_row(confidence_score=CONFIDENCE_FLOOR)
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(r.decision, ShadowEligibilityDecision.ELIGIBLE)

    def test_risk_reject_blocks(self):
        row = _ok_row(risk_decision="REJECT")
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_RISK_BLOCK,
        )

    def test_risk_block_blocks(self):
        row = _ok_row(risk_decision="BLOCK")
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_RISK_BLOCK,
        )

    def test_risk_no_signal_blocks(self):
        row = _ok_row(risk_decision="NO_SIGNAL")
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_NO_SIGNAL,
        )

    def test_drawdown_halt_blocks(self):
        row = _ok_row(risk_decision="HALTED_BY_DRAWDOWN_GUARD")
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_DRAWDOWN_GUARD,
        )

    def test_data_failure_token_blocks(self):
        for token in DATA_FAILURE_DIAGNOSTIC_TOKENS:
            with self.subTest(token=token):
                row = _ok_row()
                row["raw_signal"]["diagnostic_token"] = token
                r = evaluate_shadow_eligibility(row)
                self.assertEqual(
                    r.decision,
                    ShadowEligibilityDecision.NOT_ELIGIBLE_DATA_FAILURE,
                )

    def test_unknown_diagnostic_token_does_not_block(self):
        # An unknown token should pass-through; we do not know which
        # side it falls on.
        row = _ok_row()
        row["raw_signal"]["diagnostic_token"] = "ALL_OK_PASS_THROUGH"
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(r.decision, ShadowEligibilityDecision.ELIGIBLE)

    def test_missing_canary_verdict_blocks(self):
        row = _ok_row()
        row["raw_signal"].pop("canary_preflight_verdict", None)
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_CANARY_DEFERRED,
        )

    def test_refused_canary_verdict_blocks(self):
        row = _ok_row()
        row["raw_signal"]["canary_preflight_verdict"] = (
            "CANARY_PREFLIGHT_REFUSED")
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_CANARY_DEFERRED,
        )

    def test_unknown_risk_decision_blocks(self):
        row = _ok_row(risk_decision="WHATEVER_NEW")
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_UNKNOWN,
        )


class TestMalformedInput(unittest.TestCase):

    def test_none_row_returns_unknown(self):
        r = evaluate_shadow_eligibility(None)
        self.assertEqual(
            r.decision, ShadowEligibilityDecision.NOT_ELIGIBLE_UNKNOWN)

    def test_non_mapping_row_returns_unknown(self):
        r = evaluate_shadow_eligibility([1, 2, 3])  # type: ignore[arg-type]
        self.assertEqual(
            r.decision, ShadowEligibilityDecision.NOT_ELIGIBLE_UNKNOWN)

    def test_empty_row_returns_no_confidence(self):
        r = evaluate_shadow_eligibility({})
        # Empty row: observe_only False, confidence None → NO_CONFIDENCE.
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_NO_CONFIDENCE,
        )

    def test_confidence_invalid_type_returns_no_confidence(self):
        row = _ok_row(confidence_score="not-a-number")
        r = evaluate_shadow_eligibility(row)
        self.assertEqual(
            r.decision,
            ShadowEligibilityDecision.NOT_ELIGIBLE_NO_CONFIDENCE,
        )

    def test_to_dict_is_serialisable(self):
        r = evaluate_shadow_eligibility(_ok_row())
        d = r.to_dict()
        self.assertEqual(d["decision"], "ELIGIBLE")
        self.assertTrue(d["eligible"])
        self.assertEqual(d["risk_decision"], "APPROVE")


class TestImmutability(unittest.TestCase):

    def test_result_is_frozen(self):
        r = evaluate_shadow_eligibility(_ok_row())
        with self.assertRaises(Exception):
            r.eligible = False  # type: ignore[misc]

    def test_row_is_not_mutated(self):
        row = _ok_row()
        snapshot = {k: (dict(v) if isinstance(v, dict) else v)
                    for k, v in row.items()}
        evaluate_shadow_eligibility(row)
        self.assertEqual(row.keys(), snapshot.keys())
        for k, v in snapshot.items():
            self.assertEqual(row[k], v)


class TestNoBrokerImport(unittest.TestCase):
    """Static AST scan — shadow_eligibility.py must not import any
    broker-execution surface or network library.
    """

    def test_no_forbidden_imports(self):
        path = REPO_ROOT / "shared" / "shadow_eligibility.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {
            "alpaca_orders",
            "shared.alpaca_orders",
            "requests",
            "urllib.request",
            "http.client",
            "alpaca",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name, forbidden)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, forbidden)


if __name__ == "__main__":
    unittest.main()
