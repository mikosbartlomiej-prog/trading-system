"""v3.24.0 (2026-06-15) — emit_signal_opportunity with FORCED confidence persistence.

WHY
---
v3.22 wired ONE entry point that monitors call after generating a
SignalEvent, but the 2026-06-15 audit showed 100% of the last 7 days of
real-market rows (16,238 rows) had ``confidence_score=null`` and an
empty ``confidence_components={}``. Reason: monitors built SignalEvents
with empty or partial ``confidence_inputs``, and the emitter silently
wrote nulls. That broke shadow-eligibility forever.

v3.24 closes the gap. For every ENTRY-CAPABLE event we now MUST end
with one of two outcomes per row:

  (a) a numeric ``confidence_score`` + non-empty ``confidence_components``
      + an explicit ``confidence_decision`` (ALLOW / ALERT_ONLY / BLOCK),
      OR
  (b) ``confidence_status="ERROR"`` with an explicit ``confidence_error``
      string and ``blocking_reason="CONFIDENCE_COMPUTE_FAILED"``.

A silent null is no longer an acceptable outcome for an entry-capable
row. For observe-only rows (``entry_capable=False``) we tag
``confidence_status="OBSERVE_ONLY_SKIP"``; ``confidence_score`` MAY be
null there.

CHAIN
-----

    SignalEvent
        │
        ▼
    emit_signal_opportunity(event)
        │
        ├── signal_event.validate(...)            # input check
        ├── (entry_capable?) → build_confidence_inputs(event, ...)   # v3.24
        ├── (entry_capable?) → compute_confidence(**components)
        ├── (always)         → record_opportunity(...)  # ledger persist
        └── (always)         → return outcome envelope

HARD SAFETY
-----------
- NEVER imports alpaca_orders.
- NEVER calls submit_order / place_order / safe_close /
  place_stock_bracket / place_crypto_order / place_simple_buy /
  place_option_order / close_position / close_all_positions.
- NEVER makes network calls.
- Fail-soft on EVERY external call (ledger write, confidence compute,
  audit emit). Failures are surfaced in the return payload AND
  persisted on the ledger row, not raised.

FREE OPERATION
--------------
Zero paid API calls. Pure local I/O via the ledger.
"""

from __future__ import annotations

import dataclasses
from collections import OrderedDict
from typing import Any

# Import the signal event types — these are pure dataclasses, safe to
# import unconditionally.
try:
    from signal_event import SignalEvent, validate as _validate_event
except ImportError:
    from shared.signal_event import SignalEvent, validate as _validate_event  # type: ignore


VERSION = "v3.24.0"
IDEMPOTENCY_CACHE_SIZE = 1024

# Status sentinels (also documented in module docstring).
CONFIDENCE_STATUS_OK = "OK"
CONFIDENCE_STATUS_ERROR = "ERROR"
CONFIDENCE_STATUS_OBSERVE_ONLY_SKIP = "OBSERVE_ONLY_SKIP"
CONFIDENCE_STATUS_UNAVAILABLE = "UNAVAILABLE"

# Process-local idempotency cache. OrderedDict so we can evict in FIFO
# order when the cache is full. NOT thread-safe by design — single-cron
# usage pattern means there is never concurrent emission from one
# process. The cache is process-local: a restart resets dedupe.
_IDEMPOTENCY_CACHE: "OrderedDict[str, dict]" = OrderedDict()


# ─── Internal helpers ────────────────────────────────────────────────────────


def _compute_confidence_safely(confidence_inputs: dict) -> tuple[
        str, float | None, dict, str | None, list[str], str | None]:
    """Try to compute confidence. Never raise.

    Returns:
        (status, score, components, verdict, warnings, error_message)

    ``error_message`` is non-None iff status == "ERROR" (compute raised /
    import failed / inputs malformed). v3.24: an ERROR is always
    persisted on the ledger row so the operator can audit the cause.
    """
    warnings: list[str] = []
    if not isinstance(confidence_inputs, dict):
        return (CONFIDENCE_STATUS_ERROR, None, {}, None,
                ["confidence_inputs is not a dict"],
                "INPUTS_NOT_DICT")
    try:
        try:
            from confidence import compute_confidence  # type: ignore
        except ImportError:
            from shared.confidence import compute_confidence  # type: ignore
    except Exception as e:  # pragma: no cover - import failure
        return (CONFIDENCE_STATUS_ERROR, None, {}, None,
                [f"compute_confidence import failed: {e}"],
                f"IMPORT_FAILED: {type(e).__name__}: {e}")

    try:
        report = compute_confidence(**confidence_inputs)
    except TypeError as e:
        return (CONFIDENCE_STATUS_ERROR, None, {}, None,
                [f"compute_confidence TypeError: {e}"],
                f"TYPE_ERROR: {e}")
    except Exception as e:
        return (CONFIDENCE_STATUS_ERROR, None, {}, None,
                [f"compute_confidence raised: {e}"],
                f"{type(e).__name__}: {e}")

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

    return (CONFIDENCE_STATUS_OK, score_f, dict(components),
            verdict, warnings, None)


