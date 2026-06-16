"""v3.29 ETAP 6 (2026-06-16) — LLM Advisory Authority Model.

CONTAINMENT MODULE — read this before changing anything.

This module is the **choke point** that prevents the LLM from
mutating any system state. Every LLM advisory output produced by the
v3.29 advisory mesh MUST pass ``validate_output()`` here before being
written to disk or surfaced to a human.

WHY THIS EXISTS
---------------
The pre-v3.29 ``shared/llm_advisory_registry.py`` defines the *agent*
authority levels (L0..L5) and which forbidden-action tokens must be
listed on every advisory row. v3.29 ETAP 6 adds an explicit
``LLMAdvisoryOutput`` schema that the *advisory mesh runner*
constructs, and validates that the LLM never sneaks an
``EXECUTE_ORDER`` / ``PLACE_ORDER`` / ``CLEAR_SAFE_MODE`` / etc.
through any output field.

This file does NOT replace ``llm_advisory_registry.py`` — it sits on
top as the schema layer used by the new mesh (``llm_advisory_mesh.py``).

HARD INVARIANTS (cannot be opted out of)
----------------------------------------
* NEVER imports ``alpaca_orders``.
* NEVER calls broker.
* NEVER mutates any runtime flag, safe_mode, broker_repair_required,
  allocator gate state, or readiness counters.
* NEVER writes to any file.
* ``must_not_execute_orders`` is forced ``True`` on every payload.
* ``advisory_only`` is forced ``True`` on every payload.
* ``authority_level`` is restricted to ``L0_ADVISORY_ONLY`` or
  ``L1_VETO_RECOMMEND_ONLY``. ``L5_EXECUTE_FORBIDDEN`` is a sentinel
  and cannot appear on output.

STANDING MARKERS (footer of every dump / doc)
---------------------------------------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE``
- ``NO_LLM_STATE_MUTATION``
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

# ─── Advisory roles (v3.29 ETAP 6) ─────────────────────────────────────────

ADVISORY_ROLES: frozenset = frozenset({
    "INCIDENT_REVIEW",
    "RISK_REVIEW",
    "STRATEGY_REVIEW",
    "NO_SIGNAL_DIAGNOSTIC",
    "SHADOW_CANDIDATE_REVIEW",
    "TRIGGER_WATCHLIST_REVIEW",
    "DAILY_BRIEF",
    "ALLOCATOR_PLAN_CRITIC",
    "EQUITY_RECONCILIATION_CRITIC",
    "FINAL_ARBITER",
})

# ─── Authority levels (v3.29 ETAP 6) ───────────────────────────────────────

AUTHORITY_LEVEL_ADVISORY            = "L0_ADVISORY_ONLY"
AUTHORITY_LEVEL_VETO_RECOMMEND      = "L1_VETO_RECOMMEND_ONLY"
# Sentinel — NEVER assignable on output. Assigning raises ValueError.
AUTHORITY_LEVEL_EXECUTE_FORBIDDEN   = "L5_EXECUTE_FORBIDDEN"

ASSIGNABLE_AUTHORITY_LEVELS: frozenset = frozenset({
    AUTHORITY_LEVEL_ADVISORY,
    AUTHORITY_LEVEL_VETO_RECOMMEND,
})

# ─── Forbidden output tokens (v3.29 ETAP 6) ────────────────────────────────
#
# These tokens must never appear in any LLMAdvisoryOutput.recommendation
# / findings / risk_level / authority_level / etc. The validator scans
# the recommendation field for any forbidden value.

FORBIDDEN_OUTPUTS: frozenset = frozenset({
    "EXECUTE_ORDER",
    "PLACE_ORDER",
    "CLEAR_SAFE_MODE",
    "FLIP_BROKER_FLAG",
    "MUTATE_THRESHOLD",
    "PROMOTE_VARIANT",
    "OVERRIDE_GATE",
})

# ─── Recommendation enum (v3.29 ETAP 6) ────────────────────────────────────

ALLOWED_RECOMMENDATIONS: frozenset = frozenset({
    "ALLOW", "REVIEW", "WATCH", "CAUTION", "BLOCK_RECOMMENDED",
})

ALLOWED_RISK_LEVELS:  frozenset = frozenset({
    "LOW", "MEDIUM", "HIGH", "CRITICAL",
})

ALLOWED_CONFIDENCE_VALUES: frozenset = frozenset({"LOW", "MEDIUM", "HIGH"})

# ─── Standing markers ──────────────────────────────────────────────────────

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE",
    "NO_LLM_STATE_MUTATION",
)


# ─── Secret-redaction patterns ─────────────────────────────────────────────
#
# Anything that LOOKS like a secret must be replaced with ``[REDACTED]``
# before any LLM text is written to disk. Patterns are intentionally
# conservative — better to over-redact than to leak.

_SECRET_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    # OpenAI / Anthropic key prefixes (sk-ant-..., sk-...)
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"), "[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),   "[REDACTED]"),
    # GitHub tokens (gh_..., ghp_..., ghs_..., gho_..., github_pat_...)
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"),    "[REDACTED]"),
    (re.compile(r"\bghs_[A-Za-z0-9]{20,}"),    "[REDACTED]"),
    (re.compile(r"\bgho_[A-Za-z0-9]{20,}"),    "[REDACTED]"),
    (re.compile(r"\bgh_[A-Za-z0-9_]{20,}"),    "[REDACTED]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "[REDACTED]"),
    # Bare KEY=VALUE pairs for known secret env vars.
    (re.compile(
        r"\b(GEMINI_API_KEY|ANTHROPIC_API_KEY|OPENAI_API_KEY"
        r"|ALPACA_API_KEY|ALPACA_SECRET_KEY|GMAIL_APP_PASSWORD"
        r"|WORKFLOW_PAT|REDDIT_CLIENT_SECRET"
        r"|NEWSAPI_KEY|FINNHUB_API_KEY)\s*=\s*[^\s]+"),
     r"\1=[REDACTED]"),
    # Bare KEY: VALUE patterns (JSON-ish / YAML-ish leaks).
    (re.compile(
        r"\"(GEMINI_API_KEY|ANTHROPIC_API_KEY|OPENAI_API_KEY"
        r"|ALPACA_API_KEY|ALPACA_SECRET_KEY|GMAIL_APP_PASSWORD)\"\s*:\s*\"[^\"]+\""),
     r'"\1": "[REDACTED]"'),
    # Long uppercase alphanumeric tokens (Alpaca-shape).
    (re.compile(r"\b[A-Z0-9]{20,}\b"),         "[REDACTED]"),
)


def redact_secrets(text: str) -> str:
    """Return ``text`` with any plausible secret pattern replaced.

    NEVER raises. Always returns a string. If ``text`` is not a string
    it is coerced via ``str(...)``.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return ""
    out = text
    for pat, repl in _SECRET_PATTERNS:
        try:
            out = pat.sub(repl, out)
        except Exception:
            continue
    return out


