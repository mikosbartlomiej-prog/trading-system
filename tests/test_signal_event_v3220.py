"""v3.22.0 (2026-06-15) — ETAP 1 unit tests for shared/signal_event.py.

Coverage:
  * Required-field validation.
  * Enum validation (pipeline / action / side).
  * entry_capable contract (requires confidence_inputs + risk_inputs).
  * observe-only events can skip confidence_inputs.
  * to_dict / from_dict round-trip.
  * build_signal_id is deterministic.
  * Module never imports alpaca_orders or broker functions.

NEVER places trades. NEVER imports alpaca_orders.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))

import signal_event as se  # noqa: E402


def _valid_kwargs(**overrides) -> dict:
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
        entry_capable=False,
    )
    base.update(overrides)
    return base


class TestValidate(unittest.TestCase):

    def test_required_fields_validate_ok(self):
        ev = se.SignalEvent(**_valid_kwargs())
        self.assertEqual(se.validate(ev), [])

    def test_missing_signal_id_fails(self):
        ev = se.SignalEvent(**_valid_kwargs(signal_id=""))
        errs = se.validate(ev)
        self.assertTrue(any("signal_id" in e for e in errs), errs)

    def test_missing_strategy_id_fails(self):
        ev = se.SignalEvent(**_valid_kwargs(strategy_id=""))
        errs = se.validate(ev)
        self.assertTrue(any("strategy_id" in e for e in errs), errs)

    def test_missing_symbol_fails(self):
        ev = se.SignalEvent(**_valid_kwargs(symbol=""))
        errs = se.validate(ev)
        self.assertTrue(any("symbol" in e for e in errs), errs)

    def test_missing_timestamp_fails(self):
        ev = se.SignalEvent(**_valid_kwargs(timestamp_iso=""))
        errs = se.validate(ev)
        self.assertTrue(any("timestamp_iso" in e for e in errs), errs)

    def test_missing_source_monitor_fails(self):
        ev = se.SignalEvent(**_valid_kwargs(source_monitor=""))
        errs = se.validate(ev)
        self.assertTrue(any("source_monitor" in e for e in errs), errs)

    def test_invalid_pipeline_fails(self):
        ev = se.SignalEvent(**_valid_kwargs(pipeline="live"))
        errs = se.validate(ev)
        self.assertTrue(any("pipeline" in e for e in errs), errs)

    def test_invalid_action_fails(self):
        ev = se.SignalEvent(**_valid_kwargs(action="ZIGZAG"))
        errs = se.validate(ev)
        self.assertTrue(any("action" in e for e in errs), errs)

    def test_invalid_side_fails(self):
        ev = se.SignalEvent(**_valid_kwargs(side="sideways"))
        errs = se.validate(ev)
        self.assertTrue(any("side" in e for e in errs), errs)

    def test_invalid_evidence_source_fails(self):
        ev = se.SignalEvent(**_valid_kwargs(evidence_source="LIVE"))
        errs = se.validate(ev)
        self.assertTrue(any("evidence_source" in e for e in errs), errs)

    def test_entry_capable_requires_confidence_inputs(self):
        ev = se.SignalEvent(**_valid_kwargs(
            entry_capable=True,
            risk_inputs={"size_usd": 10_000},
            # confidence_inputs left empty
        ))
        errs = se.validate(ev)
        self.assertTrue(any("confidence_inputs" in e for e in errs), errs)

    def test_entry_capable_requires_risk_inputs(self):
        ev = se.SignalEvent(**_valid_kwargs(
            entry_capable=True,
            confidence_inputs={"primary_score": 0.7},
            # risk_inputs left empty
        ))
        errs = se.validate(ev)
        self.assertTrue(any("risk_inputs" in e for e in errs), errs)

    def test_entry_capable_with_both_inputs_validates(self):
        ev = se.SignalEvent(**_valid_kwargs(
            entry_capable=True,
            confidence_inputs={"primary_score": 0.7},
            risk_inputs={"size_usd": 10_000},
        ))
        self.assertEqual(se.validate(ev), [])

    def test_observe_only_can_skip_confidence_inputs(self):
        ev = se.SignalEvent(**_valid_kwargs(
            entry_capable=False,
            action="HALTED",
            # both empty
        ))
        self.assertEqual(se.validate(ev), [])


class TestSerialisation(unittest.TestCase):

    def test_to_dict_round_trip(self):
        ev = se.SignalEvent(**_valid_kwargs(
            entry_capable=True,
            confidence_inputs={"primary_score": 0.7},
            risk_inputs={"size_usd": 10_000},
            metadata={"audit_link": "audit-123"},
        ))
        d = se.to_dict(ev)
        self.assertIsInstance(d, dict)
        self.assertEqual(d["signal_id"], "sig-001")
        self.assertEqual(d["confidence_inputs"], {"primary_score": 0.7})
        self.assertEqual(d["metadata"], {"audit_link": "audit-123"})
        # Mutating the returned dict must not affect the event.
        d["confidence_inputs"]["primary_score"] = 0.0
        self.assertEqual(ev.confidence_inputs["primary_score"], 0.7)

    def test_from_dict_round_trip(self):
        ev = se.SignalEvent(**_valid_kwargs(
            entry_capable=True,
            confidence_inputs={"primary_score": 0.7},
            risk_inputs={"size_usd": 10_000},
        ))
        d = se.to_dict(ev)
        ev2 = se.from_dict(d)
        self.assertEqual(ev, ev2)

    def test_from_dict_rejects_invalid(self):
        bad = _valid_kwargs(pipeline="live")
        with self.assertRaises(ValueError):
            se.from_dict(bad)

    def test_from_dict_rejects_non_dict(self):
        with self.assertRaises(TypeError):
            se.from_dict("not a dict")  # type: ignore[arg-type]


class TestBuildSignalId(unittest.TestCase):

    def test_build_signal_id_is_deterministic(self):
        a = se.build_signal_id("momentum-long", "AAPL",
                               "2026-06-15T13:30:00Z", "price-monitor")
        b = se.build_signal_id("momentum-long", "AAPL",
                               "2026-06-15T13:30:00Z", "price-monitor")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("momentum-long:AAPL:"), a)

    def test_build_signal_id_changes_with_timestamp(self):
        a = se.build_signal_id("momentum-long", "AAPL",
                               "2026-06-15T13:30:00Z", "price-monitor")
        b = se.build_signal_id("momentum-long", "AAPL",
                               "2026-06-15T13:31:00Z", "price-monitor")
        self.assertNotEqual(a, b)


def _scan_module_code_only(path: Path) -> tuple[list[str], list[str]]:
    """Return (imports, called_names) from a module's actual code, stripping
    docstrings and comments. Uses ast.parse so doc text never trips a check.
    """
    tree = ast.parse(path.read_text())
    # Strip docstrings (Expr/Constant at top of Module / FunctionDef /
    # ClassDef / AsyncFunctionDef) so any forbidden tokens that appear
    # only in commentary do not register.
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

    def test_module_never_imports_alpaca_orders(self):
        imports, _ = _scan_module_code_only(REPO_ROOT / "shared" / "signal_event.py")
        for name in imports:
            self.assertNotIn("alpaca", name.lower(),
                             f"forbidden alpaca import {name!r}")

    def test_ast_scan_no_broker_imports(self):
        imports, _ = _scan_module_code_only(REPO_ROOT / "shared" / "signal_event.py")
        for name in imports:
            self.assertNotIn("alpaca", name.lower(),
                             f"forbidden alpaca import {name!r}")

    def test_no_broker_function_calls(self):
        _, called = _scan_module_code_only(REPO_ROOT / "shared" / "signal_event.py")
        forbidden_calls = {
            "submit_order", "place_order", "safe_close",
            "place_stock_bracket", "place_crypto_order",
            "place_simple_buy", "place_option_order",
            "close_position", "close_all_positions",
        }
        for name in called:
            self.assertNotIn(name, forbidden_calls,
                             f"forbidden call {name!r}")

    def test_frozen_dataclass(self):
        ev = se.SignalEvent(**_valid_kwargs())
        with self.assertRaises(Exception):
            ev.signal_id = "mutated"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
