"""v3.22 (2026-06-07) — Order rejection structured audit tests.

After 2026-06-05 saw 8 BUYs all fail with the useless reason
"Alpaca rejected order (see stdout)", we want:
- a deterministic classifier mapping (status, exception, body) → category
- a structured payload covering all diagnostic fields
- replacement reason line that no longer references stdout
- audit emit fail-soft when audit module missing
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


class TestRejectionClassification(unittest.TestCase):
    def test_403_with_insufficient_buying_power(self):
        from order_rejection_audit import classify_rejection, INSUFFICIENT_BUYING_POWER
        result = classify_rejection(403, "insufficient buying power", None)
        self.assertEqual(result, INSUFFICIENT_BUYING_POWER)

    def test_422_invalid_order(self):
        from order_rejection_audit import classify_rejection, INVALID_ORDER
        result = classify_rejection(422, "invalid qty", None)
        self.assertEqual(result, INVALID_ORDER)

    def test_409_duplicate_order(self):
        from order_rejection_audit import classify_rejection, DUPLICATE_ORDER
        result = classify_rejection(409, None, {"message": "duplicate client_order_id"})
        self.assertEqual(result, DUPLICATE_ORDER)

    def test_500_broker_unavailable(self):
        from order_rejection_audit import classify_rejection, BROKER_UNAVAILABLE
        result = classify_rejection(500, "Internal Server Error", None)
        self.assertEqual(result, BROKER_UNAVAILABLE)

    def test_503_broker_unavailable(self):
        from order_rejection_audit import classify_rejection, BROKER_UNAVAILABLE
        result = classify_rejection(503, "Service Unavailable", None)
        self.assertEqual(result, BROKER_UNAVAILABLE)

    def test_pdt_block_pattern(self):
        from order_rejection_audit import classify_rejection, PDT_BLOCK
        result = classify_rejection(403, "Pattern Day Trader rule violation", None)
        self.assertEqual(result, PDT_BLOCK)

    def test_market_closed(self):
        from order_rejection_audit import classify_rejection, MARKET_CLOSED
        result = classify_rejection(422, None, {"message": "Market is closed"})
        self.assertEqual(result, MARKET_CLOSED)

    def test_unknown_fallback(self):
        from order_rejection_audit import classify_rejection, UNKNOWN_BROKER_REJECTION
        result = classify_rejection(None, None, None)
        self.assertEqual(result, UNKNOWN_BROKER_REJECTION)

    def test_403_without_text_assumed_bp(self):
        # 403 with no descriptive text — most often BP exhaustion at Alpaca paper
        from order_rejection_audit import classify_rejection, INSUFFICIENT_BUYING_POWER
        result = classify_rejection(403, None, None)
        self.assertEqual(result, INSUFFICIENT_BUYING_POWER)


class TestPayloadShape(unittest.TestCase):
    def test_full_payload_carries_all_fields(self):
        from order_rejection_audit import build_rejection_payload
        p = build_rejection_payload(
            symbol="AAPL",
            side="buy",
            order_qty=10,
            order_notional=1500.0,
            http_status=403,
            exception_str="insufficient buying power",
            response_body={"message": "insufficient_buying_power", "code": 40310000},
            buying_power_at_attempt=400.0,
            available_cash_at_attempt=100.0,
            risk_decision="ALLOW",
            strategy="allocator-rebalance",
        )
        self.assertEqual(p["rejection_category"], "INSUFFICIENT_BUYING_POWER")
        self.assertEqual(p["http_status"], 403)
        self.assertEqual(p["alpaca_error_code"], 40310000)
        self.assertEqual(p["alpaca_message"], "insufficient_buying_power")
        self.assertEqual(p["buying_power_at_attempt"], 400.0)
        self.assertEqual(p["symbol"], "AAPL")
        self.assertEqual(p["strategy"], "allocator-rebalance")
        self.assertIsNotNone(p["raw_exception"])

    def test_format_reason_line_replaces_bare_message(self):
        from order_rejection_audit import build_rejection_payload, format_reason_line
        p = build_rejection_payload(
            symbol="AAPL", side="buy", order_qty=10, order_notional=1500.0,
            http_status=403, exception_str="insufficient buying power",
            response_body=None,
        )
        line = format_reason_line(p)
        # No longer references stdout
        self.assertNotIn("see stdout", line)
        self.assertIn("INSUFFICIENT_BUYING_POWER", line)
        self.assertTrue(line.startswith("Alpaca rejected:"))


class TestAuditEmitFailSoft(unittest.TestCase):
    def test_emit_audit_does_not_raise_when_audit_missing(self):
        # Even with a malformed payload, emit_audit must never raise.
        from order_rejection_audit import emit_audit
        try:
            emit_audit(None)  # type: ignore[arg-type]
            emit_audit({})
            emit_audit({"symbol": "X", "rejection_category": "UNKNOWN_BROKER_REJECTION"})
        except Exception as e:
            self.fail(f"emit_audit raised: {e}")


class TestAllocatorReasonLineNotBareStdout(unittest.TestCase):
    """Static-source guard: the legacy 'see stdout' line must be gone."""

    def test_legacy_bare_reason_removed_from_allocator(self):
        src = (REPO_ROOT / "shared" / "allocator.py").read_text(encoding="utf-8")
        # The bare line should NOT appear as a result["reason"] assignment.
        self.assertNotIn(
            'result["reason"] = "Alpaca rejected order (see stdout)"',
            src,
            "legacy bare 'see stdout' reason still present in allocator.py",
        )

    def test_allocator_imports_rejection_helper(self):
        src = (REPO_ROOT / "shared" / "allocator.py").read_text(encoding="utf-8")
        self.assertIn("order_rejection_audit", src)
        self.assertIn("format_reason_line", src)


if __name__ == "__main__":
    unittest.main()
