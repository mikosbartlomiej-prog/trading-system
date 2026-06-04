#!/usr/bin/env python3
"""
Static auditor for .github/workflows/*.yml.

Checks (spec §B and §J):

  1. Every schedule-triggered workflow has a `concurrency:` block.
  2. Permissions are explicit and minimal:
       - default `contents: read`
       - `contents: write` only on an allow-list of writers
       - `pull-requests: write` only on PR-creating workflows
       - `actions: write` only on watchdog/manual-trigger workflows
  3. Workflows that `git commit` something declare `contents: write`.
  4. No workflow leaks raw secrets into `run:` strings.

Exits 0 when all checks pass, 1 otherwise. Designed to be invoked from
.github/workflows/security-audit.yml on every PR.

Implementation note: parsed with a tiny line-oriented regex parser rather
than PyYAML so the script has zero runtime dependencies — runs anywhere
Python 3.11 + stdlib is available (matches the rest of the repo).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# Workflows allowed to write to repo (commit state files etc.). Anything not
# on this list MUST NOT have `contents: write`.
CONTENTS_WRITE_ALLOWLIST: set[str] = {
    "auto-merge.yml",
    "daily-learning.yml",
    "daily-learning-watchdog.yml",
    "emergency-close-positions.yml",
    "morning-allocator.yml",
    "weekly-retro.yml",
    "sync-workflows.yml",
    "monitor-health.yml",
    "autonomous-code-loop.yml",
    # v3.5 IntradayProfitGovernor — exit-monitor + options-exit-monitor
    # commit learning-loop/runtime_state.json each tick so FSM state
    # persists across 5-min runs. Allowed write scope = ONLY that file
    # (enforced by workflow's `git add` line, not by audit).
    "exit-monitor.yml",
    "options-exit-monitor.yml",
    # v3.8.8 (2026-05-18) — reddit-monitor + crypto-monitor commit
    # learning-loop/runtime_state.json so routine_budget counters persist
    # across cron ticks (curator P2_optional cap of 4/day must enforce
    # globally, not per-tick). Allowed write scope = ONLY runtime_state.json
    # (enforced by workflow's `git add learning-loop/runtime_state.json`).
    "reddit-monitor.yml",
    "crypto-monitor.yml",
    # v3.9.2 (2026-05-21) — politician-monitor commits its dedupe state
    # (politician-monitor/state.json) + may update runtime_state.json
    # via routine_budget. Allowed write scope = ONLY politician-monitor/
    # state.json + learning-loop/runtime_state.json (enforced by
    # workflow's explicit `git add` lines).
    "politician-monitor.yml",
    # v3.9.6 (2026-05-22 post-incident) — autonomous-remediation commits
    # audit JSONL events to journal/autonomy/<date>.jsonl. Previously
    # contents:read meant audit writes never reached origin (2026-05-22
    # incident had 0 audit events for 7+ position-affecting remediation
    # runs). Allowed write scope = ONLY journal/autonomy/.
    "autonomous-remediation.yml",
    # v3.9.10 (2026-05-27) — forensic-position-origin commits audit JSONL
    # findings (provenance audit). Operator-triggered workflow_dispatch only.
    # Allowed write scope = ONLY journal/autonomy/ (enforced by workflow's
    # explicit `git add journal/autonomy/`).
    "forensic-position-origin.yml",
    # v3.9.10 Layer 1 (2026-05-27) — incident-pattern-detector commits
    # learning-loop/incidents/<date>.md + audit JSONL + (rarely) flips
    # config/capital_deployment.json::auto_execute_rebalance=false on
    # CRITICAL finding (only when INCIDENT_AUTO_DISABLE=true env set).
    # Cron */5 24/7. Allowed write scope = incidents/ + journal/autonomy/
    # + config/capital_deployment.json (operator-reversible flip).
    "incident-pattern-detector.yml",
    # v3.10 (2026-05-27) — one-shot op-correction for 2026-05-27 NOW SHORT
    # incident. Cron '31 13 28 5 *' fires only on 2026-05-28 13:31 UTC.
    # Commits audit JSONL of buy-to-cover decision. Can be deleted after
    # successful run (kept for historical traceability).
    "cover-now-short-20260528.yml",
    # v3.16.0 (2026-06-04) — doj-monitor commits its dedupe state
    # (doj-monitor/state.json) + runtime_state.json (heartbeat + routine_budget).
    # SEC 8-K + DOJ RSS emit-only monitor (FB-008 Option B). Cron 0 */2 24/7.
    # Allowed write scope = ONLY doj-monitor/state.json + learning-loop/
    # runtime_state.json (enforced by workflow's explicit `git add` lines).
    "doj-monitor.yml",
}

# Workflows allowed to create PRs.
PR_WRITE_ALLOWLIST: set[str] = {
    "daily-learning.yml",
    "autonomous-code-loop.yml",
}

# Workflows allowed to trigger other workflows.
ACTIONS_WRITE_ALLOWLIST: set[str] = {
    "daily-learning-watchdog.yml",
    "sync-workflows.yml",
    # v3.6 entry-monitors-watchdog retriggers stale price-monitor /
    # options-monitor when their last run is > 10 min old (defends
    # against GitHub Actions cron-skip seen during 2026-05-13/14 push event).
    "entry-monitors-watchdog.yml",
}


RE_TOP_LEVEL_KEY = re.compile(r"^([a-zA-Z_-]+):", re.M)


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""


def has_schedule(text: str) -> bool:
    """True if the workflow has a `schedule:` trigger."""
    if "schedule:" not in text:
        return False
    # Crude: schedule must appear under the `on:` block. We accept any
    # occurrence — false positives are vanishingly rare in practice.
    return bool(re.search(r"^\s*schedule:\s*$", text, re.M))


def has_concurrency(text: str) -> bool:
    return bool(re.search(r"^concurrency:\s*$", text, re.M))


def has_workflow_dispatch(text: str) -> bool:
    return "workflow_dispatch:" in text


def get_permissions_block(text: str) -> dict[str, str]:
    """
    Parse top-level `permissions:` block. Returns {key: value}.
    Sub-job permissions are NOT inspected — auditor focuses on workflow-level.
    """
    perms: dict[str, str] = {}
    # Tolerant of inline `# comments` on each line.
    m = re.search(r"^permissions:\s*\n((?:\s+[a-zA-Z_-]+:\s*[a-zA-Z_-]+\s*(?:#[^\n]*)?\n)+)",
                  text, re.M)
    if not m:
        # Inline form?
        m2 = re.search(r"^permissions:\s*([a-zA-Z_-]+)\s*$", text, re.M)
        if m2:
            perms["__inline__"] = m2.group(1)
        return perms
    body = m.group(1)
    for line in body.splitlines():
        line = line.split("#", 1)[0].strip()  # drop comment, strip
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        perms[k.strip()] = v.strip()
    return perms


def writes_git_in_run(text: str) -> bool:
    """Heuristic: does any `run:` step invoke `git commit` or `git push`?"""
    for m in re.finditer(r"run:\s*\|?\s*\n?(.+?)(?:\n\s*-\s*name:|\Z)", text, re.S):
        body = m.group(1)
        if re.search(r"\bgit\s+(commit|push)\b", body):
            return True
    # Also catch single-line `run: git commit ...`
    if re.search(r"run:\s*.*\bgit\s+(commit|push)\b", text):
        return True
    return False


def find_secret_leaks(text: str) -> list[str]:
    """
    Detect patterns that would echo raw secrets to logs. Common bad pattern:
      run: echo ${{ secrets.FOO }}
      run: curl ... -H "Authorization: $TOKEN"
    """
    issues: list[str] = []
    for m in re.finditer(r"run:\s*echo\s+(?:.*\$\{\{\s*secrets\.[A-Z_]+\s*\}\})", text):
        issues.append(f"echo-secret-to-log: {m.group(0)[:80]}")
    return issues


def audit_workflow(path: Path) -> list[str]:
    name = path.name
    text = _read(path)
    if not text.strip():
        return [f"{name}: empty / unreadable"]

    issues: list[str] = []

    # 1. concurrency required on schedule workflows
    if has_schedule(text) and not has_concurrency(text):
        issues.append(
            f"{name}: schedule workflow MUST declare `concurrency:` "
            "(spec §B.1)"
        )

    # 2. permissions
    perms = get_permissions_block(text)
    contents_perm = perms.get("contents", perms.get("__inline__", ""))
    pr_perm = perms.get("pull-requests", "")
    actions_perm = perms.get("actions", "")

    if contents_perm == "write" and name not in CONTENTS_WRITE_ALLOWLIST:
        issues.append(
            f"{name}: declares `contents: write` but not on allow-list "
            f"(spec §B.4). Allow-list: {sorted(CONTENTS_WRITE_ALLOWLIST)}"
        )
    if pr_perm == "write" and name not in PR_WRITE_ALLOWLIST:
        issues.append(
            f"{name}: declares `pull-requests: write` but not on allow-list "
            f"(spec §B.4)"
        )
    if actions_perm == "write" and name not in ACTIONS_WRITE_ALLOWLIST:
        issues.append(
            f"{name}: declares `actions: write` but not on allow-list "
            f"(spec §B.4)"
        )

    # 3. git commit/push requires contents: write — UNLESS the push is
    # done with a personal access token (PAT, e.g. WORKFLOW_PAT) which
    # supplies its own write scope. sync-workflows.yml uses WORKFLOW_PAT
    # for the push so GITHUB_TOKEN's contents: read is correct.
    uses_pat = re.search(r"\$\{\{\s*secrets\.WORKFLOW_PAT\s*\}\}", text) is not None
    if writes_git_in_run(text) and contents_perm != "write" and not uses_pat:
        issues.append(
            f"{name}: uses `git commit`/`git push` but no `contents: write` permission "
            f"(and no WORKFLOW_PAT detected — set one or grant contents:write)"
        )

    # 4. secret-leak heuristics
    for leak in find_secret_leaks(text):
        issues.append(f"{name}: {leak}")

    return issues


def iter_workflows() -> Iterable[Path]:
    if not WORKFLOWS_DIR.exists():
        return []
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


def main() -> int:
    total = 0
    failing = 0
    all_issues: list[str] = []
    for wf in iter_workflows():
        total += 1
        issues = audit_workflow(wf)
        if issues:
            failing += 1
            all_issues.extend(issues)

    if all_issues:
        print("=== workflow-audit FAILED ===\n")
        for line in all_issues:
            print(f"  - {line}")
        print(f"\n{failing}/{total} workflows have issues.")
        return 1

    print(f"=== workflow-audit OK ({total} workflows clean) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
