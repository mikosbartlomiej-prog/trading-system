"""v3.28.3 (2026-06-09) — LLM advisory output quality guard.

Inspects a batch of v3.28.x advisory rows and returns a deterministic
quality verdict. The guard is consumed by
``scripts/run_llm_advisory_mesh.py`` after generation so the runner can
write a ``quality_status`` alongside the standard mesh status.

HARD SAFETY
-----------
- NEVER imports the broker-orders module.
- NEVER submits orders or mutates trading state.
- NEVER counts advisory output as real-market evidence.
- Only inspects the rows; never modifies them on disk.
- Secret-shaped tokens in any row block the batch and return
  ``LLM_ADVISORY_QUALITY_SECRET_LEAK_BLOCKED``.
- Unsafe action-suggestion tokens (e.g. "enable broker paper")
  block the batch and return ``LLM_ADVISORY_QUALITY_UNSAFE_BLOCKED``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# ─── Quality status enum ────────────────────────────────────────────────────

LLM_ADVISORY_QUALITY_ACCEPTABLE                = (
    "LLM_ADVISORY_QUALITY_ACCEPTABLE")
LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER       = (
    "LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER")
LLM_ADVISORY_QUALITY_PROVIDER_OUTPUT_NOT_USED  = (
    "LLM_ADVISORY_QUALITY_PROVIDER_OUTPUT_NOT_USED")
LLM_ADVISORY_QUALITY_SCHEMA_INVALID            = (
    "LLM_ADVISORY_QUALITY_SCHEMA_INVALID")
LLM_ADVISORY_QUALITY_SECRET_LEAK_BLOCKED       = (
    "LLM_ADVISORY_QUALITY_SECRET_LEAK_BLOCKED")
LLM_ADVISORY_QUALITY_UNSAFE_BLOCKED            = (
    "LLM_ADVISORY_QUALITY_UNSAFE_BLOCKED")
LLM_ADVISORY_QUALITY_INSUFFICIENT_SAMPLE       = (
    "LLM_ADVISORY_QUALITY_INSUFFICIENT_SAMPLE")
# v3.29.1 — finer-grained "empty analysis" / "no evidence dict" modes.
LLM_ADVISORY_QUALITY_EMPTY_ANALYSIS            = (
    "LLM_ADVISORY_QUALITY_EMPTY_ANALYSIS")
LLM_ADVISORY_QUALITY_NO_EVIDENCE_VALUES_USED   = (
    "LLM_ADVISORY_QUALITY_NO_EVIDENCE_VALUES_USED")

ALL_QUALITY_STATUSES: frozenset[str] = frozenset({
    LLM_ADVISORY_QUALITY_ACCEPTABLE,
    LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER,
    LLM_ADVISORY_QUALITY_PROVIDER_OUTPUT_NOT_USED,
    LLM_ADVISORY_QUALITY_SCHEMA_INVALID,
    LLM_ADVISORY_QUALITY_SECRET_LEAK_BLOCKED,
    LLM_ADVISORY_QUALITY_UNSAFE_BLOCKED,
    LLM_ADVISORY_QUALITY_INSUFFICIENT_SAMPLE,
    LLM_ADVISORY_QUALITY_EMPTY_ANALYSIS,
    LLM_ADVISORY_QUALITY_NO_EVIDENCE_VALUES_USED,
})

# Statuses for which the runner MUST NOT commit the produced rows.
BLOCKING_STATUSES: frozenset[str] = frozenset({
    LLM_ADVISORY_QUALITY_SECRET_LEAK_BLOCKED,
    LLM_ADVISORY_QUALITY_UNSAFE_BLOCKED,
})


# ─── Generic-placeholder signatures ────────────────────────────────────────

_PLACEHOLDER_PHRASES: tuple[str, ...] = (
    "OBSERVATION: advisory mesh ran",
    "no execution; agent=",
    "v3.28 advisory output. Deterministic gates remain",
    "advisory_only — no provider call performed",
)

# Tokens that, if present in `recommendation` / `rationale` /
# `proposed_next_actions`, indicate the provider is suggesting an
# unsafe action. We block the batch — the deterministic gates remain
# final, but we will not even archive a suggestion to break them.
_UNSAFE_PHRASES: tuple[str, ...] = (
    "enable broker paper",
    "enable live trading",
    "set EDGE_GATE_ENABLED=true",
    "set ALLOW_BROKER_PAPER=true",
    "set BROKER_EXECUTION_ENABLED=true",
    "reset the baseline",
    "lower the drawdown guard",
    "place an order",
    "submit_order",
    "place_order",
    "safe_close",
)

# Secret-shape patterns: Google AI Studio key (AIza...), Anthropic
# sk-ant-* tokens, OpenAI sk-* tokens, 20+ char uppercase-alphanumeric
# runs.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{8,}"),
    re.compile(r"\b[A-Z0-9]{20,}\b"),
)


@dataclass
class QualityReport:
    status:                       str
    rows_seen:                    int = 0
    rows_with_provider_used:      int = 0
    rows_with_provider_skipped:   int = 0
    rows_with_provider_failed:    int = 0
    generic_placeholder_count:    int = 0
    empty_risks_count:            int = 0
    empty_next_actions_count:     int = 0
    zero_confidence_count:        int = 0
    confidence_min:               float = 1.0
    confidence_max:               float = 0.0
    secret_leak_hits:             int = 0
    unsafe_phrase_hits:           int = 0
    rationale:                    list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status":                     self.status,
            "rows_seen":                  self.rows_seen,
            "rows_with_provider_used":    self.rows_with_provider_used,
            "rows_with_provider_skipped": self.rows_with_provider_skipped,
            "rows_with_provider_failed":  self.rows_with_provider_failed,
            "generic_placeholder_count":  self.generic_placeholder_count,
            "empty_risks_count":          self.empty_risks_count,
            "empty_next_actions_count":   self.empty_next_actions_count,
            "zero_confidence_count":      self.zero_confidence_count,
            "confidence_min":             round(self.confidence_min, 4),
            "confidence_max":             round(self.confidence_max, 4),
            "secret_leak_hits":           self.secret_leak_hits,
            "unsafe_phrase_hits":         self.unsafe_phrase_hits,
            "rationale":                  list(self.rationale),
        }


def _row_text_blob(row: dict) -> str:
    """Concatenate the operator-visible string fields for pattern
    scanning."""
    parts: list[str] = []
    for k in ("recommendation", "rationale"):
        v = row.get(k)
        if isinstance(v, str):
            parts.append(v)
    for k in ("risks_identified", "proposed_next_actions"):
        v = row.get(k)
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
    return " ".join(parts)


def _hits_secret_pattern(text: str) -> int:
    if not text:
        return 0
    total = 0
    for pat in _SECRET_PATTERNS:
        for m in pat.findall(text):
            tok = m if isinstance(m, str) else (
                m[0] if m else "")
            # Filter out enum tokens (uppercase + underscores).
            if tok.replace("_", "").replace("-", "").isalnum() and \
                  ("_" in tok or "-" in tok):
                continue
            total += 1
    return total


def _hits_unsafe_phrase(text: str) -> int:
    if not text:
        return 0
    lower = text.lower()
    return sum(1 for p in _UNSAFE_PHRASES if p.lower() in lower)


def _is_generic_placeholder_row(row: dict) -> bool:
    blob = _row_text_blob(row)
    for phrase in _PLACEHOLDER_PHRASES:
        if phrase in blob:
            return True
    return False


# ─── Public API ────────────────────────────────────────────────────────────

def evaluate_quality(rows: Iterable[dict],
                       *,
                       min_acceptable_rows: int = 3) -> QualityReport:
    """Inspect a batch of advisory rows and return a QualityReport.

    Precedence:
    1. Any secret-shape hit → SECRET_LEAK_BLOCKED.
    2. Any unsafe-phrase hit → UNSAFE_BLOCKED.
    3. Schema-missing fields (required keys absent) → SCHEMA_INVALID.
    4. No rows OR fewer than ``min_acceptable_rows`` → INSUFFICIENT_SAMPLE.
    5. >50% generic placeholder OR every row has empty risks +
       empty next actions + 0.0 confidence → GENERIC_PLACEHOLDER.
    6. Every row carries `provider_status` ∈
       {PROVIDER_SKIPPED_DISABLED, PROVIDER_FAILED_FAIL_SOFT} →
       PROVIDER_OUTPUT_NOT_USED.
    7. Otherwise → ACCEPTABLE.
    """
    rows_list = list(rows or [])
    rep = QualityReport(
        status=LLM_ADVISORY_QUALITY_ACCEPTABLE,
        rows_seen=len(rows_list),
        confidence_min=1.0, confidence_max=0.0,
    )
    if rep.rows_seen == 0:
        rep.status = LLM_ADVISORY_QUALITY_INSUFFICIENT_SAMPLE
        rep.rationale.append("no rows produced")
        return rep

    REQUIRED = ("recommendation", "rationale", "risks_identified",
                 "proposed_next_actions", "confidence",
                 "advisory_only", "may_execute",
                 "broker_order_submitted",
                 "affects_readiness_gate")
    schema_invalid = False
    for r in rows_list:
        if not isinstance(r, dict):
            schema_invalid = True
            break
        for k in REQUIRED:
            if k not in r:
                schema_invalid = True
                break
        if schema_invalid:
            break
    if schema_invalid:
        rep.status = LLM_ADVISORY_QUALITY_SCHEMA_INVALID
        rep.rationale.append("at least one row missing required fields")
        return rep

    for r in rows_list:
        blob = _row_text_blob(r)
        sec = _hits_secret_pattern(blob)
        rep.secret_leak_hits += sec
        unsafe = _hits_unsafe_phrase(blob)
        rep.unsafe_phrase_hits += unsafe
        if _is_generic_placeholder_row(r):
            rep.generic_placeholder_count += 1
        risks = r.get("risks_identified") or []
        if not risks:
            rep.empty_risks_count += 1
        actions = r.get("proposed_next_actions") or []
        if not actions:
            rep.empty_next_actions_count += 1
        try:
            c = float(r.get("confidence", 0.0))
        except (TypeError, ValueError):
            c = 0.0
        if c <= 0.0:
            rep.zero_confidence_count += 1
        rep.confidence_min = min(rep.confidence_min, c)
        rep.confidence_max = max(rep.confidence_max, c)
        prov = r.get("provider_status") or ""
        if prov == "PROVIDER_USED":
            rep.rows_with_provider_used += 1
        elif prov == "PROVIDER_SKIPPED_DISABLED":
            rep.rows_with_provider_skipped += 1
        elif prov == "PROVIDER_FAILED_FAIL_SOFT":
            rep.rows_with_provider_failed += 1

    if rep.secret_leak_hits > 0:
        rep.status = LLM_ADVISORY_QUALITY_SECRET_LEAK_BLOCKED
        rep.rationale.append(
            f"{rep.secret_leak_hits} secret-shape token(s) found")
        return rep
    if rep.unsafe_phrase_hits > 0:
        rep.status = LLM_ADVISORY_QUALITY_UNSAFE_BLOCKED
        rep.rationale.append(
            f"{rep.unsafe_phrase_hits} unsafe-action phrase(s) found")
        return rep
    if rep.rows_seen < min_acceptable_rows:
        rep.status = LLM_ADVISORY_QUALITY_INSUFFICIENT_SAMPLE
        rep.rationale.append(
            f"only {rep.rows_seen} rows; need ≥{min_acceptable_rows}")
        return rep

    # Provider never used at all → distinguish from generic placeholder.
    if (rep.rows_with_provider_used == 0
            and (rep.rows_with_provider_skipped
                  + rep.rows_with_provider_failed)
                  == rep.rows_seen):
        rep.status = LLM_ADVISORY_QUALITY_PROVIDER_OUTPUT_NOT_USED
        rep.rationale.append(
            "no row carried PROVIDER_USED — provider output was not "
            "incorporated")
        return rep

    # v3.29.1 — empty-analysis precedence BEFORE genericness:
    # all-empty rows is a strictly stronger signal than placeholder
    # phrases.
    all_empty_quality = (
        rep.empty_risks_count == rep.rows_seen
        and rep.empty_next_actions_count == rep.rows_seen
        and rep.zero_confidence_count == rep.rows_seen)
    if all_empty_quality:
        rep.status = LLM_ADVISORY_QUALITY_EMPTY_ANALYSIS
        rep.rationale.append(
            "all rows have empty risks_identified + empty "
            "proposed_next_actions + zero confidence")
        return rep
    # Genericness check: >50% rows match a placeholder phrase.
    half = rep.rows_seen / 2.0
    if rep.generic_placeholder_count > half:
        rep.status = LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER
        rep.rationale.append(
            f"{rep.generic_placeholder_count}/{rep.rows_seen} rows look "
            f"like generic placeholder; empty-risks="
            f"{rep.empty_risks_count}; empty-next="
            f"{rep.empty_next_actions_count}; "
            f"zero-conf={rep.zero_confidence_count}")
        return rep

    # v3.29.1 — evidence-values gate: not a hard fail, but if NO row
    # carries an evidence_values_used dict with at least one key,
    # downgrade to NO_EVIDENCE_VALUES_USED so the operator knows
    # the model did not ground its analysis in the evidence.
    rows_seen = rep.rows_seen
    rows_with_evidence_values = sum(
        1 for r in rows_list
        if isinstance(r.get("evidence_values_used"), dict)
        and r["evidence_values_used"])
    if rows_with_evidence_values == 0:
        rep.status = LLM_ADVISORY_QUALITY_NO_EVIDENCE_VALUES_USED
        rep.rationale.append(
            "no row populated evidence_values_used — model output is "
            "not grounded in the evidence dict")
        return rep

    rep.status = LLM_ADVISORY_QUALITY_ACCEPTABLE
    rep.rationale.append(
        f"{rep.rows_with_provider_used} row(s) carried PROVIDER_USED; "
        f"confidence range "
        f"[{rep.confidence_min:.2f}, {rep.confidence_max:.2f}]; "
        f"{rows_with_evidence_values}/{rows_seen} rows populated "
        f"evidence_values_used")
    return rep


__all__ = [
    "LLM_ADVISORY_QUALITY_ACCEPTABLE",
    "LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER",
    "LLM_ADVISORY_QUALITY_PROVIDER_OUTPUT_NOT_USED",
    "LLM_ADVISORY_QUALITY_SCHEMA_INVALID",
    "LLM_ADVISORY_QUALITY_SECRET_LEAK_BLOCKED",
    "LLM_ADVISORY_QUALITY_UNSAFE_BLOCKED",
    "LLM_ADVISORY_QUALITY_INSUFFICIENT_SAMPLE",
    "ALL_QUALITY_STATUSES", "BLOCKING_STATUSES",
    "QualityReport", "evaluate_quality",
]
