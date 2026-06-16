"""v3.28 ETAP 7 (2026-06-16) — tests for scripts/reconcile_equity_gap.py.

Hard invariants asserted:

* writes the reconciliation JSON + Markdown,
* > 2% gap → EQUITY_GAP_UNRESOLVED_BLOCKS_ALLOCATOR,
* 0.5–2% gap → EQUITY_GAP_WARN,
* < 0.5% gap → EQUITY_GAP_OK,
* missing inputs handled gracefully (fail-soft, not raise),
* no broker call / no ``alpaca_orders`` import,
* thresholds NEVER mutated by the script at runtime,
* standing markers footer present in the Markdown output.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "reconcile_equity_gap.py"


def _load_module():
    """Load the script as a module so we can call ``main`` directly.

    Register in ``sys.modules`` BEFORE exec so dataclasses can resolve
    forward refs (required on Python 3.9 with
    ``from __future__ import annotations``).
    """
    if "reconcile_equity_gap" in sys.modules:
        del sys.modules["reconcile_equity_gap"]
    spec = importlib.util.spec_from_file_location(
        "reconcile_equity_gap", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["reconcile_equity_gap"] = module
    spec.loader.exec_module(module)
    return module


class _IsolatedEnv(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_path = Path(self._tmp.name)
        self._docs_dir = self._tmp_path / "docs"
        self._out_dir = self._tmp_path / "learning-loop"
        self._audit_dir = self._tmp_path / "audit"
        for p in (self._docs_dir, self._out_dir, self._audit_dir):
            p.mkdir(parents=True, exist_ok=True)
        self._prev_audit = os.environ.pop("AUDIT_TRADING_DIR", None)
        self._prev_out = os.environ.pop("EQUITY_GAP_OUTPUT_DIR", None)
        self._prev_docs = os.environ.pop("EQUITY_GAP_DOCS_DIR", None)
        self._prev_rt = os.environ.pop("RUNTIME_STATE_PATH", None)
        os.environ["AUDIT_TRADING_DIR"]    = str(self._audit_dir)
        os.environ["EQUITY_GAP_OUTPUT_DIR"] = str(self._out_dir)
        os.environ["EQUITY_GAP_DOCS_DIR"]   = str(self._docs_dir)
        self.mod = _load_module()
        # Force the module to read from our isolated runtime_state path.
        self._rt_path = self._out_dir / "runtime_state.json"
        os.environ["RUNTIME_STATE_PATH"] = str(self._rt_path)

    def tearDown(self):
        for k, prev in (
            ("AUDIT_TRADING_DIR",      self._prev_audit),
            ("EQUITY_GAP_OUTPUT_DIR",  self._prev_out),
            ("EQUITY_GAP_DOCS_DIR",    self._prev_docs),
            ("RUNTIME_STATE_PATH",     self._prev_rt),
        ):
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev
        self._tmp.cleanup()

    def _seed_runtime(self, *, current: float, peak: float | None,
                       positions: dict | None = None) -> None:
        payload = {
            "intraday_governor": {
                "current_equity":        current,
                "intraday_peak_equity":  peak,
                "session_start_equity":  current,
                "date":                  "2026-06-16",
            },
            "positions": positions or {},
        }
        self._rt_path.write_text(json.dumps(payload), encoding="utf-8")


class TestEquityGapReconciliation(_IsolatedEnv):

    # 1. Writes the reconciliation JSON (dated + latest) and the Markdown.
    def test_01_writes_reconciliation_outputs(self):
        self._seed_runtime(current=100_000.0, peak=100_100.0)
        rc = self.mod.main(["--dry-run", "false"])
        self.assertEqual(rc, 0)
        dated = list(self._out_dir.glob("equity_gap_reconciliation_*.json"))
        # latest + dated (or only dated if same name); require ≥ 1 of each.
        latest = list(self._out_dir.glob("equity_gap_reconciliation_latest.json"))
        markdown = list(self._docs_dir.glob("EQUITY_GAP_RECONCILIATION_*.md"))
        self.assertGreaterEqual(len(dated), 1)
        self.assertEqual(len(latest), 1)
        self.assertGreaterEqual(len(markdown), 1)

    # 2. > 2% gap → BLOCKS_ALLOCATOR.
    def test_02_above_2_pct_emits_blocks_allocator(self):
        self._seed_runtime(current=97_000.0, peak=100_000.0)  # gap = -3%
        payload = self.mod.build_report()
        self.assertEqual(payload["verdict"], self.mod.VERDICT_BLOCKS)
        self.assertLess(payload["gap_pct"], -2.0)

    # 3. 0.5%–2% gap → WARN.
    def test_03_warn_range_emits_warn(self):
        self._seed_runtime(current=99_000.0, peak=100_000.0)  # gap = -1%
        payload = self.mod.build_report()
        self.assertEqual(payload["verdict"], self.mod.VERDICT_WARN)

    # 4. < 0.5% gap → OK.
    def test_04_below_0_5_pct_emits_ok(self):
        self._seed_runtime(current=99_900.0, peak=100_000.0)  # gap = -0.1%
        payload = self.mod.build_report()
        self.assertEqual(payload["verdict"], self.mod.VERDICT_OK)

    # 5. Missing peak (None) is handled — does NOT raise.
    def test_05_handles_missing_inputs(self):
        # No runtime_state file at all → should not raise; verdict defaults
        # to OK because gap_pct is None.
        try:
            payload = self.mod.build_report(
                current_equity=100_000.0,
                peak_equity=None,
                positions={},
                dashboard={},
                realized_pl_today=0.0,
            )
        except Exception as e:
            self.fail(f"build_report raised on missing inputs: {e!r}")
        self.assertIn(payload["verdict"], {
            self.mod.VERDICT_OK,
            self.mod.VERDICT_WARN,
            self.mod.VERDICT_BLOCKS,
        })

    # 6. AST: no broker call inside this script.
    def test_06_ast_no_broker_call(self):
        tree = ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"))
        forbidden = {
            "submit_order", "place_order", "safe_close",
            "place_stock_order", "place_crypto_order", "place_option_order",
            "close_position", "close_all_positions",
            "cancel_order", "cancel_all_orders",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name: str | None = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name and name in forbidden:
                    self.fail(f"Forbidden broker call: {name}()")
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn("alpaca_orders", (node.module or ""))
            elif isinstance(node, ast.Import):
                for n in node.names:
                    self.assertNotIn("alpaca_orders", n.name)

    # 7. Script must NEVER change the thresholds at runtime.
    def test_07_thresholds_not_mutated(self):
        ok_before    = self.mod.EQUITY_GAP_OK_THRESHOLD_PCT
        warn_before  = self.mod.EQUITY_GAP_WARN_UPPER_PCT
        block_before = self.mod.EQUITY_GAP_BLOCKS_ALLOCATOR_PCT
        self._seed_runtime(current=95_000.0, peak=100_000.0)
        # Multiple invocations to confirm idempotence.
        self.mod.build_report()
        self.mod.main(["--dry-run", "false"])
        self.assertEqual(self.mod.EQUITY_GAP_OK_THRESHOLD_PCT, ok_before)
        self.assertEqual(self.mod.EQUITY_GAP_WARN_UPPER_PCT, warn_before)
        self.assertEqual(self.mod.EQUITY_GAP_BLOCKS_ALLOCATOR_PCT, block_before)
        # And the threshold values are exactly the documented constants.
        self.assertEqual(ok_before, 0.5)
        self.assertEqual(warn_before, 2.0)
        self.assertEqual(block_before, 2.0)

    # 8. Standing markers footer must be present in the Markdown.
    def test_08_standing_markers_in_markdown(self):
        self._seed_runtime(current=100_000.0, peak=100_100.0)
        self.mod.main(["--dry-run", "false"])
        mds = list(self._docs_dir.glob("EQUITY_GAP_RECONCILIATION_*.md"))
        self.assertGreaterEqual(len(mds), 1)
        body = mds[0].read_text(encoding="utf-8")
        for marker in (
            "EDGE_GATE_ENABLED=false",
            "ALLOW_BROKER_PAPER=false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
        ):
            self.assertIn(marker, body,
                          f"Markdown footer missing standing marker: {marker}")


if __name__ == "__main__":
    unittest.main()
