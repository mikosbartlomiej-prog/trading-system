"""Security: secret scan + audit scripts + env masking. Spec §14."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ..models import Finding
from ..utils import repo_root


CATEGORY = "security"
PRINCIPLE = "SECURITY"


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    # 1. audit + scan scripts exist
    scripts = {
        "scripts/audit_workflows.py":    "AUDIT_WORKFLOWS_SCRIPT",
        "scripts/secret_scan_light.py":  "SECRET_SCAN_SCRIPT",
    }
    for path, fid in scripts.items():
        p = root / path
        findings.append(Finding(
            id=f"SEC_{fid}_EXISTS",
            category=CATEGORY,
            severity="PASS" if p.exists() else "FAIL",
            status="PASS" if p.exists() else "FAIL",
            message=f"{path} present." if p.exists() else f"{path} missing.",
            principle=PRINCIPLE,
            recommendation=f"Restore {path}." if not p.exists() else "",
        ))

    # 2. Run secret_scan_light against the repo (live execution)
    secret_scan = root / "scripts" / "secret_scan_light.py"
    if secret_scan.exists():
        try:
            r = subprocess.run(
                [sys.executable, str(secret_scan)],
                capture_output=True, text=True, cwd=str(root), timeout=60,
            )
            clean = r.returncode == 0
            findings.append(Finding(
                id="SEC_SECRET_SCAN_CLEAN",
                category=CATEGORY,
                severity="PASS" if clean else "FAIL",
                status="PASS" if clean else "FAIL",
                message="secret_scan_light reports no findings." if clean
                        else f"secret_scan_light failed: {r.stdout[-400:]}",
                principle=PRINCIPLE,
                recommendation="Review secret_scan_light output and remove leaked secrets." if not clean else "",
                blocking=not clean,
            ))
        except Exception as e:
            findings.append(Finding(
                id="SEC_SECRET_SCAN_CLEAN",
                category=CATEGORY,
                severity="WARN", status="SKIP",
                message=f"secret_scan_light could not be executed: {e}",
                principle=PRINCIPLE,
            ))

    # 3. workflow audit clean
    audit_wf = root / "scripts" / "audit_workflows.py"
    if audit_wf.exists():
        try:
            r = subprocess.run(
                [sys.executable, str(audit_wf)],
                capture_output=True, text=True, cwd=str(root), timeout=30,
            )
            clean = r.returncode == 0
            findings.append(Finding(
                id="SEC_WORKFLOW_AUDIT_CLEAN",
                category=CATEGORY,
                severity="PASS" if clean else "FAIL",
                status="PASS" if clean else "FAIL",
                message="audit_workflows reports no issues." if clean
                        else f"audit_workflows reports issues: {r.stdout[-400:]}",
                principle=PRINCIPLE,
                recommendation="Fix audit_workflows.py issues." if not clean else "",
            ))
        except Exception as e:
            findings.append(Finding(
                id="SEC_WORKFLOW_AUDIT_CLEAN",
                category=CATEGORY,
                severity="WARN", status="SKIP",
                message=f"audit_workflows could not be executed: {e}",
                principle=PRINCIPLE,
            ))

    # 4. mask() helper exists in secret_scan_light
    if secret_scan.exists():
        from ..utils import read_text
        text = read_text(secret_scan)
        has_mask = "def mask(" in text
        findings.append(Finding(
            id="SEC_ENV_MASKING_HELPER",
            category=CATEGORY,
            severity="PASS" if has_mask else "WARN",
            status="PASS" if has_mask else "WARN",
            message="mask() helper for secret-shaped strings present." if has_mask
                    else "No env-masking helper exposed.",
            principle=PRINCIPLE,
            recommendation="Expose a mask() helper in secret_scan_light or shared module." if not has_mask else "",
        ))

    return findings
