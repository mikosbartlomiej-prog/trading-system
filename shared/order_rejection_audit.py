"""v3.22 (2026-06-07) — Order rejection structured audit.

After the 2026-06-07 incident where 8 BUYs failed on 2026-06-05 with
the bare reason "Alpaca rejected order (see stdout)", we classify
every Alpaca rejection into a structured category so the next
execution.json carries real diagnostic detail.

The classifier is pure (no I/O), deterministic, fail-soft. It is
called by shared/alpaca_orders.py on failure and by
shared/allocator.py to surface the category in execution.json.

CONTRACT
--------
- classify_rejection(http_status, exception_str, response_body) -> str
- Returns one of REJECTION_CATEGORIES (closed enum)
- INSUFFICIENT_BUYING_POWER takes priority over INVALID_ORDER when both signals present
- UNKNOWN_BROKER_REJECTION when nothing matches (preserves raw context)
- This module DOES NOT mutate state, place orders, or skip risk gates.
"""

from __future__ import annotations

from typing import Any

INSUFFICIENT_BUYING_POWER = "INSUFFICIENT_BUYING_POWER"
MARKET_CLOSED             = "MARKET_CLOSED"
PDT_BLOCK                 = "PDT_BLOCK"
RISK_BLOCK                = "RISK_BLOCK"
INVALID_ORDER             = "INVALID_ORDER"
DUPLICATE_ORDER           = "DUPLICATE_ORDER"
BROKER_UNAVAILABLE        = "BROKER_UNAVAILABLE"
UNKNOWN_BROKER_REJECTION  = "UNKNOWN_BROKER_REJECTION"

REJECTION_CATEGORIES: frozenset[str] = frozenset({
    INSUFFICIENT_BUYING_POWER,
    MARKET_CLOSED,
    PDT_BLOCK,
    RISK_BLOCK,
    INVALID_ORDER,
    DUPLICATE_ORDER,
    BROKER_UNAVAILABLE,
    UNKNOWN_BROKER_REJECTION,
})


_BP_HINTS = (
    "insufficient buying power",
    "insufficient_buying_power",
    "buying power",
    "not enough buying power",
)
_PDT_HINTS = (
    "pattern day trader",
    "pdt",
    "day trading buying power",
)
_DUP_HINTS = (
    "duplicate",
    "already exists",
    "client_order_id",
)
_MARKET_HINTS = (
    "market closed",
    "market is closed",
    "outside trading hours",
    "outside market hours",
)
_RISK_HINTS = (
    "wash trade",
    "potential wash",
    "halted",
    "restricted",
    "symbol not tradable",
    "not tradable",
)


def _safe_lower(x: Any) -> str:
    try:
        return str(x).lower() if x is not None else ""
    except Exception:
        return ""


def _matches(text: str, hints) -> bool:
    return any(h in text for h in hints)


def classify_rejection(
    http_status: int | None,
    exception_str: str | None = None,
    response_body: Any = None,
) -> str:
    """Map (status, exception, body) to a REJECTION_CATEGORIES value.

    Order matters — first match wins:
      1. INSUFFICIENT_BUYING_POWER (most common operational rejection)
      2. PDT_BLOCK
      3. DUPLICATE_ORDER
      4. MARKET_CLOSED
      5. RISK_BLOCK (wash trade / halted / not tradable)
      6. INVALID_ORDER (4xx semantic)
      7. BROKER_UNAVAILABLE (5xx)
      8. UNKNOWN_BROKER_REJECTION (fallback)
    """
    # Combine all text sources for matching
    text_parts = []
    if exception_str:
        text_parts.append(_safe_lower(exception_str))
    if isinstance(response_body, dict):
        for k in ("message", "error", "msg", "detail"):
            v = response_body.get(k)
            if v:
                text_parts.append(_safe_lower(v))
    elif response_body is not None:
        text_parts.append(_safe_lower(response_body))
    text = " ".join(text_parts)

    # Status normalization
    try:
        status = int(http_status) if http_status is not None else 0
    except (TypeError, ValueError):
        status = 0

    if _matches(text, _BP_HINTS):
        return INSUFFICIENT_BUYING_POWER
    if _matches(text, _PDT_HINTS):
        return PDT_BLOCK
    if _matches(text, _DUP_HINTS) or status == 409:
        return DUPLICATE_ORDER
    if _matches(text, _MARKET_HINTS):
        return MARKET_CLOSED
    if _matches(text, _RISK_HINTS):
        return RISK_BLOCK
    if 500 <= status < 600:
        return BROKER_UNAVAILABLE
    if status == 403 and not text:
        # 403 with no text — most often BP exhaustion at Alpaca paper
        return INSUFFICIENT_BUYING_POWER
    if 400 <= status < 500:
        return INVALID_ORDER
    return UNKNOWN_BROKER_REJECTION


