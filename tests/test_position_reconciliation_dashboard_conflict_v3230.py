"""v3.23 (2026-06-08) — Position reconciliation dashboard conflict tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestStatusEnum(unittest.TestCase):
    def test_all_statuses_present(self):
        import position_reconciliation_status as p
        for s in (
            p.VERIFIED_OPEN, p.VERIFIED_CLOSED,
            p.STALE_LOCAL_OPEN, p.STALE_LOCAL_CLOSED,
            p.BROKER_SIDE_CLOSED, p.ORPHAN_BROKER_POSITION,
            p.LOCAL_BROKER_CONFLICT,
            p.DASHBOARD_VERIFIED_POSITION, p.DASHBOARD_VERIFIED_NOT_OPEN,
            p.API_UNAVAILABLE_OPERATOR_DASHBOARD_PROVIDED,
            p.UNKNOWN_REQUIRES_API_VERIFICATION,
            p.BROKER_SIDE_CLOSED_OR_DASHBOARD_VERIFIED_NOT_OPEN,
            p.STALE_LOCAL_TIME_EXPIRED_BUT_DASHBOARD_OPEN,
            p.STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN,
            p.STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN_DUST,
            p.VERIFIED_CLOSED_FROM_AUDIT_SAFE_CLOSE,
        ):
            self.assertIn(s, p.ALL_STATUSES)

    def test_invariants_true(self):
        import position_reconciliation_status as p
        self.assertTrue(p.NEVER_CLOSES_POSITIONS)
        self.assertTrue(p.NEVER_MODIFIES_POSITIONS)
        self.assertTrue(p.NEVER_PLACES_ORDERS)
        self.assertTrue(p.NEVER_LOWERS_RISK)


class TestClassifierAMDAnomaly(unittest.TestCase):
    def test_dashboard_not_open_no_safe_close(self):
        # AMD case
        import position_reconciliation_status as p
        r = p.classify("AMD",
                        local_state="armed",
                        broker_evidence="dashboard_not_open",
                        has_audit_safe_close=False)
        self.assertEqual(r.status,
                          p.BROKER_SIDE_CLOSED_OR_DASHBOARD_VERIFIED_NOT_OPEN)
        self.assertTrue(r.requires_api_followup)

    def test_dashboard_not_open_with_safe_close(self):
        # CRWD/NOW/QQQ/SPY/PANW/ORCL/GLD case
        import position_reconciliation_status as p
        r = p.classify("CRWD",
                        local_state="closed",
                        broker_evidence="dashboard_not_open",
                        has_audit_safe_close=True)
        self.assertEqual(r.status, p.VERIFIED_CLOSED_FROM_AUDIT_SAFE_CLOSE)


class TestClassifierETHPrecision(unittest.TestCase):
    def test_time_expired_but_dashboard_open(self):
        # ETHUSD case
        import position_reconciliation_status as p
        r = p.classify("ETHUSD",
                        local_state="time_expired",
                        broker_evidence="dashboard_open",
                        has_audit_safe_close=False)
        self.assertEqual(r.status, p.STALE_LOCAL_TIME_EXPIRED_BUT_DASHBOARD_OPEN)


class TestClassifierAVAXSOLLTC(unittest.TestCase):
    def test_local_closed_dashboard_open(self):
        # AVAXUSD case
        import position_reconciliation_status as p
        r = p.classify("AVAXUSD",
                        local_state="closed",
                        broker_evidence="dashboard_open",
                        has_audit_safe_close=False)
        self.assertEqual(r.status, p.STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN)

    def test_local_closed_dashboard_open_dust(self):
        # SOLUSD/LTCUSD dust cases
        import position_reconciliation_status as p
        for sym in ("SOLUSD", "LTCUSD"):
            r = p.classify(sym,
                            local_state="closed",
                            broker_evidence="dashboard_open",
                            has_audit_safe_close=False,
                            dust=True)
            self.assertEqual(r.status, p.STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN_DUST)
            self.assertTrue(r.dust)


class TestFailSoft(unittest.TestCase):
    def test_classify_with_none_inputs(self):
        import position_reconciliation_status as p
        r = p.classify("X", local_state=None, broker_evidence=None)
        self.assertEqual(r.status, p.UNKNOWN_REQUIRES_API_VERIFICATION)
        self.assertTrue(r.requires_api_followup)

    def test_batch_handles_malformed_entry(self):
        import position_reconciliation_status as p
        # Mix valid + malformed
        result = p.classify_batch({
            "AMD":     {"local_state": "armed", "broker_evidence": "dashboard_not_open"},
            "garbage": "not_a_dict",
        })
        self.assertIn("AMD", result)
        # "garbage" not a dict → skipped, NOT raised


class TestNoOrderPlacingInModule(unittest.TestCase):
    def test_module_does_not_import_alpaca_orders(self):
        # AST-walk: no Call nodes naming forbidden functions, no
        # Import/ImportFrom of alpaca_orders. Docstrings/comments are
        # skipped by AST so they can legitimately mention safe_close
        # as the diagnosed mechanism.
        import ast
        src = (REPO_ROOT / "shared" / "position_reconciliation_status.py").read_text()
        tree = ast.parse(src)
        forbidden_names = {"place_stock_bracket", "place_crypto_order",
                            "place_simple_buy", "safe_close"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = (func.id if isinstance(func, ast.Name)
                         else func.attr if isinstance(func, ast.Attribute)
                         else None)
                if name in forbidden_names:
                    self.fail(f"forbidden call to {name!r}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if getattr(node, "module", None) == "alpaca_orders":
                    self.fail("forbidden import of alpaca_orders")


if __name__ == "__main__":
    unittest.main()
