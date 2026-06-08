"""v3.25.0 (2026-06-09) — structured crypto exit policy.

Companion to ``shared/crypto_exposure_policy.py``. After the SOL/LTC
sell_to_close cycle on 2026-06-06 (combined ~$27k market sell per
symbol, no local audit ties the exit to a specific risk reason), we
must require:

- every market crypto exit carries a structured reason from a closed
  enum,
- every exit emits an audit event even when no order is placed,
- dust positions (notional < ``DUST_NOTIONAL_USD``) are NOT auto-closed
  — they require explicit operator decision,
- precision rounding never rounds UP (delegates to
  ``shared/crypto_precision.round_qty_down`` when available),
- repeated identical close attempts within a short window are deduped
  (no close spam from per-cron precision races).

CONTRACT
--------
- READ-ONLY decision module. Does NOT submit orders.
- Does NOT call the live broker endpoint.
- Returns a deterministic ``CryptoExitDecision`` enum + structured
  reason that callers must honor.

INVARIANTS (test-asserted)
--------------------------
- NEVER_PLACES_ORDERS = True
- NEVER_AUTO_CLOSES_DUST_WITHOUT_OPERATOR_DECISION = True
- NEVER_ROUNDS_UP = True
- NEVER_ALLOWS_MARKET_EXIT_WITHOUT_REASON = True
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# ─── Structured exit-reason enum ─────────────────────────────────────────────
#
# Every crypto exit MUST carry one of these reasons. Generic "close it"
# requests are rejected.

EXIT_REASON_EMERGENCY                 = "EXIT_REASON_EMERGENCY"
EXIT_REASON_STOP_LIKE                 = "EXIT_REASON_STOP_LIKE"
EXIT_REASON_TIME_EXPIRY               = "EXIT_REASON_TIME_EXPIRY"
EXIT_REASON_RISK_REDUCTION            = "EXIT_REASON_RISK_REDUCTION"
EXIT_REASON_OPERATOR_REQUESTED        = "EXIT_REASON_OPERATOR_REQUESTED"
EXIT_REASON_TAKE_PROFIT               = "EXIT_REASON_TAKE_PROFIT"
EXIT_REASON_REBALANCE                 = "EXIT_REASON_REBALANCE"
EXIT_REASON_REGIME_FLIP               = "EXIT_REASON_REGIME_FLIP"

ALLOWED_EXIT_REASONS: frozenset[str] = frozenset({
    EXIT_REASON_EMERGENCY,
    EXIT_REASON_STOP_LIKE,
    EXIT_REASON_TIME_EXPIRY,
    EXIT_REASON_RISK_REDUCTION,
    EXIT_REASON_OPERATOR_REQUESTED,
    EXIT_REASON_TAKE_PROFIT,
    EXIT_REASON_REBALANCE,
    EXIT_REASON_REGIME_FLIP,
})

# Market exits (no limit price) — narrower allowlist. Limit exits may
# carry any of the above; market exits must be one of these.
MARKET_EXIT_ALLOWED_REASONS: frozenset[str] = frozenset({
    EXIT_REASON_EMERGENCY,
    EXIT_REASON_STOP_LIKE,
    EXIT_REASON_RISK_REDUCTION,
    EXIT_REASON_OPERATOR_REQUESTED,
})

# Decision tokens.
ALLOW_LIMIT                                    = "CRYPTO_EXIT_ALLOWED_LIMIT"
ALLOW_MARKET                                   = "CRYPTO_EXIT_ALLOWED_MARKET"
BLOCK_NO_REASON                                = "CRYPTO_EXIT_BLOCKED_NO_REASON"
BLOCK_INVALID_REASON                           = "CRYPTO_EXIT_BLOCKED_INVALID_REASON"
BLOCK_MARKET_EXIT_REQUIRES_RISK_REASON         = "CRYPTO_EXIT_BLOCKED_MARKET_REQUIRES_RISK_REASON"
BLOCK_DUST_OPERATOR_DECISION_REQUIRED          = "CRYPTO_EXIT_BLOCKED_DUST_OPERATOR_DECISION_REQUIRED"
BLOCK_DEDUPED_REPEATED_CLOSE                   = "CRYPTO_EXIT_BLOCKED_DEDUPED_REPEATED_CLOSE"
BLOCK_AUDIT_PATH_UNAVAILABLE                   = "CRYPTO_EXIT_BLOCKED_AUDIT_PATH_UNAVAILABLE"
BLOCK_QTY_ROUND_UP_REJECTED                    = "CRYPTO_EXIT_BLOCKED_QTY_ROUND_UP_REJECTED"
BLOCK_PRECISION_RACE_GUARD                     = "CRYPTO_EXIT_BLOCKED_PRECISION_RACE_GUARD"

ALL_EXIT_DECISIONS: frozenset[str] = frozenset({
    ALLOW_LIMIT, ALLOW_MARKET,
    BLOCK_NO_REASON, BLOCK_INVALID_REASON,
    BLOCK_MARKET_EXIT_REQUIRES_RISK_REASON,
    BLOCK_DUST_OPERATOR_DECISION_REQUIRED,
    BLOCK_DEDUPED_REPEATED_CLOSE,
    BLOCK_AUDIT_PATH_UNAVAILABLE,
    BLOCK_QTY_ROUND_UP_REJECTED,
    BLOCK_PRECISION_RACE_GUARD,
})

# Status tokens.
CRYPTO_EXIT_AUDIT_REQUIRED               = "CRYPTO_EXIT_AUDIT_REQUIRED"
CRYPTO_EXIT_REASON_REQUIRED              = "CRYPTO_EXIT_REASON_REQUIRED"
CRYPTO_DUST_EXIT_OPERATOR_DECISION       = "CRYPTO_DUST_EXIT_OPERATOR_DECISION"
CRYPTO_MARKET_EXIT_REQUIRES_RISK_REASON  = "CRYPTO_MARKET_EXIT_REQUIRES_RISK_REASON"
CRYPTO_PRECISION_CLOSE_GUARD_ACTIVE      = "CRYPTO_PRECISION_CLOSE_GUARD_ACTIVE"

ALL_STATUS_TOKENS: frozenset[str] = frozenset({
    CRYPTO_EXIT_AUDIT_REQUIRED,
    CRYPTO_EXIT_REASON_REQUIRED,
    CRYPTO_DUST_EXIT_OPERATOR_DECISION,
    CRYPTO_MARKET_EXIT_REQUIRES_RISK_REASON,
    CRYPTO_PRECISION_CLOSE_GUARD_ACTIVE,
})

# Defaults.
DUST_NOTIONAL_USD                = 1.0
DEDUP_WINDOW_SECONDS             = 600     # 10 minutes
PRECISION_RACE_MAX_RETRIES       = 3
PRECISION_RACE_WINDOW_SECONDS    = 3600    # 1 hour

# Invariants.
NEVER_PLACES_ORDERS                                = True
NEVER_AUTO_CLOSES_DUST_WITHOUT_OPERATOR_DECISION   = True
NEVER_ROUNDS_UP                                    = True
NEVER_ALLOWS_MARKET_EXIT_WITHOUT_REASON            = True


@dataclass
class CryptoExitInputs:
    symbol: str
    side: str = "sell"  # crypto exits are sell_to_close on Alpaca paper
    proposed_qty: float = 0.0
    proposed_order_type: str = "limit"  # "limit" or "market"
    proposed_limit_price: float | None = None
    current_position_notional_usd: float = 0.0
    reason: str | None = None
    # Operator-policy flag — only relevant for dust exits.
    operator_dust_close_approved: bool = False
    # Per-symbol close-attempt history (epoch seconds list).
    recent_close_attempts_epoch: list[float] = field(default_factory=list)
    # Per-symbol precision-failure count within the precision-race window.
    precision_failures_recent: int = 0
    now_epoch: float | None = None
    audit_emit_available: bool = True


@dataclass
class CryptoExitDecision:
    decision: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_allow(self) -> bool:
        return self.decision in (ALLOW_LIMIT, ALLOW_MARKET)

    @property
    def is_block(self) -> bool:
        return self.decision.startswith("CRYPTO_EXIT_BLOCKED")


def _is_crypto_symbol(symbol: str) -> bool:
    s = (symbol or "").upper()
    return s.endswith("USD") or s.endswith("/USD")


def _round_qty_down_safe(qty: float, decimals: int = 9) -> float:
    """Wrapper around shared.crypto_precision.round_qty_down with safe
    fallback. NEVER rounds up."""
    try:
        try:
            from crypto_precision import round_qty_down
        except ImportError:
            from shared.crypto_precision import round_qty_down
        return round_qty_down(qty, decimals)
    except Exception:
        # Manual floor-rounding fallback.
        if qty <= 0:
            return 0.0
        mult = 10 ** decimals
        return int(qty * mult) / mult


def evaluate_crypto_exit(inputs: CryptoExitInputs) -> CryptoExitDecision:
    """Return a deterministic exit decision.

    Pure function. No I/O. No order submission.
    """
    if not _is_crypto_symbol(inputs.symbol):
        return CryptoExitDecision(
            decision=BLOCK_INVALID_REASON,
            reason=f"non-crypto symbol: {inputs.symbol}",
            details={"symbol": inputs.symbol},
        )
    if inputs.proposed_qty <= 0:
        return CryptoExitDecision(
            decision=BLOCK_INVALID_REASON,
            reason="non-positive qty",
            details={"qty": inputs.proposed_qty},
        )
    # 1) Reason required.
    if not inputs.reason:
        return CryptoExitDecision(
            decision=BLOCK_NO_REASON,
            reason="every crypto exit must carry a structured reason",
            details={"allowed_reasons": sorted(ALLOWED_EXIT_REASONS)},
        )
    if inputs.reason not in ALLOWED_EXIT_REASONS:
        return CryptoExitDecision(
            decision=BLOCK_INVALID_REASON,
            reason=f"unrecognized exit reason: {inputs.reason!r}",
            details={"allowed_reasons": sorted(ALLOWED_EXIT_REASONS)},
        )

    # 2) Audit emission must be available.
    if not inputs.audit_emit_available:
        return CryptoExitDecision(
            decision=BLOCK_AUDIT_PATH_UNAVAILABLE,
            reason="audit emission unavailable — exit refused fail-closed",
            details={},
        )

    # 3) Dust exits require explicit operator decision.
    is_dust = (inputs.current_position_notional_usd
               < DUST_NOTIONAL_USD)
    if is_dust and not inputs.operator_dust_close_approved:
        return CryptoExitDecision(
            decision=BLOCK_DUST_OPERATOR_DECISION_REQUIRED,
            reason=(f"{inputs.symbol} notional "
                     f"${inputs.current_position_notional_usd:.4f} < "
                     f"${DUST_NOTIONAL_USD:.2f} (dust); operator must "
                     f"approve close"),
            details={"notional_usd":
                       inputs.current_position_notional_usd},
        )

    # 4) Quantity must NOT be rounded up.
    rounded = _round_qty_down_safe(inputs.proposed_qty)
    if rounded > inputs.proposed_qty + 1e-12:
        return CryptoExitDecision(
            decision=BLOCK_QTY_ROUND_UP_REJECTED,
            reason="qty would be rounded UP — refusing",
            details={"proposed_qty": inputs.proposed_qty,
                      "rounded": rounded},
        )

    # 5) Precision-race guard: if we've recently failed on precision
    # multiple times in a row, refuse further attempts until window passes.
    if (inputs.precision_failures_recent
            >= PRECISION_RACE_MAX_RETRIES):
        return CryptoExitDecision(
            decision=BLOCK_PRECISION_RACE_GUARD,
            reason=(f"{inputs.precision_failures_recent} recent "
                     f"precision failures (>"
                     f"{PRECISION_RACE_MAX_RETRIES-1}); cooldown active"),
            details={"failures": inputs.precision_failures_recent},
        )

    # 6) Dedupe identical close attempts within the dedup window.
    now = inputs.now_epoch if inputs.now_epoch is not None else time.time()
    recent_in_window = [
        t for t in inputs.recent_close_attempts_epoch
        if (now - t) <= DEDUP_WINDOW_SECONDS
    ]
    if recent_in_window:
        return CryptoExitDecision(
            decision=BLOCK_DEDUPED_REPEATED_CLOSE,
            reason=(f"{len(recent_in_window)} recent close attempts "
                     f"in last {DEDUP_WINDOW_SECONDS // 60} min — dedupe"),
            details={"recent_attempts": len(recent_in_window)},
        )

    # 7) Market exits require risk-side reason.
    is_market = (inputs.proposed_order_type or "").lower() == "market"
    if is_market and inputs.reason not in MARKET_EXIT_ALLOWED_REASONS:
        return CryptoExitDecision(
            decision=BLOCK_MARKET_EXIT_REQUIRES_RISK_REASON,
            reason=(f"market exit requires risk-side reason "
                     f"(emergency/stop/risk_reduction/operator); got "
                     f"{inputs.reason}"),
            details={"required_set":
                       sorted(MARKET_EXIT_ALLOWED_REASONS)},
        )

    # All checks passed.
    if is_market:
        return CryptoExitDecision(
            decision=ALLOW_MARKET,
            reason=f"market exit allowed: {inputs.reason}",
            details={"qty_floored": rounded},
        )
    return CryptoExitDecision(
        decision=ALLOW_LIMIT,
        reason=f"limit exit allowed: {inputs.reason}",
        details={"qty_floored": rounded,
                  "limit_price": inputs.proposed_limit_price},
    )


def policy_summary() -> dict[str, Any]:
    return {
        "version": "v3.25.0",
        "allowed_exit_reasons": sorted(ALLOWED_EXIT_REASONS),
        "market_exit_allowed_reasons": sorted(MARKET_EXIT_ALLOWED_REASONS),
        "dust_notional_usd": DUST_NOTIONAL_USD,
        "dedup_window_seconds": DEDUP_WINDOW_SECONDS,
        "precision_race_max_retries": PRECISION_RACE_MAX_RETRIES,
        "decisions": sorted(ALL_EXIT_DECISIONS),
        "status_tokens": sorted(ALL_STATUS_TOKENS),
        "invariants": {
            "NEVER_PLACES_ORDERS": NEVER_PLACES_ORDERS,
            "NEVER_AUTO_CLOSES_DUST_WITHOUT_OPERATOR_DECISION":
                NEVER_AUTO_CLOSES_DUST_WITHOUT_OPERATOR_DECISION,
            "NEVER_ROUNDS_UP": NEVER_ROUNDS_UP,
            "NEVER_ALLOWS_MARKET_EXIT_WITHOUT_REASON":
                NEVER_ALLOWS_MARKET_EXIT_WITHOUT_REASON,
        },
    }


__all__ = [
    # Reasons
    "EXIT_REASON_EMERGENCY", "EXIT_REASON_STOP_LIKE",
    "EXIT_REASON_TIME_EXPIRY", "EXIT_REASON_RISK_REDUCTION",
    "EXIT_REASON_OPERATOR_REQUESTED", "EXIT_REASON_TAKE_PROFIT",
    "EXIT_REASON_REBALANCE", "EXIT_REASON_REGIME_FLIP",
    "ALLOWED_EXIT_REASONS", "MARKET_EXIT_ALLOWED_REASONS",
    # Decisions
    "ALLOW_LIMIT", "ALLOW_MARKET",
    "BLOCK_NO_REASON", "BLOCK_INVALID_REASON",
    "BLOCK_MARKET_EXIT_REQUIRES_RISK_REASON",
    "BLOCK_DUST_OPERATOR_DECISION_REQUIRED",
    "BLOCK_DEDUPED_REPEATED_CLOSE",
    "BLOCK_AUDIT_PATH_UNAVAILABLE",
    "BLOCK_QTY_ROUND_UP_REJECTED",
    "BLOCK_PRECISION_RACE_GUARD",
    "ALL_EXIT_DECISIONS",
    # Status tokens
    "CRYPTO_EXIT_AUDIT_REQUIRED",
    "CRYPTO_EXIT_REASON_REQUIRED",
    "CRYPTO_DUST_EXIT_OPERATOR_DECISION",
    "CRYPTO_MARKET_EXIT_REQUIRES_RISK_REASON",
    "CRYPTO_PRECISION_CLOSE_GUARD_ACTIVE",
    "ALL_STATUS_TOKENS",
    # Invariants
    "NEVER_PLACES_ORDERS",
    "NEVER_AUTO_CLOSES_DUST_WITHOUT_OPERATOR_DECISION",
    "NEVER_ROUNDS_UP",
    "NEVER_ALLOWS_MARKET_EXIT_WITHOUT_REASON",
    # Data classes
    "CryptoExitInputs", "CryptoExitDecision",
    # API
    "evaluate_crypto_exit", "policy_summary",
]
