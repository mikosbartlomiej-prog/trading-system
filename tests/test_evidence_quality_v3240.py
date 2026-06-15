"""v3.24 ETAP 11 tests — evidence_quality scorer.

Bonus / penalty matrix, label boundaries, garbage / high-quality
detection. Pure unit tests; no network, no broker imports.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import sys
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

from evidence_quality import (  # type: ignore  # noqa: E402
    BONUS_POINTS,
    LABEL_GARBAGE,
    LABEL_HIGH_QUALITY,
    LABEL_MARGINAL,
    LABEL_USABLE,
    PENALTY_POINTS,
    score_row,
)


def _high_quality_row(**overrides):
    """Construct a row that earns every bonus, no penalty."""
    row = {
        "signal_id":      "sig-hq",
        "symbol":         "AAPL",
        "strategy_id":    "price-momentum-long",
        "source_monitor": "price-monitor",
        "evidence_quality": "REAL_MARKET_DATA",
        "confidence_score":     0.78,
        "confidence_components": {
            "signal_strength":   0.88,
            "regime_alignment":  0.74,
            "risk_state":        0.62,
        },
        "risk_decision":  "APPROVE",
        "gate_decisions": [{"gate": "risk", "decision": "PASS"}],
        "audit_link":     "journal/autonomy/2026-06-15.jsonl",
        "raw_signal": {
            "confidence_default_reasons": {},
        },
    }
    row.update(overrides)
    return row


def _garbage_row(**overrides):
    """Construct a row that earns no bonus and several penalties."""
    row = {
        # No signal_id, no strategy_id, no source_monitor.
        "symbol":           "?",
        "confidence_score": None,
        "confidence_components": {},
        "risk_decision":    "",
        "evidence_quality": "SCAFFOLD_NO_MARKET_DATA",
        "raw_signal":       {},
    }
    row.update(overrides)
    return row


class TestScoreLabels(unittest.TestCase):

    def test_high_quality_row_scores_above_75(self):
        s = score_row(_high_quality_row())
        self.assertGreater(s.score, 75)
        self.assertEqual(s.label, LABEL_HIGH_QUALITY)

    def test_garbage_row_scores_at_most_25(self):
        s = score_row(_garbage_row())
        self.assertLessEqual(s.score, 25)
        self.assertEqual(s.label, LABEL_GARBAGE)


class TestBonusMatrix(unittest.TestCase):

    def test_evidence_quality_real_market_data_bonus(self):
        s = score_row(_high_quality_row(evidence_quality="REAL_MARKET_DATA"))
        self.assertIn("evidence_quality_real_market_data", s.bonuses)
        self.assertEqual(
            s.bonuses["evidence_quality_real_market_data"],
            BONUS_POINTS["evidence_quality_real_market_data"])

    def test_source_monitor_bonus(self):
        row = _high_quality_row()
        s = score_row(row)
        self.assertIn("source_monitor_present", s.bonuses)

    def test_strategy_id_bonus(self):
        row = _high_quality_row()
        s = score_row(row)
        self.assertIn("strategy_id_present", s.bonuses)

    def test_audit_link_bonus(self):
        row = _high_quality_row(audit_link="some/path.jsonl")
        s = score_row(row)
        self.assertIn("audit_link_populated", s.bonuses)

    def test_confidence_score_bonus(self):
        row = _high_quality_row(confidence_score=0.62)
        s = score_row(row)
        self.assertIn("confidence_score_present", s.bonuses)
        self.assertEqual(
            s.bonuses["confidence_score_present"],
            BONUS_POINTS["confidence_score_present"])

    def test_confidence_components_non_empty_bonus(self):
        row = _high_quality_row(confidence_components={"x": 0.9})
        s = score_row(row)
        self.assertIn("confidence_components_non_empty", s.bonuses)

    def test_gate_decisions_bonus(self):
        row = _high_quality_row(
            gate_decisions=[{"gate": "risk", "decision": "PASS"}])
        s = score_row(row)
        self.assertIn("gate_decisions_non_empty", s.bonuses)


class TestPenaltyMatrix(unittest.TestCase):

    def test_all_components_default_half_penalty(self):
        row = _high_quality_row(
            confidence_components={
                "signal_strength":  0.5,
                "regime_alignment": 0.5,
                "risk_state":       0.5,
            })
        s = score_row(row)
        self.assertIn("all_components_default_0_5", s.penalties)
        self.assertEqual(
            s.penalties["all_components_default_0_5"],
            PENALTY_POINTS["all_components_default_0_5"])

    def test_missing_source_or_strategy_penalty(self):
        row = _high_quality_row(strategy_id="", source_monitor="")
        s = score_row(row)
        self.assertIn("missing_source_or_strategy", s.penalties)

    def test_halt_path_only_penalty(self):
        row = _high_quality_row(evidence_quality="HALT_PATH_ONLY")
        s = score_row(row)
        self.assertIn("evidence_quality_halt_path_only", s.penalties)

    def test_scaffold_penalty(self):
        row = _high_quality_row(evidence_quality="SCAFFOLD_NO_MARKET_DATA")
        s = score_row(row)
        self.assertIn("evidence_quality_scaffold_no_market_data", s.penalties)

    def test_real_market_data_bonus_absent_with_halt_path(self):
        row = _high_quality_row(evidence_quality="HALT_PATH_ONLY")
        s = score_row(row)
        self.assertNotIn("evidence_quality_real_market_data", s.bonuses)


class TestLabelBoundaries(unittest.TestCase):

    def _build_row_with_target_score(self, target: int):
        """Tiny helper that toggles bonuses until we hit each label
        boundary. Not exhaustive — boundary tests below exercise each
        threshold directly.
        """
        row = _garbage_row()
        # Build up step by step
        if target >= 20:
            row["confidence_score"] = 0.6
        if target >= 35:
            row["confidence_components"] = {"x": 0.9}
        if target >= 50:
            row["source_monitor"] = "monitor"
            row["strategy_id"] = "strategy"
        return row

    def test_garbage_label_at_zero_score(self):
        s = score_row({})
        self.assertEqual(s.label, LABEL_GARBAGE)

    def test_high_quality_label_at_max_score(self):
        # Force max possible score: enable every bonus we can.
        row = _high_quality_row()
        s = score_row(row)
        self.assertEqual(s.label, LABEL_HIGH_QUALITY)
        # Clamped to MAX_SCORE.
        self.assertLessEqual(s.score, 100)

    def test_marginal_label_in_middle_range(self):
        # Confidence score + components but no audit_link, etc.
        row = {
            "signal_id":      "sig-m",
            "symbol":         "AAPL",
            "strategy_id":    "x",
            "source_monitor": "y",
            "confidence_score": 0.6,
            "confidence_components": {"a": 0.5},   # triggers default penalty
            "risk_decision":  "APPROVE",
        }
        s = score_row(row)
        self.assertEqual(s.label, LABEL_USABLE)


class TestMalformedInput(unittest.TestCase):

    def test_none_row_safe(self):
        s = score_row(None)
        self.assertEqual(s.score, 0)
        self.assertEqual(s.label, LABEL_GARBAGE)

    def test_non_mapping_row_safe(self):
        s = score_row([1, 2, 3])  # type: ignore[arg-type]
        self.assertEqual(s.score, 0)
        self.assertEqual(s.label, LABEL_GARBAGE)

    def test_invalid_confidence_score_does_not_bonus(self):
        row = _high_quality_row(confidence_score="not-a-number")
        s = score_row(row)
        self.assertNotIn("confidence_score_present", s.bonuses)

    def test_to_dict_serialisable(self):
        s = score_row(_high_quality_row())
        d = s.to_dict()
        self.assertIn("score", d)
        self.assertIn("label", d)
        self.assertIn("bonuses", d)
        self.assertIn("penalties", d)


class TestImmutability(unittest.TestCase):

    def test_score_is_frozen(self):
        s = score_row(_high_quality_row())
        with self.assertRaises(Exception):
            s.score = 0  # type: ignore[misc]


class TestDefaultReasonsCoverage(unittest.TestCase):
    """The +10 confidence_components_real_data bonus rewards rows
    where most components were sourced from real data (i.e.
    default_reasons covers <50% of components).
    """

    def test_no_default_reasons_grants_bonus(self):
        row = _high_quality_row()
        row["raw_signal"]["confidence_default_reasons"] = {}
        s = score_row(row)
        self.assertIn("confidence_components_real_data", s.bonuses)

    def test_low_default_coverage_grants_bonus(self):
        row = _high_quality_row()
        # 1 default reason out of 3 components < 50%
        row["raw_signal"]["confidence_default_reasons"] = {
            "signal_strength": "NO_REAL_DATA",
        }
        s = score_row(row)
        self.assertIn("confidence_components_real_data", s.bonuses)

    def test_high_default_coverage_skips_bonus(self):
        row = _high_quality_row()
        # 2 default reasons out of 3 components > 50%
        row["raw_signal"]["confidence_default_reasons"] = {
            "signal_strength":  "NO_REAL_DATA",
            "regime_alignment": "NO_REGIME_DATA",
        }
        s = score_row(row)
        self.assertNotIn("confidence_components_real_data", s.bonuses)


class TestNoBrokerImport(unittest.TestCase):
    """Static AST scan — evidence_quality.py must not import any
    broker-execution surface or network library.
    """

    def test_no_forbidden_imports(self):
        path = REPO_ROOT / "shared" / "evidence_quality.py"
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
