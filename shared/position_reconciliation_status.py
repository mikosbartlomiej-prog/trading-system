"""v3.23.0 (2026-06-08) — Formal position reconciliation status model.

After 2026-06-08 operator dashboard verification revealed that the
previous local-state-only inference was wrong on multiple counts:

- 7 of 8 equity positions had safe_close events but local state still
  showed them as ARMED
- AMD had ZERO safe_close events but was NOT on the dashboard
  (broker-side close without local audit attribution)
- AVAXUSD/SOLUSD/LTCUSD local CLOSED but dashboard OPEN with dust
- ETHUSD local TIME_EXPIRED but dashboard OPEN at +$523

This module is the formal source-of-truth classifier. It is read-only
and never closes/modifies positions. Callers feed it (local_state,
broker_evidence, audit_close_events) and get back a single
PositionReconciliationStatus enum value + rationale.

CONTRACT
--------
- READ-ONLY. Never places trades. Never closes positions.
- Never resets equity baseline.
- Never lowers risk thresholds.
- Treats local state as ONE input, not the source of truth.
- When broker/dashboard data conflict with local state, flags conflict
  explicitly — never silently overrides.
- Fail-soft: malformed input never raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# ─── Closed enum of statuses ─────────────────────────────────────────────────

VERIFIED_OPEN                                = "VERIFIED_OPEN"
VERIFIED_CLOSED                              = "VERIFIED_CLOSED"
STALE_LOCAL_OPEN                             = "STALE_LOCAL_OPEN"
STALE_LOCAL_CLOSED                           = "STALE_LOCAL_CLOSED"
BROKER_SIDE_CLOSED                           = "BROKER_SIDE_CLOSED"
ORPHAN_BROKER_POSITION                       = "ORPHAN_BROKER_POSITION"
LOCAL_BROKER_CONFLICT                        = "LOCAL_BROKER_CONFLICT"
DASHBOARD_VERIFIED_POSITION                  = "DASHBOARD_VERIFIED_POSITION"
DASHBOARD_VERIFIED_NOT_OPEN                  = "DASHBOARD_VERIFIED_NOT_OPEN"
API_UNAVAILABLE_OPERATOR_DASHBOARD_PROVIDED  = "API_UNAVAILABLE_OPERATOR_DASHBOARD_PROVIDED"
UNKNOWN_REQUIRES_API_VERIFICATION            = "UNKNOWN_REQUIRES_API_VERIFICATION"

# Extended variants for specific scenarios surfaced by 2026-06-07/08 incident.
BROKER_SIDE_CLOSED_OR_DASHBOARD_VERIFIED_NOT_OPEN = (
    "BROKER_SIDE_CLOSED_OR_DASHBOARD_VERIFIED_NOT_OPEN"
)
STALE_LOCAL_TIME_EXPIRED_BUT_DASHBOARD_OPEN  = "STALE_LOCAL_TIME_EXPIRED_BUT_DASHBOARD_OPEN"
STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN        = "STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN"
STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN_DUST   = "STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN_DUST"
VERIFIED_CLOSED_FROM_AUDIT_SAFE_CLOSE        = "VERIFIED_CLOSED_FROM_AUDIT_SAFE_CLOSE"

# v3.23.1 (2026-06-08) — refined AMD-style closes after operator
# provided manual Order History extracts from the dashboard.
DASHBOARD_ORDER_HISTORY_VERIFIED_CLOSED       = "DASHBOARD_ORDER_HISTORY_VERIFIED_CLOSED"
EXTERNAL_API_MARKET_CLOSE_VERIFIED_FROM_DASHBOARD = (
    "EXTERNAL_API_MARKET_CLOSE_VERIFIED_FROM_DASHBOARD"
)
# Secondary issue marker (not a reconciliation status itself but
# emitted alongside when applicable). The actual market sell_to_close
# was placed via Alpaca access_key but no safe_close audit row exists.
MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT = (
    "MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT"
)

ALL_STATUSES: frozenset[str] = frozenset({
    VERIFIED_OPEN,
    VERIFIED_CLOSED,
    STALE_LOCAL_OPEN,
    STALE_LOCAL_CLOSED,
    BROKER_SIDE_CLOSED,
    ORPHAN_BROKER_POSITION,
    LOCAL_BROKER_CONFLICT,
    DASHBOARD_VERIFIED_POSITION,
    DASHBOARD_VERIFIED_NOT_OPEN,
    API_UNAVAILABLE_OPERATOR_DASHBOARD_PROVIDED,
    UNKNOWN_REQUIRES_API_VERIFICATION,
    BROKER_SIDE_CLOSED_OR_DASHBOARD_VERIFIED_NOT_OPEN,
    STALE_LOCAL_TIME_EXPIRED_BUT_DASHBOARD_OPEN,
    STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN,
    STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN_DUST,
    VERIFIED_CLOSED_FROM_AUDIT_SAFE_CLOSE,
    DASHBOARD_ORDER_HISTORY_VERIFIED_CLOSED,
    EXTERNAL_API_MARKET_CLOSE_VERIFIED_FROM_DASHBOARD,
})

# Module invariants — test-asserted.
NEVER_CLOSES_POSITIONS  = True
NEVER_MODIFIES_POSITIONS = True
NEVER_PLACES_ORDERS      = True
NEVER_LOWERS_RISK        = True


@dataclass
class ReconciliationResult:
    symbol: str
    status: str
    rationale: str
    local_state: str | None = None
    broker_evidence: str | None = None
    has_audit_safe_close: bool = False
    dust: bool = False
    requires_api_followup: bool = False

    def to_dict(self) -> dict:
        return {
            "symbol":                  self.symbol,
            "status":                  self.status,
            "rationale":               self.rationale,
            "local_state":             self.local_state,
            "broker_evidence":         self.broker_evidence,
            "has_audit_safe_close":    self.has_audit_safe_close,
            "dust":                    self.dust,
            "requires_api_followup":   self.requires_api_followup,
        }


# ─── Inputs ──────────────────────────────────────────────────────────────────

# local_state: one of "open", "closed", "time_expired", "armed", "intake",
#              "trailing", "invalidating", None
# broker_evidence: one of "dashboard_open", "dashboard_not_open",
#                   "api_open", "api_not_open", "unknown"
# has_audit_safe_close: bool — were there safe_close events for this symbol?
# dust: bool — is the position dust (very small qty)?


def _norm_local(s: str | None) -> str:
    if s is None:
        return "unknown"
    s = str(s).strip().lower()
    if s in ("armed", "intake", "trailing", "invalidating"):
        return "open"
    if s == "time_expired":
        return "time_expired"
    if s in ("closed", "settled"):
        return "closed"
    if s == "open":
        return "open"
    return "unknown"


def _norm_broker(s: str | None) -> str:
    if s is None:
        return "unknown"
    return str(s).strip().lower()


def classify(
    symbol: str,
    *,
    local_state: str | None,
    broker_evidence: str | None,
    has_audit_safe_close: bool = False,
    dust: bool = False,
    manual_order_history_evidence: bool = False,
    manual_order_history_close_type: str | None = None,
    submitter_source: str | None = None,
) -> ReconciliationResult:
    """Return a deterministic reconciliation status.

    See docstring of module for input semantics.
    Pure function — no I/O.

    v3.23.1: when ``manual_order_history_evidence`` is True (operator
    has provided a sanitized order-history row from the Alpaca paper
    dashboard with explicit close type and submitter source), the
    classifier returns a more precise status:

    - DASHBOARD_ORDER_HISTORY_VERIFIED_CLOSED (any close type, any
      submitter)
    - EXTERNAL_API_MARKET_CLOSE_VERIFIED_FROM_DASHBOARD (market sell
      via ``access_key`` submitter — signals an audit-gap finding
      that the caller should attach separately)
    """
    local = _norm_local(local_state)
    broker = _norm_broker(broker_evidence)

    # 0. (v3.23.1) Manual order-history evidence takes precedence over
    #    the loose "dashboard says not_open" inference because we now
    #    have a concrete close order id + price + timestamp.
    if manual_order_history_evidence:
        cls = (manual_order_history_close_type or "").strip().lower()
        sub = (submitter_source or "").strip().lower()
        if cls == "market" and sub == "access_key":
            return ReconciliationResult(
                symbol=symbol,
                status=EXTERNAL_API_MARKET_CLOSE_VERIFIED_FROM_DASHBOARD,
                rationale=(
                    "Operator-provided Order History row shows the close was a "
                    "market sell_to_close placed via Alpaca access_key submitter. "
                    "Position is verified closed, but the absence of a local "
                    "safe_close audit row indicates an external script bypassed "
                    "shared/alpaca_orders.py::safe_close(). "
                    "See: MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT."
                ),
                local_state=local_state, broker_evidence=broker_evidence,
                has_audit_safe_close=has_audit_safe_close, dust=dust,
                requires_api_followup=False,
            )
        return ReconciliationResult(
            symbol=symbol,
            status=DASHBOARD_ORDER_HISTORY_VERIFIED_CLOSED,
            rationale=(
                "Operator-provided Order History row verifies the position is "
                "closed. Close price and timestamp are known."
            ),
            local_state=local_state, broker_evidence=broker_evidence,
            has_audit_safe_close=has_audit_safe_close, dust=dust,
            requires_api_followup=False,
        )

    # 1. Dashboard NOT_OPEN + has safe_close → audit-verified closed.
    if broker in ("dashboard_not_open", "api_not_open") and has_audit_safe_close:
        return ReconciliationResult(
            symbol=symbol,
            status=VERIFIED_CLOSED_FROM_AUDIT_SAFE_CLOSE,
            rationale="Broker/dashboard confirms closed AND audit JSONL has a safe_close event.",
            local_state=local_state, broker_evidence=broker_evidence,
            has_audit_safe_close=True, dust=dust,
        )

    # 2. Dashboard NOT_OPEN + NO safe_close → broker-side close inferred
    #    (e.g. AMD anomaly: bracket SL/TP child fired at broker without
    #    going through local safe_close, OR position was always invalid).
    if broker in ("dashboard_not_open", "api_not_open") and not has_audit_safe_close:
        return ReconciliationResult(
            symbol=symbol,
            status=BROKER_SIDE_CLOSED_OR_DASHBOARD_VERIFIED_NOT_OPEN,
            rationale=(
                "Broker/dashboard confirms NOT open but no local safe_close in audit. "
                "Likely broker-side bracket SL/TP child fired without local attribution. "
                "Requires Alpaca order history to confirm close price."
            ),
            local_state=local_state, broker_evidence=broker_evidence,
            has_audit_safe_close=False, dust=dust,
            requires_api_followup=True,
        )

    # 3. Local TIME_EXPIRED + dashboard OPEN → stale exit loop scenario
    #    (ETHUSD on 2026-06-08).
    if local == "time_expired" and broker in ("dashboard_open", "api_open"):
        return ReconciliationResult(
            symbol=symbol,
            status=STALE_LOCAL_TIME_EXPIRED_BUT_DASHBOARD_OPEN,
            rationale=(
                "Local position-manager flagged TIME_EXPIRED and exit-monitor is "
                "attempting close, but broker/dashboard shows position still open. "
                "Likely Alpaca precision rounding rejection — operator review recommended."
            ),
            local_state=local_state, broker_evidence=broker_evidence,
            has_audit_safe_close=has_audit_safe_close, dust=dust,
        )

    # 4. Local CLOSED + dashboard OPEN → stale local CLOSED.
    if local == "closed" and broker in ("dashboard_open", "api_open"):
        if dust:
            return ReconciliationResult(
                symbol=symbol,
                status=STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN_DUST,
                rationale=(
                    "Local position-manager flagged CLOSED but broker/dashboard "
                    "shows dust position open. Likely partial close residual."
                ),
                local_state=local_state, broker_evidence=broker_evidence,
                has_audit_safe_close=has_audit_safe_close, dust=True,
            )
        return ReconciliationResult(
            symbol=symbol,
            status=STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN,
            rationale=(
                "Local position-manager flagged CLOSED but broker/dashboard "
                "shows open. Local state widely stale — operator review recommended."
            ),
            local_state=local_state, broker_evidence=broker_evidence,
            has_audit_safe_close=has_audit_safe_close, dust=False,
        )

    # 5. Local OPEN + dashboard OPEN → verified open.
    if local == "open" and broker in ("dashboard_open", "api_open"):
        # Distinguish API-verified vs operator-dashboard-verified.
        if broker == "dashboard_open":
            return ReconciliationResult(
                symbol=symbol,
                status=DASHBOARD_VERIFIED_POSITION,
                rationale="Local OPEN matches operator-provided dashboard OPEN.",
                local_state=local_state, broker_evidence=broker_evidence,
                has_audit_safe_close=has_audit_safe_close, dust=dust,
            )
        return ReconciliationResult(
            symbol=symbol,
            status=VERIFIED_OPEN,
            rationale="Local OPEN matches broker API OPEN.",
            local_state=local_state, broker_evidence=broker_evidence,
            has_audit_safe_close=has_audit_safe_close, dust=dust,
        )

    # 6. Local CLOSED + dashboard NOT_OPEN → verified closed.
    if local == "closed" and broker in ("dashboard_not_open", "api_not_open"):
        return ReconciliationResult(
            symbol=symbol,
            status=VERIFIED_CLOSED,
            rationale="Both local and broker/dashboard agree on CLOSED.",
            local_state=local_state, broker_evidence=broker_evidence,
            has_audit_safe_close=has_audit_safe_close, dust=dust,
        )

    # 7. Local OPEN + broker unknown → stale local open (suspect).
    if local == "open" and broker == "unknown":
        return ReconciliationResult(
            symbol=symbol,
            status=STALE_LOCAL_OPEN,
            rationale=(
                "Local state shows OPEN but no broker/dashboard evidence. "
                "Cannot verify without API call."
            ),
            local_state=local_state, broker_evidence=broker_evidence,
            has_audit_safe_close=has_audit_safe_close, dust=dust,
            requires_api_followup=True,
        )

    # 8. Local CLOSED + broker unknown → stale local closed (suspect).
    if local == "closed" and broker == "unknown":
        return ReconciliationResult(
            symbol=symbol,
            status=STALE_LOCAL_CLOSED,
            rationale=(
                "Local state shows CLOSED but no broker/dashboard evidence. "
                "Cannot verify without API call."
            ),
            local_state=local_state, broker_evidence=broker_evidence,
            has_audit_safe_close=has_audit_safe_close, dust=dust,
            requires_api_followup=True,
        )

    # 9. Anything else → unknown.
    return ReconciliationResult(
        symbol=symbol,
        status=UNKNOWN_REQUIRES_API_VERIFICATION,
        rationale=(
            f"Insufficient data to classify: "
            f"local_state={local_state!r}, broker_evidence={broker_evidence!r}, "
            f"has_audit_safe_close={has_audit_safe_close}."
        ),
        local_state=local_state, broker_evidence=broker_evidence,
        has_audit_safe_close=has_audit_safe_close, dust=dust,
        requires_api_followup=True,
    )


def classify_batch(symbols_data: Mapping[str, dict]) -> dict[str, ReconciliationResult]:
    """Classify a batch of symbols. See classify() for the per-symbol contract."""
    out: dict[str, ReconciliationResult] = {}
    for sym, data in symbols_data.items():
        if not isinstance(data, dict):
            continue
        try:
            out[sym] = classify(
                sym,
                local_state=data.get("local_state"),
                broker_evidence=data.get("broker_evidence"),
                has_audit_safe_close=bool(data.get("has_audit_safe_close")),
                dust=bool(data.get("dust", False)),
            )
        except Exception as e:
            # Fail-soft: never raise.
            out[sym] = ReconciliationResult(
                symbol=sym,
                status=UNKNOWN_REQUIRES_API_VERIFICATION,
                rationale=f"classify() raised {type(e).__name__}: {e!s}",
            )
    return out


__all__ = [
    # Statuses
    "VERIFIED_OPEN", "VERIFIED_CLOSED",
    "STALE_LOCAL_OPEN", "STALE_LOCAL_CLOSED",
    "BROKER_SIDE_CLOSED", "ORPHAN_BROKER_POSITION", "LOCAL_BROKER_CONFLICT",
    "DASHBOARD_VERIFIED_POSITION", "DASHBOARD_VERIFIED_NOT_OPEN",
    "API_UNAVAILABLE_OPERATOR_DASHBOARD_PROVIDED",
    "UNKNOWN_REQUIRES_API_VERIFICATION",
    "BROKER_SIDE_CLOSED_OR_DASHBOARD_VERIFIED_NOT_OPEN",
    "STALE_LOCAL_TIME_EXPIRED_BUT_DASHBOARD_OPEN",
    "STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN",
    "STALE_LOCAL_CLOSED_BUT_DASHBOARD_OPEN_DUST",
    "VERIFIED_CLOSED_FROM_AUDIT_SAFE_CLOSE",
    "DASHBOARD_ORDER_HISTORY_VERIFIED_CLOSED",
    "EXTERNAL_API_MARKET_CLOSE_VERIFIED_FROM_DASHBOARD",
    "MARKET_SELL_CLOSE_VIA_ACCESS_KEY_WITHOUT_SAFE_CLOSE_AUDIT",
    "ALL_STATUSES",
    # Invariants
    "NEVER_CLOSES_POSITIONS", "NEVER_MODIFIES_POSITIONS",
    "NEVER_PLACES_ORDERS", "NEVER_LOWERS_RISK",
    # API
    "ReconciliationResult", "classify", "classify_batch",
]
