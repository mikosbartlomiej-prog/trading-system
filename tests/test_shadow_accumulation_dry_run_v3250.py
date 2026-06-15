"""v3.25 — Tests for the conditional shadow accumulation dry-run script."""
from __future__ import annotations

import ast
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
if str(REPO_ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "shared"))

import run_shadow_accumulation_dry_run as mod


def _make_observe_row(ts: str = "2026-06-15T12:00:00+00:00",
                      sid: str = "obs1") -> dict:
    return {
        "timestamp": ts,
        "signal_id": sid,
        "observe_only": True,
        "confidence_score": None,
        "risk_decision": "UNKNOWN",
    }


def _make_eligible_row(ts: str = "2026-06-15T12:00:00+00:00",
                       sid: str = "ok1") -> dict:
    return {
        "timestamp": ts,
        "signal_id": sid,
        "observe_only": False,
        "confidence_score": 0.80,
        "risk_decision": "APPROVE",
        "canary_preflight_verdict": "CANARY_PREFLIGHT_DRY_RUN_OK",
        "symbol": "AAPL",
        "strategy": "momentum-long",
        "asset_class": "us_equity",
        "side": "long",
        "raw_signal": {
            "price": 195.0,
            "intended_price": 195.0,
        },
    }


class TestDryRunDefaultDoesNotWriteFills(unittest.TestCase):
    def test_default_dry_run_writes_no_fills_even_when_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            shadow_dir = td_path / "shadow_ledger"
            mod.SHADOW_LEDGER_DIR = shadow_dir
            mod.SHADOW_EVIDENCE_DIR = td_path / "shadow_evidence"
            mod.AUDIT_FILE = mod.SHADOW_EVIDENCE_DIR / "audit.jsonl"
            rows = [_make_eligible_row()]
            summary = mod.process_rows(
                rows, dry_run=True, as_of_iso="2026-06-15T12:00:00+00:00")
            self.assertEqual(summary["eligible_count"], 1)
            self.assertEqual(summary["fills_written"], [])
            # No file in shadow_ledger.
            self.assertFalse(
                shadow_dir.exists() and any(shadow_dir.iterdir()),
                "dry-run must not create shadow_ledger files")


