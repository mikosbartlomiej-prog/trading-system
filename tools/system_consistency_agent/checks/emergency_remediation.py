"""Emergency engine + remediation. Spec §11."""

from __future__ import annotations

from pathlib import Path

from ..models import Finding
from ..utils import read_text


CATEGORY = "emergency_remediation"
PRINCIPLE = "EMERGENCY_REMEDIATION"


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    ee = root / "shared" / "emergency_engine.py"
    rm = root / "shared" / "remediation.py"

    if not ee.exists():
        findings.append(Finding(
            id="EM_ENGINE_MODULE_EXISTS",
            category=CATEGORY, severity="FAIL", status="FAIL",
            message="shared/emergency_engine.py missing.",
            principle=PRINCIPLE,
            recommendation="Restore emergency_engine.",
            blocking=True,
        ))
    else:
        text = read_text(ee)
        required = ["scan_emergency_conditions", "execute_emergency_close",
                    "EmergencyTarget", "assert_paper_only",
                    "MAX_ATTEMPTS_PER_DAY"]
        missing = [s for s in required if s not in text]
        findings.append(Finding(
            id="EM_ENGINE_API_PRESENT",
            category=CATEGORY,
            severity="PASS" if not missing else "FAIL",
            status="PASS" if not missing else "FAIL",
            message="Emergency engine API complete." if not missing
                    else f"Missing: {missing}",
            principle=PRINCIPLE,
            recommendation="Restore missing emergency_engine primitives." if missing else "",
            blocking=bool(missing),
        ))
        conditions = ["hard_loss", "no_exit_plan", "duplicate_exits",
                       "stale_exit_order", "option_near_dte", "defensive_mode"]
        missing_conds = [c for c in conditions if c not in text]
        findings.append(Finding(
            id="EM_ENGINE_CONDITIONS_COVERED",
            category=CATEGORY,
            severity="PASS" if not missing_conds else "WARN",
            status="PASS" if not missing_conds else "WARN",
            message="All emergency conditions covered." if not missing_conds
                    else f"Conditions missing: {missing_conds}",
            principle=PRINCIPLE,
            recommendation="Add missing condition branches in scan_emergency_conditions." if missing_conds else "",
        ))

    if not rm.exists():
        findings.append(Finding(
            id="EM_REMEDIATION_MODULE_EXISTS",
            category=CATEGORY, severity="FAIL", status="FAIL",
            message="shared/remediation.py missing.",
            principle=PRINCIPLE,
            recommendation="Restore shared/remediation.py.",
            blocking=True,
        ))
    else:
        text = read_text(rm)
        actions = ["CANCEL_STALE_ORDERS", "RECREATE_EXIT_PLAN",
                    "BLOCK_NEW_ENTRIES", "PANIC_CLOSE_OPTIONS"]
        missing_acts = [a for a in actions if a not in text]
        findings.append(Finding(
            id="EM_REMEDIATION_ACTIONS_PRESENT",
            category=CATEGORY,
            severity="PASS" if not missing_acts else "FAIL",
            status="PASS" if not missing_acts else "FAIL",
            message="Remediation defines all required actions." if not missing_acts
                    else f"Missing actions: {missing_acts}",
            principle=PRINCIPLE,
            recommendation="Restore missing action handlers." if missing_acts else "",
        ))
        cooldown = "REMEDIATION_COOLDOWN_S" in text and "_cooldown_ok" in text
        findings.append(Finding(
            id="EM_REMEDIATION_COOLDOWN",
            category=CATEGORY,
            severity="PASS" if cooldown else "WARN",
            status="PASS" if cooldown else "WARN",
            message="Remediation cooldown prevents loops." if cooldown
                    else "Remediation may loop without cooldown.",
            principle=PRINCIPLE,
            recommendation="Add per-(action,subject) cooldown." if not cooldown else "",
        ))

    return findings
