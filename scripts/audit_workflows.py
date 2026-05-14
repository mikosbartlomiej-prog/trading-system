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

    # 3. git commit/push requires contents: write
    if writes_git_in_run(text) and contents_perm != "write":
        issues.append(
            f"{name}: uses `git commit`/`git push` but no `contents: write` permission"
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
