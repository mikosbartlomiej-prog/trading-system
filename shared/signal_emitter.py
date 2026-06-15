"""v3.22.0 (2026-06-15) — ETAP 2 — emit_signal_opportunity.

WHY
---
v3.22 needs ONE entry point that monitors call after generating a
SignalEvent. That entry point must:

  1. Validate the event (signal_event.validate)
  2. Try to compute a confidence score (shared.confidence.compute_confidence)
  3. Persist the result via the opportunity ledger
     (shared.signal_opportunity_ledger.record_opportunity)
  4. NEVER place a trade, NEVER call the broker, NEVER touch the network.

Without this, every monitor would have to re-implement the same 3-step
chain, and the inevitable drift would corrupt the ledger.

CHAIN
-----

    SignalEvent
        │
        ▼
    emit_signal_opportunity(event)
        │
        ├── signal_event.validate(...)            # input check
        ├── shared.confidence.compute_confidence  # advisory score
        └── shared.signal_opportunity_ledger.record_opportunity(...)   # persist

HARD SAFETY
-----------
- NEVER imports alpaca_orders.
- NEVER calls submit_order / place_order / safe_close /
  place_stock_bracket / place_crypto_order / place_simple_buy /
  place_option_order / close_position / close_all_positions.
- NEVER makes network calls.
- Fail-soft on EVERY external call (ledger write, confidence compute,
  audit emit). Failures are surfaced in the return payload, not raised.

FREE OPERATION
--------------
Zero paid API calls. Pure local I/O via the ledger.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

# Import the signal event types — these are pure dataclasses, safe to
# import unconditionally.
try:
    from signal_event import SignalEvent, validate as _validate_event
except ImportError:
    from shared.signal_event import SignalEvent, validate as _validate_event  # type: ignore


VERSION = "v3.22.0"
IDEMPOTENCY_CACHE_SIZE = 1024

# Process-local idempotency cache. OrderedDict so we can evict in FIFO
# order when the cache is full. NOT thread-safe by design — single-cron
# usage pattern means there is never concurrent emission from one
# process. The cache is process-local: a restart resets dedupe.
_IDEMPOTENCY_CACHE: "OrderedDict[str, dict]" = OrderedDict()


# ─── Internal helpers ────────────────────────────────────────────────────────


def _compute_confidence_safely(confidence_inputs: dict) -> tuple[
        str, float | None, dict, str | None, list[str]]:
    """Try to compute confidence. Never raise.

    Returns:
        (status, score, components, verdict, warnings)
    """
    warnings: list[str] = []
    if not isinstance(confidence_inputs, dict):
        return ("UNAVAILABLE", None, {}, None,
                ["confidence_inputs is not a dict"])
    try:
        try:
            from confidence import compute_confidence  # type: ignore
        except ImportError:
            from shared.confidence import compute_confidence  # type: ignore
    except Exception as e:  # pragma: no cover - import failure
        return ("UNAVAILABLE", None, {}, None,
                [f"compute_confidence import failed: {e}"])

    try:
        report = compute_confidence(**confidence_inputs)
    except TypeError as e:
        # Unknown kwarg or malformed inputs.
        return ("UNAVAILABLE", None, {}, None,
                [f"compute_confidence TypeError: {e}"])
    except Exception as e:
        return ("UNAVAILABLE", None, {}, None,
                [f"compute_confidence raised: {e}"])

    # Extract fields defensively — different ConfidenceReport versions
    # use slightly different attribute names.
    score = getattr(report, "total", None)
    components = getattr(report, "components", {}) or {}
    verdict = getattr(report, "decision", None) or getattr(report, "verdict", None)
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
        warnings.append("could not coerce confidence score to float")

    return ("OK", score_f, dict(components), verdict, warnings)


def _record_opportunity_safely(
    *,
    event: SignalEvent,
    confidence_score: float | None,
    confidence_components: dict,
    rejection_reasons: list[str],
) -> tuple[bool, dict | None, str | None]:
    """Try to persist via the ledger. Never raise. Returns
    (success, record, error_message_or_None)."""
    try:
        try:
            from signal_opportunity_ledger import record_opportunity  # type: ignore
        except ImportError:
            from shared.signal_opportunity_ledger import (  # type: ignore
                record_opportunity,
            )
    except Exception as e:
        return (False, None, f"ledger import failed: {e}")

    try:
        record = record_opportunity(
            signal_id=event.signal_id,
            strategy=event.strategy_id,
            symbol=event.symbol,
            raw_signal=dict(event.raw_signal or {}),
            confidence_score=confidence_score,
            confidence_components=confidence_components,
            paper_action=None,
            shadow_action=None,
            audit_link=(event.metadata or {}).get("audit_link"),
            timestamp=event.timestamp_iso,
            rejection_reasons=list(rejection_reasons or []),
        )
        return (True, record, None)
    except Exception as e:
        return (False, None, f"ledger write failed: {e}")


def _cache_key(idempotency_key: str | None, event: SignalEvent) -> str | None:
    if idempotency_key:
        return str(idempotency_key)
    # Fall back to the event's signal_id only if it is non-empty and the
    # caller did not opt-out by leaving idempotency_key=None. We use None
    # here meaning "no dedupe" so that we don't accidentally dedupe
    # back-to-back observe events that legitimately share a signal_id.
    return None


def _check_and_record_idempotency(key: str | None, result: dict) -> dict | None:
    """If `key` was seen recently, return a DUPLICATE response. Else cache."""
    if not key:
        return None
    if key in _IDEMPOTENCY_CACHE:
        cached = _IDEMPOTENCY_CACHE[key]
        return {
            "emitted":              False,
            "status":               "DUPLICATE_SUPPRESSED",
            "signal_id":            cached.get("signal_id"),
            "first_seen_status":    cached.get("status"),
            "first_seen_signal_id": cached.get("signal_id"),
        }
    # Insert and trim if needed.
    _IDEMPOTENCY_CACHE[key] = {
        "signal_id": result.get("signal_id"),
        "status":    result.get("status"),
    }
    while len(_IDEMPOTENCY_CACHE) > IDEMPOTENCY_CACHE_SIZE:
        _IDEMPOTENCY_CACHE.popitem(last=False)
    return None


def _clear_idempotency_cache_for_tests() -> None:
    """Test helper. Not part of the public API."""
    _IDEMPOTENCY_CACHE.clear()


# ─── Public API ──────────────────────────────────────────────────────────────


def emit_signal_opportunity(
    event: SignalEvent,
    *,
    dry_run: bool = False,
    idempotency_key: str | None = None,
) -> dict:
    """Validate → compute confidence → persist via ledger.

    Returns a dict describing the emission outcome:

        {
          "emitted":               bool,
          "status":                "EMITTED" | "BLOCKING_VALIDATION_ERROR"
                                  | "LEDGER_WRITE_FAILED"
                                  | "DUPLICATE_SUPPRESSED"
                                  | "DRY_RUN",
          "signal_id":             str | None,
          "confidence_score":      float | None,
          "confidence_verdict":    str | None,
          "audit_link":            str | None,
          "warnings":              list[str],
          "errors":                list[str] | absent,
        }

    Parameters
    ----------
    event : SignalEvent
        The validated signal carrier.
    dry_run : bool
        If True, run validation + confidence but DO NOT write to the
        ledger. Useful for tests and for monitors that want a preview.
    idempotency_key : str | None
        If provided, repeated calls with the same key inside the cache
        window return ``DUPLICATE_SUPPRESSED``.

    HARD SAFETY
    -----------
    This function NEVER places a trade, NEVER calls the broker, NEVER
    makes network calls.
    """
    warnings: list[str] = []

    # ── Step 0 — basic type check ─────────────────────────────────────────
    if not isinstance(event, SignalEvent):
        return {
            "emitted":           False,
            "status":            "BLOCKING_VALIDATION_ERROR",
            "errors":            ["event is not a SignalEvent instance"],
            "audit_link":        None,
            "signal_id":         None,
            "confidence_score":  None,
            "confidence_verdict": None,
            "warnings":          [],
        }

    # ── Step 1 — validate the event ───────────────────────────────────────
    errors = _validate_event(event)
    if errors and event.entry_capable:
        return {
            "emitted":           False,
            "status":            "BLOCKING_VALIDATION_ERROR",
            "errors":            errors,
            "audit_link":        (event.metadata or {}).get("audit_link"),
            "signal_id":         event.signal_id or None,
            "confidence_score":  None,
            "confidence_verdict": None,
            "warnings":          warnings,
        }

    # For non-entry-capable events that still have validation errors, we
    # treat the errors as additional rejection_reasons but proceed with
    # ledger emission so the observation is captured for audit. They are
    # also surfaced in `warnings` so callers know something was off.
    rejection_reasons: list[str] = []
    if errors and not event.entry_capable:
        warnings.append("non-entry event has validation issues; recording anyway")
        rejection_reasons.extend(f"validation: {e}" for e in errors)

    # ── Step 2 — compute confidence (advisory) ────────────────────────────
    confidence_status = "SKIPPED"
    confidence_score: float | None = None
    confidence_components: dict = {}
    confidence_verdict: str | None = None

    if event.entry_capable:
        (
            confidence_status,
            confidence_score,
            confidence_components,
            confidence_verdict,
            conf_warnings,
        ) = _compute_confidence_safely(event.confidence_inputs or {})
        warnings.extend(conf_warnings)
    else:
        warnings.append("confidence skipped: event.entry_capable=False")

    audit_link = (event.metadata or {}).get("audit_link")

    # ── Step 3 — idempotency check (BEFORE any side-effecting write) ──────
    # Spec contract: a duplicate emit must NOT produce a second ledger row.
    # We check the cache here and short-circuit so the second call only
    # returns the cached envelope.
    key = _cache_key(idempotency_key, event)
    if key and key in _IDEMPOTENCY_CACHE:
        cached = _IDEMPOTENCY_CACHE[key]
        return {
            "emitted":              False,
            "status":               "DUPLICATE_SUPPRESSED",
            "signal_id":            cached.get("signal_id"),
            "first_seen_status":    cached.get("status"),
            "first_seen_signal_id": cached.get("signal_id"),
        }

    # ── Step 4 — dry-run short-circuit ────────────────────────────────────
    if dry_run:
        return {
            "emitted":            False,
            "status":             "DRY_RUN",
            "signal_id":          event.signal_id,
            "confidence_score":   confidence_score,
            "confidence_verdict": confidence_verdict,
            "confidence_status":  confidence_status,
            "audit_link":         audit_link,
            "warnings":           warnings,
        }

    # ── Step 5 — persist via the ledger ───────────────────────────────────
    ok, record, write_error = _record_opportunity_safely(
        event=event,
        confidence_score=confidence_score,
        confidence_components=confidence_components,
        rejection_reasons=rejection_reasons,
    )
    if not ok:
        return {
            "emitted":            False,
            "status":             "LEDGER_WRITE_FAILED",
            "signal_id":          event.signal_id,
            "confidence_score":   confidence_score,
            "confidence_verdict": confidence_verdict,
            "confidence_status":  confidence_status,
            "audit_link":         audit_link,
            "warnings":           warnings,
            "error":              write_error or "unknown ledger error",
        }

    result = {
        "emitted":            True,
        "status":             "EMITTED",
        "signal_id":          event.signal_id,
        "confidence_score":   confidence_score,
        "confidence_verdict": confidence_verdict,
        "confidence_status":  confidence_status,
        "audit_link":         audit_link,
        "warnings":           warnings,
        "record":             record,
    }

    # ── Step 6 — cache the successful emit for future dedupe ──────────────
    if key:
        _IDEMPOTENCY_CACHE[key] = {
            "signal_id": result.get("signal_id"),
            "status":    result.get("status"),
        }
        while len(_IDEMPOTENCY_CACHE) > IDEMPOTENCY_CACHE_SIZE:
            _IDEMPOTENCY_CACHE.popitem(last=False)

    return result


__all__ = [
    "VERSION",
    "IDEMPOTENCY_CACHE_SIZE",
    "emit_signal_opportunity",
]
