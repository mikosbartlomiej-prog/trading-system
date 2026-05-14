"""
Schema validation + sanitization for learning-loop/state.json.

The LLM may propose state overrides; without validation, hallucinated keys
or out-of-range values can poison the runtime config. This module:

  1. Enforces the schema (whitelist of fields per strategy).
  2. Clamps numeric overrides into safe bounds.
  3. Coerces types (size_multiplier float, enabled bool).
  4. Strips unknown keys silently.
  5. Returns a structured report so callers (analyzer + lane2) can log
     what was dropped and why.

Schema (per strategy entry in state["strategies"][<name>]):
  size_multiplier:   float, clamped to [SIZE_MULT_MIN, SIZE_MULT_MAX]
  enabled:           bool
  side_bias:         "long" | "short" | None
  paused_until:      ISO-8601 date string or None
  notes:             free-text (truncated to NOTES_MAX_LEN)

Top-level state fields:
  state_version, last_writer, last_write_reason, last_validated_at,
  strategies, pending_llm, history (free-form)
"""

from __future__ import annotations

from datetime import date
from typing import Any

SIZE_MULT_MIN = 0.30
SIZE_MULT_MAX = 2.00
ALLOWED_SIDE_BIAS = {"long", "short"}
NOTES_MAX_LEN = 500

STRATEGY_FIELDS = {
    "size_multiplier",
    "enabled",
    "side_bias",
    "paused_until",
    "notes",
}

TOP_LEVEL_FIELDS = {
    "state_version",
    "last_writer",
    "last_write_reason",
    "last_validated_at",
    "strategies",
    "pending_llm",
    "history",
    "tp_hit_rate",
    "schema_errors",
}


def _coerce_bool(value: Any) -> bool | None:
    """Return strict bool or None if uncoercible. LLM frequently emits
    'yes please' or other free-text — we drop those silently."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return None


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_date(value: Any) -> str | None:
    """Accept ISO-8601 date or datetime string. Returns canonical YYYY-MM-DD
    or None if uncoercible. Strict — won't accept timestamps as 'tomorrow'."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Accept YYYY-MM-DD or YYYY-MM-DDTHH:MM... (truncate after date).
    head = s[:10]
    try:
        date.fromisoformat(head)
        return head
    except ValueError:
        return None


def validate_strategy_override(
    name: str, raw: Any
) -> tuple[dict[str, Any], list[str]]:
    """
    Validate one strategy entry. Returns (sanitized_dict, errors).

    Sanitized dict only contains valid fields with coerced values. Errors
    is a list of human-readable strings describing what was dropped/clamped.
    """
    errors: list[str] = []
    if not isinstance(raw, dict):
        return {}, [f"strategy '{name}' not a dict (got {type(raw).__name__})"]

    out: dict[str, Any] = {}

    # size_multiplier
    if "size_multiplier" in raw:
        v = _coerce_float(raw["size_multiplier"])
        if v is None:
            errors.append(f"'{name}'.size_multiplier not numeric — dropped")
        else:
            clamped = max(SIZE_MULT_MIN, min(SIZE_MULT_MAX, v))
            if clamped != v:
                errors.append(
                    f"'{name}'.size_multiplier {v} clamped to {clamped} "
                    f"(bounds [{SIZE_MULT_MIN}, {SIZE_MULT_MAX}])"
                )
            out["size_multiplier"] = clamped

    # enabled
    if "enabled" in raw:
        b = _coerce_bool(raw["enabled"])
        if b is None:
            errors.append(f"'{name}'.enabled not boolean — dropped")
        else:
            out["enabled"] = b

    # side_bias
    if "side_bias" in raw:
        v = raw["side_bias"]
        if v is None:
            out["side_bias"] = None
        elif isinstance(v, str) and v.lower() in ALLOWED_SIDE_BIAS:
            out["side_bias"] = v.lower()
        else:
            errors.append(
                f"'{name}'.side_bias '{v}' not in {sorted(ALLOWED_SIDE_BIAS)} — dropped"
            )

    # paused_until
    if "paused_until" in raw:
        v = _coerce_date(raw["paused_until"])
        if raw["paused_until"] is None or v is not None:
            out["paused_until"] = v
        else:
            errors.append(
                f"'{name}'.paused_until '{raw['paused_until']}' not ISO date — dropped"
            )

    # notes
    if "notes" in raw:
        v = raw["notes"]
        if isinstance(v, str):
            out["notes"] = v[:NOTES_MAX_LEN]
        else:
            errors.append(f"'{name}'.notes not string — dropped")

    # Drop any unknown keys with a single grouped error
    extras = set(raw.keys()) - STRATEGY_FIELDS
    if extras:
        errors.append(
            f"'{name}' unknown fields dropped: {sorted(extras)}"
        )

    return out, errors


def validate_state(state: Any) -> tuple[dict[str, Any], list[str]]:
    """
    Validate the whole state dict.

    Returns (sanitized_state, errors). Sanitized state always has a
    `strategies` dict (possibly empty) and never carries unknown top-level
    fields. The original `state` is not mutated.
    """
    errors: list[str] = []

    if not isinstance(state, dict):
        return {"strategies": {}}, [f"state not a dict (got {type(state).__name__})"]

    out: dict[str, Any] = {}

    # Copy over known top-level fields verbatim (deeper validation only on
    # strategies which is the security-sensitive surface).
    for k in TOP_LEVEL_FIELDS:
        if k in state and k != "strategies":
            out[k] = state[k]

    # Strategies
    strategies_raw = state.get("strategies") or {}
    if not isinstance(strategies_raw, dict):
        errors.append("'strategies' not a dict — replaced with {}")
        strategies_raw = {}

    out["strategies"] = {}
    for name, body in strategies_raw.items():
        if not isinstance(name, str) or not name.strip():
            errors.append(f"strategy with non-string name skipped: {name!r}")
            continue
        sanitized, errs = validate_strategy_override(name, body)
        if sanitized:
            out["strategies"][name] = sanitized
        errors.extend(errs)

    # Note unknown top-level keys but don't fail
    extras = set(state.keys()) - TOP_LEVEL_FIELDS
    if extras:
        errors.append(f"top-level unknown fields dropped: {sorted(extras)}")

    return out, errors


def is_valid(state: Any) -> bool:
    """True iff validation produced no errors AND state has the right shape."""
    _, errors = validate_state(state)
    return not errors
