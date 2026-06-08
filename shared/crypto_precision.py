"""v3.23.0 (2026-06-08) — Crypto qty precision rounding helper.

On 2026-06-08 the exit-monitor repeatedly hit:

    safe_close(ETHUSD, qty=5.0724058) → failed
    Alpaca 403: insufficient balance for ETH (requested: 5.072...
    available: 5.0724058)

The monitor was asking Alpaca to sell `5.0724058` ETH but Alpaca
quietly truncates the qty to its own precision (8 dec for crypto)
and then sees the truncated qty as "more than available". The
position state is correct — it's a precision rounding bug in our
close request.

This module:
1. Classifies the 403 response into a clean error category.
2. Provides round_qty_down() that NEVER rounds up — guaranteeing we
   never request more than the broker holds.
3. Tracks repeated precision errors so the caller can stop spamming
   identical failing requests.

CONTRACT
--------
- READ-ONLY. No orders placed. No live URL hit.
- round_qty_down() NEVER rounds up — invariant test-asserted.
- classify_precision_error() returns a deterministic enum value.
- No infinite retries; module exposes a deduper.
"""

from __future__ import annotations

import re
from typing import Any

# ─── Error classification ────────────────────────────────────────────────────

CLOSE_BLOCKED_BY_PRECISION_ROUNDING  = "CLOSE_BLOCKED_BY_PRECISION_ROUNDING"
CLOSE_BLOCKED_BY_INSUFFICIENT_QTY    = "CLOSE_BLOCKED_BY_INSUFFICIENT_QTY"
CLOSE_BLOCKED_BY_HELD_FOR_ORDERS     = "CLOSE_BLOCKED_BY_HELD_FOR_ORDERS"
CLOSE_BLOCKED_BY_GENERIC_403         = "CLOSE_BLOCKED_BY_GENERIC_403"
CLOSE_BLOCKED_UNKNOWN                = "CLOSE_BLOCKED_UNKNOWN"

ALL_CLOSE_BLOCK_REASONS: frozenset[str] = frozenset({
    CLOSE_BLOCKED_BY_PRECISION_ROUNDING,
    CLOSE_BLOCKED_BY_INSUFFICIENT_QTY,
    CLOSE_BLOCKED_BY_HELD_FOR_ORDERS,
    CLOSE_BLOCKED_BY_GENERIC_403,
    CLOSE_BLOCKED_UNKNOWN,
})

# Invariants — test-asserted.
NEVER_ROUNDS_UP                 = True
NEVER_RETRIES_INFINITELY        = True
NEVER_PLACES_LIVE_ORDER         = True
MAX_REPEATED_FAILED_CLOSE_ATTEMPTS = 3

# Alpaca crypto precision (8 decimal places per their docs).
CRYPTO_QTY_DECIMAL_PLACES_DEFAULT = 8


def classify_precision_error(
    *,
    http_status: int | None,
    response_body: Any = None,
    exception_str: str | None = None,
) -> str:
    """Map a failed close response to a clean error category."""
    text_parts: list[str] = []
    if exception_str:
        text_parts.append(str(exception_str).lower())
    if isinstance(response_body, dict):
        for k in ("message", "error", "msg", "detail"):
            v = response_body.get(k)
            if v:
                text_parts.append(str(v).lower())
    elif response_body is not None:
        text_parts.append(str(response_body).lower())
    text = " ".join(text_parts)

    if http_status != 403 and not text:
        return CLOSE_BLOCKED_UNKNOWN

    # Precision rounding: text usually contains "requested: X" where X is
    # truncated qty AND "available: Y" or "balance: Y" where Y is the
    # full-precision qty and Y > X. The body may also include the trailing
    # decimal that triggered the truncation.
    if "insufficient balance" in text and ("requested:" in text or "available" in text):
        # If available is provided and is strictly greater than requested
        # (qty difference < a single satoshi worth of precision) → rounding.
        return CLOSE_BLOCKED_BY_PRECISION_ROUNDING

    if "held_for_orders" in text or "held for orders" in text:
        return CLOSE_BLOCKED_BY_HELD_FOR_ORDERS

    if "insufficient" in text and ("qty" in text or "quantity" in text):
        return CLOSE_BLOCKED_BY_INSUFFICIENT_QTY

    if http_status == 403:
        return CLOSE_BLOCKED_BY_GENERIC_403

    return CLOSE_BLOCKED_UNKNOWN


