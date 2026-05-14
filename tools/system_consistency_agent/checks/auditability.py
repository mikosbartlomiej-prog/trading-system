"""Audit trail. Spec §12."""

from __future__ import annotations

from pathlib import Path

from ..models import Finding
from ..utils import read_text


CATEGORY = "auditability"
PRINCIPLE = "AUDITABILITY"

REQUIRED_DECISION_FIELDS = [
    "timestamp", "actor", "decision_type", "decision", "reason",
    "deterministic_inputs_hash", "affected_symbols", "strategy",
    "risk_metrics", "state_before_hash", "state_after_hash",
    "code_before_sha", "code_after_sha", "action_taken", "result",
    "rollback_available", "rollback_action", "errors",
]


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    aud = root / "shared" / "audit.py"
    if not aud.exists():
        findings.append(Finding(
            id="AUDIT_MODULE_EXISTS",
            category=CATEGORY, severity="FAIL", status="FAIL",
            message="shared/audit.py missing.",
            principle=PRINCIPLE,
            recommendation="Restore shared/audit.py.",
            blocking=True,
        ))
        return findings

    text = read_text(aud)
    required_api = ["write_audit_event", "write_code_audit_event",
                    "read_today", "read_range"]
    missing = [s for s in required_api if s not in text]
    findings.append(Finding(
        id="AUDIT_API_PRESENT",
        category=CATEGORY,
        severity="PASS" if not missing else "FAIL",
        status="PASS" if not missing else "FAIL",
        message="Audit API complete." if not missing
                else f"Missing: {missing}",
        principle=PRINCIPLE,
        recommendation="Restore audit primitives." if missing else "",
    ))

    # Decision dataclass fields
    autonomy = root / "shared" / "autonomy.py"
    if autonomy.exists():
        a_text = read_text(autonomy)
        missing_fields = [f for f in REQUIRED_DECISION_FIELDS if f not in a_text]
        findings.append(Finding(
            id="AUDIT_DECISION_FIELDS_COMPLETE",
            category=CATEGORY,
            severity="PASS" if not missing_fields else "FAIL",
            status="PASS" if not missing_fields else "FAIL",
            message="Decision dataclass has all required audit fields." if not missing_fields
                    else f"Missing decision fields: {missing_fields}",
            principle=PRINCIPLE,
            recommendation="Add the missing fields to Decision dataclass." if missing_fields else "",
        ))

    # Audit written from emergency + remediation modules
    for mod_rel in ("shared/emergency_engine.py", "shared/remediation.py",
                     "learning-loop/code_autonomy.py"):
        p = root / mod_rel
        if not p.exists():
            continue
        text = read_text(p)
        writes_audit = "write_audit_event" in text or "write_code_audit_event" in text
        findings.append(Finding(
            id=f"AUDIT_WRITES_FROM_{mod_rel.replace('/', '_').upper().replace('.PY', '')}",
            category=CATEGORY,
            severity="PASS" if writes_audit else "WARN",
            status="PASS" if writes_audit else "WARN",
            message=f"{mod_rel} writes audit events." if writes_audit
                    else f"{mod_rel} does NOT write audit events.",
            principle=PRINCIPLE,
            recommendation=f"Add write_audit_event call in {mod_rel}." if not writes_audit else "",
        ))

    return findings
