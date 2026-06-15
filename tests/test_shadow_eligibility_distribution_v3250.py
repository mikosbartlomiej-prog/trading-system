"""v3.25 — Tests for the shadow eligibility distribution reporter."""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
if str(REPO_ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "shared"))

import build_shadow_eligibility_distribution_report as mod


class TestDistributionIncludesAll10Decisions(unittest.TestCase):
    """The output must list a count for every one of the 10 decision tokens
    even if the count is zero. This guarantees downstream readers can map
    over a stable schema."""

    def test_distribution_includes_all_10_decisions(self) -> None:
        rows: list[dict] = []  # zero rows
        payload = mod.build_payload(rows, cutoff_iso="2026-06-15T00:00:00+00:00")
        self.assertEqual(payload["rows_evaluated"], 0)
        # All 10 tokens must be present, each mapped to 0.
        self.assertEqual(len(payload["by_decision"]), 10)
        for tok in mod.ALL_DECISION_TOKENS:
            self.assertIn(tok, payload["by_decision"])
            self.assertEqual(payload["by_decision"][tok], 0)


class TestZeroEligibleWhenAllRowsNullConfidence(unittest.TestCase):
    """An observe-only row with null confidence_score must produce
    NOT_ELIGIBLE_OBSERVE_ONLY (observe gate runs first), with zero
    ELIGIBLE."""

    def test_zero_eligible_when_all_rows_observe_only(self) -> None:
        rows = [
            {
                "timestamp": "2026-06-15T12:00:00+00:00",
                "signal_id": f"x{i}",
                "observe_only": True,
                "confidence_score": None,
                "risk_decision": "UNKNOWN",
            }
            for i in range(5)
        ]
        payload = mod.build_payload(
            rows, cutoff_iso="2026-06-15T00:00:00+00:00")
        self.assertEqual(payload["rows_evaluated"], 5)
        self.assertEqual(payload["eligible_count"], 0)
        self.assertEqual(payload["by_decision"]["NOT_ELIGIBLE_OBSERVE_ONLY"], 5)


class TestEligibleWhenConfidenceAboveThresholdAndRiskApprove(unittest.TestCase):
    """A row carrying confidence_score ≥ 0.50, risk APPROVE, an acceptable
    canary verdict, and not observe-only must produce ELIGIBLE."""

    def test_eligible_when_all_conditions_met(self) -> None:
        rows = [{
            "timestamp": "2026-06-15T12:00:00+00:00",
            "signal_id": "e1",
            "observe_only": False,
            "confidence_score": 0.75,
            "risk_decision": "APPROVE",
            "canary_preflight_verdict": "CANARY_PREFLIGHT_DRY_RUN_OK",
        }]
        payload = mod.build_payload(
            rows, cutoff_iso="2026-06-15T00:00:00+00:00")
        self.assertEqual(payload["eligible_count"], 1)
        self.assertEqual(payload["by_decision"]["ELIGIBLE"], 1)


class TestReporterWritesStandingMarkers(unittest.TestCase):
    """The output payload always carries the 8 standing markers."""

    def test_reporter_emits_standing_markers(self) -> None:
        payload = mod.build_payload([], cutoff_iso="2026-06-15T00:00:00+00:00")
        self.assertIn("standing_markers", payload)
        for m in mod.STANDING_MARKERS:
            self.assertIn(m, payload["standing_markers"])

    def test_reporter_writes_to_files_when_invoked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            ledger_dir = td_path / "ledger"
            ledger_dir.mkdir()
            (ledger_dir / "2026-06-15.jsonl").write_text(
                json.dumps({
                    "timestamp": "2026-06-15T12:00:00+00:00",
                    "signal_id": "u1",
                    "observe_only": True,
                }) + "\n"
            )
            out_json = td_path / "out.json"
            out_md = td_path / "out.md"
            rc = mod.main([
                "--ledger-dir", str(ledger_dir),
                "--cutoff-iso", "2026-06-15T00:00:00+00:00",
                "--output-json", str(out_json),
                "--output-md", str(out_md),
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(out_json.exists())
            self.assertTrue(out_md.exists())
            payload = json.loads(out_json.read_text())
            self.assertIn("standing_markers", payload)
            md_text = out_md.read_text()
            for m in mod.STANDING_MARKERS:
                self.assertIn(m, md_text)


class TestReporterNeverImportsAlpacaOrders(unittest.TestCase):
    """AST-level scan over the reporter source. We refuse to ever import
    a broker module from this script."""

    def test_no_import_of_alpaca_orders(self) -> None:
        src = Path(mod.__file__).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod_name = node.module or ""
                self.assertNotIn("alpaca_orders", mod_name)
        # Also: nothing in the source mentions a broker entry point
        # name. We allowlist a small set of forbidden function names.
        forbidden = (
            "submit_order(", "place_order(", "safe_close(",
            "place_stock_order(", "place_crypto_order(",
            "place_option_order(", "close_position(", "close_all_positions(",
        )
        for name in forbidden:
            self.assertNotIn(name, src)


if __name__ == "__main__":
    unittest.main()
