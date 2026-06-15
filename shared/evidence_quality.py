"""v3.24 ETAP 11 — Per-row evidence quality scorer (NO-NETWORK).

Scores a single opportunity_ledger row for evidence quality on a
0–100 integer scale and assigns a coarse label
(``GARBAGE`` / ``MARGINAL`` / ``USABLE`` / ``HIGH_QUALITY``).

This module exists so the learning loop can rank rows by how
trustworthy their evidence is BEFORE feeding them into the unlock
gate. A 100% default-component confidence is technically "computed"
but provides zero information; the scorer penalises such rows
heavily.

HARD SAFETY
-----------
- NEVER imports ``shared.alpaca_orders`` or ``alpaca_orders``.
- NEVER imports any broker SDK.
- NEVER imports ``requests``, ``urllib``, or other network libraries.
- NEVER calls a broker / submits an order. This module is pure
  arithmetic over a single ``dict`` row.
- NEVER mutates the row it inspects.
- Scoring is advisory; a HIGH_QUALITY label DOES NOT, by itself,
  authorise a trade. EDGE_GATE_ENABLED, ALLOW_BROKER_PAPER, and
  every live-trading flag remain false at all times.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


# ─── Tunables ──────────────────────────────────────────────────────


#: Maximum possible score. Total of all bonus points exceeds 100 so
#: the scorer clamps to [0, 100]. Penalties may push below zero
#: pre-clamp; the clamp re-floors to 0.
MAX_SCORE: int = 100

#: Bonus point values. Keys are stable strings used in the
#: ``bonuses`` dict on the result. The sum is intentionally larger
#: than 100 so a well-populated row earns the max even if one
#: bonus is absent.
BONUS_POINTS: dict[str, int] = {
    # Top-level row quality.
    "evidence_quality_real_market_data": 15,
    "source_monitor_present":            10,
    "strategy_id_present":               10,
    "audit_link_populated":              5,
    # Confidence.
    "confidence_score_present":          20,
    "confidence_components_non_empty":   15,
    "confidence_components_real_data":   10,   # default-reasons coverage <50%
    # Risk and gates.
    "risk_decision_present":             10,
    "gate_decisions_non_empty":          5,
}

#: Penalty point values. Same key convention as ``BONUS_POINTS``.
PENALTY_POINTS: dict[str, int] = {
    "all_components_default_0_5":          15,
    "missing_source_or_strategy":          10,
    "evidence_quality_halt_path_only":     5,
    "evidence_quality_scaffold_no_market_data": 10,
}

#: Label thresholds. Values are inclusive upper bounds for each
#: label EXCEPT ``HIGH_QUALITY`` which is the catch-all above
#: ``USABLE_MAX``.
LABEL_GARBAGE_MAX:  int = 25
LABEL_MARGINAL_MAX: int = 50
LABEL_USABLE_MAX:   int = 75

LABEL_GARBAGE:      str = "GARBAGE"
LABEL_MARGINAL:     str = "MARGINAL"
LABEL_USABLE:       str = "USABLE"
LABEL_HIGH_QUALITY: str = "HIGH_QUALITY"

ALL_LABELS: tuple[str, ...] = (
    LABEL_GARBAGE,
    LABEL_MARGINAL,
    LABEL_USABLE,
    LABEL_HIGH_QUALITY,
)


# ─── Result dataclass ──────────────────────────────────────────────


@dataclass(frozen=True)
class EvidenceQualityScore:
    """One immutable scoring result per row."""

    row_id:    str
    score:     int                     # 0..100 inclusive
    bonuses:   dict[str, int] = field(default_factory=dict)
    penalties: dict[str, int] = field(default_factory=dict)
    label:     str           = LABEL_GARBAGE

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_id":    self.row_id,
            "score":     self.score,
            "label":     self.label,
            "bonuses":   dict(self.bonuses),
            "penalties": dict(self.penalties),
        }


# ─── Helpers ───────────────────────────────────────────────────────


def _str_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _is_non_empty_string(v: Any) -> bool:
    return bool(_str_value(v))


def _is_non_empty_mapping(v: Any) -> bool:
    return isinstance(v, Mapping) and len(v) > 0


def _is_non_empty_list(v: Any) -> bool:
    return isinstance(v, (list, tuple)) and len(v) > 0


def _label_for(score: int) -> str:
    if score <= LABEL_GARBAGE_MAX:
        return LABEL_GARBAGE
    if score <= LABEL_MARGINAL_MAX:
        return LABEL_MARGINAL
    if score <= LABEL_USABLE_MAX:
        return LABEL_USABLE
    return LABEL_HIGH_QUALITY


def _all_components_default_half(components: Mapping[str, Any]) -> bool:
    """True iff every component score is exactly 0.5 (the default).

    A row whose confidence was computed from 100% default inputs is
    not zero, but it carries no real information either. We treat
    that as a penalty so the unlock gate does not promote pure
    scaffolding rows.
    """
    if not components:
        return False
    n = 0
    half = 0
    for v in components.values():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        n += 1
        if abs(f - 0.5) < 1e-9:
            half += 1
    return n > 0 and half == n


def _row_id_of(row: Mapping[str, Any]) -> str:
    sid = row.get("signal_id")
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    sym = row.get("symbol")
    ts  = row.get("timestamp")
    return f"{sym or '?'}:{ts or '?'}"


# ─── Public API ───────────────────────────────────────────────────


def score_row(row: Mapping[str, Any] | None) -> EvidenceQualityScore:
    """Score a single opportunity_ledger row.

    Pure function. NEVER raises (fail-soft on malformed input).
    NEVER mutates ``row``. NEVER calls a broker / network.

    Bonuses (positive):

    - ``+15`` ``row.evidence_quality == "REAL_MARKET_DATA"`` (top-level OR raw_signal)
    - ``+10`` ``source_monitor`` present (top-level OR raw_signal)
    - ``+10`` ``strategy_id`` present (top-level OR raw_signal)
    - ``+5``  ``audit_link`` populated
    - ``+20`` ``confidence_score`` not null
    - ``+15`` ``confidence_components`` non-empty
    - ``+10`` ``confidence_default_reasons`` covers <50% of components
    - ``+10`` ``risk_decision`` present
    - ``+5``  ``gate_decisions`` list non-empty

    Penalties (negative):

    - ``-15`` all confidence components default 0.5
    - ``-10`` ``source_monitor`` or ``strategy_id`` missing
    - ``-5``  ``evidence_quality == "HALT_PATH_ONLY"``
    - ``-10`` ``evidence_quality == "SCAFFOLD_NO_MARKET_DATA"``

    Final score is clamped to ``[0, 100]``; label is derived from the
    clamped score using ``LABEL_*_MAX`` thresholds.
    """
    if not isinstance(row, Mapping):
        return EvidenceQualityScore(
            row_id="?",
            score=0,
            bonuses={},
            penalties={"row_not_mapping": 0},
            label=LABEL_GARBAGE,
        )

    raw = row.get("raw_signal")
    if not isinstance(raw, Mapping):
        raw = {}

    bonuses:   dict[str, int] = {}
    penalties: dict[str, int] = {}

    # ── evidence_quality (top-level or raw_signal) ────────────────
    eq = row.get("evidence_quality") or raw.get("evidence_quality")
    eq_str = (eq or "").strip().upper() if isinstance(eq, str) else ""

    if eq_str == "REAL_MARKET_DATA":
        bonuses["evidence_quality_real_market_data"] = (
            BONUS_POINTS["evidence_quality_real_market_data"])
    elif eq_str == "HALT_PATH_ONLY":
        penalties["evidence_quality_halt_path_only"] = (
            PENALTY_POINTS["evidence_quality_halt_path_only"])
    elif eq_str == "SCAFFOLD_NO_MARKET_DATA":
        penalties["evidence_quality_scaffold_no_market_data"] = (
            PENALTY_POINTS["evidence_quality_scaffold_no_market_data"])

    # ── source_monitor / strategy_id presence ──────────────────────
    has_source = (
        _is_non_empty_string(row.get("source_monitor"))
        or _is_non_empty_string(raw.get("source_monitor"))
    )
    has_strategy = (
        _is_non_empty_string(row.get("strategy_id"))
        or _is_non_empty_string(row.get("strategy"))
        or _is_non_empty_string(raw.get("strategy_id"))
        or _is_non_empty_string(raw.get("strategy"))
    )

    if has_source:
        bonuses["source_monitor_present"] = BONUS_POINTS["source_monitor_present"]
    if has_strategy:
        bonuses["strategy_id_present"] = BONUS_POINTS["strategy_id_present"]
    if (not has_source) or (not has_strategy):
        penalties["missing_source_or_strategy"] = (
            PENALTY_POINTS["missing_source_or_strategy"])

    # ── audit_link ────────────────────────────────────────────────
    if _is_non_empty_string(row.get("audit_link")):
        bonuses["audit_link_populated"] = BONUS_POINTS["audit_link_populated"]

    # ── confidence_score ──────────────────────────────────────────
    cs = row.get("confidence_score")
    if cs is None:
        cs = raw.get("confidence_score")
    if cs is not None:
        try:
            float(cs)
            bonuses["confidence_score_present"] = (
                BONUS_POINTS["confidence_score_present"])
        except (TypeError, ValueError):
            pass

    # ── confidence_components ─────────────────────────────────────
    components = row.get("confidence_components")
    if not isinstance(components, Mapping):
        components = raw.get("confidence_components")
    if not isinstance(components, Mapping):
        components = {}

    if _is_non_empty_mapping(components):
        bonuses["confidence_components_non_empty"] = (
            BONUS_POINTS["confidence_components_non_empty"])

        # Default-reasons coverage bonus (real data on most components)
        default_reasons = raw.get("confidence_default_reasons")
        if isinstance(default_reasons, Mapping):
            if len(default_reasons) < (len(components) / 2.0):
                bonuses["confidence_components_real_data"] = (
                    BONUS_POINTS["confidence_components_real_data"])
        else:
            # No default_reasons at all → assume real data.
            bonuses["confidence_components_real_data"] = (
                BONUS_POINTS["confidence_components_real_data"])

        # 100% default 0.5 penalty.
        if _all_components_default_half(components):
            penalties["all_components_default_0_5"] = (
                PENALTY_POINTS["all_components_default_0_5"])

    # ── risk_decision ─────────────────────────────────────────────
    if _is_non_empty_string(row.get("risk_decision")):
        bonuses["risk_decision_present"] = BONUS_POINTS["risk_decision_present"]

    # ── gate_decisions ────────────────────────────────────────────
    if _is_non_empty_list(row.get("gate_decisions")):
        bonuses["gate_decisions_non_empty"] = (
            BONUS_POINTS["gate_decisions_non_empty"])

    # ── tally ─────────────────────────────────────────────────────
    raw_score = sum(bonuses.values()) - sum(penalties.values())
    score = max(0, min(MAX_SCORE, raw_score))

    return EvidenceQualityScore(
        row_id=_row_id_of(row),
        score=score,
        bonuses=dict(bonuses),
        penalties=dict(penalties),
        label=_label_for(score),
    )


__all__ = [
    "EvidenceQualityScore",
    "score_row",
    "MAX_SCORE",
    "BONUS_POINTS",
    "PENALTY_POINTS",
    "LABEL_GARBAGE",
    "LABEL_MARGINAL",
    "LABEL_USABLE",
    "LABEL_HIGH_QUALITY",
    "LABEL_GARBAGE_MAX",
    "LABEL_MARGINAL_MAX",
    "LABEL_USABLE_MAX",
    "ALL_LABELS",
]