# ─── LLMAdvisoryOutput dataclass ───────────────────────────────────────────

@dataclass(frozen=True)
class LLMAdvisoryOutput:
    """Canonical LLM advisory output schema (v3.29 ETAP 6).

    Every LLM advisory call in the v3.29 mesh constructs an instance
    of this dataclass. The instance is then passed through
    ``validate_output()`` (which delegates to ``__post_init__`` plus
    a top-level forbidden-token scan) BEFORE being written to disk.

    Required invariants (all enforced in ``__post_init__``):

    * ``agent_name`` must be in ``ADVISORY_ROLES``.
    * ``authority_level`` must be in ``ASSIGNABLE_AUTHORITY_LEVELS``
      (i.e. L0 or L1; L5 sentinel is rejected).
    * ``input_artifacts`` must be a tuple of strings (paths).
    * ``risk_level`` must be in ``ALLOWED_RISK_LEVELS``.
    * ``recommendation`` must be in ``ALLOWED_RECOMMENDATIONS``.
    * ``confidence`` must be in ``ALLOWED_CONFIDENCE_VALUES``.
    * ``advisory_only`` must be ``True``.
    * ``must_not_execute_orders`` must be ``True``.
    * ``veto_recommendation`` must be a bool — does NOT enforce
      anything; the deterministic gate stack decides.
    * ``findings`` / ``limitations`` are free-form strings; they are
      run through ``redact_secrets`` before being returned via
      ``to_dict()``.
    * No field value may contain any forbidden output token from
      ``FORBIDDEN_OUTPUTS``.
    """

    agent_name:              str
    authority_level:         str
    input_artifacts:         tuple
    findings:                str
    risk_level:              str
    recommendation:          str
    veto_recommendation:     bool
    confidence:              str
    limitations:             str
    must_not_execute_orders: bool = True
    advisory_only:           bool = True

    def __post_init__(self):
        # Agent name — must be a recognised advisory role.
        if self.agent_name not in ADVISORY_ROLES:
            raise ValueError(
                f"unknown agent_name={self.agent_name!r}; "
                f"must be one of {sorted(ADVISORY_ROLES)}")
        # Authority level — must be L0 or L1. L5 is rejected.
        if self.authority_level == AUTHORITY_LEVEL_EXECUTE_FORBIDDEN:
            raise ValueError(
                "L5_EXECUTE_FORBIDDEN is a sentinel and cannot be "
                "assigned to LLMAdvisoryOutput")
        if self.authority_level not in ASSIGNABLE_AUTHORITY_LEVELS:
            raise ValueError(
                f"authority_level={self.authority_level!r} not in "
                f"{sorted(ASSIGNABLE_AUTHORITY_LEVELS)}")
        # advisory_only / must_not_execute_orders — must be True.
        if self.advisory_only is not True:
            raise ValueError("advisory_only must be True")
        if self.must_not_execute_orders is not True:
            raise ValueError("must_not_execute_orders must be True")
        # input_artifacts — tuple of strings.
        if not isinstance(self.input_artifacts, tuple):
            raise ValueError("input_artifacts must be a tuple")
        for a in self.input_artifacts:
            if not isinstance(a, str):
                raise ValueError(
                    "input_artifacts must contain strings only")
        # Enum checks.
        if self.risk_level not in ALLOWED_RISK_LEVELS:
            raise ValueError(
                f"risk_level={self.risk_level!r} not in "
                f"{sorted(ALLOWED_RISK_LEVELS)}")
        if self.recommendation not in ALLOWED_RECOMMENDATIONS:
            raise ValueError(
                f"recommendation={self.recommendation!r} not in "
                f"{sorted(ALLOWED_RECOMMENDATIONS)}")
        if self.confidence not in ALLOWED_CONFIDENCE_VALUES:
            raise ValueError(
                f"confidence={self.confidence!r} not in "
                f"{sorted(ALLOWED_CONFIDENCE_VALUES)}")
        if not isinstance(self.veto_recommendation, bool):
            raise ValueError("veto_recommendation must be a bool")
        # Forbidden output token scan across every string field.
        _assert_no_forbidden_tokens(self)

    def to_dict(self) -> dict:
        """Return a dict with secret-redaction applied to free-form
        fields. NEVER raises."""
        d = asdict(self)
        # input_artifacts was a tuple — keep as list for JSON.
        d["input_artifacts"] = list(self.input_artifacts)
        d["findings"]    = redact_secrets(self.findings)
        d["limitations"] = redact_secrets(self.limitations)
        d["standing_markers"] = list(STANDING_MARKERS)
        return d


