"""Full autonomous trading — no human approval required. Spec §2."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Evidence, Finding
from ..utils import grep_pattern, rel, repo_root, walk_files, read_text


CATEGORY = "trading_autonomy"
PRINCIPLE = "NO_HUMAN_APPROVAL"

FORBIDDEN_PATTERNS = (
    re.compile(r"approval\s+needed", re.I),
    re.compile(r"manual\s+confirm(?:ation)?\s+required", re.I),
    re.compile(r"waiting\s+for\s+human", re.I),
    re.compile(r"pending\s+user\s+approval", re.I),
    re.compile(r"please\s+approve", re.I),
    re.compile(r"awaiting\s+operator", re.I),
)

# Strings allowed in docs (operator runbook) and in the agent's own modules.
EXEMPT_PATHS = (
    "docs/",
    "tests/",
    "tools/system_consistency_agent/",
    "scripts/audit_workflows.py",
    "scripts/secret_scan_light.py",
    "learning-loop/patch_validator.py",
    "CLAUDE.md",
    "shared/autonomy.py",
)


def _is_exempt(p: Path) -> bool:
    rp = str(rel(p))
    return any(rp.startswith(x) or rp == x.rstrip("/") for x in EXEMPT_PATHS)


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    # 1. No forbidden approval wording in trading code paths
    paths = [p for p in walk_files(root, include_globs=("*.py", "*.yml", "*.yaml"))
             if not _is_exempt(p)]
    all_hits: list[Evidence] = []
    for pat in FORBIDDEN_PATTERNS:
        all_hits.extend(grep_pattern(pat, paths))
    findings.append(Finding(
        id="AUTONOMY_NO_APPROVAL_WORDING_IN_CODE",
        category=CATEGORY,
        severity="FAIL" if all_hits else "PASS",
        status="FAIL" if all_hits else "PASS",
        message=(f"Found {len(all_hits)} occurrences of approval-needed wording in trading code."
                 if all_hits
                 else "No approval-needed wording in trading code."),
        principle=PRINCIPLE,
        evidence=all_hits[:10],
        recommendation="Replace with deterministic decisions (APPROVE/REJECT) and audit emails." if all_hits else "",
        blocking=bool(all_hits),
    ))

    # 2. shared/autonomy.py defines forbidden states / decision types
    autonomy = root / "shared" / "autonomy.py"
    if autonomy.exists():
        text = read_text(autonomy)
        has_types = ("APPROVE_ENTRY" in text and "REJECT_ENTRY" in text
                     and "EMERGENCY_CLOSE" in text)
        findings.append(Finding(
            id="AUTONOMY_DECISION_TYPES_DEFINED",
            category=CATEGORY,
            severity="PASS" if has_types else "FAIL",
            status="PASS" if has_types else "FAIL",
            message=("Autonomy decision enum is defined."
                     if has_types
                     else "Missing decision-type enum in shared/autonomy.py."),
            principle=PRINCIPLE,
            recommendation="Restore DECISION_TYPES with APPROVE_ENTRY, REJECT_ENTRY, EMERGENCY_CLOSE, ..." if not has_types else "",
            blocking=not has_types,
        ))

    # 3. options-monitor has OPTIONS_ENABLED gate (auto APPROVE/REJECT, not approval-needed)
    om = root / "options-monitor" / "monitor.py"
    if om.exists():
        text = read_text(om)
        has_gate = "options_enabled" in text or "OPTIONS_ENABLED" in text
        findings.append(Finding(
            id="AUTONOMY_OPTIONS_HAS_ENABLED_GATE",
            category=CATEGORY,
            severity="PASS" if has_gate else "FAIL",
            status="PASS" if has_gate else "FAIL",
            message=("options-monitor reads OPTIONS_ENABLED for auto APPROVE/REJECT decision."
                     if has_gate
                     else "options-monitor does NOT gate on OPTIONS_ENABLED."),
            principle=PRINCIPLE,
            recommendation="Add `if not options_enabled(): return safe_no_op` early in run_scan." if not has_gate else "",
        ))

    # 4. panic_close_options has AUTONOMOUS_PANIC_CLOSE_OPTIONS path
    panic = root / "scripts" / "panic_close_options.py"
    if panic.exists():
        text = read_text(panic)
        has_autonomous = "AUTONOMOUS_PANIC_CLOSE_OPTIONS" in text
        findings.append(Finding(
            id="AUTONOMY_PANIC_CLOSE_HAS_AUTONOMOUS_MODE",
            category=CATEGORY,
            severity="PASS" if has_autonomous else "FAIL",
            status="PASS" if has_autonomous else "FAIL",
            message=("panic_close_options.py supports AUTONOMOUS_PANIC_CLOSE_OPTIONS env."
                     if has_autonomous
                     else "panic_close_options.py only supports manual CONFIRM env."),
            principle=PRINCIPLE,
            recommendation="Accept AUTONOMOUS_PANIC_CLOSE_OPTIONS=true so remediation pipeline can trigger it." if not has_autonomous else "",
        ))

    # 5. emergency_engine has scan_emergency_conditions (auto-select targets)
    ee = root / "shared" / "emergency_engine.py"
    if ee.exists():
        text = read_text(ee)
        has_scan = "def scan_emergency_conditions" in text
        has_exec = "def execute_emergency_close" in text
        findings.append(Finding(
            id="AUTONOMY_EMERGENCY_AUTOSELECT",
            category=CATEGORY,
            severity="PASS" if (has_scan and has_exec) else "FAIL",
            status="PASS" if (has_scan and has_exec) else "FAIL",
            message=("emergency_engine auto-selects targets and executes closes."
                     if (has_scan and has_exec)
                     else "emergency_engine missing scan/execute primitives."),
            principle=PRINCIPLE,
            recommendation="Restore scan_emergency_conditions + execute_emergency_close." if not (has_scan and has_exec) else "",
            blocking=not (has_scan and has_exec),
        ))

    return findings
