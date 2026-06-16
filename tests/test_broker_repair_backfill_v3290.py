"""v3.29 ETAP 3 (2026-06-16) — tests for scripts/backfill_broker_repair_from_incidents.py.

Asserts:

* historical P13 → backfills repair-required entry,
* operator marker for symbol suppresses backfill,
* idempotent re-run does not duplicate,
* allocator blocks after backfill,
* no broker call,
* AVAXUSD backfilled when no marker exists,
* AST no alpaca_orders import,
* script never closes positions,
* AVAXUSD test confirms the entry is created when no marker exists,
* standing markers footer in MD output.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


def _load_script():
    script_path = _REPO_ROOT / "scripts" / "backfill_broker_repair_from_incidents.py"
    if "backfill_broker_repair_from_incidents" in sys.modules:
        del sys.modules["backfill_broker_repair_from_incidents"]
    spec = importlib.util.spec_from_file_location(
        "backfill_broker_repair_from_incidents", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["backfill_broker_repair_from_incidents"] = module
    spec.loader.exec_module(module)
    return module


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _close_fail_row(symbol: str, when: datetime, *, with_403: bool = True) -> dict:
    err = "Alpaca 403 insufficient balance" if with_403 else "broker timeout"
    return {
        "decision_type":     "CLOSE_POSITION",
        "decision":          "FAILED",
        "actor":             "safe_close",
        "affected_symbols":  [symbol],
        "reason":            err,
        "action_taken":      "safe_close attempted",
        "errors":            [err],
        "result":            "failed",
        "status":            "failed",
        "timestamp":         when.isoformat(),
    }


def _safe_mode_enter_row(when: datetime, reason: str = "P13") -> dict:
    return {
        "decision_type": "SAFE_MODE_ENTERED",
        "actor":         "incident-pattern-detector",
        "reason":        reason,
        "action_taken":  "safe_mode ENTERED (INCIDENT_P13_BRACKET_INTERLOCK)",
        "timestamp":     when.isoformat(),
    }


class _IsolatedEnv(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._audit_dir = tmp / "audit"
        self._docs_dir  = tmp / "docs"
        self._markers_dir = tmp / "operator_markers"
        self._brr_path = tmp / "broker_repair_required_latest.json"
        for p in (self._audit_dir, self._docs_dir, self._markers_dir):
            p.mkdir(parents=True, exist_ok=True)
        self._prev = {
            "AUDIT_TRADING_DIR":               os.environ.pop("AUDIT_TRADING_DIR", None),
            "BROKER_REPAIR_BACKFILL_DOCS_DIR": os.environ.pop("BROKER_REPAIR_BACKFILL_DOCS_DIR", None),
            "BROKER_REPAIR_REQUIRED_PATH":     os.environ.pop("BROKER_REPAIR_REQUIRED_PATH", None),
            "OPERATOR_MARKERS_DIR":            os.environ.pop("OPERATOR_MARKERS_DIR", None),
        }
        os.environ["AUDIT_TRADING_DIR"] = str(self._audit_dir)
        os.environ["BROKER_REPAIR_BACKFILL_DOCS_DIR"] = str(self._docs_dir)
        os.environ["BROKER_REPAIR_REQUIRED_PATH"] = str(self._brr_path)
        os.environ["OPERATOR_MARKERS_DIR"] = str(self._markers_dir)
        # Force re-import of underlying state modules to pick up env tweak.
        for mod in ("broker_repair_required", "operator_repair_state",
                    "backfill_broker_repair_from_incidents"):
            if mod in sys.modules:
                del sys.modules[mod]
        self.script = _load_script()
        import broker_repair_required as brr  # noqa
        import operator_repair_state as ors   # noqa
        self.brr = brr
        self.ors = ors

    def tearDown(self):
        for k, v in self._prev.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        self._tmp.cleanup()

    def _write_audit_rows(self, rows: list[dict]) -> None:
        by_day: dict[str, list[dict]] = {}
        for r in rows:
            ts = r.get("timestamp") or _now().isoformat()
            day = ts[:10]
            by_day.setdefault(day, []).append(r)
        for day, day_rows in by_day.items():
            path = self._audit_dir / f"{day}.jsonl"
            with open(path, "a", encoding="utf-8") as fh:
                for r in day_rows:
                    fh.write(json.dumps(r) + "\n")


class TestBackfillBehaviour(_IsolatedEnv):

    def test_01_historical_p13_backfills(self):
        # 5 failed closes for AVAXUSD today, no operator marker.
        ts = _now() - timedelta(hours=2)
        rows = [_close_fail_row("AVAXUSD", ts + timedelta(seconds=i * 60))
                for i in range(5)]
        self._write_audit_rows(rows)

        actions = self.script.run_backfill(lookback_days=2, dry_run=False)
        sym_actions = {(a.symbol, a.action) for a in actions}
        self.assertIn(("AVAXUSD", "MARKED"), sym_actions)
        self.assertTrue(self.brr.is_repair_required("AVAXUSD"))

    def test_02_operator_marker_suppresses_backfill(self):
        ts = _now() - timedelta(hours=2)
        rows = [_close_fail_row("AVAXUSD", ts + timedelta(seconds=i * 60))
                for i in range(5)]
        self._write_audit_rows(rows)
        # Write operator marker first.
        self.ors.write_marker(self.ors.OperatorRepairConfirmation(
            symbol="AVAXUSD", incident_type="P13",
            dashboard_checked=True, open_orders_checked=True,
            stale_oco_cancelled_by_operator="true",
            position_closed_by_operator="true",
            final_position_state="qty=0",
            final_open_orders_state="none",
            equity_checked=True, operator_note="operator handled",
            timestamp_iso=_now().isoformat(),
        ))
        actions = self.script.run_backfill(lookback_days=2, dry_run=False)
        sym_actions = {(a.symbol, a.action) for a in actions}
        self.assertIn(("AVAXUSD", "SKIPPED_OPERATOR_MARKER"), sym_actions)
        self.assertFalse(self.brr.is_repair_required("AVAXUSD"))

    def test_03_idempotent_rerun(self):
        ts = _now() - timedelta(hours=2)
        rows = [_close_fail_row("AVAXUSD", ts + timedelta(seconds=i * 60))
                for i in range(5)]
        self._write_audit_rows(rows)
        self.script.run_backfill(lookback_days=2, dry_run=False)
        # Capture state after first run.
        state1 = json.loads(self._brr_path.read_text())
        # Re-run.
        actions = self.script.run_backfill(lookback_days=2, dry_run=False)
        sym_actions = {(a.symbol, a.action) for a in actions}
        self.assertIn(("AVAXUSD", "SKIPPED_ALREADY_MARKED"), sym_actions)
        state2 = json.loads(self._brr_path.read_text())
        # Same set of entries.
        self.assertEqual(set(state1["entries"].keys()), set(state2["entries"].keys()))

    def test_04_allocator_blocks_after_backfill(self):
        ts = _now() - timedelta(hours=2)
        rows = [_close_fail_row("AVAXUSD", ts + timedelta(seconds=i * 60))
                for i in range(5)]
        self._write_audit_rows(rows)
        self.script.run_backfill(lookback_days=2, dry_run=False)
        # Allocator gate should now block on broker_repair_required.
        if "allocator_incident_gate" in sys.modules:
            del sys.modules["allocator_incident_gate"]
        import allocator_incident_gate as gate  # noqa
        result = gate.evaluate()
        self.assertIn(result.decision.name,
                      {"BLOCK_BROKER_REPAIR_REQUIRED", "BLOCK_SAFE_MODE_ACTIVE",
                       "BLOCK_SAFE_MODE_INCONSISTENT", "BLOCK_UNKNOWN"},
                      f"Got {result.decision}")

    def test_05_no_broker_call_during_backfill(self):
        """No broker module should have been imported during the run."""
        ts = _now() - timedelta(hours=2)
        rows = [_close_fail_row("AVAXUSD", ts + timedelta(seconds=i * 60))
                for i in range(5)]
        self._write_audit_rows(rows)
        # Ensure alpaca_orders not in sys.modules before run.
        sys.modules.pop("alpaca_orders", None)
        sys.modules.pop("shared.alpaca_orders", None)
        self.script.run_backfill(lookback_days=2, dry_run=False)
        # And not after either.
        self.assertNotIn("alpaca_orders", sys.modules)
        self.assertNotIn("shared.alpaca_orders", sys.modules)

    def test_06_avaxusd_backfilled_when_no_marker(self):
        # v3.30 (2026-06-16): AVAXUSD canonicalizes to AVAX/USD on backfill.
        ts = _now() - timedelta(hours=2)
        rows = [_close_fail_row("AVAXUSD", ts + timedelta(seconds=i * 60))
                for i in range(5)]
        self._write_audit_rows(rows)
        # No marker.
        self.assertFalse(self.ors.has_repair_confirmation("AVAXUSD"))
        self.script.run_backfill(lookback_days=2, dry_run=False)
        # AVAXUSD input canonicalizes to AVAX/USD entry key.
        entries = json.loads(self._brr_path.read_text()).get("entries", {})
        self.assertIn("AVAX/USD", entries)

    def test_07_ast_no_alpaca_orders_import(self):
        path = _REPO_ROOT / "scripts" / "backfill_broker_repair_from_incidents.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {"alpaca_orders", "shared.alpaca_orders"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn(n.name, forbidden)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, forbidden)

    def test_08_no_close_position_or_safe_close_calls(self):
        path = _REPO_ROOT / "scripts" / "backfill_broker_repair_from_incidents.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {
            "close_position", "safe_close", "place_order", "submit_order",
            "cancel_order", "place_stock_order", "place_crypto_order",
            "place_option_order", "exit_safe_mode",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (getattr(node.func, "attr", None)
                        or getattr(node.func, "id", None) or "")
                self.assertNotIn(name, forbidden,
                                 f"forbidden call {name} in backfill script")

    def test_09_standing_markers_in_status_md(self):
        ts = _now() - timedelta(hours=2)
        rows = [_close_fail_row("AVAXUSD", ts + timedelta(seconds=i * 60))
                for i in range(5)]
        self._write_audit_rows(rows)
        actions = self.script.run_backfill(lookback_days=2, dry_run=False)
        md_path = self.script.write_status_markdown(actions)
        text = Path(md_path).read_text()
        for marker in [
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
            "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
        ]:
            self.assertIn(marker, text)

    def test_10_invariant_constants(self):
        self.assertIs(self.script.LIVE_TRADING_UNSUPPORTED, True)
        self.assertIs(self.script.NO_ORDER_PLACEMENT, True)
        self.assertIs(self.script.NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT, True)
        self.assertIs(self.script.EDGE_GATE_ENABLED, False)
        self.assertIs(self.script.ALLOW_BROKER_PAPER, False)


if __name__ == "__main__":
    unittest.main()