# ─── Validation helpers ────────────────────────────────────────────────────

def _assert_no_forbidden_tokens(payload) -> None:
    """Scan every string-bearing field for any FORBIDDEN_OUTPUTS token.

    Raises ``ValueError`` with the offending token name and field name.
    """
    if isinstance(payload, LLMAdvisoryOutput):
        fields_to_scan: list[tuple[str, str]] = [
            ("findings",       payload.findings),
            ("recommendation", payload.recommendation),
            ("limitations",    payload.limitations),
            ("risk_level",     payload.risk_level),
            ("agent_name",     payload.agent_name),
        ]
    elif isinstance(payload, dict):
        fields_to_scan = [
            (k, v) for k, v in payload.items()
            if isinstance(v, str)
        ]
    else:
        return
    for fname, value in fields_to_scan:
        if not isinstance(value, str):
            continue
        upper = value.upper()
        for tok in FORBIDDEN_OUTPUTS:
            if tok in upper:
                raise ValueError(
                    f"forbidden output token {tok!r} found in "
                    f"field {fname!r}")


def assert_no_execution_intent(payload: Any) -> None:
    """Raise ``ValueError`` if ``payload`` contains any
    ``FORBIDDEN_OUTPUTS`` token in any string field.

    Accepts ``LLMAdvisoryOutput`` or a plain dict.
    """
    _assert_no_forbidden_tokens(payload)


