"""v3.17.0 (2026-06-04) — Mandatory entry audit emission helper.

Closes Task 3 from Codex audit 2026-06-04: every entry decision
(placed / rejected / failed) MUST emit a dedicated JSONL audit event.

USAGE PATTERN

Inside place_stock_bracket / place_crypto_order / place_simple_buy
(and similarly any future entry point):

    from _entry_audit import emit_entry_audit
    ...
    emit_entry_audit(
        proposal={...},          # what the caller WANTED to do
        result="placed",          # placed / rejected / failed
        result_reason="ok",
        order=alpaca_order_json,  # only on placed
        risk_verdict={...},       # optional - from evaluate_trade
    )

CONTRACT
--------

1. NEVER raises. Audit emit failure must not block (or unblock) entry
   decisions.  All exceptions are caught + logged with print().
2. Emits a TRADING-kind JSONL line (journal/autonomy/YYYY-MM-DD.jsonl).
3. decision_type:
     - "APPROVE_ENTRY"  → result == "placed"
     - "REJECT_ENTRY"   → result == "rejected" | "failed"
4. Repeated failures bubble up to safe_mode via `_record_audit_failure`.
   After 3 consecutive audit emit errors during a single interpreter,
   tries to trip safe_mode (CONFIDENCE_BROKEN/OPERATOR trigger). This is
   defensive only — if even safe_mode trip fails, the function still
   returns silently.

FIELDS PERSISTED
----------------

The Decision record's `inputs` dict captures:
  - symbol, action, strategy
  - size_usd, entry_price, stop_loss, take_profit
  - source_type (if present in proposal)
  - confidence_report (if present in proposal["_confidence_report"])
  - risk_verdict (if supplied via kwarg)

The Decision's `affected_symbols` list contains the single symbol.
The Decision's `result` is the literal placed/rejected/failed string.
The Decision's `action_taken` describes the broker action.

SAFE-MODE ESCALATION
--------------------

If `EMIT_FAILURES_BEFORE_SAFE_MODE` consecutive emit failures happen,
the helper attempts to enter safe_mode with trigger "OPERATOR" and
reason "entry_audit_emit_failures_exceeded".  This is best-effort and
fail-soft.
"""

from __future__ import annotations

import os
from typing import Any

# Counter of consecutive emit failures inside one interpreter. Used for
# defensive safe_mode escalation.
_AUDIT_EMIT_FAILURE_COUNT = 0
EMIT_FAILURES_BEFORE_SAFE_MODE = 3


# ─── Public API ───────────────────────────────────────────────────────────────