class TestDryRunFalseWithEligibleWritesFill(unittest.TestCase):
    def test_eligible_row_with_execute_writes_fill(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            mod.SHADOW_LEDGER_DIR = td_path / "shadow_ledger"
            mod.SHADOW_EVIDENCE_DIR = td_path / "shadow_evidence"
            mod.AUDIT_FILE = mod.SHADOW_EVIDENCE_DIR / "audit.jsonl"

            # Mock maybe_simulate_from_row to return a stand-in fill so
            # we don't depend on the simulator's deep schema requirements.
            class _StubFill:
                fill_status = "FILLED"
                signal_id = "ok1"

                def to_dict(self) -> dict:
                    return {
                        "fill_status": "FILLED",
                        "signal_id": "ok1",
                        "is_paper_trade": False,
                    }

            with mock.patch(
                "shared.shadow_simulator.maybe_simulate_from_row",
                return_value=_StubFill(),
            ):
                rows = [_make_eligible_row()]
                summary = mod.process_rows(
                    rows, dry_run=False,
                    as_of_iso="2026-06-15T12:00:00+00:00")

            self.assertEqual(summary["eligible_count"], 1)
            self.assertEqual(len(summary["fills_written"]), 1)
            shadow_file = mod.SHADOW_LEDGER_DIR / "2026-06-15.jsonl"
            self.assertTrue(shadow_file.exists())
            line = shadow_file.read_text().strip()
            payload = json.loads(line)
            self.assertEqual(payload["fill_status"], "FILLED")
            self.assertFalse(payload["is_paper_trade"])


class TestDryRunFalseWithZeroEligibleWritesNoFill(unittest.TestCase):
    """Even with --dry-run False, if zero rows are ELIGIBLE the script
    must write zero shadow fills. The precondition gate is the eligibility
    verdict itself."""

    def test_no_fill_when_zero_eligible_even_in_execute_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            mod.SHADOW_LEDGER_DIR = td_path / "shadow_ledger"
            mod.SHADOW_EVIDENCE_DIR = td_path / "shadow_evidence"
            mod.AUDIT_FILE = mod.SHADOW_EVIDENCE_DIR / "audit.jsonl"
            rows = [_make_observe_row()]
            summary = mod.process_rows(
                rows, dry_run=False,
                as_of_iso="2026-06-15T12:00:00+00:00")
            self.assertEqual(summary["eligible_count"], 0)
            self.assertEqual(summary["fills_written"], [])
            # Shadow ledger directory may exist but must have no fill rows.
            shadow_file = mod.SHADOW_LEDGER_DIR / "2026-06-15.jsonl"
            self.assertFalse(shadow_file.exists())


class TestNoBrokerCall(unittest.TestCase):
    """AST-level scan: the script must never reference a broker entry
    point name or import alpaca_orders."""

    def test_script_does_not_import_alpaca_orders(self) -> None:
        src = Path(mod.__file__).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("alpaca_orders", alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn("alpaca_orders", node.module or "")

    def test_script_does_not_reference_broker_entry_points(self) -> None:
        src = Path(mod.__file__).read_text()
        for name in (
            "submit_order(", "place_order(", "safe_close(",
            "place_stock_order(", "place_crypto_order(",
            "place_option_order(", "close_position(",
            "close_all_positions(",
        ):
            self.assertNotIn(name, src)


class TestNoNetworkCall(unittest.TestCase):
    """The script source must never reference a network library."""

    def test_no_network_library_imports(self) -> None:
        src = Path(mod.__file__).read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name, (
                        "requests", "urllib", "urllib.request",
                        "http.client", "httpx", "socket",
                    ))
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module or "", (
                    "requests", "urllib", "urllib.request",
                    "http.client", "httpx",
                ))

    def test_runtime_does_not_open_socket(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            mod.SHADOW_LEDGER_DIR = td_path / "shadow_ledger"
            mod.SHADOW_EVIDENCE_DIR = td_path / "shadow_evidence"
            mod.AUDIT_FILE = mod.SHADOW_EVIDENCE_DIR / "audit.jsonl"
            # Patch socket.socket to refuse any opening.
            with mock.patch.object(socket, "socket",
                                    side_effect=RuntimeError("network blocked")):
                summary = mod.process_rows(
                    [_make_observe_row()], dry_run=True,
                    as_of_iso="2026-06-15T12:00:00+00:00")
            self.assertEqual(summary["eligible_count"], 0)


class TestAuditRowWrittenForEachDecision(unittest.TestCase):
    def test_audit_row_per_decision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            mod.SHADOW_LEDGER_DIR = td_path / "shadow_ledger"
            mod.SHADOW_EVIDENCE_DIR = td_path / "shadow_evidence"
            mod.AUDIT_FILE = mod.SHADOW_EVIDENCE_DIR / "audit.jsonl"
            rows = [
                _make_observe_row(sid="obs1"),
                _make_observe_row(sid="obs2"),
                _make_observe_row(sid="obs3"),
            ]
            mod.process_rows(rows, dry_run=True,
                              as_of_iso="2026-06-15T12:00:00+00:00")
            self.assertTrue(mod.AUDIT_FILE.exists())
            audit_lines = mod.AUDIT_FILE.read_text().splitlines()
            self.assertEqual(len(audit_lines), 3)
            for line in audit_lines:
                row = json.loads(line)
                self.assertIn("decision", row)
                self.assertIn("standing_markers", row)
                self.assertEqual(row["dry_run"], True)
                self.assertEqual(row["fill_written"], False)


if __name__ == "__main__":
    unittest.main()
