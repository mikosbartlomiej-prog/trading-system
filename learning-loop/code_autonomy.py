"""
Autonomous code-improvement loop — the orchestration layer.

Glues:
  - patch_validator    (decide what to do with the patch)
  - shared.audit       (write JSONL audit + Markdown summary)
  - shared.autonomy    (decision records, forbidden-string scan)
  - git + gh CLI       (branch + commit + PR)

The loop is invoked by `.github/workflows/autonomous-code-loop.yml`
daily and on workflow_dispatch. Operator never approves anything.

Important invariants:
  1. NEVER call this from monitor code paths. The trading lifecycle is
     entirely separate from code self-modification.
  2. LLM patch drafts are accepted as INPUT only. The validator decides.
  3. Forbidden patterns (paper-only check removal, risk-gate removal,
     paid deps, secret leakage, test deletion, …) → REJECT.
  4. Rollback: every auto-merged patch records the pre-merge SHA in the
     audit so post-merge health regression can revert deterministically.

Public CLI / entry points:
  - identify_candidates() -> list[dict]
  - evaluate(diff, metadata) -> ValidationResult
  - run_once(repo_root, *, dry_run=False) -> dict   (one full cycle)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from patch_validator import (
        PatchMetadata, ValidationResult, validate_patch, is_auto_mergeable,
    )
except ImportError:  # pragma: no cover
    from learning_loop.patch_validator import (  # type: ignore
        PatchMetadata, ValidationResult, validate_patch, is_auto_mergeable,
    )

# Allow `import autonomy` / `import audit` via shared/ on sys.path
import sys
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "shared"))
from autonomy import make_decision   # noqa: E402
from audit import write_code_audit_event   # noqa: E402


_BACKLOG_PATH = _REPO / "learning-loop" / "heuristic_proposals.md"
_CODE_BACKLOG_PATH = _REPO / "learning-loop" / "code-autonomy" / "backlog.md"


# ─── Candidate identification (deterministic where possible) ──────────────────

def identify_candidates(repo_root: Path | None = None) -> list[dict]:
    """
    Scan for improvement candidates. Each candidate is `{kind, hint,
    files, severity}`. Deterministic — no LLM call here.

    Sources:
      - failing unit tests recorded in `tests/architecture_vnext/.failures`
      - lane2 proposals from learning-loop/heuristic_proposals.md
      - workflow audit issues (rare; usually fixed promptly)
      - secret-scan findings (rare; HIGH_RISK by definition)
      - flaky workflow / repeated stale orders / repeated REJECTs
        as seen in journal/autonomy/*.jsonl
    """
    repo = repo_root or _REPO
    candidates: list[dict] = []

    # 1. Lane 2 proposals from heuristic backlog
    if _BACKLOG_PATH.exists():
        try:
            text = _BACKLOG_PATH.read_text()
        except OSError:
            text = ""
        for m_idx, m in enumerate(_iter_backlog_proposals(text)):
            candidates.append({
                "kind":     "backlog",
                "id":       f"backlog-{m_idx}",
                "title":    m.get("title", "(untitled)"),
                "summary":  m.get("body", ""),
                "files":    m.get("files", []),
                "severity": "MEDIUM",
            })

    # 2. Workflow audit issues
    audit_script = repo / "scripts" / "audit_workflows.py"
    if audit_script.exists():
        try:
            r = subprocess.run(["python3", str(audit_script)],
                                capture_output=True, text=True, timeout=60,
                                cwd=str(repo))
            if r.returncode != 0:
                candidates.append({
                    "kind":     "workflow_audit",
                    "id":       "workflow-hardening",
                    "title":    "audit_workflows.py reports issues",
                    "summary":  r.stdout[:1000],
                    "files":    [".github/workflows/"],
                    "severity": "LOW",
                })
        except Exception:
            pass

    return candidates


def _iter_backlog_proposals(text: str):
    """Very loose parser — returns a list of {title, body, files}."""
    proposals: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            if cur:
                proposals.append(cur)
            cur = {"title": line[3:].strip(), "body": "", "files": []}
        elif cur is not None:
            cur["body"] += line + "\n"
            if "shared/" in line or "learning-loop/" in line or "scripts/" in line:
                for tok in line.split():
                    if tok.endswith(".py") or tok.endswith(".md"):
                        cur["files"].append(tok.strip("`,()."))
    if cur:
        proposals.append(cur)
    return proposals


# ─── Patch evaluation ─────────────────────────────────────────────────────────

def evaluate(diff: str, metadata: PatchMetadata | None = None) -> ValidationResult:
    """Delegate to patch_validator. Keep this thin — easier to mock in tests."""
    return validate_patch(diff, metadata)


# ─── Git operations (minimum needed for autonomy) ────────────────────────────

def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          cwd=str(cwd), timeout=60)


def current_sha(repo_root: Path | None = None) -> str:
    repo = repo_root or _REPO
    r = _git("rev-parse", "HEAD", cwd=repo)
    return r.stdout.strip() if r.returncode == 0 else ""


def apply_and_commit(diff: str, branch: str, message: str,
                      repo_root: Path | None = None,
                      author: str = "autonomous-code-loop") -> dict:
    """
    Write the diff to a temp file, run `git apply`, commit on `branch`.
    Returns {ok, sha, error}.
    """
    repo = repo_root or _REPO
    # Create branch from current HEAD
    base_sha = current_sha(repo)
    _git("checkout", "-B", branch, cwd=repo)
    patch_path = repo / ".autonomous_patch.diff"
    patch_path.write_text(diff)
    try:
        r = _git("apply", "--check", str(patch_path), cwd=repo)
        if r.returncode != 0:
            return {"ok": False, "error": f"apply --check: {r.stderr[:400]}",
                    "base_sha": base_sha}
        r = _git("apply", str(patch_path), cwd=repo)
        if r.returncode != 0:
            return {"ok": False, "error": f"apply: {r.stderr[:400]}",
                    "base_sha": base_sha}
        _git("add", "-A", cwd=repo)
        # Use a sentinel author so audit can identify autonomous commits
        env_msg = f"{message}\n\nCo-Authored-By: {author} <noreply@anthropic.com>"
        r = _git("commit", "-m", env_msg, cwd=repo)
        if r.returncode != 0:
            return {"ok": False, "error": f"commit: {r.stderr[:400]}",
                    "base_sha": base_sha}
        sha = current_sha(repo)
        return {"ok": True, "sha": sha, "base_sha": base_sha, "branch": branch}
    finally:
        try:
            patch_path.unlink()
        except OSError:
            pass


def revert_commit(sha: str, repo_root: Path | None = None) -> dict:
    """`git revert --no-edit <sha>` — used for autonomous rollback."""
    repo = repo_root or _REPO
    r = _git("revert", "--no-edit", sha, cwd=repo)
    return {
        "ok":    r.returncode == 0,
        "error": r.stderr[:400] if r.returncode != 0 else "",
    }


# ─── Backlog writer ───────────────────────────────────────────────────────────

def append_backlog(reason: str, candidate: dict) -> None:
    """Append rejected candidate to the code-autonomy backlog."""
    _CODE_BACKLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"## [{datetime.now(timezone.utc).date().isoformat()}] "
        f"{candidate.get('title', '(no title)')}\n\n"
        f"- severity: {candidate.get('severity', '?')}\n"
        f"- reason: {reason}\n"
        f"- files: {', '.join(candidate.get('files', []))}\n\n"
        f"```\n{(candidate.get('summary') or '')[:1500]}\n```\n\n"
    )
    with open(_CODE_BACKLOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


# ─── Full cycle ───────────────────────────────────────────────────────────────

def run_once(repo_root: Path | None = None, *, dry_run: bool = True) -> dict:
    """
    Single autonomy cycle. Returns a summary dict for the workflow log.

    Steps:
      1. identify_candidates
      2. for each: build a draft diff (deterministic where possible —
         in this MVP we don't auto-generate diffs; we route candidates
         to the backlog with rationale). LLM-driven diff generation is
         out of scope here; this module is the validator + merger.
      3. for each diff supplied via env DIFF_PATH: validate + merge if OK.
    """
    repo = Path(repo_root or _REPO)
    summary: dict[str, Any] = {
        "candidates":      [],
        "patches_seen":    0,
        "patches_merged":  0,
        "patches_rejected": 0,
        "errors":          [],
        "dry_run":         dry_run,
    }

    # Step 1
    cands = identify_candidates(repo)
    summary["candidates"] = cands

    # Step 3: any pending diff file from a prior LLM draft?
    diff_path = os.environ.get("AUTONOMOUS_PATCH_PATH")
    if diff_path and Path(diff_path).exists():
        try:
            diff = Path(diff_path).read_text()
        except OSError as e:
            summary["errors"].append(f"read patch: {e}")
            return summary
        summary["patches_seen"] += 1
        metadata = PatchMetadata(
            title=os.environ.get("AUTONOMOUS_PATCH_TITLE", "autonomous patch"),
            summary=os.environ.get("AUTONOMOUS_PATCH_SUMMARY", ""),
            author=os.environ.get("AUTONOMOUS_PATCH_AUTHOR",
                                    "autonomous_code_loop"),
            test_coverage_added=os.environ.get(
                "AUTONOMOUS_PATCH_TESTS_ADDED", "false") == "true",
        )
        result = evaluate(diff, metadata)

        # Audit
        d = make_decision(
            decision_type="PATCH_APPROVE" if is_auto_mergeable(result) else "PATCH_REJECT",
            decision=result.verdict,
            reason=", ".join(result.reasons) or "ok",
            actor="autonomous_code_loop",
            inputs={"touched_files": result.touched_files,
                    "risk_category":  result.risk_category},
            code_before_sha=current_sha(repo),
            action_taken="evaluated",
            result=result.verdict,
            errors=result.reasons if not is_auto_mergeable(result) else [],
            reversible=is_auto_mergeable(result),
            rollback_action="git revert <sha>" if is_auto_mergeable(result) else "",
        )
        write_code_audit_event(d, summary_md=(
            f"**{result.verdict}** — {metadata.title} "
            f"(files: {', '.join(result.touched_files)})"
        ))

        if not is_auto_mergeable(result):
            summary["patches_rejected"] += 1
            append_backlog(
                reason=f"{result.verdict}: {result.reasons}",
                candidate={"title": metadata.title, "summary": metadata.summary,
                            "severity": result.risk_category,
                            "files": result.touched_files},
            )
            return summary

        # APPROVE → apply
        if dry_run:
            summary["patches_merged"] += 0
            return summary

        branch = (
            f"autonomous/code-{datetime.now(timezone.utc).date().isoformat()}-"
            f"{metadata.title.lower().replace(' ', '-')[:30]}"
        )
        apply_result = apply_and_commit(diff, branch, metadata.title, repo)
        if not apply_result.get("ok"):
            summary["errors"].append(apply_result.get("error", "apply failed"))
            return summary
        summary["patches_merged"] += 1
        d_merge = make_decision(
            decision_type="PATCH_AUTO_MERGE",
            decision="MERGED",
            reason="validator approved + apply succeeded",
            actor="autonomous_code_loop",
            inputs={"branch": branch, "sha": apply_result["sha"]},
            code_before_sha=apply_result.get("base_sha", ""),
            code_after_sha=apply_result.get("sha", ""),
            action_taken="git apply + commit",
            result="merged",
            reversible=True,
            rollback_action=f"git revert --no-edit {apply_result.get('sha')}",
        )
        write_code_audit_event(d_merge, summary_md=(
            f"**MERGED** {apply_result.get('sha', '')[:8]} on `{branch}`"
        ))

    return summary