def validate_output(payload: Any) -> list[str]:
    """Validate a payload (dict or LLMAdvisoryOutput). Return list of
    error strings. Empty list means the payload is valid.

    NEVER raises; collects errors so the caller can decide whether to
    drop the row or surface diagnostics. ``LLMAdvisoryOutput``
    instances are validated against their own ``__post_init__``; a
    dict is validated field-by-field against the same rules.
    """
    errors: list[str] = []
    if isinstance(payload, LLMAdvisoryOutput):
        # Already validated in __post_init__ — re-scan forbidden tokens
        # belt-and-braces.
        try:
            _assert_no_forbidden_tokens(payload)
        except ValueError as e:
            errors.append(str(e))
        return errors
    if not isinstance(payload, dict):
        errors.append("payload must be a dict or LLMAdvisoryOutput")
        return errors
    required = (
        "agent_name", "authority_level", "input_artifacts",
        "findings", "risk_level", "recommendation",
        "veto_recommendation", "confidence", "limitations",
        "must_not_execute_orders", "advisory_only",
    )
    for k in required:
        if k not in payload:
            errors.append(f"missing required field: {k}")
    if errors:
        return errors
    # Forbidden-token scan first — catches "EXECUTE_ORDER" in any field.
    try:
        _assert_no_forbidden_tokens(payload)
    except ValueError as e:
        errors.append(str(e))
    # Enum / type checks.
    if payload["advisory_only"] is not True:
        errors.append("advisory_only must be True")
    if payload["must_not_execute_orders"] is not True:
        errors.append("must_not_execute_orders must be True")
    if payload["agent_name"] not in ADVISORY_ROLES:
        errors.append(
            f"unknown agent_name: {payload['agent_name']!r}")
    if payload["authority_level"] == AUTHORITY_LEVEL_EXECUTE_FORBIDDEN:
        errors.append(
            "L5_EXECUTE_FORBIDDEN is a sentinel and cannot appear")
    elif payload["authority_level"] not in ASSIGNABLE_AUTHORITY_LEVELS:
        errors.append(
            f"unknown authority_level: {payload['authority_level']!r}")
    if payload["risk_level"] not in ALLOWED_RISK_LEVELS:
        errors.append(f"unknown risk_level: {payload['risk_level']!r}")
    if payload["recommendation"] not in ALLOWED_RECOMMENDATIONS:
        errors.append(
            f"unknown recommendation: {payload['recommendation']!r}")
    if payload["confidence"] not in ALLOWED_CONFIDENCE_VALUES:
        errors.append(f"unknown confidence: {payload['confidence']!r}")
    if not isinstance(payload["veto_recommendation"], bool):
        errors.append("veto_recommendation must be bool")
    if not isinstance(payload["input_artifacts"], (list, tuple)):
        errors.append("input_artifacts must be a list/tuple")
    else:
        for a in payload["input_artifacts"]:
            if not isinstance(a, str):
                errors.append(
                    "input_artifacts must contain strings only")
                break
    return errors


def make_advisory_output(
    *,
    agent_name:          str,
    authority_level:     str = AUTHORITY_LEVEL_ADVISORY,
    input_artifacts:     Iterable[str] = (),
    findings:            str = "",
    risk_level:          str = "LOW",
    recommendation:      str = "REVIEW",
    veto_recommendation: bool = False,
    confidence:          str = "LOW",
    limitations:         str = "",
) -> LLMAdvisoryOutput:
    """Factory that builds an ``LLMAdvisoryOutput`` with the v3.29
    invariants (``advisory_only=True``, ``must_not_execute_orders=True``)
    forced on. Raises if invariants are violated.
    """
    return LLMAdvisoryOutput(
        agent_name=agent_name,
        authority_level=authority_level,
        input_artifacts=tuple(input_artifacts),
        findings=findings,
        risk_level=risk_level,
        recommendation=recommendation,
        veto_recommendation=bool(veto_recommendation),
        confidence=confidence,
        limitations=limitations,
        must_not_execute_orders=True,
        advisory_only=True,
    )


__all__ = [
    "ADVISORY_ROLES",
    "AUTHORITY_LEVEL_ADVISORY",
    "AUTHORITY_LEVEL_VETO_RECOMMEND",
    "AUTHORITY_LEVEL_EXECUTE_FORBIDDEN",
    "ASSIGNABLE_AUTHORITY_LEVELS",
    "FORBIDDEN_OUTPUTS",
    "ALLOWED_RECOMMENDATIONS",
    "ALLOWED_RISK_LEVELS",
    "ALLOWED_CONFIDENCE_VALUES",
    "STANDING_MARKERS",
    "LLMAdvisoryOutput",
    "redact_secrets",
    "validate_output",
    "assert_no_execution_intent",
    "make_advisory_output",
]
