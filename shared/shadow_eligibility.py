"""v3.24 ETAP 7 — Shadow eligibility evaluator (NO-BROKER, NO-NETWORK).

Decides whether a single opportunity_ledger row qualifies for shadow
simulation. This module is the v3.24 successor to the v3.23 ad-hoc
checks scattered across the shadow code paths. It is the single
choke-point: ``shared/shadow_simulator.maybe_simulate_from_row``
delegates to :func:`evaluate_shadow_eligibility` before constructing
ANY shadow fill, so a row that does not pass here CANNOT become a
ShadowFill.

HARD SAFETY
-----------
- NEVER imports ``shared.alpaca_orders`` or ``alpaca_orders``.
- NEVER imports any broker SDK.
- NEVER imports ``requests``, ``urllib``, or other network libraries.
- NEVER calls a broker / submits an order. This module is pure
  arithmetic over a single ``dict`` row.
- NEVER mutates the row it inspects.
- Per the master safety contract, an ELIGIBLE verdict does NOT, by
  itself, authorise a trade. It only authorises a hypothetical
  ShadowFill record. EDGE_GATE_ENABLED, ALLOW_BROKER_PAPER, and
  every live-trading flag remain false at all times.

CONTRACT
--------
- One public dataclass: :class:`ShadowEligibilityResult`.
- One public enum: :class:`ShadowEligibilityDecision`.
- One public function: :func:`evaluate_shadow_eligibility`.
- Eligibility threshold mirrors v3.24 spec:
  ``confidence_score >= 0.50 AND
   risk_decision in {APPROVE, DETECTED} AND
   canary verdict in {CANARY_PREFLIGHT_DRY_RUN_OK,
                      CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED}``.
- Order of checks is deterministic and matches the decision enum so a
  reviewer can trace any verdict from the row schema alone.

The phrase "diagnostic_token" in this module refers to the
``raw_signal.diagnostic_token`` slot. A non-empty token that names a
known failure mode produces ``NOT_ELIGIBLE_DATA_FAILURE``; absence of
a token has no effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


# ─── Decision enum ──────────────────────────────────────────────────


class ShadowEligibilityDecision(str, Enum):
    """One enum value per eligibility outcome.

    Order of members matches the order of checks performed by
    :func:`evaluate_shadow_eligibility`. ``ELIGIBLE`` is the only
    value that authorises a ShadowFill downstream.
    """

    ELIGIBLE                           = "ELIGIBLE"
    NOT_ELIGIBLE_NO_CONFIDENCE         = "NOT_ELIGIBLE_NO_CONFIDENCE"
    NOT_ELIGIBLE_CONFIDENCE_LOW        = "NOT_ELIGIBLE_CONFIDENCE_LOW"
    NOT_ELIGIBLE_RISK_BLOCK            = "NOT_ELIGIBLE_RISK_BLOCK"
    NOT_ELIGIBLE_NO_SIGNAL             = "NOT_ELIGIBLE_NO_SIGNAL"
    NOT_ELIGIBLE_DRAWDOWN_GUARD        = "NOT_ELIGIBLE_DRAWDOWN_GUARD"
    NOT_ELIGIBLE_DATA_FAILURE          = "NOT_ELIGIBLE_DATA_FAILURE"
    NOT_ELIGIBLE_CANARY_DEFERRED       = "NOT_ELIGIBLE_CANARY_DEFERRED"
    NOT_ELIGIBLE_OBSERVE_ONLY          = "NOT_ELIGIBLE_OBSERVE_ONLY"
    NOT_ELIGIBLE_UNKNOWN               = "NOT_ELIGIBLE_UNKNOWN"


# ─── Result dataclass ───────────────────────────────────────────────


@dataclass(frozen=True)
class ShadowEligibilityResult:
    """One immutable verdict per row.

    ``eligible`` is a redundant boolean kept on the object for
    callers that prefer truth-testing over enum comparison. It is
    derived from ``decision`` and is guaranteed consistent.
    """

    decision:         ShadowEligibilityDecision
    reason:           str
    confidence_score: float | None
    risk_decision:    str
    canary_verdict:   str | None
    eligible:         bool = field(default=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision":         self.decision.value,
            "reason":           self.reason,
            "confidence_score": self.confidence_score,
            "risk_decision":    self.risk_decision,
            "canary_verdict":   self.canary_verdict,
            "eligible":         self.eligible,
        }


# ─── Constants ──────────────────────────────────────────────────────


#: Minimum confidence score for ELIGIBLE.
CONFIDENCE_FLOOR: float = 0.50

#: Risk decisions that are acceptable for shadow simulation. APPROVE
#: is the canonical entry-capable verdict; DETECTED is the v3.24
#: "signal observed but not yet APPROVE-stamped" verdict that we
#: still want to shadow.
ALLOWED_RISK_DECISIONS: frozenset[str] = frozenset({"APPROVE", "DETECTED"})

#: Risk decisions that mean "hard block".
BLOCK_RISK_DECISIONS: frozenset[str] = frozenset({
    "REJECT", "BLOCK", "DEFER",
})

#: Risk decisions that mean "no actionable signal was produced".
NO_SIGNAL_RISK_DECISIONS: frozenset[str] = frozenset({
    "NO_SIGNAL", "OBSERVE_ONLY_NO_SIGNAL",
})

#: Substrings that indicate a drawdown-guard halt anywhere in the
#: ``risk_decision`` string.
DRAWDOWN_GUARD_SUBSTRINGS: tuple[str, ...] = (
    "HALTED_BY_DRAWDOWN", "DRAWDOWN_GUARD", "DRAWDOWN_HALT",
)

#: Canary verdicts that are acceptable for shadow simulation. Both
#: are preflight-only — neither implies an order was placed.
ALLOWED_CANARY_VERDICTS: frozenset[str] = frozenset({
    "CANARY_PREFLIGHT_DRY_RUN_OK",
    "CANARY_READY_TO_EXECUTE_BUT_ORDER_PLACEMENT_DEFERRED",
})

#: Diagnostic tokens that indicate a data failure (a market-data
#: provider error, a stale-bars condition, an auth failure, etc.).
#: A row carrying any of these in ``raw_signal.diagnostic_token``
#: gets ``NOT_ELIGIBLE_DATA_FAILURE``. The set is intentionally
#: small and conservative; unknown tokens DO NOT trigger a data
#: failure rejection because we cannot tell which side they fall
#: on.
DATA_FAILURE_DIAGNOSTIC_TOKENS: frozenset[str] = frozenset({
    "PROVIDER_ERROR",
    "AUTH_FAILED",
    "MARKET_DATA_STALE",
    "MARKET_CLOSED_OR_NO_BARS",
    "INSUFFICIENT_BARS_FOR_SIGNAL",
    "FETCH_FAILED",
    "API_QUOTA_EXCEEDED",
    "INTERNAL_ERROR",
})


# ─── Internal helpers ───────────────────────────────────────────────


def _get_raw(row: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = row.get("raw_signal")
    if isinstance(raw, Mapping):
        return raw
    return {}


def _read_observe_only(row: Mapping[str, Any], raw: Mapping[str, Any]) -> bool:
    # The observe-only flag may live on the row or on raw_signal. Either
    # location wins; both are acceptable.
    for src in (row, raw):
        v = src.get("observe_only")
        if isinstance(v, bool) and v:
            return True
        if isinstance(v, str) and v.strip().lower() in ("true", "1", "yes"):
            return True
    # v3.24 also exposes confidence_status=OBSERVE_ONLY_SKIP. Mirror
    # that here so observation rows never sneak into shadow.
    cs = raw.get("confidence_status")
    if isinstance(cs, str) and cs.strip().upper() == "OBSERVE_ONLY_SKIP":
        return True
    return False


def _read_confidence_score(row: Mapping[str, Any]) -> float | None:
    v = row.get("confidence_score")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _read_risk_decision(row: Mapping[str, Any]) -> str:
    rd = row.get("risk_decision")
    if isinstance(rd, str):
        return rd.strip().upper()
    return ""


def _read_diagnostic_token(raw: Mapping[str, Any]) -> str | None:
    tok = raw.get("diagnostic_token")
    if isinstance(tok, str) and tok.strip():
        return tok.strip().upper()
    return None


def _read_canary_verdict(row: Mapping[str, Any],
                         raw: Mapping[str, Any]) -> str | None:
    for src in (row, raw):
        v = src.get("canary_preflight_verdict") or src.get("canary_verdict")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _result(decision: ShadowEligibilityDecision,
            reason: str,
            *,
            confidence_score: float | None,
            risk_decision: str,
            canary_verdict: str | None,
            ) -> ShadowEligibilityResult:
    return ShadowEligibilityResult(
        decision=decision,
        reason=reason,
        confidence_score=confidence_score,
        risk_decision=risk_decision,
        canary_verdict=canary_verdict,
        eligible=(decision == ShadowEligibilityDecision.ELIGIBLE),
    )


# ─── Public API ─────────────────────────────────────────────────────


def evaluate_shadow_eligibility(
    row: Mapping[str, Any] | None,
) -> ShadowEligibilityResult:
    """Decide whether a single opportunity_ledger row may proceed to a
    ShadowFill.

    Pure function. NEVER raises (fail-soft on malformed input). NEVER
    mutates ``row``. NEVER calls a broker / network.

    Order of checks (matches the enum order):

    1. ``observe_only`` flag set → ``NOT_ELIGIBLE_OBSERVE_ONLY``
    2. ``confidence_score`` is ``None`` → ``NOT_ELIGIBLE_NO_CONFIDENCE``
    3. ``confidence_score < 0.50`` → ``NOT_ELIGIBLE_CONFIDENCE_LOW``
    4. ``risk_decision`` indicates hard block (REJECT, BLOCK, DEFER)
       → ``NOT_ELIGIBLE_RISK_BLOCK``
    5. ``risk_decision == NO_SIGNAL`` → ``NOT_ELIGIBLE_NO_SIGNAL``
    6. ``risk_decision`` contains drawdown-guard substring →
       ``NOT_ELIGIBLE_DRAWDOWN_GUARD``
    7. ``raw_signal.diagnostic_token`` ∈ fail set →
       ``NOT_ELIGIBLE_DATA_FAILURE``
    8. canary verdict missing or not acceptable →
       ``NOT_ELIGIBLE_CANARY_DEFERRED``
    9. ``risk_decision`` not in {APPROVE, DETECTED} →
       ``NOT_ELIGIBLE_UNKNOWN``
    10. otherwise → ``ELIGIBLE``
    """
    # Defensive: malformed input never raises.
    if not isinstance(row, Mapping):
        return _result(
            ShadowEligibilityDecision.NOT_ELIGIBLE_UNKNOWN,
            "row is not a mapping",
            confidence_score=None,
            risk_decision="",
            canary_verdict=None,
        )

    raw = _get_raw(row)
    confidence_score = _read_confidence_score(row)
    risk_decision    = _read_risk_decision(row)
    canary_verdict   = _read_canary_verdict(row, raw)

    # 1. observe_only — diagnostic rows must never produce a ShadowFill.
    if _read_observe_only(row, raw):
        return _result(
            ShadowEligibilityDecision.NOT_ELIGIBLE_OBSERVE_ONLY,
            "row is observe_only; diagnostic only, never shadowed",
            confidence_score=confidence_score,
            risk_decision=risk_decision,
            canary_verdict=canary_verdict,
        )

    # 2. confidence missing — v3.24 entry-capable rows MUST carry a
    # numeric score. Absence is a hard miss.
    if confidence_score is None:
        return _result(
            ShadowEligibilityDecision.NOT_ELIGIBLE_NO_CONFIDENCE,
            "confidence_score is null",
            confidence_score=None,
            risk_decision=risk_decision,
            canary_verdict=canary_verdict,
        )

    # 3. confidence below floor.
    if confidence_score < CONFIDENCE_FLOOR:
        return _result(
            ShadowEligibilityDecision.NOT_ELIGIBLE_CONFIDENCE_LOW,
            f"confidence_score={confidence_score:.3f} < {CONFIDENCE_FLOOR}",
            confidence_score=confidence_score,
            risk_decision=risk_decision,
            canary_verdict=canary_verdict,
        )

    # 4. risk hard-block.
    if risk_decision in BLOCK_RISK_DECISIONS:
        return _result(
            ShadowEligibilityDecision.NOT_ELIGIBLE_RISK_BLOCK,
            f"risk_decision={risk_decision!r} is a hard block",
            confidence_score=confidence_score,
            risk_decision=risk_decision,
            canary_verdict=canary_verdict,
        )

    # 5. no-signal.
    if risk_decision in NO_SIGNAL_RISK_DECISIONS:
        return _result(
            ShadowEligibilityDecision.NOT_ELIGIBLE_NO_SIGNAL,
            f"risk_decision={risk_decision!r} carries no signal",
            confidence_score=confidence_score,
            risk_decision=risk_decision,
            canary_verdict=canary_verdict,
        )

    # 6. drawdown-guard halt.
    for s in DRAWDOWN_GUARD_SUBSTRINGS:
        if s in risk_decision:
            return _result(
                ShadowEligibilityDecision.NOT_ELIGIBLE_DRAWDOWN_GUARD,
                f"risk_decision={risk_decision!r} is a drawdown-guard halt",
                confidence_score=confidence_score,
                risk_decision=risk_decision,
                canary_verdict=canary_verdict,
            )

    # 7. diagnostic token indicates upstream data failure.
    tok = _read_diagnostic_token(raw)
    if tok is not None and tok in DATA_FAILURE_DIAGNOSTIC_TOKENS:
        return _result(
            ShadowEligibilityDecision.NOT_ELIGIBLE_DATA_FAILURE,
            f"diagnostic_token={tok!r} indicates upstream data failure",
            confidence_score=confidence_score,
            risk_decision=risk_decision,
            canary_verdict=canary_verdict,
        )

    # 8. canary verdict missing or not acceptable.
    if canary_verdict is None:
        return _result(
            ShadowEligibilityDecision.NOT_ELIGIBLE_CANARY_DEFERRED,
            "canary verdict missing",
            confidence_score=confidence_score,
            risk_decision=risk_decision,
            canary_verdict=None,
        )
    if canary_verdict not in ALLOWED_CANARY_VERDICTS:
        return _result(
            ShadowEligibilityDecision.NOT_ELIGIBLE_CANARY_DEFERRED,
            f"canary verdict {canary_verdict!r} not in passthrough set",
            confidence_score=confidence_score,
            risk_decision=risk_decision,
            canary_verdict=canary_verdict,
        )

    # 9. risk must be in the accepted set. Anything else is unknown.
    if risk_decision not in ALLOWED_RISK_DECISIONS:
        return _result(
            ShadowEligibilityDecision.NOT_ELIGIBLE_UNKNOWN,
            f"risk_decision={risk_decision!r} not in {{APPROVE, DETECTED}}",
            confidence_score=confidence_score,
            risk_decision=risk_decision,
            canary_verdict=canary_verdict,
        )

    # 10. ELIGIBLE.
    return _result(
        ShadowEligibilityDecision.ELIGIBLE,
        "all gates pass",
        confidence_score=confidence_score,
        risk_decision=risk_decision,
        canary_verdict=canary_verdict,
    )


__all__ = [
    "ShadowEligibilityDecision",
    "ShadowEligibilityResult",
    "evaluate_shadow_eligibility",
    "CONFIDENCE_FLOOR",
    "ALLOWED_RISK_DECISIONS",
    "BLOCK_RISK_DECISIONS",
    "NO_SIGNAL_RISK_DECISIONS",
    "DRAWDOWN_GUARD_SUBSTRINGS",
    "ALLOWED_CANARY_VERDICTS",
    "DATA_FAILURE_DIAGNOSTIC_TOKENS",
]
