"""State write policy + schema coherence. Spec §9."""

from __future__ import annotations

from pathlib import Path

from ..models import Finding
from ..utils import read_text, list_workflows


CATEGORY = "state_policy"
PRINCIPLE = "STATE_WRITE_POLICY"


REQUIRED_ALLOWED_ACTORS = {"daily-learning", "daily-report",
                            "weekly-retro", "manual-maintenance"}


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    # 1. state_policy.py exists with allowlist
    sp = root / "shared" / "state_policy.py"
    if not sp.exists():
        findings.append(Finding(
            id="STATE_POLICY_MODULE_EXISTS",
            category=CATEGORY, severity="FAIL", status="FAIL",
            message="shared/state_policy.py missing.",
            principle=PRINCIPLE,
            recommendation="Restore shared/state_policy.py.",
            blocking=True,
        ))
    else:
        text = read_text(sp)
        actors_ok = all(a in text for a in REQUIRED_ALLOWED_ACTORS)
        findings.append(Finding(
            id="STATE_POLICY_ALLOWED_ACTORS",
            category=CATEGORY,
            severity="PASS" if actors_ok else "FAIL",
            status="PASS" if actors_ok else "FAIL",
            message="ALLOWED_ACTORS contains required writers." if actors_ok
                    else "ALLOWED_ACTORS missing one of: daily-learning/weekly-retro/daily-report/manual-maintenance.",
            principle=PRINCIPLE,
            recommendation="Restore the actor allowlist." if not actors_ok else "",
        ))
        has_assert = "assert_can_write_state" in text and "StateWriteForbidden" in text
        findings.append(Finding(
            id="STATE_POLICY_GUARD",
            category=CATEGORY,
            severity="PASS" if has_assert else "FAIL",
            status="PASS" if has_assert else "FAIL",
            message="assert_can_write_state + StateWriteForbidden defined." if has_assert
                    else "Missing assert_can_write_state / StateWriteForbidden.",
            principle=PRINCIPLE,
            recommendation="Re-add the assert/raise pair." if not has_assert else "",
        ))

    # 2. state_schema.py exists with validate_state
    ss = root / "shared" / "state_schema.py"
    if not ss.exists():
        findings.append(Finding(
            id="STATE_SCHEMA_MODULE_EXISTS",
            category=CATEGORY, severity="FAIL", status="FAIL",
            message="shared/state_schema.py missing.",
            principle=PRINCIPLE,
            recommendation="Restore shared/state_schema.py.",
            blocking=True,
        ))
    else:
        text = read_text(ss)
        has_required = ("validate_state" in text and "SIZE_MULT_MIN" in text
                        and "SIZE_MULT_MAX" in text)
        findings.append(Finding(
            id="STATE_SCHEMA_VALIDATOR",
            category=CATEGORY,
            severity="PASS" if has_required else "FAIL",
            status="PASS" if has_required else "FAIL",
            message="validate_state + size_multiplier bounds defined." if has_required
                    else "Missing validate_state or size_multiplier bounds.",
            principle=PRINCIPLE,
            recommendation="Restore validate_state + bounds." if not has_required else "",
        ))

    # 3. exit-monitor + reddit-monitor workflows do NOT commit state.json
    for wf_name in ("exit-monitor.yml", "reddit-monitor.yml"):
        wf = root / ".github" / "workflows" / wf_name
        if not wf.exists():
            continue
        text = read_text(wf)
        commits_state = "git add learning-loop/state.json" in text or \
                        "git commit" in text and "state.json" in text
        findings.append(Finding(
            id=f"STATE_POLICY_WORKFLOW_NO_STATE_COMMIT_{wf_name.replace('.yml','').upper()}",
            category=CATEGORY,
            severity="FAIL" if commits_state else "PASS",
            status="FAIL" if commits_state else "PASS",
            message=f"{wf_name} commits state.json on every tick." if commits_state
                    else f"{wf_name} does NOT commit state.json (correct).",
            principle=PRINCIPLE,
            recommendation=f"Remove state.json commit step from {wf_name}." if commits_state else "",
        ))

    return findings
