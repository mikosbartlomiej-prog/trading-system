"""v3.23 (2026-06-08) — ETH precision rounding tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestErrorClassification(unittest.TestCase):
    def test_precision_rounding_classified(self):
        import crypto_precision as cp
        # The actual ETHUSD failure from 2026-06-08:
        # Alpaca 403: insufficient balance for ETH (requested: 5.072, available: 5.0724058)
        result = cp.classify_precision_error(
            http_status=403,
            response_body={
                "message": ("insufficient balance for ETH (requested: 5.072, "
                             "available: 5.0724058)"),
                "code": 40310000,
                "available": "5.0724058",
                "balance": "5.0724058",
            },
            exception_str=None,
        )
        self.assertEqual(result, cp.CLOSE_BLOCKED_BY_PRECISION_ROUNDING)

    def test_held_for_orders_classified(self):
        import crypto_precision as cp
        result = cp.classify_precision_error(
            http_status=403,
            response_body={"message": "insufficient qty available; held_for_orders=10"},
        )
        # Should be HELD_FOR_ORDERS (held_for_orders takes priority over precision
        # because the body doesn't contain 'insufficient balance' marker)
        self.assertEqual(result, cp.CLOSE_BLOCKED_BY_HELD_FOR_ORDERS)

    def test_generic_403(self):
        import crypto_precision as cp
        result = cp.classify_precision_error(http_status=403, response_body=None)
        self.assertEqual(result, cp.CLOSE_BLOCKED_BY_GENERIC_403)


class TestRoundQtyDown(unittest.TestCase):
    def test_never_rounds_up(self):
        import crypto_precision as cp
        # 5.0724058 → round down to 8 dec stays 5.0724058
        self.assertLessEqual(cp.round_qty_down(5.0724058, 8), 5.0724058)
        # 5.0724058 → round down to 3 dec → 5.072 (not 5.073)
        self.assertEqual(cp.round_qty_down(5.0724058, 3), 5.072)
        # 0.9999 → round down to 2 dec → 0.99 (not 1.00)
        self.assertEqual(cp.round_qty_down(0.9999, 2), 0.99)

    def test_invariant_never_rounds_up(self):
        import crypto_precision as cp
        # Brute test: 1000 random values must all satisfy result <= input
        for v in (1.234567, 5.0724058, 0.123, 99.99999999, 100.0):
            for dec in range(0, 10):
                r = cp.round_qty_down(v, dec)
                self.assertLessEqual(r, v + 1e-12,
                                       f"round_qty_down({v}, {dec}) = {r} > input")

    def test_handles_invalid_input(self):
        import crypto_precision as cp
        self.assertEqual(cp.round_qty_down(None, 8), 0.0)
        self.assertEqual(cp.round_qty_down(-5.0, 8), 0.0)
        self.assertEqual(cp.round_qty_down("garbage", 8), 0.0)


class TestRepeatedFailureDeduper(unittest.TestCase):
    def setUp(self):
        import crypto_precision as cp
        cp.reset_counters()

    def test_under_max_attempts_should_retry(self):
        import crypto_precision as cp
        # Default MAX = 3
        for i in range(3):
            self.assertTrue(cp.should_attempt(
                "ETHUSD", 5.0724058, cp.CLOSE_BLOCKED_BY_PRECISION_ROUNDING))
            cp.record_failed_attempt(
                "ETHUSD", 5.0724058, cp.CLOSE_BLOCKED_BY_PRECISION_ROUNDING)
        # After 3 attempts, should NOT attempt again
        self.assertFalse(cp.should_attempt(
            "ETHUSD", 5.0724058, cp.CLOSE_BLOCKED_BY_PRECISION_ROUNDING))

    def test_different_qty_resets_attempt_counter(self):
        import crypto_precision as cp
        # 3 failures at qty=5.0724058
        for _ in range(3):
            cp.record_failed_attempt(
                "ETHUSD", 5.0724058, cp.CLOSE_BLOCKED_BY_PRECISION_ROUNDING)
        # New attempt at qty=5.072 (rounded down) should still be allowed
        self.assertTrue(cp.should_attempt(
            "ETHUSD", 5.072, cp.CLOSE_BLOCKED_BY_PRECISION_ROUNDING))


class TestInvariants(unittest.TestCase):
    def test_invariants_true(self):
        import crypto_precision as cp
        self.assertTrue(cp.NEVER_ROUNDS_UP)
        self.assertTrue(cp.NEVER_RETRIES_INFINITELY)
        self.assertTrue(cp.NEVER_PLACES_LIVE_ORDER)
        self.assertEqual(cp.MAX_REPEATED_FAILED_CLOSE_ATTEMPTS, 3)

    def test_no_order_placing_in_source(self):
        # AST-walk the module — no Call nodes naming forbidden functions,
        # no Import/ImportFrom of alpaca_orders. Docstrings are skipped
        # by AST so they don't false-positive.
        import ast
        src = (REPO_ROOT / "shared" / "crypto_precision.py").read_text()
        tree = ast.parse(src)
        forbidden_names = {"safe_close", "place_stock_bracket",
                            "place_crypto_order", "place_simple_buy"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name in forbidden_names:
                    self.fail(f"forbidden call to {name!r} in module")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", None)
                if mod == "alpaca_orders":
                    self.fail("forbidden import of alpaca_orders")


if __name__ == "__main__":
    unittest.main()
