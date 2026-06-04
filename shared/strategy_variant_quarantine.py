"""v3.20.0 (2026-06-04) — ETAP 6 — Strategy Variant Quarantine.

WHY
---
Audit-board 2026-06-02 verdict remained `NOT_SAFE_FOR_LIVE_TRADING` /
`APPROVE_PAPER_TRADING_WITH_WARNINGS`. The system has no empirical
edge yet. Operators (and learning-loop heuristics) keep proposing
strategy *variants* — tweaks to thresholds, regime filters, confidence
caps, exit rules, cooldowns, universe filters. Without a hard
quarantine boundary those tweaks risk silently mutating the active
strategy registry the runtime trading path reads.

This module establishes a quarantine zone for strategy variants. A
variant is a SHADOW description of a proposed change. It is NEVER
loaded by the runtime trading path. It does NOT raise risk. It is
PERSISTED to disk in `learning-loop/variant_quarantine/<id>.json` so
that learning-loop and the experiment scheduler (ETAP 7) can read it
later for replay / observe-only purposes.

The accepted override fields are deliberately narrow — only the
declared whitelist is allowed:

    threshold, regime_filter, confidence_cap, universe_filter,
    exit_rule, cooldown

Anything else is silently dropped (with an audit emission). The
status enum is closed and never contains LIVE_APPROVED.

CONTRACT
--------
- register_variant(parent_strategy, change_rationale, params, ...) →
  dict (the persisted variant record).
- list_variants() / load_quarantined_variants() / get_variant(id) /
  set_status(id, new_status).
- Variants never enter `shared/strategy_quality_gate.py` active set.
  `load_quarantined_variants` is the ONLY reader and the runtime
  trading path does NOT import this module.
- evidence_source must be REPLAY or BACKTEST. PAPER is rejected.

FREE OPERATION
--------------
Pure stdlib. No network. No paid APIs. Deterministic id derivation.
Fail-soft audit emission.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


# ─── Module location bootstrap ────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─── Closed status enum ──────────────────────────────────────────────────────

QUARANTINED                  = "QUARANTINED"
REPLAY_TESTING               = "REPLAY_TESTING"
SHADOW_OBSERVE               = "SHADOW_OBSERVE"
REJECTED                     = "REJECTED"
CANDIDATE_FOR_MANUAL_REVIEW  = "CANDIDATE_FOR_MANUAL_REVIEW"

ALL_STATUSES: frozenset[str] = frozenset({
    QUARANTINED,
    REPLAY_TESTING,
    SHADOW_OBSERVE,
    REJECTED,
    CANDIDATE_FOR_MANUAL_REVIEW,
})

# Live-trading status DOES NOT EXIST here. By construction.
# See ETAP 6 contract: NO LIVE STATUS.


# ─── Override whitelist ──────────────────────────────────────────────────────

ALLOWED_OVERRIDE_KEYS: frozenset[str] = frozenset({
    "threshold",
    "regime_filter",
    "confidence_cap",
    "universe_filter",
    "exit_rule",
    "cooldown",
})


# ─── Evidence source whitelist (subset of EvidenceSource) ────────────────────

ALLOWED_EVIDENCE_SOURCES: frozenset[str] = frozenset({"REPLAY", "BACKTEST"})


# ─── Persistence directory ───────────────────────────────────────────────────

def _quarantine_dir() -> Path:
    """Directory holding one JSON record per variant.

    Overridable via env for tests so unit runs never touch the real
    quarantine zone.
    """
    override = os.environ.get("VARIANT_QUARANTINE_DIR")
    if override:
        return Path(override)
    return _REPO_ROOT / "learning-loop" / "variant_quarantine"


def _ensure_dir(p: Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fail-soft: caller will see write failure on next step.
        return


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_status(value: str | None, *, default: str = QUARANTINED) -> str:
    """Return value if valid; otherwise default. Never raises."""
    if isinstance(value, str) and value in ALL_STATUSES:
        return value
    return default


def _filter_overrides(params: Mapping[str, Any] | None
                      ) -> tuple[dict[str, Any], list[str]]:
    """Keep only whitelisted keys. Return (kept, dropped_keys)."""
    if not isinstance(params, Mapping):
        return {}, []
    kept: dict[str, Any] = {}
    dropped: list[str] = []
    for k, v in params.items():
        if not isinstance(k, str):
            dropped.append(repr(k))
            continue
        if k in ALLOWED_OVERRIDE_KEYS:
            kept[k] = v
        else:
            dropped.append(k)
    return kept, dropped


def _canonical_params_json(params: Mapping[str, Any]) -> str:
    """Stable JSON used for id derivation."""
    try:
        return json.dumps(params, sort_keys=True, separators=(",", ":"),
                          default=str)
    except (TypeError, ValueError):
        # Final safety net: fall back to repr to keep determinism.
        return repr(sorted(params.items()))


def derive_variant_id(parent_strategy: str,
                      params: Mapping[str, Any]) -> str:
    """`sha256(parent + json(params))[:12]` (lower-case hex).

    Pure / deterministic / no side effects.
    """
    parent_s = parent_strategy if isinstance(parent_strategy, str) else ""
    payload = parent_s + "|" + _canonical_params_json(params or {})
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return digest[:12]


def _validate_evidence_source(evidence_source: str | None) -> str:
    """REPLAY or BACKTEST only. Anything else (including PAPER) raises."""
    if not isinstance(evidence_source, str):
        raise ValueError(
            "evidence_source must be 'REPLAY' or 'BACKTEST' — got "
            f"{type(evidence_source).__name__}"
        )
    v = evidence_source.strip().upper()
    if v not in ALLOWED_EVIDENCE_SOURCES:
        raise ValueError(
            f"evidence_source must be one of {sorted(ALLOWED_EVIDENCE_SOURCES)};"
            f" PAPER is forbidden for quarantined variants — got {v!r}"
        )
    return v


# ─── Audit emission (fail-soft) ──────────────────────────────────────────────

def emit_audit_event(event_type: str, variant_id: str,
                     parent_strategy: str, status: str,
                     reason: str,
                     extras: Mapping[str, Any] | None = None) -> None:
    """Best-effort JSONL audit. Never raises into caller."""
    try:
        try:
            from audit import write_audit_event           # type: ignore
            from autonomy import make_decision            # type: ignore
        except ImportError:
            from shared.audit import write_audit_event    # type: ignore
            from shared.autonomy import make_decision     # type: ignore
        # Map quarantine status onto a known DECISION_TYPES value.
        if status in (REJECTED,):
            decision_type = "PAUSE_STRATEGY"
        elif status in (QUARANTINED, REPLAY_TESTING, SHADOW_OBSERVE,
                        CANDIDATE_FOR_MANUAL_REVIEW):
            decision_type = "RESUME_STRATEGY"
        else:
            decision_type = "PAUSE_STRATEGY"
        risk_metrics: dict[str, Any] = {
            "event_type":      event_type,
            "variant_id":      variant_id,
            "parent_strategy": parent_strategy,
            "status":          status,
        }
        if extras:
            try:
                risk_metrics["extras"] = dict(extras)
            except Exception:
                pass
        d = make_decision(
            decision_type=decision_type,
            decision=status,
            reason=f"strategy-variant-quarantine: {reason}",
            actor="strategy-variant-quarantine",
            strategy=parent_strategy,
            risk_metrics=risk_metrics,
            reversible=True,
        )
        write_audit_event(d, kind="trading")
    except Exception:
        # Audit MUST NEVER break the caller.
        return


# ─── Persistence ─────────────────────────────────────────────────────────────

def _variant_path(variant_id: str) -> Path:
    return _quarantine_dir() / f"{variant_id}.json"


def _write_record(record: dict) -> Path:
    path = _variant_path(record["id"])
    _ensure_dir(path.parent)
    try:
        path.write_text(json.dumps(record, indent=2, sort_keys=True,
                                   default=str), encoding="utf-8")
    except OSError:
        # Fail-soft — caller still gets the dict in memory, but persistence
        # failed. Audit a separate event so it's reconstructable.
        emit_audit_event(
            "VARIANT_PERSIST_FAILED",
            record.get("id", "?"),
            record.get("parent_strategy", ""),
            record.get("status", QUARANTINED),
            "could not write variant JSON to disk",
        )
    return path


def _read_record(path: Path) -> dict | None:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ─── Public API ──────────────────────────────────────────────────────────────

def register_variant(
    parent_strategy: str,
    change_rationale: str,
    params: Mapping[str, Any],
    *,
    evidence_source: str,
    test_results: Mapping[str, Any] | None = None,
    promotion_criteria: Iterable[str] | None = None,
    rejection_criteria: Iterable[str] | None = None,
    status: str = QUARANTINED,
) -> dict:
    """Register a new variant, persist a JSON record, return the record.

    Parameters
    ----------
    parent_strategy : str
        Name of the parent strategy. The variant does NOT mutate the
        parent in any way.
    change_rationale : str
        Plain-language why this variant exists.
    params : Mapping[str, Any]
        Proposed override values. Keys outside ALLOWED_OVERRIDE_KEYS are
        silently dropped (and reported in audit).
    evidence_source : str
        Must be "REPLAY" or "BACKTEST" — PAPER is rejected outright. This
        enforces the rule that quarantine variants live OUTSIDE the
        paper-trading edge ledger.
    test_results : Mapping[str, Any], optional
        Optional results dict from a prior replay / backtest. May be empty.
    promotion_criteria / rejection_criteria : Iterable[str], optional
        Operator-supplied bullet criteria for later manual review.
    status : str
        Initial status. Defaults to QUARANTINED. LIVE_APPROVED is NOT a
        valid status by construction.

    Raises
    ------
    ValueError
        If evidence_source is not REPLAY/BACKTEST, or parent_strategy
        is missing.
    """
    if not isinstance(parent_strategy, str) or not parent_strategy.strip():
        raise ValueError("parent_strategy must be a non-empty string")

    source = _validate_evidence_source(evidence_source)

    if not isinstance(params, Mapping):
        params = {}
    kept, dropped = _filter_overrides(params)
    variant_id = derive_variant_id(parent_strategy, kept)

    if test_results is None or not isinstance(test_results, Mapping):
        tr_dict: dict[str, Any] = {}
    else:
        tr_dict = dict(test_results)

    record = {
        "id":                 variant_id,
        "parent_strategy":    parent_strategy,
        "change_rationale":   str(change_rationale or "").strip(),
        "params":             kept,
        "test_results":       tr_dict,
        "promotion_criteria": sorted({str(x).strip() for x in
                                      (promotion_criteria or []) if str(x).strip()}),
        "rejection_criteria": sorted({str(x).strip() for x in
                                      (rejection_criteria or []) if str(x).strip()}),
        "status":             _coerce_status(status, default=QUARANTINED),
        "created_at_iso":     _safe_now_iso(),
        "evidence_source":    source,
        "dropped_param_keys": sorted(dropped),
    }
    _write_record(record)
    emit_audit_event(
        "VARIANT_REGISTERED", variant_id, parent_strategy,
        record["status"],
        f"registered variant for {parent_strategy} "
        f"(source={source}, kept={sorted(kept)}, dropped={record['dropped_param_keys']})",
    )
    return record


def list_variants(*, status: str | None = None) -> list[dict]:
    """Return all persisted variants. Optionally filter by status."""
    out: list[dict] = []
    base = _quarantine_dir()
    if not base.exists():
        return out
    try:
        for entry in sorted(base.glob("*.json")):
            rec = _read_record(entry)
            if rec is None:
                continue
            if status is not None and rec.get("status") != status:
                continue
            out.append(rec)
    except OSError:
        return out
    return out


def get_variant(variant_id: str) -> dict | None:
    """Return single variant record or None."""
    if not isinstance(variant_id, str) or not variant_id.strip():
        return None
    return _read_record(_variant_path(variant_id.strip()))


def set_status(variant_id: str, new_status: str,
               *, reason: str = "") -> dict | None:
    """Update status. Refuses LIVE_APPROVED-style strings."""
    rec = get_variant(variant_id)
    if rec is None:
        return None
    if new_status not in ALL_STATUSES:
        # Refuse unknown statuses; never silently invent LIVE_APPROVED.
        emit_audit_event(
            "VARIANT_STATUS_REJECTED",
            variant_id, rec.get("parent_strategy", ""),
            rec.get("status", QUARANTINED),
            f"refused unknown status {new_status!r}",
        )
        return rec
    prev = rec.get("status", QUARANTINED)
    rec["status"] = new_status
    rec["last_status_change_iso"] = _safe_now_iso()
    if reason:
        rec["last_status_reason"] = str(reason).strip()
    _write_record(rec)
    emit_audit_event(
        "VARIANT_STATUS_CHANGED", variant_id,
        rec.get("parent_strategy", ""),
        new_status,
        f"{prev} -> {new_status}; reason={reason or '(none)'}",
    )
    return rec


def load_quarantined_variants() -> list[dict]:
    """Return all known variants (any status).

    This is the ONLY entry point intended for callers that want to
    enumerate variants (e.g. the experiment scheduler, learning-loop
    reporting). The runtime trading path does NOT import this module
    or call this function — that separation is what keeps variants
    out of the live signal path.
    """
    return list_variants(status=None)


__all__ = [
    # statuses
    "QUARANTINED",
    "REPLAY_TESTING",
    "SHADOW_OBSERVE",
    "REJECTED",
    "CANDIDATE_FOR_MANUAL_REVIEW",
    "ALL_STATUSES",
    # whitelists
    "ALLOWED_OVERRIDE_KEYS",
    "ALLOWED_EVIDENCE_SOURCES",
    # helpers
    "derive_variant_id",
    "emit_audit_event",
    # API
    "register_variant",
    "list_variants",
    "get_variant",
    "set_status",
    "load_quarantined_variants",
]
