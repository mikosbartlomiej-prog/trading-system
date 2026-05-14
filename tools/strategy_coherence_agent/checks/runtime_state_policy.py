"""Spec §19 — runtime state policy.

  - shared/state_policy.py exists with an ALLOWED_ACTORS allowlist.
  - 5-min monitor workflows DO NOT write learning-loop/state.json
    (rule C from architecture vNext).
  - Intraday governor / peak tracker persistence lives in a runtime file
    (e.g. learning-loop/runtime_state.json) NOT state.json.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Evidence, Finding
from ..utils import list_workflows, read_text, rel


CATEGORY  = "runtime_state_policy"
PRINCIPLE = "RUNTIME_STATE_POLICY"

# Monitor workflows that may NOT commit state.json (5-min cron files).
MONITOR_WORKFLOW_GLOBS = (
    "price-monitor.yml", "crypto-monitor.yml", "defense-monitor.yml",
    "geo-monitor.yml", "twitter-monitor.yml", "reddit-monitor.yml",
    "options-monitor.yml",
)


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    sp = root / "shared" / "state_policy.py"
    if not sp.exists():
        out.append(Finding(
            id="RSP_STATE_POLICY_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="shared/state_policy.py missing.",
            recommendation="Add the state-write allowlist module.",
        ))
        return out

    sp_text = read_text(sp)
    if "ALLOWED_ACTORS" not in sp_text:
        out.append(Finding(
            id="RSP_ALLOWED_ACTORS_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message="state_policy.py missing ALLOWED_ACTORS allowlist.",
            recommendation="Add ALLOWED_ACTORS frozenset.",
            evidence=[Evidence(file=str(rel(sp)))],
        ))
    else:
        out.append(Finding(
            id="RSP_ALLOWED_ACTORS_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="state_policy.ALLOWED_ACTORS declared.",
        ))

    # Runtime allowlist (for the new intraday governor file)
    if "RUNTIME_STATE_ACTORS" in sp_text or "runtime_state" in sp_text:
        out.append(Finding(
            id="RSP_RUNTIME_ALLOWLIST_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="state_policy distinguishes runtime_state.json from state.json.",
        ))
    else:
        out.append(Finding(
            id="RSP_RUNTIME_ALLOWLIST_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="state_policy.py has no separate runtime_state.json allowlist.",
            recommendation="Add RUNTIME_STATE_ACTORS (intraday-monitor, etc.) "
                           "so high-frequency monitors don't pollute state.json.",
            evidence=[Evidence(file=str(rel(sp)))],
        ))

    # 5-min monitor workflows do NOT commit state.json
    wf_dir = root / ".github" / "workflows"
    offenders: list[Evidence] = []
    for wf in MONITOR_WORKFLOW_GLOBS:
        p = wf_dir / wf
        if not p.exists():
            continue
        text = read_text(p)
        # A workflow that does `git add learning-loop/state.json` + push is
        # the dangerous pattern.
        if "state.json" in text and "git add" in text \
           and "runtime_state.json" not in text:
            for i, line in enumerate(text.splitlines(), 1):
                if "state.json" in line and "runtime_state.json" not in line:
                    offenders.append(Evidence(file=str(rel(p)), line=i,
                                              snippet=line.strip()[:160]))
                    break
    if offenders:
        out.append(Finding(
            id="RSP_MONITOR_COMMITS_STATE_JSON",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message=f"Monitor workflow(s) commit state.json: {len(offenders)} found.",
            expected="Monitors NEVER commit state.json (rule C).",
            observed=f"{len(offenders)} workflow(s) do",
            recommendation="Move writes to runtime_state.json or remove the "
                           "git-add step.",
            evidence=offenders[:8],
        ))
    else:
        out.append(Finding(
            id="RSP_MONITORS_RESPECT_RULE_C",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="No monitor workflow commits state.json.",
        ))

    # Intraday governor persistence is NOT in state.json
    gov = root / "shared" / "intraday_governor.py"
    if gov.exists():
        gt = read_text(gov)
        if "state.json" in gt and "runtime_state" not in gt:
            out.append(Finding(
                id="RSP_GOVERNOR_USES_STATE_JSON",
                category=CATEGORY, severity="FAIL", status="FAIL",
                principle=PRINCIPLE,
                message="intraday_governor persists to state.json — "
                        "this is the rule-C violation that broke v3.3.",
                expected="Persistence in runtime_state.json (separate file)",
                observed="state.json reference in module",
                recommendation="Migrate to shared.runtime_state (separate file).",
                evidence=[Evidence(file=str(rel(gov)))],
            ))
        elif "runtime_state" in gt:
            out.append(Finding(
                id="RSP_GOVERNOR_USES_RUNTIME_STATE",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="intraday_governor uses runtime_state.json (correct).",
            ))

    # shared/runtime_state.py must actually exist — the governor's import
    # would fail loudly in production but a static audit should call this
    # out before that happens.
    rs = root / "shared" / "runtime_state.py"
    if not rs.exists():
        out.append(Finding(
            id="RSP_RUNTIME_STATE_MODULE_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="shared/runtime_state.py missing — intraday_governor "
                    "has no persistence backend.",
            expected="shared/runtime_state.py with read_section / write_section",
            observed="file absent",
            recommendation="Add shared/runtime_state.py custodying "
                           "learning-loop/runtime_state.json.",
        ))
    else:
        rst = read_text(rs)
        if "runtime_state.json" not in rst:
            out.append(Finding(
                id="RSP_RUNTIME_STATE_FILE_PATH_UNCLEAR",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="shared/runtime_state.py does not reference learning-loop/runtime_state.json.",
                recommendation="Pin the canonical file path so other tools can grep for it.",
                evidence=[Evidence(file=str(rel(rs)))],
            ))
        else:
            out.append(Finding(
                id="RSP_RUNTIME_STATE_MODULE_OK",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="shared/runtime_state.py custodies learning-loop/runtime_state.json.",
            ))

    # exit-monitor.yml workflow MUST set STATE_WRITE_ACTOR — otherwise the
    # state_policy assertion will reject every runtime_state write at
    # cron-tick time.
    em_yml = root / ".github" / "workflows" / "exit-monitor.yml"
    if em_yml.exists():
        em_text = read_text(em_yml)
        if "STATE_WRITE_ACTOR" not in em_text:
            out.append(Finding(
                id="RSP_EXIT_MONITOR_NO_ACTOR",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="exit-monitor.yml does not set STATE_WRITE_ACTOR — "
                        "runtime_state.json writes will be rejected at runtime.",
                expected="env.STATE_WRITE_ACTOR=intraday-monitor (or exit-monitor)",
                observed="env var absent",
                recommendation="Add STATE_WRITE_ACTOR to the env block.",
                evidence=[Evidence(file=str(rel(em_yml)))],
            ))
        elif "intraday-monitor" in em_text or "exit-monitor" in em_text:
            out.append(Finding(
                id="RSP_EXIT_MONITOR_ACTOR_OK",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="exit-monitor.yml declares STATE_WRITE_ACTOR.",
            ))

    return out
