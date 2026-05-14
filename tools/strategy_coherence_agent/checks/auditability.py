"""Spec §18 — strategic decisions are audited.

We don't require every event_type to be explicitly hard-coded — the
audit writer takes free-form decision dicts — but key strategic events
must be reachable from the code that triggers them:
  - PROFIT_LOCK_TRIGGERED, DEFEND_DAY_TRIGGERED,
    RED_DAY_AFTER_GREEN_PROTECTION, BLOCK_NEW_ENTRIES_INTRADAY,
    POSITION_MFE_TRAIL_REDUCE, POSITION_MFE_TRAIL_EXIT,
    REDUCE_GROSS_EXPOSURE_INTRADAY (governor side)
  - allocation_plan_generated, rebalance_order_submitted (allocator side)
"""

from __future__ import annotations

from pathlib import Path

from ..models import Evidence, Finding
from ..utils import read_text, rel


CATEGORY  = "auditability"
PRINCIPLE = "STRATEGIC_DECISION_AUDIT"

INTRADAY_EVENTS = (
    "PROFIT_LOCK_TRIGGERED", "DEFEND_DAY_TRIGGERED",
    "RED_DAY_AFTER_GREEN", "BLOCK_NEW_ENTRIES_INTRADAY",
    "POSITION_MFE_TRAIL",
)

ALLOCATOR_EVENTS = (
    "allocation_plan", "rebalance_order",
)


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    audit = root / "shared" / "audit.py"
    if not audit.exists():
        out.append(Finding(
            id="AUD_MODULE_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="shared/audit.py missing — no append-only decision log.",
            recommendation="Add shared/audit.py with write_audit_event().",
        ))
        return out

    audit_text = read_text(audit)
    if "write_audit_event" not in audit_text or "jsonl" not in audit_text.lower():
        out.append(Finding(
            id="AUD_API_INCOMPLETE",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message="shared/audit.py missing write_audit_event / JSONL output.",
            recommendation="Implement write_audit_event(decision) → JSONL path.",
            evidence=[Evidence(file=str(rel(audit)))],
        ))
    else:
        out.append(Finding(
            id="AUD_API_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="shared/audit.py exposes write_audit_event + JSONL.",
        ))

    # Intraday events emitted by governor / exit-monitor
    gov = root / "shared" / "intraday_governor.py"
    em = root / "exit-monitor" / "monitor.py"
    intraday_text = ""
    if gov.exists():
        intraday_text += read_text(gov)
    if em.exists():
        intraday_text += "\n" + read_text(em)

    missing_intraday = [e for e in INTRADAY_EVENTS if e not in intraday_text]
    if missing_intraday:
        out.append(Finding(
            id="AUD_INTRADAY_EVENTS_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"Intraday events not surfaced: {', '.join(missing_intraday)}.",
            expected="Every transition / harvest event written via emit_audit",
            observed="missing: " + ", ".join(missing_intraday),
            recommendation="Add emit_audit(event_type, snap, ...) calls for "
                           "the missing transitions.",
        ))
    else:
        out.append(Finding(
            id="AUD_INTRADAY_EVENTS_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="All intraday governor event types appear in the code path.",
        ))

    # Allocator events
    alloc = root / "shared" / "allocator.py"
    if alloc.exists():
        at = read_text(alloc)
        if not any(e in at.lower() for e in ALLOCATOR_EVENTS):
            out.append(Finding(
                id="AUD_ALLOCATOR_EVENTS_MISSING",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="shared/allocator.py has no allocation_plan / rebalance_order trace.",
                recommendation="Emit audit events for plan creation and order submission.",
                evidence=[Evidence(file=str(rel(alloc)))],
            ))

    # journal/autonomy directory pattern documented
    runbook = root / "docs" / "OPERATIONS_RUNBOOK.md"
    if runbook.exists():
        rtext = read_text(runbook)
        if "journal/autonomy" not in rtext:
            out.append(Finding(
                id="AUD_RUNBOOK_NO_JOURNAL_REFERENCE",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="OPERATIONS_RUNBOOK.md does not point at journal/autonomy/.",
                recommendation="Document where audit JSONL lives.",
            ))

    return out
