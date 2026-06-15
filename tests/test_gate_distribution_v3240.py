"""v3.24 (2026-06-15) — tests for scripts/gate_distribution_report.py.

Synthetic ledger rows in a temp dir + verification that:
  * monitor / strategy / risk_decision / confidence_decision counts
    are computed correctly
  * top blocker per strategy / per monitor is the most common
    rejection reason
  * shadow_eligible_count == 0 surfaces dominant explanation tokens
  * data-failure tokens are extracted from raw_signal.{diagnostic_token,
    confidence_error, blocking_reason}

HARD SAFETY
-----------
- AST scan confirms script does NOT import alpaca_orders.
- AST scan confirms script does NOT use the network.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
for p in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_module():
    target = SCRIPTS_DIR / "gate_distribution_report.py"
    spec = importlib.util.spec_from_file_location(
        "gate_distribution_report_v324", str(target))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_ledger(tmp_root: Path, date_iso: str,
                   rows: list[dict]) -> None:
    """Write JSONL rows to tmp_root/learning-loop/opportunity_ledger."""
    d = tmp_root / "learning-loop" / "opportunity_ledger"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{date_iso}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8")


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()
        self.as_of = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)

    def _run(self, rows):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            _write_ledger(tdp, self.as_of.date().isoformat(), rows)
            return self.mod.build_distribution(
                as_of=self.as_of, repo_root=tdp)

    def test_total_rows_counted(self):
        rows = [
            {"strategy": "crypto-momentum", "risk_decision": "NO_SIGNAL"},
            {"strategy": "momentum-long", "risk_decision": "REJECT"},
        ]
        out = self._run(rows)
        self.assertEqual(out["total_rows"], 2)

    def test_rows_by_monitor(self):
        rows = [
            {"strategy": "crypto-momentum", "risk_decision": "NO_SIGNAL"},
            {"strategy": "momentum-long", "risk_decision": "REJECT"},
            {"strategy": "geo-defense", "risk_decision": "NO_SIGNAL"},
        ]
        out = self._run(rows)
        self.assertEqual(out["rows_by_monitor"].get("crypto-monitor"), 1)
        self.assertEqual(out["rows_by_monitor"].get("price-monitor"), 1)
        self.assertEqual(out["rows_by_monitor"].get("geo-monitor"), 1)

    def test_rows_by_risk_decision(self):
        rows = [
            {"strategy": "crypto-momentum", "risk_decision": "NO_SIGNAL"},
            {"strategy": "crypto-momentum", "risk_decision": "NO_SIGNAL"},
            {"strategy": "momentum-long", "risk_decision": "REJECT"},
            {"strategy": "momentum-long",
             "risk_decision": "HALTED_BY_DRAWDOWN_GUARD"},
        ]
        out = self._run(rows)
        self.assertEqual(out["rows_by_risk_decision"]["NO_SIGNAL"], 2)
        self.assertEqual(out["rows_by_risk_decision"]["REJECT"], 1)
        self.assertEqual(
            out["rows_by_risk_decision"]["HALTED_BY_DRAWDOWN_GUARD"], 1)

    def test_rows_by_confidence_decision_null(self):
        # No confidence_score, no confidence_decision in raw_signal:
        # row defaults to NULL
        rows = [
            {"strategy": "crypto-momentum",
             "risk_decision": "DETECTED",
             "confidence_score": None,
             "raw_signal": {}},
        ]
        out = self._run(rows)
        self.assertEqual(out["rows_by_confidence_decision"]["NULL"], 1)

    def test_rows_by_confidence_decision_block_and_allow(self):
        rows = [
            {"strategy": "crypto-momentum",
             "risk_decision": "DETECTED",
             "confidence_score": 0.7,
             "raw_signal": {"confidence_decision": "ALLOW"}},
            {"strategy": "crypto-momentum",
             "risk_decision": "DETECTED",
             "confidence_score": 0.3,
             "raw_signal": {"confidence_decision": "BLOCK"}},
            {"strategy": "crypto-momentum",
             "risk_decision": "DETECTED",
             "confidence_score": None,
             "raw_signal": {"confidence_status": "ERROR"}},
        ]
        out = self._run(rows)
        self.assertEqual(
            out["rows_by_confidence_decision"]["ALLOW"], 1)
        self.assertEqual(
            out["rows_by_confidence_decision"]["BLOCK"], 1)
        self.assertEqual(
            out["rows_by_confidence_decision"]["ERROR"], 1)

    def test_shadow_eligible_counted_correctly(self):
        rows = [
            # eligible: APPROVE + score >= 0.50
            {"strategy": "crypto-momentum",
             "risk_decision": "APPROVE",
             "confidence_score": 0.7},
            # not eligible (score below)
            {"strategy": "crypto-momentum",
             "risk_decision": "APPROVE",
             "confidence_score": 0.4},
            # eligible (DETECTED treated as APPROVE in v3.22+ semantics)
            {"strategy": "momentum-long",
             "risk_decision": "DETECTED",
             "confidence_score": 0.55},
            # not eligible (no score)
            {"strategy": "geo-defense",
             "risk_decision": "DETECTED",
             "confidence_score": None},
            # not eligible (REJECT)
            {"strategy": "crypto-momentum",
             "risk_decision": "REJECT",
             "confidence_score": 0.99},
        ]
        out = self._run(rows)
        self.assertEqual(out["shadow_eligible_count"], 2)

    def test_zero_shadow_eligible_surfaces_dominant_explanation(self):
        rows = [
            {"strategy": "crypto-momentum",
             "risk_decision": "DETECTED",
             "confidence_score": None,
             "raw_signal": {"confidence_status": "ERROR",
                              "blocking_reason": "DATA_QUALITY_FAILURE"}},
            {"strategy": "crypto-momentum",
             "risk_decision": "NO_SIGNAL",
             "confidence_score": None,
             "raw_signal": {}},
            {"strategy": "momentum-long",
             "risk_decision": "REJECT",
             "confidence_score": None,
             "raw_signal": {}},
        ]
        out = self._run(rows)
        self.assertEqual(out["shadow_eligible_count"], 0)
        self.assertGreater(len(out["dominant_explanation"]), 0)
        factors = {e["factor"] for e in out["dominant_explanation"]}
        # MUST surface at least one explicit explanation tokens
        # (confidence NULL share OR risk REJECT/NO_SIGNAL share OR
        # confidence ERROR share).
        explanation_keywords = []
        for e in out["dominant_explanation"]:
            explanation_keywords.append(e["factor"])
        # Must include at least one specific factor token.
        has_specific = any(
            f.startswith("confidence_decision=") or
            f.startswith("risk_decision=") for f in factors)
        self.assertTrue(has_specific,
                         f"Expected explicit dominant tokens, got {factors}")

    def test_data_failure_tokens_extracted(self):
        rows = [
            {"strategy": "crypto-momentum",
             "risk_decision": "DETECTED",
             "raw_signal": {"diagnostic_token": "STALE_BARS"}},
            {"strategy": "crypto-momentum",
             "risk_decision": "DETECTED",
             "raw_signal": {"diagnostic_token": "STALE_BARS"}},
            {"strategy": "crypto-momentum",
             "risk_decision": "DETECTED",
             "raw_signal": {"data_quality_failure": "NO_MARKET_DATA"}},
        ]
        out = self._run(rows)
        token_keys = list(out["rows_by_data_failure_token"].keys())
        self.assertTrue(
            any("STALE_BARS" in k for k in token_keys),
            f"expected STALE_BARS token, got {token_keys}")
        self.assertTrue(
            any("NO_MARKET_DATA" in k for k in token_keys),
            f"expected NO_MARKET_DATA token, got {token_keys}")

    def test_top_blocker_per_strategy(self):
        # crypto-momentum: 2x "risk: low_score" + 1x "confidence: BLOCK"
        rows = [
            {"strategy": "crypto-momentum",
             "rejection_reasons": ["risk: low_score"]},
            {"strategy": "crypto-momentum",
             "rejection_reasons": ["risk: low_score"]},
            {"strategy": "crypto-momentum",
             "rejection_reasons": ["confidence: BLOCK"]},
        ]
        out = self._run(rows)
        top = out["top_blocker_per_strategy"].get("crypto-momentum", {})
        self.assertEqual(top.get("top_blocker"), "risk: low_score")
        self.assertEqual(top.get("count"), 2)

    def test_top_blocker_per_monitor(self):
        rows = [
            {"strategy": "crypto-momentum",
             "rejection_reasons": ["risk: low_score"]},
            {"strategy": "crypto-oversold-bounce",
             "rejection_reasons": ["risk: low_score"]},
            {"strategy": "momentum-long",
             "rejection_reasons": ["confidence: BLOCK"]},
        ]
        out = self._run(rows)
        crypto_top = out["top_blocker_per_monitor"].get(
            "crypto-monitor", {})
        self.assertEqual(crypto_top.get("count"), 2)
        self.assertEqual(crypto_top.get("top_blocker"), "risk: low_score")


class TestSafety(unittest.TestCase):
    def test_script_does_not_import_alpaca_orders(self):
        src = (SCRIPTS_DIR / "gate_distribution_report.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        "alpaca_orders", alias.name or "")
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(
                    "alpaca_orders", node.module or "")

    def test_script_does_not_make_network_calls(self):
        src = (SCRIPTS_DIR / "gate_distribution_report.py").read_text(
            encoding="utf-8")
        for forbidden in ("import requests", "from requests",
                           "urllib.request", "http.client",
                           "socket.connect"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
