"""Workflow coherence. Spec §13."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Finding
from ..utils import list_workflows, read_text, rel


CATEGORY = "workflows"
PRINCIPLE = "WORKFLOW_COHERENCE"


def _has_schedule(text: str) -> bool:
    return bool(re.search(r"^\s*schedule:\s*$", text, re.M))


def _has_concurrency(text: str) -> bool:
    return bool(re.search(r"^concurrency:\s*$", text, re.M))


def _writes_git(text: str) -> bool:
    return bool(re.search(r"\bgit\s+(commit|push)\b", text))


def _has_contents_write(text: str) -> bool:
    return bool(re.search(r"^\s*contents:\s*write", text, re.M))


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    schedule_missing_concurrency: list[str] = []
    git_write_without_contents: list[str] = []
    workflow_count = 0

    # Workflows that legitimately push via PAT (e.g. sync-workflows.yml uses
    # WORKFLOW_PAT) don't need GITHUB_TOKEN's contents: write — the PAT
    # supplies its own scope.
    import re as _re_workflows
    _RE_PAT = _re_workflows.compile(r"\$\{\{\s*secrets\.WORKFLOW_PAT\s*\}\}")

    for wf in list_workflows(root):
        workflow_count += 1
        text = read_text(wf)
        name = wf.name
        if _has_schedule(text) and not _has_concurrency(text):
            schedule_missing_concurrency.append(name)
        uses_pat = bool(_RE_PAT.search(text))
        if _writes_git(text) and not _has_contents_write(text) and not uses_pat:
            git_write_without_contents.append(name)

    findings.append(Finding(
        id="WF_SCHEDULE_HAS_CONCURRENCY",
        category=CATEGORY,
        severity="PASS" if not schedule_missing_concurrency else "FAIL",
        status="PASS" if not schedule_missing_concurrency else "FAIL",
        message=("All schedule workflows declare concurrency." if not schedule_missing_concurrency
                  else f"Missing concurrency: {schedule_missing_concurrency}"),
        principle=PRINCIPLE,
        recommendation="Add concurrency: block to those workflows." if schedule_missing_concurrency else "",
    ))

    findings.append(Finding(
        id="WF_GIT_WRITE_HAS_PERMISSIONS",
        category=CATEGORY,
        severity="PASS" if not git_write_without_contents else "FAIL",
        status="PASS" if not git_write_without_contents else "FAIL",
        message=("All workflows that git-commit declare contents: write." if not git_write_without_contents
                  else f"git commit/push without contents: write in: {git_write_without_contents}"),
        principle=PRINCIPLE,
        recommendation="Add contents: write or remove the git commit step." if git_write_without_contents else "",
    ))

    # autonomous-code-loop has gates
    acl = root / ".github" / "workflows" / "autonomous-code-loop.yml"
    findings.append(Finding(
        id="WF_AUTONOMOUS_CODE_LOOP_EXISTS",
        category=CATEGORY,
        severity="PASS" if acl.exists() else "FAIL",
        status="PASS" if acl.exists() else "FAIL",
        message="autonomous-code-loop.yml present." if acl.exists() else "Missing autonomous-code-loop.yml.",
        principle=PRINCIPLE,
        recommendation="Restore autonomous-code-loop.yml." if not acl.exists() else "",
    ))

    # autonomous-remediation has paper-only env / scheduling
    rem = root / ".github" / "workflows" / "autonomous-remediation.yml"
    findings.append(Finding(
        id="WF_AUTONOMOUS_REMEDIATION_EXISTS",
        category=CATEGORY,
        severity="PASS" if rem.exists() else "FAIL",
        status="PASS" if rem.exists() else "FAIL",
        message="autonomous-remediation.yml present." if rem.exists() else "Missing autonomous-remediation.yml.",
        principle=PRINCIPLE,
        recommendation="Restore autonomous-remediation.yml." if not rem.exists() else "",
    ))

    # security-audit.yml exists
    sa = root / ".github" / "workflows" / "security-audit.yml"
    findings.append(Finding(
        id="WF_SECURITY_AUDIT_EXISTS",
        category=CATEGORY,
        severity="PASS" if sa.exists() else "WARN",
        status="PASS" if sa.exists() else "WARN",
        message="security-audit.yml present." if sa.exists() else "Missing security-audit.yml.",
        principle=PRINCIPLE,
        recommendation="Restore security-audit.yml." if not sa.exists() else "",
    ))

    findings.append(Finding(
        id="WF_INVENTORY_COUNT",
        category=CATEGORY,
        severity="INFO", status="PASS",
        message=f"Inventory: {workflow_count} workflow files under .github/workflows/.",
        principle=PRINCIPLE,
    ))

    return findings
