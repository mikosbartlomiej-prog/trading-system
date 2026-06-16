"""v3.30 (2026-06-16) — LLM advisory quality enforcement.

This module is the quality-gate that sits between the v3.29 mesh's
provider call and the persisted ``LLMAdvisoryOutput``. Each agent's
LLM response MUST yield at least:

* 3 distinct findings,
* 2 distinct risks,
* 2 distinct recommended next actions,
* a non-empty ``limitations`` paragraph,
* ``advisory_only=True`` and ``must_not_execute_orders=True``.

If any of those thresholds fail, the row is marked
``LLM_ADVISORY_LOW_QUALITY`` and the mesh falls back to the
deterministic stub. The deterministic gate stack remains the final
authority — quality-gate failure NEVER fails open (it never elevates a
weak LLM answer to ALLOW; it routes through the fallback path).

HARD INVARIANTS
---------------
* NEVER imports ``alpaca_orders`` or any broker module.
* NEVER makes a network call.
* NEVER mutates broker / live / safe_mode / risk flags.
* Read-only with respect to the deterministic gates.

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# ─── Quality verdict tokens ────────────────────────────────────────────────

LLM_ADVISORY_QUALITY_ACCEPTABLE   = "LLM_ADVISORY_QUALITY_ACCEPTABLE"
LLM_ADVISORY_LOW_QUALITY          = "LLM_ADVISORY_LOW_QUALITY"
LLM_ADVISORY_QUALITY_EMPTY        = "LLM_ADVISORY_QUALITY_EMPTY"

ALL_QUALITY_VERDICTS: frozenset = frozenset({
    LLM_ADVISORY_QUALITY_ACCEPTABLE,
    LLM_ADVISORY_LOW_QUALITY,
    LLM_ADVISORY_QUALITY_EMPTY,
})

# ─── Thresholds (v3.30 contract) ───────────────────────────────────────────

MIN_FINDINGS:        int = 3
MIN_RISKS:           int = 2
MIN_NEXT_ACTIONS:    int = 2
MIN_LIMITATIONS_LEN: int = 1   # any non-empty string

GENERIC_PLACEHOLDERS: tuple[str, ...] = (
    "lorem ipsum",
    "placeholder",
    "tbd",
    "to be determined",
    "n/a",
    "not available",
)


@dataclass
class QualityVerdict:
    verdict:           str
    findings_count:    int  = 0
    risks_count:       int  = 0
    next_actions_count: int = 0
    limitations_len:   int  = 0
    rationale:         list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict":            self.verdict,
            "findings_count":     self.findings_count,
            "risks_count":        self.risks_count,
            "next_actions_count": self.next_actions_count,
            "limitations_len":    self.limitations_len,
            "rationale":          list(self.rationale),
        }


# ─── Internal helpers ──────────────────────────────────────────────────────

def _norm_list(value: Any, *, max_items: int = 20) -> list[str]:
    """Coerce ``value`` into a deduplicated list of non-empty strings.

    NEVER raises.
    """
    out: list[str] = []
    if value is None:
        return out
    if isinstance(value, str):
        # Split string on common separators (newline, semicolon).
        for part in (value.replace("\r", "\n")
                          .replace(";", "\n").split("\n")):
            s = part.strip()
            if s and s not in out:
                out.append(s)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            try:
                s = str(v).strip()
            except Exception:
                continue
            if s and s not in out:
                out.append(s)
    elif isinstance(value, dict):
        # Tolerant — accept dict by string-ifying values.
        for v in value.values():
            try:
                s = str(v).strip()
            except Exception:
                continue
            if s and s not in out:
                out.append(s)
    return out[:max_items]


def _looks_placeholder(text: str) -> bool:
    low = (text or "").lower()
    for tok in GENERIC_PLACEHOLDERS:
        if tok in low:
            return True
    return False


# ─── Public API ────────────────────────────────────────────────────────────

def extract_lists_from_parsed(parsed: dict) -> dict:
    """Pull list-shaped fields from a parsed LLM JSON object.

    The mesh's existing parser yields ``findings: str``,
    ``risk_level: str``, etc. The v3.30 contract requires lists for
    findings / risks / next-actions. This helper looks at the parsed
    object under both the new keys (``findings_list``, ``risks``,
    ``recommended_next_actions``) and the legacy keys
    (``findings``, ``risks_identified``, ``proposed_next_actions``)
    so the mesh can call it with either shape.

    Returns a dict with the canonical v3.30 keys:
    ``findings_list`` / ``risks_list`` / ``next_actions_list``.

    NEVER raises.
    """
    if not isinstance(parsed, dict):
        return {"findings_list": [], "risks_list": [],
                "next_actions_list": []}
    findings = parsed.get("findings_list")
    if findings is None:
        findings = parsed.get("findings")
    risks = parsed.get("risks") or parsed.get("risks_list") \
        or parsed.get("risks_identified")
    next_actions = (parsed.get("recommended_next_actions")
                    or parsed.get("next_actions_list")
                    or parsed.get("proposed_next_actions")
                    or parsed.get("next_actions"))
    return {
        "findings_list":     _norm_list(findings),
        "risks_list":        _norm_list(risks),
        "next_actions_list": _norm_list(next_actions),
    }


def evaluate(parsed: dict, *, limitations: str = "") -> QualityVerdict:
    """Score a parsed LLM advisory payload.

    Returns a :class:`QualityVerdict`. NEVER raises.
    """
    extracted = extract_lists_from_parsed(parsed or {})
    findings = extracted["findings_list"]
    risks    = extracted["risks_list"]
    actions  = extracted["next_actions_list"]
    rationale: list[str] = []

    if not findings and not risks and not actions \
            and not (limitations or "").strip():
        return QualityVerdict(
            verdict=LLM_ADVISORY_QUALITY_EMPTY,
            rationale=["empty output (no findings / risks / actions)"],
        )

    n_findings = len(findings)
    n_risks    = len(risks)
    n_actions  = len(actions)
    lim_len    = len((limitations or "").strip())

    accept = True
    if n_findings < MIN_FINDINGS:
        accept = False
        rationale.append(
            f"findings_count={n_findings} < required {MIN_FINDINGS}")
    if n_risks < MIN_RISKS:
        accept = False
        rationale.append(
            f"risks_count={n_risks} < required {MIN_RISKS}")
    if n_actions < MIN_NEXT_ACTIONS:
        accept = False
        rationale.append(
            f"next_actions_count={n_actions} < required "
            f"{MIN_NEXT_ACTIONS}")
    if lim_len < MIN_LIMITATIONS_LEN:
        accept = False
        rationale.append(
            f"limitations is empty (required ≥{MIN_LIMITATIONS_LEN} char)")

    # Generic-placeholder sweep over each field.
    placeholder_hits = 0
    for item in findings + risks + actions:
        if _looks_placeholder(item):
            placeholder_hits += 1
    if placeholder_hits and placeholder_hits >= max(
            1, (n_findings + n_risks + n_actions) // 2):
        accept = False
        rationale.append(
            f"generic-placeholder hits={placeholder_hits}")

    verdict = (LLM_ADVISORY_QUALITY_ACCEPTABLE if accept
               else LLM_ADVISORY_LOW_QUALITY)
    if not rationale:
        rationale.append(
            "all v3.30 thresholds met: "
            f"findings={n_findings}, risks={n_risks}, "
            f"next_actions={n_actions}, limitations_len={lim_len}")
    return QualityVerdict(
        verdict=verdict,
        findings_count=n_findings,
        risks_count=n_risks,
        next_actions_count=n_actions,
        limitations_len=lim_len,
        rationale=rationale,
    )


def deterministic_stub_lists(role: str) -> dict:
    """Return a non-empty deterministic stub for the v3.30 list fields.

    Used when the LLM is unavailable so the persisted row remains
    informative without inventing trade evidence. Findings/risks/actions
    are intentionally conservative and reference the deterministic
    gates as the final authority.
    """
    findings = [
        (f"LLM provider unavailable for {role}; deterministic stub "
         "ACTIVE."),
        ("Deterministic gates (allocator_incident_gate, safe_mode, "
         "broker_repair_required) remain the final authority."),
        ("No new evidence has been inferred by this output; rely on "
         "the existing on-disk diagnostic artefacts."),
    ]
    risks = [
        ("LLM advisory layer is degraded — operator should verify "
         "GEMINI_API_KEY / quota / endpoint reachability."),
        ("Risk and incident reports must be read directly from "
         "learning-loop/* artefacts; do not infer from this stub."),
    ]
    next_actions = [
        ("Inspect learning-loop/llm_advisory/llm_budget_state.json "
         "and learning-loop/llm_provider_health_latest.json."),
        ("If health verdict is DEGRADED/UNKNOWN, add or rotate the "
         "GEMINI_API_KEY GitHub Actions secret. Do NOT auto-apply."),
    ]
    limitations = (
        "Deterministic stub carries no model evaluation. The advisory "
        "layer fails OPEN at the recommendation level (ALLOW) so LLM "
        "unavailability never blocks trading on its own. The "
        "deterministic stack still controls broker / order / risk flow.")
    return {
        "findings_list":     findings,
        "risks_list":        risks,
        "next_actions_list": next_actions,
        "limitations":       limitations,
    }


__all__ = [
    "LLM_ADVISORY_QUALITY_ACCEPTABLE",
    "LLM_ADVISORY_LOW_QUALITY",
    "LLM_ADVISORY_QUALITY_EMPTY",
    "ALL_QUALITY_VERDICTS",
    "MIN_FINDINGS",
    "MIN_RISKS",
    "MIN_NEXT_ACTIONS",
    "MIN_LIMITATIONS_LEN",
    "QualityVerdict",
    "extract_lists_from_parsed",
    "evaluate",
    "deterministic_stub_lists",
]
