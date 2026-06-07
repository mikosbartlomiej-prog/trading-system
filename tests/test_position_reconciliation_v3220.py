"""v3.22 (2026-06-07) — Position reconciliation tests.

Verifies the position_reconciliation_report.py script:
- builds without crash when Alpaca creds are missing
- never closes positions or places orders (static scan)
- invariants are all True in output
- markdown rendering covers all positions
- JSON output is valid
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


class TestPositionReconciliationBuild(unittest.TestCase):
    def setUp(self):
        for mod in ("position_reconciliation_report",):
            sys.modules.pop(mod, None)

    def test_build_report_returns_dict(self):
        import position_reconciliation_report as p
        report = p.build_report()
        self.assertIsInstance(report, dict)
        self.assertEqual(report["version"], "v3.22.0")

    def test_invariants_all_true(self):
        import position_reconciliation_report as p
        report = p.build_report()
        inv = report["invariants"]
        self.assertTrue(inv["live_trading_disabled"])
        self.assertFalse(inv["edge_gate_enabled"])
        self.assertTrue(inv["read_only"])
        self.assertTrue(inv["does_not_close_positions"])
        self.assertTrue(inv["does_not_place_orders"])

    def test_alpaca_creds_missing_fail_soft(self):
        # Save + clear env to force the fail-soft path
        saved_key = os.environ.pop("ALPACA_API_KEY", None)
        saved_secret = os.environ.pop("ALPACA_SECRET_KEY", None)
        try:
            import position_reconciliation_report as p
            snap = p.fetch_alpaca_snapshot()
            self.assertFalse(snap["available"])
            self.assertIn("error", snap)
        finally:
            if saved_key:
                os.environ["ALPACA_API_KEY"] = saved_key
            if saved_secret:
                os.environ["ALPACA_SECRET_KEY"] = saved_secret

    def test_markdown_renders(self):
        import position_reconciliation_report as p
        report = p.build_report()
        md = p.render_markdown(report)
        self.assertIn("Position Reconciliation Report", md)
        self.assertIn("READ-ONLY", md)
        self.assertIn("does not place trades", md)


class TestReadOnlyContract(unittest.TestCase):
    """Script must NOT import alpaca_orders or call any close/place fn."""

    def test_no_alpaca_orders_import_or_call(self):
        src = (REPO_ROOT / "scripts" / "position_reconciliation_report.py").read_text()
        # Look for actual usage (import statements + function calls with paren)
        for forbidden in [
            "from alpaca_orders",
            "import alpaca_orders",
            "place_stock_bracket(",
            "place_crypto_order(",
            "place_simple_buy(",
            "safe_close(",
            "close_position(",
        ]:
            self.assertNotIn(forbidden, src, f"forbidden usage: {forbidden}")


class TestCLI(unittest.TestCase):
    def test_no_write_json_outputs_valid_json(self):
        result = subprocess.run(
            ["python3", str(REPO_ROOT / "scripts" / "position_reconciliation_report.py"),
             "--no-write", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr[:500]}")
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout is not valid JSON: {e}")
        self.assertEqual(data["version"], "v3.22.0")
        self.assertFalse(data["invariants"]["edge_gate_enabled"])


if __name__ == "__main__":
    unittest.main()
