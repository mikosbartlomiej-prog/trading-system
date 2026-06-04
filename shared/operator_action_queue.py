"""v3.21.0 (2026-06-04) — ETAP 10 — Operator Action Queue.

WHY
---
The audit-board cycle keeps surfacing items that require human review
(strategy lower-bound regressions, variant promotions, gate-calibration
warnings, fill-model drift, edge-gate readiness). Today those items
arrive scattered across reports and emails. The Operator Action Queue
centralises them as a single append-only ledger plus a deterministic
markdown rollup that the operator can sweep daily.

This module is review-gated. It is governed by Multi-Agent Audit Board.
Items in the queue are non-auto-apply by design — the system enqueues
them, the runtime continues unchanged, and the Audit Board sweeps them
on a deterministic cadence. No item can ever be marked LIVE /
LIVE_APPROVED / LIVE_ENABLED.

INVARIANTS (verified by tests + audit)
--------------------------------------
- ``QUEUE_NEVER_AUTO_APPLIES = True``
- ``QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY = True``
- Every action carries ``can_auto_apply = False`` (asserted on construction).
- Every action carries deterministic ``id`` (sha256 over canonical key).

CONTRACT
--------
- ``ActionType`` is a closed enum (frozenset of strings).
- ``Severity`` is a closed enum.
- ``enqueue_action(...)`` returns the persisted dict. Idempotent on id.
- ``list_actions(status=...)`` returns a list (most recent first).
- ``render_report()`` returns deterministic markdown.
- ``write_queue_jsonl(...)`` appends to
  ``learning-loop/operator_action_queue.jsonl``.
- ``write_markdown_report(...)`` writes
  ``docs/operator_action_queue_LATEST.md``.

FREE OPERATION
--------------
Pure stdlib. Free-tier safe. Offline. No paid APIs.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


# ─── Module location bootstrap ───────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─── Hard invariants ─────────────────────────────────────────────────────────

# Spec: queue items NEVER auto-apply. Both flags are verified by tests
# and by the audit board agent.
QUEUE_NEVER_AUTO_APPLIES:           bool = True
QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY: bool = True


# ─── Closed enums ────────────────────────────────────────────────────────────

ACTION_TYPES: frozenset[str] = frozenset({
    "REVIEW_STRATEGY",
    "REVIEW_VARIANT",
    "DISABLE_CANDIDATE",
    "KEEP_OBSERVING",
    "ADD_DATA_SOURCE_REVIEW",
    "CHECK_BROKER_PAPER",
    "REVIEW_GATE_CALIBRATION",
    "REVIEW_FILL_MODEL",
    "REVIEW_EDGE_GATE",
    "NO_ACTION",
})

SEVERITIES: frozenset[str] = frozenset({
    "P0",  # urgent operator review (e.g. safety report)
    "P1",  # high priority
    "P2",  # medium
    "P3",  # low / housekeeping
})

# Closed status enum. No LIVE / LIVE_APPROVED / LIVE_ENABLED by design.
STATUSES: frozenset[str] = frozenset({
    "OPEN",
    "ACKNOWLEDGED",
    "DEFERRED",
    "CLOSED_NO_ACTION",
    "CLOSED_REVIEWED",
})


# ─── Deterministic phrasing — safe wording bank ──────────────────────────────

# These deterministic phrases pass the
# AAD_FORBIDDEN_WORDING_IN_NON_LIFECYCLE audit and are what callers
# should embed in ``rationale``.
SAFE_PHRASES: tuple[str, ...] = (
    "non-auto-apply by design",
    "governed by Multi-Agent Audit Board",
    "review-gated",
    "queued for evidence accumulation",
    "operator sweep recommended",
)


# ─── Paths ───────────────────────────────────────────────────────────────────


def _queue_jsonl_path() -> Path:
    return Path(
        os.environ.get("OPERATOR_ACTION_QUEUE_PATH")
        or _REPO_ROOT / "learning-loop" / "operator_action_queue.jsonl"
    )


def _report_md_path() -> Path:
    return Path(
        os.environ.get("OPERATOR_ACTION_QUEUE_REPORT_PATH")
        or _REPO_ROOT / "docs" / "operator_action_queue_LATEST.md"
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


# ─── Deterministic id ────────────────────────────────────────────────────────


def _deterministic_id(action_type: str,
                      source_module: str,
                      severity: str,
                      rationale: str,
                      evidence_links: Iterable[str]) -> str:
    """Stable id over canonical key.

    Two calls with the same logical content (in particular: same
    action_type + source_module + severity + rationale + sorted
    evidence_links) yield the same id, which makes ``enqueue_action``
    idempotent on retries.
    """
    h = hashlib.sha256()
    h.update((action_type or "").encode("utf-8"))
    h.update(b"|")
    h.update((source_module or "").encode("utf-8"))
    h.update(b"|")
    h.update((severity or "").encode("utf-8"))
    h.update(b"|")
    h.update((rationale or "").encode("utf-8"))
    h.update(b"|")
    for link in sorted(set(str(x) for x in (evidence_links or []))):
        h.update(link.encode("utf-8"))
        h.update(b",")
    return "oaq_" + h.hexdigest()[:24]


# ─── Action record ───────────────────────────────────────────────────────────


def _validate(action_type: str, severity: str, rationale: str,
              evidence_links: Iterable[str], can_auto_apply: bool,
              recommended_review_deadline_iso: str) -> None:
    if action_type not in ACTION_TYPES:
        raise ValueError(
            f"unknown action_type '{action_type}'. "
            f"Allowed: {sorted(ACTION_TYPES)}"
        )
    if severity not in SEVERITIES:
        raise ValueError(
            f"unknown severity '{severity}'. Allowed: {sorted(SEVERITIES)}"
        )
    # Hard invariant — queue items NEVER auto-apply.
    if bool(can_auto_apply) is not False:
        raise AssertionError(
            "QUEUE_NEVER_AUTO_APPLIES invariant violated: "
            "can_auto_apply must be False"
        )
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("rationale must be a non-empty string")
    if not isinstance(recommended_review_deadline_iso, str) \
       or not recommended_review_deadline_iso.strip():
        raise ValueError(
            "recommended_review_deadline_iso must be a non-empty string"
        )
    if evidence_links is None:
        raise ValueError("evidence_links must be iterable (may be empty)")


def make_action(action_type: str,
                source_module: str,
                severity: str,
                rationale: str,
                *,
                evidence_links: Iterable[str] = (),
                recommended_review_deadline_iso: str | None = None,
                affected_strategies: Iterable[str] = (),
                affected_symbols: Iterable[str] = (),
                ) -> dict:
    """Construct an action dict. Always sets ``can_auto_apply=False``.

    Raises ``AssertionError`` if anyone tries to flip can_auto_apply.
    """
    deadline = recommended_review_deadline_iso or _utc_now_iso()
    _validate(action_type, severity, rationale, evidence_links,
              can_auto_apply=False,
              recommended_review_deadline_iso=deadline)
    aid = _deterministic_id(action_type, source_module, severity,
                            rationale, evidence_links)
    record: dict[str, Any] = {
        "id":                              aid,
        "action_type":                     action_type,
        "severity":                        severity,
        "source_module":                   str(source_module or "unknown"),
        "rationale":                       str(rationale),
        "evidence_links":                  sorted({str(x) for x in evidence_links}),
        "recommended_review_deadline_iso": deadline,
        "can_auto_apply":                  False,
        "status":                          "OPEN",
        "created_at":                      _utc_now_iso(),
        "affected_strategies":             sorted({str(s) for s in affected_strategies}),
        "affected_symbols":                sorted({str(s) for s in affected_symbols}),
    }
    # Defensive: post-condition assert the invariant.
    assert record["can_auto_apply"] is False, \
        "QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY violated"
    return record


# ─── Persistence ─────────────────────────────────────────────────────────────


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        return []
    return out


def _write_jsonl(path: Path, records: Iterable[dict]) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, default=str, sort_keys=True) + "\n")


def _append_jsonl(path: Path, record: dict) -> None:
    _ensure_parent(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str, sort_keys=True) + "\n")


def _emit_audit(record: dict) -> None:
    """Fail-soft audit emission via shared.audit + autonomy."""
    try:
        try:
            from audit import write_audit_event           # type: ignore
            from autonomy import make_decision            # type: ignore
        except ImportError:
            from shared.audit import write_audit_event    # type: ignore
            from shared.autonomy import make_decision     # type: ignore
        decision = make_decision(
            decision_type="PAUSE_STRATEGY",
            decision=record.get("action_type", "REVIEW_STRATEGY"),
            reason=(
                "operator-action-queue: review-gated; "
                "non-auto-apply by design"
            ),
            actor="operator-action-queue",
            strategy=(record.get("affected_strategies") or [None])[0],
            affected_symbols=record.get("affected_symbols", []),
            risk_metrics={
                "queue_id":      record.get("id"),
                "severity":      record.get("severity"),
                "source_module": record.get("source_module"),
                "evidence_links": record.get("evidence_links", []),
            },
            reversible=True,
        )
        write_audit_event(decision, kind="trading")
    except Exception:
        # Audit MUST NEVER break the queue.
        return


# ─── Public API ──────────────────────────────────────────────────────────────


def enqueue_action(action_type: str,
                   source_module: str,
                   severity: str,
                   rationale: str,
                   *,
                   evidence_links: Iterable[str] = (),
                   recommended_review_deadline_iso: str | None = None,
                   affected_strategies: Iterable[str] = (),
                   affected_symbols: Iterable[str] = (),
                   ) -> dict:
    """Persist a new action. Idempotent on deterministic id.

    Behaviour:
      - Constructs an action via ``make_action`` (invariants enforced).
      - Reads the on-disk queue; if an action with the same id already
        exists we return that record unmodified (idempotency).
      - Otherwise appends to the JSONL file and emits an audit event.

    Returns the persisted dict.
    """
    record = make_action(
        action_type=action_type,
        source_module=source_module,
        severity=severity,
        rationale=rationale,
        evidence_links=evidence_links,
        recommended_review_deadline_iso=recommended_review_deadline_iso,
        affected_strategies=affected_strategies,
        affected_symbols=affected_symbols,
    )
    path = _queue_jsonl_path()
    existing = _read_jsonl(path)
    for r in existing:
        if isinstance(r, dict) and r.get("id") == record["id"]:
            return r
    _append_jsonl(path, record)
    _emit_audit(record)
    return record


def list_actions(*, status: str | None = None,
                 action_type: str | None = None,
                 severity: str | None = None,
                 limit: int | None = None) -> list[dict]:
    """Return queue contents sorted by ``created_at`` descending."""
    records = _read_jsonl(_queue_jsonl_path())
    out = [r for r in records if isinstance(r, dict)]
    if status:
        out = [r for r in out if r.get("status") == status]
    if action_type:
        out = [r for r in out if r.get("action_type") == action_type]
    if severity:
        out = [r for r in out if r.get("severity") == severity]
    out.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    if limit is not None and isinstance(limit, int) and limit >= 0:
        out = out[:limit]
    return out


def set_status(action_id: str, new_status: str) -> dict | None:
    """Update a single action's status (operator audit trail)."""
    if new_status not in STATUSES:
        raise ValueError(
            f"unknown status '{new_status}'. Allowed: {sorted(STATUSES)}"
        )
    path = _queue_jsonl_path()
    records = _read_jsonl(path)
    updated: dict | None = None
    for r in records:
        if isinstance(r, dict) and r.get("id") == action_id:
            r["status"] = new_status
            r["status_updated_at"] = _utc_now_iso()
            # Invariant: can_auto_apply remains False forever.
            r["can_auto_apply"] = False
            updated = r
    if updated is not None:
        _write_jsonl(path, records)
    return updated


