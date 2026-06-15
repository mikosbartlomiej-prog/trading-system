"""v3.22.0 (2026-06-15) — ETAP 2 unit tests for shared/signal_emitter.py.

Coverage:
  * Happy path writes a row to the opportunity ledger.
  * Confidence score + components persisted on a successful emit.
  * Missing confidence_inputs blocks an entry_capable event.
  * Observe-only events emit without confidence_inputs.
  * Ledger write failure surfaces emitted=False (no raise).
  * compute_confidence ImportError → status UNAVAILABLE (no raise).
  * The module never calls any broker function (AST scan).
  * The module never makes a network call (no requests / urllib usage).
  * Idempotency: a repeat key returns DUPLICATE_SUPPRESSED.
  * Audit link from metadata is written through.

NEVER places trades. NEVER imports alpaca_orders.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _valid_event(**overrides):
    import signal_event as se
    base = dict(
        signal_id="sig-001",
        strategy_id="momentum-long",
        symbol="AAPL",
        asset_class="us_equity",
        side="long",
        action="BUY",
        timestamp_iso="2026-06-15T13:30:00Z",
        source_monitor="price-monitor",
        pipeline="monitor",
        evidence_source="PAPER",
        entry_capable=True,
        confidence_inputs={"primary_score": 0.7},
        risk_inputs={"size_usd": 10_000},
        metadata={"audit_link": "audit-abc"},
    )
    base.update(overrides)
    return se.SignalEvent(**base)


class _BaseEmitterTest(unittest.TestCase):

    def setUp(self):
        # Sandbox the ledger and audit directories.
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger_dir = Path(self.tmp.name) / "opportunity_ledger"
        self.audit_dir = Path(self.tmp.name) / "audit"
        os.environ["OPPORTUNITY_LEDGER_DIR"] = str(self.ledger_dir)
        os.environ["AUDIT_TRADING_DIR"] = str(self.audit_dir)

        # Force a fresh import so the ledger sees the new env var.
        for mod in list(sys.modules):
            if mod in (
                "signal_event",
                "signal_emitter",
                "signal_opportunity_ledger",
            ) or mod.endswith((
                ".signal_event",
                ".signal_emitter",
                ".signal_opportunity_ledger",
            )):
                del sys.modules[mod]

        import signal_emitter  # noqa: F401
        self.signal_emitter = signal_emitter
        # Wipe the process-local idempotency cache so test isolation holds.
        signal_emitter._clear_idempotency_cache_for_tests()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("OPPORTUNITY_LEDGER_DIR", None)
        os.environ.pop("AUDIT_TRADING_DIR", None)

    def _read_ledger(self):
        # Find the single jsonl file inside the ledger dir.
        if not self.ledger_dir.exists():
            return []
        rows = []
        for p in sorted(self.ledger_dir.glob("*.jsonl")):
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        return rows


class TestHappyPath(_BaseEmitterTest):

    def test_happy_path_writes_opportunity_row(self):
        # Stub compute_confidence to return a predictable score.
        class _FakeReport:
            total = 0.72
            components = {"data_quality": 0.9, "signal_strength": 0.6}
            decision = "ALLOW"

        with patch("shared.confidence.compute_confidence",
                   return_value=_FakeReport(), create=True):
            with patch("confidence.compute_confidence",
                       return_value=_FakeReport(), create=True):
                result = self.signal_emitter.emit_signal_opportunity(_valid_event())

        self.assertTrue(result["emitted"], result)
        self.assertEqual(result["status"], "EMITTED")
        self.assertEqual(result["signal_id"], "sig-001")
        self.assertEqual(result["audit_link"], "audit-abc")
        rows = self._read_ledger()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["signal_id"], "sig-001")
        self.assertEqual(rows[0]["strategy"], "momentum-long")
        self.assertEqual(rows[0]["symbol"], "AAPL")

    def test_confidence_score_persisted(self):
        class _FakeReport:
            total = 0.83
            components = {"data_quality": 0.9}
            decision = "ALLOW"

        with patch("shared.confidence.compute_confidence",
                   return_value=_FakeReport(), create=True):
            with patch("confidence.compute_confidence",
                       return_value=_FakeReport(), create=True):
                self.signal_emitter.emit_signal_opportunity(_valid_event())

        rows = self._read_ledger()
        self.assertAlmostEqual(rows[0]["confidence_score"], 0.83, places=4)

    def test_confidence_components_persisted(self):
        class _FakeReport:
            total = 0.55
            components = {"data_quality": 0.9, "signal_strength": 0.3}
            decision = "ALERT_ONLY"

        with patch("shared.confidence.compute_confidence",
                   return_value=_FakeReport(), create=True):
            with patch("confidence.compute_confidence",
                       return_value=_FakeReport(), create=True):
                self.signal_emitter.emit_signal_opportunity(_valid_event())

        rows = self._read_ledger()
        self.assertEqual(rows[0]["confidence_components"],
                         {"data_quality": 0.9, "signal_strength": 0.3})

    def test_emit_writes_audit_link_if_metadata_supplied(self):
        class _FakeReport:
            total = 0.7
            components = {}
            decision = "ALLOW"

        ev = _valid_event(metadata={"audit_link": "audit-XYZ"})
        with patch("shared.confidence.compute_confidence",
                   return_value=_FakeReport(), create=True):
            with patch("confidence.compute_confidence",
                       return_value=_FakeReport(), create=True):
                result = self.signal_emitter.emit_signal_opportunity(ev)

        self.assertEqual(result["audit_link"], "audit-XYZ")
        rows = self._read_ledger()
        self.assertEqual(rows[0]["audit_link"], "audit-XYZ")


class TestValidationContract(_BaseEmitterTest):

    def test_missing_confidence_inputs_blocks_entry_capable(self):
        # v3.24 supersedes v3.22: when an entry_capable event arrives
        # with empty confidence_inputs, the emitter back-fills via
        # build_confidence_inputs BEFORE validate runs, so the event
        # no longer fails validation. The row is persisted with either
        # a numeric confidence_score OR confidence_status=ERROR.
        import signal_event as se
        bad = se.SignalEvent(
            signal_id="sig-X",
            strategy_id="momentum-long",
            symbol="AAPL",
            asset_class="us_equity",
            side="long",
            action="BUY",
            timestamp_iso="2026-06-15T13:30:00Z",
            source_monitor="price-monitor",
            pipeline="monitor",
            evidence_source="PAPER",
            entry_capable=True,
            confidence_inputs={},      # v3.24: builder back-fills
            risk_inputs={"size_usd": 10_000},
        )
        result = self.signal_emitter.emit_signal_opportunity(bad)
        # v3.24 contract: emitted=True, status=EMITTED, score numeric OR ERROR.
        self.assertTrue(result["emitted"], result)
        self.assertEqual(result["status"], "EMITTED")
        rows = self._read_ledger()
        self.assertEqual(len(rows), 1)
        # Either a real number or an explicit ERROR status — never silent null.
        status = rows[0]["raw_signal"].get("confidence_status")
        score = rows[0]["confidence_score"]
        if score is None:
            self.assertEqual(status, "ERROR")
        else:
            self.assertEqual(status, "OK")

    def test_observe_only_event_emits_without_confidence_inputs(self):
        import signal_event as se
        obs = se.SignalEvent(
            signal_id="obs-1",
            strategy_id="price-monitor",
            symbol="SPY",
            asset_class="us_equity",
            side="n/a",
            action="HALTED",
            timestamp_iso="2026-06-15T13:30:00Z",
            source_monitor="price-monitor",
            pipeline="monitor",
            evidence_source="PAPER",
            entry_capable=False,
        )
        result = self.signal_emitter.emit_signal_opportunity(obs)
        self.assertTrue(result["emitted"], result)
        self.assertEqual(result["status"], "EMITTED")
        rows = self._read_ledger()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["signal_id"], "obs-1")


class TestFailSoft(_BaseEmitterTest):

    def test_record_opportunity_failure_returns_emitted_false(self):
        def _boom(**kwargs):
            raise RuntimeError("disk full")

        # Stub confidence so it doesn't fail first.
        class _FakeReport:
            total = 0.7
            components = {}
            decision = "ALLOW"

        with patch("shared.confidence.compute_confidence",
                   return_value=_FakeReport(), create=True):
            with patch("confidence.compute_confidence",
                       return_value=_FakeReport(), create=True):
                with patch("shared.signal_opportunity_ledger.record_opportunity",
                           side_effect=_boom):
                    with patch("signal_opportunity_ledger.record_opportunity",
                               side_effect=_boom):
                        result = self.signal_emitter.emit_signal_opportunity(_valid_event())

        self.assertFalse(result["emitted"])
        self.assertEqual(result["status"], "LEDGER_WRITE_FAILED")
        self.assertIn("error", result)
        self.assertEqual(self._read_ledger(), [])

    def test_compute_confidence_unavailable_marks_status_unavailable(self):
        # v3.24 supersedes v3.22: a compute_confidence import / call
        # failure on an entry-capable event now yields confidence_status
        # ERROR (was UNAVAILABLE). Ledger write still succeeds — the
        # operator must see WHY a row has no score.
        def _import_boom(**kwargs):
            raise ImportError("confidence offline")

        with patch("shared.confidence.compute_confidence",
                   side_effect=_import_boom, create=True):
            with patch("confidence.compute_confidence",
                       side_effect=_import_boom, create=True):
                result = self.signal_emitter.emit_signal_opportunity(_valid_event())

        # Ledger write should STILL succeed (confidence is advisory).
        self.assertTrue(result["emitted"], result)
        self.assertEqual(result["confidence_status"], "ERROR")
        self.assertIsNone(result["confidence_score"])
        rows = self._read_ledger()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["confidence_score"])
        # v3.24: an explicit error reason must be recorded.
        self.assertEqual(rows[0]["raw_signal"]["confidence_status"], "ERROR")
        self.assertEqual(rows[0]["raw_signal"]["blocking_reason"],
                          "CONFIDENCE_COMPUTE_FAILED")


class TestIdempotency(_BaseEmitterTest):

    def test_duplicate_idempotency_key_returns_DUPLICATE_SUPPRESSED(self):
        class _FakeReport:
            total = 0.7
            components = {}
            decision = "ALLOW"

        with patch("shared.confidence.compute_confidence",
                   return_value=_FakeReport(), create=True):
            with patch("confidence.compute_confidence",
                       return_value=_FakeReport(), create=True):
                first = self.signal_emitter.emit_signal_opportunity(
                    _valid_event(), idempotency_key="key-A")
                second = self.signal_emitter.emit_signal_opportunity(
                    _valid_event(), idempotency_key="key-A")

        self.assertTrue(first["emitted"])
        self.assertEqual(first["status"], "EMITTED")
        self.assertFalse(second["emitted"])
        self.assertEqual(second["status"], "DUPLICATE_SUPPRESSED")
        # Only one row should be in the ledger (the first emit).
        rows = self._read_ledger()
        self.assertEqual(len(rows), 1)


def _scan_module_code_only(path: Path) -> tuple[list[str], list[str]]:
    """Return (imports, called_names), stripping docstrings + comments."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            if (node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    imports: list[str] = []
    called: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.append(func.id)
            elif isinstance(func, ast.Attribute):
                called.append(func.attr)
    return imports, called