def build_rejection_payload(
    *,
    symbol: str,
    side: str,
    order_qty: float | int | None,
    order_notional: float | None,
    http_status: int | None,
    exception_str: str | None,
    response_body: Any,
    buying_power_at_attempt: float | None = None,
    available_cash_at_attempt: float | None = None,
    risk_decision: str | None = None,
    strategy: str | None = None,
) -> dict:
    """Construct a structured rejection dict for execution.json + audit log.

    All fields are best-effort; missing inputs become None.
    """
    category = classify_rejection(http_status, exception_str, response_body)

    # Extract Alpaca error code/message when available
    alpaca_error_code = None
    alpaca_message = None
    if isinstance(response_body, dict):
        alpaca_error_code = response_body.get("code") or response_body.get("error_code")
        alpaca_message = (
            response_body.get("message")
            or response_body.get("error")
            or response_body.get("msg")
        )
    if not alpaca_message and exception_str:
        alpaca_message = str(exception_str)[:240]

    return {
        "symbol": symbol,
        "side": side,
        "order_qty": order_qty,
        "order_notional": order_notional,
        "rejection_category": category,
        "http_status": http_status,
        "alpaca_error_code": alpaca_error_code,
        "alpaca_message": alpaca_message,
        "raw_exception": (str(exception_str)[:240] if exception_str else None),
        "buying_power_at_attempt": buying_power_at_attempt,
        "available_cash_at_attempt": available_cash_at_attempt,
        "risk_decision": risk_decision,
        "strategy": strategy,
    }


def format_reason_line(rejection_payload: dict) -> str:
    """Replace the bare 'Alpaca rejected order (see stdout)' line."""
    cat = rejection_payload.get("rejection_category", UNKNOWN_BROKER_REJECTION)
    msg = rejection_payload.get("alpaca_message") or "<no message>"
    msg = str(msg)[:120]
    return f"Alpaca rejected: {cat} — {msg}"


def emit_audit(rejection_payload: dict) -> None:
    """Append one V322_ORDER_REJECTION line. Fail-soft."""
    try:
        try:
            from audit import write_audit_event  # type: ignore
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
        from datetime import datetime, timezone
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "decision": "V322_ORDER_REJECTION",
            "event_type": "V322_ORDER_REJECTION",
            "actor": "order_rejection_audit",
            "symbol": rejection_payload.get("symbol"),
            "payload": rejection_payload,
        }
        write_audit_event(record, kind="trading")
    except Exception:
        return


__all__ = [
    "REJECTION_CATEGORIES",
    "INSUFFICIENT_BUYING_POWER",
    "MARKET_CLOSED",
    "PDT_BLOCK",
    "RISK_BLOCK",
    "INVALID_ORDER",
    "DUPLICATE_ORDER",
    "BROKER_UNAVAILABLE",
    "UNKNOWN_BROKER_REJECTION",
    "classify_rejection",
    "build_rejection_payload",
    "format_reason_line",
    "emit_audit",
]