def emit_entry_audit(
    *,
    proposal: dict[str, Any],
    result: str,
    result_reason: str = "",
    order: dict | None = None,
    risk_verdict: dict | None = None,
    actor: str = "alpaca_orders",
) -> bool:
    """Emit one entry-decision audit JSONL line.

    Args:
        proposal:      what the caller wanted to place. Expected keys
                       include symbol, action, size_usd, entry_price,
                       stop_loss, take_profit, strategy.
                       May carry optional source_type +
                       _confidence_report.
        result:        "placed" | "rejected" | "failed"
        result_reason: human-readable rationale string
        order:         Alpaca order JSON returned on success (only on
                       result == "placed"); used for order_id capture.
        risk_verdict:  the dict returned by risk_officer.evaluate_trade
                       (optional — only when entry path called it).
        actor:         module that initiated the decision; used for
                       audit Decision.actor field.

    Returns:
        True if audit emit succeeded, False otherwise. NEVER raises.
    """
    global _AUDIT_EMIT_FAILURE_COUNT
    try:
        # Lazy imports — module unavailability must not prevent placing
        # entries (because the audit emit happens AFTER the decision is
        # made). Failure here is logged; the caller's order placement
        # already happened or didn't.
        try:
            from autonomy import make_decision  # type: ignore
            from audit import write_audit_event  # type: ignore
        except ImportError:  # pragma: no cover
            from shared.autonomy import make_decision  # type: ignore
            from shared.audit import write_audit_event  # type: ignore

        # Normalize core fields. Missing values default to None so the
        # audit row is still well-formed.
        symbol = (proposal.get("symbol") or "").strip().upper() or "UNKNOWN"
        action = (proposal.get("action") or proposal.get("side") or "").upper()
        strategy = proposal.get("strategy") or "auto"
        size_usd = float(proposal.get("size_usd") or 0)
        entry_price = float(proposal.get("entry_price") or proposal.get("limit_price") or 0)
        stop_loss = proposal.get("stop_loss")
        take_profit = proposal.get("take_profit")
        source_type = proposal.get("source_type")
        confidence_report = proposal.get("_confidence_report") or proposal.get("confidence_report")

        # Map result → decision_type/decision.
        result_norm = (result or "").lower()
        if result_norm == "placed":
            decision_type = "APPROVE_ENTRY"
            decision = "PLACED"
        elif result_norm == "rejected":
            decision_type = "REJECT_ENTRY"
            decision = "REJECTED"
        elif result_norm == "failed":
            decision_type = "REJECT_ENTRY"
            decision = "FAILED"
        else:
            # Unknown result string — treat as REJECT_ENTRY/UNKNOWN.
            decision_type = "REJECT_ENTRY"
            decision = (result_norm or "UNKNOWN").upper()

        order_id = None
        if order and isinstance(order, dict):
            order_id = order.get("id") or order.get("client_order_id")

        # The inputs dict is hashed into deterministic_inputs_hash; it
        # contains everything needed to reconstruct the decision.
        inputs = {
            "symbol":            symbol,
            "action":            action,
            "strategy":          strategy,
            "size_usd":          size_usd,
            "entry_price":       entry_price,
            "stop_loss":         stop_loss,
            "take_profit":       take_profit,
            "source_type":       source_type,
            "risk_verdict":      _summarize_risk_verdict(risk_verdict),
            "confidence_report": _summarize_confidence_report(confidence_report),
            "order_id":          order_id,
            "result_reason":     result_reason,
        }

        action_taken = f"{action or 'ENTRY'} {symbol} ({result_norm})"

        d = make_decision(
            decision_type=decision_type,
            decision=decision,
            reason=result_reason or f"entry {result_norm}",
            actor=actor,
            inputs=inputs,
            affected_symbols=[symbol] if symbol != "UNKNOWN" else [],
            strategy=str(strategy) if strategy else None,
            action_taken=action_taken,
            result=result_norm,
            reversible=False,
        )
        write_audit_event(d, kind="trading")
        # Successful emit — reset the failure counter (consecutive only).
        _AUDIT_EMIT_FAILURE_COUNT = 0
        return True
    except Exception as e:
        # Defensive: NEVER raise. Log + escalate after threshold.
        _AUDIT_EMIT_FAILURE_COUNT += 1
        print(
            f"  ⚠️  entry-audit emit failed ({type(e).__name__}: {e}); "
            f"streak={_AUDIT_EMIT_FAILURE_COUNT}"
        )
        if _AUDIT_EMIT_FAILURE_COUNT >= EMIT_FAILURES_BEFORE_SAFE_MODE:
            _try_trip_safe_mode(reason=f"entry_audit_emit_failures={_AUDIT_EMIT_FAILURE_COUNT}")
        return False


def reset_failure_counter() -> None:
    """Reset the in-memory consecutive-failure counter.

    Test fixture; not used by production code.
    """
    global _AUDIT_EMIT_FAILURE_COUNT
    _AUDIT_EMIT_FAILURE_COUNT = 0


def get_failure_count() -> int:
    """Return the current consecutive emit-failure count."""
    return _AUDIT_EMIT_FAILURE_COUNT


# ─── Internals ────────────────────────────────────────────────────────────────

def _summarize_risk_verdict(verdict: dict | None) -> dict | None:
    """Shrink a risk-officer verdict to just the audit-relevant fields."""
    if not isinstance(verdict, dict):
        return None
    return {
        "decision":      verdict.get("decision"),
        "verdict":       verdict.get("verdict"),
        "rationale":     verdict.get("rationale"),
        "checks_failed": verdict.get("checks_failed", []),
        "warnings":      verdict.get("warnings", []),
    }


def _summarize_confidence_report(report: Any) -> dict | None:
    """Shrink a confidence report (dict or object) to just the audit fields."""
    if report is None:
        return None
    if isinstance(report, dict):
        return {
            "decision":   report.get("decision"),
            "total":      report.get("total"),
            "components": report.get("components"),
        }
    # Object form (ConfidenceReport dataclass).
    try:
        as_dict = report.to_dict() if hasattr(report, "to_dict") else None
        if isinstance(as_dict, dict):
            return {
                "decision":   as_dict.get("decision"),
                "total":      as_dict.get("total"),
                "components": as_dict.get("components"),
            }
    except Exception:
        return None
    return None


def _try_trip_safe_mode(*, reason: str) -> None:
    """Best-effort safe_mode trip when audit emit fails repeatedly.

    Fail-soft: any exception is swallowed. The caller is already
    operating in a broken-audit regime; trying anything fancier risks
    cascading failures into the order flow.
    """
    try:
        try:
            from safe_mode import enter_safe_mode  # type: ignore
        except ImportError:  # pragma: no cover
            from shared.safe_mode import enter_safe_mode  # type: ignore
        enter_safe_mode(trigger="OPERATOR", reason=reason, actor="entry_audit")
        print(f"  🔒 safe_mode tripped due to repeated audit-emit failures: {reason}")
    except Exception as e:  # pragma: no cover
        print(f"  ⚠️  safe_mode trip also failed (audit broken): {type(e).__name__}: {e}")