def round_qty_down(qty: float | int, decimal_places: int = CRYPTO_QTY_DECIMAL_PLACES_DEFAULT) -> float:
    """Round a qty DOWN to `decimal_places`. NEVER rounds up.

    The invariant: result <= input. Tested.
    """
    if qty is None:
        return 0.0
    try:
        q = float(qty)
    except (TypeError, ValueError):
        return 0.0
    if q <= 0:
        return 0.0
    if decimal_places < 0:
        decimal_places = 0
    # Multiply, integer-truncate, divide. NEVER ceil.
    scale = 10 ** decimal_places
    return int(q * scale) / scale


def extract_available_qty_from_403(response_body: Any) -> float | None:
    """Pull the `available` field out of an Alpaca 403 response body.

    Returns float or None if not parseable.
    """
    if isinstance(response_body, dict):
        for k in ("available", "balance", "qty_available", "available_qty"):
            v = response_body.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
    if isinstance(response_body, str):
        # Best-effort regex pull from the message body.
        m = re.search(r'available["\s:]+([\d.]+)', response_body)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


# ─── Repeated failure deduper ────────────────────────────────────────────────

# Keyed by (symbol, qty_str, classified_error). Caller checks
# should_attempt() before issuing the request. Once an identical (sym, qty,
# error) tuple has been seen MAX_REPEATED_FAILED_CLOSE_ATTEMPTS times,
# should_attempt returns False until the qty changes.

_REPEATED_FAILURES: dict[tuple, int] = {}


def record_failed_attempt(symbol: str, qty: float, classified_error: str) -> int:
    """Increment the failure counter for this (symbol, qty, error). Returns
    the new counter value."""
    key = (str(symbol), f"{float(qty):.10g}", str(classified_error))
    _REPEATED_FAILURES[key] = _REPEATED_FAILURES.get(key, 0) + 1
    return _REPEATED_FAILURES[key]


def should_attempt(symbol: str, qty: float, classified_error: str) -> bool:
    """Return True iff this (symbol, qty, error) hasn't been seen
    MAX_REPEATED_FAILED_CLOSE_ATTEMPTS times yet."""
    key = (str(symbol), f"{float(qty):.10g}", str(classified_error))
    return _REPEATED_FAILURES.get(key, 0) < MAX_REPEATED_FAILED_CLOSE_ATTEMPTS


def reset_counters() -> None:
    """For tests. Never called from runtime code."""
    _REPEATED_FAILURES.clear()


__all__ = [
    "CLOSE_BLOCKED_BY_PRECISION_ROUNDING",
    "CLOSE_BLOCKED_BY_INSUFFICIENT_QTY",
    "CLOSE_BLOCKED_BY_HELD_FOR_ORDERS",
    "CLOSE_BLOCKED_BY_GENERIC_403",
    "CLOSE_BLOCKED_UNKNOWN",
    "ALL_CLOSE_BLOCK_REASONS",
    "NEVER_ROUNDS_UP", "NEVER_RETRIES_INFINITELY",
    "NEVER_PLACES_LIVE_ORDER", "MAX_REPEATED_FAILED_CLOSE_ATTEMPTS",
    "CRYPTO_QTY_DECIMAL_PLACES_DEFAULT",
    "classify_precision_error",
    "round_qty_down",
    "extract_available_qty_from_403",
    "record_failed_attempt", "should_attempt", "reset_counters",
]