# ─── Rendering ───────────────────────────────────────────────────────────────


def render_report(records: list[dict] | None = None) -> str:
    """Deterministic markdown rendering of the queue.

    Stable structure for diff-friendly review. Always carries the
    invariant flags at the top so the audit board can verify.
    """
    if records is None:
        records = list_actions()
    open_records = [r for r in records if r.get("status") == "OPEN"]
    by_sev: dict[str, list[dict]] = {s: [] for s in sorted(SEVERITIES)}
    for r in open_records:
        sev = str(r.get("severity") or "P3")
        by_sev.setdefault(sev, []).append(r)

    lines: list[str] = []
    lines.append("# Operator Action Queue — latest snapshot")
    lines.append("")
    lines.append(f"- generated_at: `{_utc_now_iso()}`")
    lines.append(f"- QUEUE_NEVER_AUTO_APPLIES: {QUEUE_NEVER_AUTO_APPLIES}")
    lines.append(
        f"- QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY: "
        f"{QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY}"
    )
    lines.append(f"- total_actions: {len(records)}")
    lines.append(f"- open_actions: {len(open_records)}")
    lines.append("")
    lines.append("Each action below is *review-gated* and *non-auto-apply "
                 "by design*. Governed by Multi-Agent Audit Board.")
    lines.append("")
    for sev in ("P0", "P1", "P2", "P3"):
        bucket = by_sev.get(sev, [])
        if not bucket:
            continue
        lines.append(f"## {sev} — {len(bucket)} item(s)")
        lines.append("")
        lines.append("| id | action_type | source_module | rationale "
                     "| review_deadline_iso | evidence_links |")
        lines.append("|---|---|---|---|---|---|")
        # Stable secondary sort by id for determinism inside a severity.
        for r in sorted(bucket, key=lambda x: str(x.get("id", ""))):
            links = ", ".join(r.get("evidence_links") or []) or "—"
            rationale = str(r.get("rationale", "")).replace("|", "\\|")
            lines.append(
                f"| `{r.get('id', '?')}` "
                f"| {r.get('action_type', '?')} "
                f"| {r.get('source_module', '?')} "
                f"| {rationale} "
                f"| {r.get('recommended_review_deadline_iso', '?')} "
                f"| {links} |"
            )
        lines.append("")
    if not open_records:
        lines.append("_No open actions — queue is clear._")
        lines.append("")
    return "\n".join(lines)


def write_markdown_report(path: Path | str | None = None,
                          records: list[dict] | None = None) -> Path:
    """Write the markdown report. Returns the path written."""
    out_path = Path(path) if path else _report_md_path()
    _ensure_parent(out_path)
    out_path.write_text(render_report(records), encoding="utf-8")
    return out_path


# ─── Invariant helper ────────────────────────────────────────────────────────


def assert_invariants() -> None:
    """Hard invariant check used by tests and audit.

    Raises ``AssertionError`` if the queue is configured to auto-apply.
    """
    assert QUEUE_NEVER_AUTO_APPLIES is True, \
        "QUEUE_NEVER_AUTO_APPLIES invariant violated"
    assert QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY is True, \
        "QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY invariant violated"


__all__ = [
    "QUEUE_NEVER_AUTO_APPLIES",
    "QUEUE_RISKY_ACTIONS_NON_AUTO_APPLY",
    "ACTION_TYPES",
    "SEVERITIES",
    "STATUSES",
    "SAFE_PHRASES",
    "make_action",
    "enqueue_action",
    "list_actions",
    "set_status",
    "render_report",
    "write_markdown_report",
    "assert_invariants",
]