class TestHardSafety(unittest.TestCase):

    def test_no_broker_call_during_emit(self):
        path = REPO_ROOT / "shared" / "signal_emitter.py"
        imports, called = _scan_module_code_only(path)
        # No alpaca import.
        for name in imports:
            self.assertNotIn("alpaca", name.lower(),
                             f"forbidden alpaca import {name!r}")
        # No forbidden broker function calls.
        forbidden_calls = {
            "submit_order", "place_order", "safe_close",
            "place_stock_bracket", "place_crypto_order",
            "place_simple_buy", "place_option_order",
            "close_position", "close_all_positions",
        }
        for name in called:
            self.assertNotIn(name, forbidden_calls,
                             f"forbidden call {name!r} in signal_emitter.py")

    def test_no_network_call_during_emit(self):
        path = REPO_ROOT / "shared" / "signal_emitter.py"
        imports, _ = _scan_module_code_only(path)
        forbidden_modules = {"requests", "urllib", "urllib.request",
                             "http.client", "socket", "httpx", "aiohttp"}
        for name in imports:
            self.assertFalse(
                name in forbidden_modules
                or any(name.startswith(bad + ".") for bad in forbidden_modules),
                f"forbidden network import {name!r}"
            )


if __name__ == "__main__":
    unittest.main()