def _record_opportunity_safely(
    *,
    event: SignalEvent,
    confidence_score: float | None,
    confidence_components: dict,
    rejection_reasons: list[str],
    extra_raw_fields: dict | None = None,
) -> tuple[bool, dict | None, str | None]:
    """Try to persist via the ledger. Never raise. Returns
    (success, record, error_message_or_None).

    v3.24: ``extra_raw_fields`` is merged into the persisted
    ``raw_signal`` payload so the v3.24 confidence-status fields
    (status, decision, error, default_reasons, builder_version,
    completeness, blocking_reason, entry_capable) are durable on
    every row.
    """
    try:
        try:
            from signal_opportunity_ledger import record_opportunity  # type: ignore
        except ImportError:
            from shared.signal_opportunity_ledger import (  # type: ignore
                record_opportunity,
            )
    except Exception as e:
        return (False, None, f"ledger import failed: {e}")

    raw = dict(event.raw_signal or {})
    if extra_raw_fields:
        raw.update(extra_raw_fields)

    try:
        record = record_opportunity(
            signal_id=event.signal_id,
            strategy=event.strategy_id,
            symbol=event.symbol,
            raw_signal=raw,
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

    # ── Step 0.5 — v3.24 back-fill: builder may populate confidence_inputs
    #              BEFORE validate runs, so that an entry-capable event
    #              with empty inputs is no longer auto-rejected ─────────
    builder_components: dict | None = None
    builder_default_reasons: dict = {}
    builder_completeness: float | None = None
    builder_version_stamp: str | None = None
    builder_error: str | None = None

    if event.entry_capable:
        try:
            try:
                from confidence_input_builder import (  # type: ignore
                    build_confidence_inputs,
                    BUILDER_VERSION,
                )
            except ImportError:
                from shared.confidence_input_builder import (  # type: ignore
                    build_confidence_inputs,
                    BUILDER_VERSION,
                )
            builder_version_stamp = BUILDER_VERSION
            built = build_confidence_inputs(
                event,
                market_context=event.market_regime or None,
                strategy_state=(event.risk_inputs or {}).get(
                    "strategy_state"),
            )
            builder_components = dict(built.components or {})
            builder_default_reasons = dict(built.default_reasons or {})
            builder_completeness = float(built.completeness or 0.0)
            builder_version_stamp = built.builder_version or BUILDER_VERSION
        except ValueError as ve:
            builder_error = f"BUILDER_ERROR: {type(ve).__name__}: {ve}"
            warnings.append(builder_error)
        except Exception as be:
            builder_error = (
                f"BUILDER_IMPORT_OR_RUN_FAILED: {type(be).__name__}: {be}"
            )
            warnings.append(builder_error)

        # If the event's confidence_inputs is empty AND the builder
        # produced components, mutate a copy of the event so validate
        # sees the populated dict. We never overwrite caller-supplied
        # inputs.
        if (not event.confidence_inputs) and builder_components:
            event = dataclasses.replace(
                event, confidence_inputs=dict(builder_components)
            )

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

    # ── Step 2 — confidence pipeline ──────────────────────────────────────
    #
    # v3.24 contract:
    #   entry_capable=True  → ALWAYS run compute_confidence on the
    #                         builder-augmented inputs. End with either
    #                         OK + numeric score OR ERROR + reason.
    #                         Silent null is FORBIDDEN.
    #   entry_capable=False → mark OBSERVE_ONLY_SKIP. score may be null.
    confidence_status = CONFIDENCE_STATUS_OBSERVE_ONLY_SKIP
    confidence_score: float | None = None
    confidence_components: dict = {}
    confidence_verdict: str | None = None
    confidence_error: str | None = None
    confidence_default_reasons: dict = dict(builder_default_reasons or {})
    confidence_builder_version: str | None = builder_version_stamp
    confidence_input_completeness: float | None = builder_completeness
    blocking_reason: str | None = None

    if event.entry_capable:
        # Step 0.5 already ran the builder. Merge: caller-supplied
        # confidence_inputs take precedence over builder-supplied keys.
        existing_inputs = event.confidence_inputs or {}
        ci_components: dict = dict(builder_components or {})
        if isinstance(existing_inputs, dict):
            for k, v in existing_inputs.items():
                # Caller value wins.
                ci_components[k] = v

        if builder_error and not ci_components:
            # The builder failed AND no caller inputs exist → ERROR.
            confidence_status = CONFIDENCE_STATUS_ERROR
            confidence_error = builder_error
            blocking_reason = "CONFIDENCE_COMPUTE_FAILED"
        else:
            (
                confidence_status,
                confidence_score,
                confidence_components,
                confidence_verdict,
                conf_warnings,
                confidence_error,
            ) = _compute_confidence_safely(ci_components)
            warnings.extend(conf_warnings)
            if confidence_status == CONFIDENCE_STATUS_ERROR:
                blocking_reason = "CONFIDENCE_COMPUTE_FAILED"

        # Mandatory persistence: entry-capable rows MUST end with either
        # a numeric score OR an ERROR + reason. Score-None or empty
        # components dict from a "successful" compute is a contract
        # violation → escalate to ERROR.
        if (confidence_status == CONFIDENCE_STATUS_OK
                and confidence_score is None):
            confidence_status = CONFIDENCE_STATUS_ERROR
            confidence_error = confidence_error or "SCORE_NULL_AFTER_OK"
            blocking_reason = "CONFIDENCE_COMPUTE_FAILED"
        if (confidence_status == CONFIDENCE_STATUS_OK
                and not confidence_components):
            confidence_status = CONFIDENCE_STATUS_ERROR
            confidence_error = confidence_error or "COMPONENTS_EMPTY_AFTER_OK"
            blocking_reason = "CONFIDENCE_COMPUTE_FAILED"
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
            "emitted":                       False,
            "status":                        "DRY_RUN",
            "signal_id":                     event.signal_id,
            "confidence_score":              confidence_score,
            "confidence_verdict":            confidence_verdict,
            "confidence_status":             confidence_status,
            "confidence_decision":           confidence_verdict,
            "confidence_error":              confidence_error,
            "confidence_default_reasons":    confidence_default_reasons,
            "confidence_builder_version":    confidence_builder_version,
            "confidence_input_completeness": confidence_input_completeness,
            "blocking_reason":               blocking_reason,
            "entry_capable":                 event.entry_capable,
            "audit_link":                    audit_link,
            "warnings":                      warnings,
        }

    # ── Step 5 — persist via the ledger ───────────────────────────────────
    # v3.24 contract: every entry-capable row carries either a real number
    # or an explicit ERROR sentinel. We persist the status fields on the
    # row's raw_signal so the learning loop can read them back.
    extra_fields = {
        "confidence_status":             confidence_status,
        "confidence_decision":           confidence_verdict,
        "confidence_default_reasons":    dict(confidence_default_reasons or {}),
        "confidence_builder_version":    confidence_builder_version,
        "confidence_input_completeness": confidence_input_completeness,
        "entry_capable":                 event.entry_capable,
    }
    if confidence_error:
        extra_fields["confidence_error"] = confidence_error
    if blocking_reason:
        extra_fields["blocking_reason"] = blocking_reason

    ok, record, write_error = _record_opportunity_safely(
        event=event,
        confidence_score=confidence_score,
        confidence_components=confidence_components,
        rejection_reasons=rejection_reasons,
        extra_raw_fields=extra_fields,
    )
    if not ok:
        return {
            "emitted":                       False,
            "status":                        "LEDGER_WRITE_FAILED",
            "signal_id":                     event.signal_id,
            "confidence_score":              confidence_score,
            "confidence_verdict":            confidence_verdict,
            "confidence_status":             confidence_status,
            "confidence_decision":           confidence_verdict,
            "confidence_error":              confidence_error,
            "confidence_default_reasons":    confidence_default_reasons,
            "confidence_builder_version":    confidence_builder_version,
            "confidence_input_completeness": confidence_input_completeness,
            "blocking_reason":               blocking_reason,
            "entry_capable":                 event.entry_capable,
            "audit_link":                    audit_link,
            "warnings":                      warnings,
            "error":                         write_error or "unknown ledger error",
        }

    result = {
        "emitted":                       True,
        "status":                        "EMITTED",
        "signal_id":                     event.signal_id,
        "confidence_score":              confidence_score,
        "confidence_verdict":            confidence_verdict,
        "confidence_status":             confidence_status,
        "confidence_decision":           confidence_verdict,
        "confidence_error":              confidence_error,
        "confidence_default_reasons":    confidence_default_reasons,
        "confidence_builder_version":    confidence_builder_version,
        "confidence_input_completeness": confidence_input_completeness,
        "blocking_reason":               blocking_reason,
        "entry_capable":                 event.entry_capable,
        "audit_link":                    audit_link,
        "warnings":                      warnings,
        "record":                        record,
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
    "CONFIDENCE_STATUS_OK",
    "CONFIDENCE_STATUS_ERROR",
    "CONFIDENCE_STATUS_OBSERVE_ONLY_SKIP",
    "CONFIDENCE_STATUS_UNAVAILABLE",
    "emit_signal_opportunity",
]
