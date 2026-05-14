"""
Patch validator — deterministic gate for autonomous code changes.

Treats every patch (regardless of origin: deterministic generator or LLM
draft) as UNTRUSTED. The validator inspects the unified diff + metadata
and decides one of:

  APPROVE_AUTO_MERGE   — low-risk, in allowlist, tests pass guarantee
  APPROVE_PR_ONLY      — medium-risk, eligible for auto-merge after CI
                         but always goes through a PR (no direct push)
  REJECT_HIGH_RISK     — high-risk; backlog only, never auto-merged
  REJECT_FORBIDDEN     — touches a forbidden file or pattern

This module never trusts an LLM. The LLM's only allowed role is to draft
the patch text; the validator decides what happens to it.

NB the validator does NOT execute tests itself — it only checks the
shape of the patch. CI (autonomous-code-loop.yml) runs the test suite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


# ─── File classification ──────────────────────────────────────────────────────

# Files where LOW_RISK edits are allowed (mostly docs + tests + scoring).
LOW_RISK_PATHS: tuple[str, ...] = (
    "docs/",
    "tests/",
    "scripts/audit_workflows.py",
    "scripts/secret_scan_light.py",
    "scripts/trading_health.py",
    "scripts/monitor_health.py",
)

# Files where MEDIUM_RISK edits are allowed (learning + risk thresholds).
MEDIUM_RISK_PATHS: tuple[str, ...] = (
    "learning-loop/adapter.py",
    "learning-loop/validation.py",
    "learning-loop/code_autonomy.py",
    "shared/signal_confirmation.py",
    "shared/portfolio_risk.py",
    "shared/state_schema.py",
    "shared/autonomy.py",
    "shared/remediation.py",
    "shared/emergency_engine.py",
    "shared/runtime_config.py",
    "config/autonomy_bounds.json",
)

# Files where NO autonomous edit is allowed. Touching these makes the
# patch automatically HIGH_RISK / backlog-only.
FORBIDDEN_PATHS: tuple[str, ...] = (
    "shared/alpaca_orders.py",
    "shared/risk_officer.py",
    "shared/risk_guards.py",
    "shared/market_data.py",     # changes API semantics
    "learning-loop/patch_validator.py",   # cannot self-modify
    "learning-loop/lane2_pr.py",
    "scripts/panic_close_options.py",
    ".github/workflows/auto-merge.yml",
    ".github/workflows/autonomous-code-loop.yml",
    ".github/workflows/security-audit.yml",
)

# Workflow files: only concurrency / permissions / CI hardening edits OK.
WORKFLOW_PATH_PREFIX = ".github/workflows/"


# ─── Forbidden content patterns ───────────────────────────────────────────────

FORBIDDEN_CONTENT_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("live_endpoint",       re.compile(r"api\.alpaca\.markets(?!/paper)", re.I)),
    ("live_endpoint_flag",  re.compile(r"LIVE_TRADING\s*=\s*[\"']?true", re.I)),
    ("live_endpoint_flag2", re.compile(r"LIVE_ENABLED\s*=\s*[\"']?true", re.I)),
    ("paper_only_disabled", re.compile(r"assert_paper_only\s*\(\s*None\s*\)", re.I)),
    ("risk_check_removed",  re.compile(r"#\s*risk[_-]?officer[_-]?(skip|bypass|disabled)", re.I)),
    ("portfolio_risk_off",  re.compile(r"USE_PORTFOLIO_RISK\s*=\s*[\"']?false", re.I)),
    ("disable_test",        re.compile(r"@(unittest\.)?skip\b|pytest\.mark\.skip\b|@xfail\b")),
    ("eval_exec",           re.compile(r"\b(eval|exec)\s*\(")),
    ("subprocess_shell",    re.compile(r"shell\s*=\s*True")),
    ("secret_literal",      re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}")),
    ("paid_dep_marker",     re.compile(r"#\s*paid[\s-]?dependency", re.I)),
)


# ─── Public types ─────────────────────────────────────────────────────────────

@dataclass
class PatchMetadata:
    """Caller-supplied context about the patch."""
    title: str = ""
    summary: str = ""
    author: str = "autonomous_code_loop"
    risk_hint: str = ""             # LLM-suggested; advisory only
    related_issue: str = ""
    test_coverage_added: bool = False
    rollback_branch: str = ""       # the SHA to revert to if post-merge health fails


@dataclass
class ValidationResult:
    verdict: str                     # APPROVE_AUTO_MERGE / APPROVE_PR_ONLY / REJECT_HIGH_RISK / REJECT_FORBIDDEN
    risk_category: str               # LOW_RISK / MEDIUM_RISK / HIGH_RISK / FORBIDDEN
    touched_files: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    forbidden_hits: list[dict] = field(default_factory=list)
    deleted_tests: list[str] = field(default_factory=list)


# ─── Diff parser ──────────────────────────────────────────────────────────────

def parse_touched_files(diff: str) -> list[str]:
    """Extract paths from `diff --git a/<path> b/<path>` headers."""
    files: list[str] = []
    for m in re.finditer(r"^diff --git a/(\S+) b/(\S+)", diff, re.M):
        target = m.group(2)
        if target not in files:
            files.append(target)
    # Also catch `+++ b/path` style if `diff --git` header is missing
    if not files:
        for m in re.finditer(r"^\+\+\+\s+b/(\S+)", diff, re.M):
            target = m.group(1)
            if target not in files and target != "/dev/null":
                files.append(target)
    return files


def _added_lines(diff: str) -> list[str]:
    """Just the added lines (starting with '+', excluding diff headers)."""
    out: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++"):
            continue
        if line.startswith("+"):
            out.append(line[1:])
    return out


def _removed_lines(diff: str) -> list[str]:
    out: list[str] = []
    for line in diff.splitlines():
        if line.startswith("---"):
            continue
        if line.startswith("-"):
            out.append(line[1:])
    return out


def _has_workflow_dangerous_edit(diff: str) -> bool:
    """
    Workflow edits allowed only when they ADD `concurrency:`, tighten
    permissions, or CI-only hardening. Forbid touching:
      - secrets:
      - new workflow_dispatch with arbitrary jobs
      - environment: (deployments)
    """
    add = "\n".join(_added_lines(diff))
    bad_patterns = (
        re.compile(r"^\s*secrets:", re.M),
        re.compile(r"environment:", re.I),
        re.compile(r"on:\s*\n\s*pull_request_target", re.I),
    )
    return any(p.search(add) for p in bad_patterns)


# ─── Validator ────────────────────────────────────────────────────────────────

def _classify_file(path: str) -> str:
    if any(path.startswith(p) for p in FORBIDDEN_PATHS):
        return "FORBIDDEN"
    if path in FORBIDDEN_PATHS:
        return "FORBIDDEN"
    if path.startswith(WORKFLOW_PATH_PREFIX):
        return "WORKFLOW"
    if any(path.startswith(p) for p in LOW_RISK_PATHS):
        return "LOW_RISK"
    if path in MEDIUM_RISK_PATHS or any(path == p for p in MEDIUM_RISK_PATHS):
        return "MEDIUM_RISK"
    return "HIGH_RISK"


def validate_patch(diff: str, metadata: PatchMetadata | None = None) -> ValidationResult:
    """
    Inspect a unified diff. Return a verdict explaining what may happen.
    """
    metadata = metadata or PatchMetadata()
    files = parse_touched_files(diff)
    if not files:
        return ValidationResult(
            verdict="REJECT_FORBIDDEN",
            risk_category="FORBIDDEN",
            touched_files=[],
            reasons=["empty diff — nothing to validate"],
        )

    reasons: list[str] = []
    warnings: list[str] = []
    forbidden_hits: list[dict] = []
    classes: list[str] = []

    # 1. File-level classification
    for path in files:
        cls = _classify_file(path)
        classes.append(cls)
        if cls == "FORBIDDEN":
            reasons.append(f"forbidden path: {path}")

    # 2. Forbidden content patterns in ADDED lines (not removed — removal is fine)
    add_blob = "\n".join(_added_lines(diff))
    for name, pat in FORBIDDEN_CONTENT_PATTERNS:
        m = pat.search(add_blob)
        if m:
            forbidden_hits.append({"pattern": name,
                                    "snippet": (m.group(0) or "")[:80]})

    # 3. Test deletion check — if a *.py under tests/ was removed entirely,
    #    block the patch. Soft-delete via filename rename is still flagged.
    deleted_tests: list[str] = []
    for path in files:
        if path.startswith("tests/") and re.search(
                rf"^diff --git a/{re.escape(path)} b/(?:/dev/null|{re.escape(path)})",
                diff, re.M):
            # Check the diff body actually removes all content
            removed = _removed_lines(diff)
            if removed and len(removed) > 5 and not _added_lines(diff):
                deleted_tests.append(path)

    # Also: any `-class Test...` / `-def test_` removed without a replacement
    if re.search(r"^-\s*(class\s+Test\w+|def\s+test_\w+)", diff, re.M):
        if not re.search(r"^\+\s*(class\s+Test\w+|def\s+test_\w+)", diff, re.M):
            reasons.append("removed test definition without replacement")

    # 4. Workflow safety
    workflow_files = [p for p in files if p.startswith(WORKFLOW_PATH_PREFIX)]
    if workflow_files and _has_workflow_dangerous_edit(diff):
        reasons.append("workflow edit touches secrets/environment/pull_request_target")

    # 5. requirements.txt / pyproject.toml / package.json — new dependency
    for path in files:
        if path.endswith(("requirements.txt", "pyproject.toml",
                          "package.json", "Pipfile")):
            # Detect ADDED package names in the diff. Any addition is HIGH_RISK
            # unless the line says something like "# free-tier".
            added = [l for l in _added_lines(diff)
                     if l.strip() and not l.lstrip().startswith("#")]
            if added:
                reasons.append(
                    f"dependency change in {path} ({len(added)} added lines) — HIGH_RISK"
                )

    # 6. Combine classifications
    has_forbidden = any(c == "FORBIDDEN" for c in classes)
    has_high = any(c == "HIGH_RISK" for c in classes)
    has_medium = any(c == "MEDIUM_RISK" for c in classes)
    has_workflow = any(c == "WORKFLOW" for c in classes)
    only_low = all(c == "LOW_RISK" for c in classes)
    if has_workflow:
        # workflow edits — must be CI hardening only; classification = MEDIUM
        has_medium = has_medium or not has_forbidden

    # Build verdict
    if has_forbidden or forbidden_hits or deleted_tests or reasons:
        verdict = "REJECT_FORBIDDEN" if (
            has_forbidden or forbidden_hits or deleted_tests
        ) else "REJECT_HIGH_RISK"
        risk = "FORBIDDEN" if has_forbidden else "HIGH_RISK"
        return ValidationResult(
            verdict=verdict, risk_category=risk,
            touched_files=files, reasons=reasons,
            warnings=warnings, forbidden_hits=forbidden_hits,
            deleted_tests=deleted_tests,
        )

    if has_high:
        return ValidationResult(
            verdict="REJECT_HIGH_RISK", risk_category="HIGH_RISK",
            touched_files=files,
            reasons=["file outside allowlist — backlog only"],
            warnings=warnings, forbidden_hits=[], deleted_tests=[],
        )

    if has_medium:
        # Medium-risk: auto-merge via PR, never direct push.
        if not metadata.test_coverage_added:
            warnings.append("MEDIUM_RISK patch should add/extend tests")
        return ValidationResult(
            verdict="APPROVE_PR_ONLY", risk_category="MEDIUM_RISK",
            touched_files=files,
            reasons=["medium-risk file edited; PR + CI required"],
            warnings=warnings, forbidden_hits=[], deleted_tests=[],
        )

    if only_low:
        return ValidationResult(
            verdict="APPROVE_AUTO_MERGE", risk_category="LOW_RISK",
            touched_files=files,
            reasons=["all touched files in low-risk allowlist"],
            warnings=warnings, forbidden_hits=[], deleted_tests=[],
        )

    # Default deny (should be unreachable, but explicit is better)
    return ValidationResult(
        verdict="REJECT_HIGH_RISK", risk_category="HIGH_RISK",
        touched_files=files,
        reasons=["unclassified path — defaulting to HIGH_RISK"],
    )


def is_auto_mergeable(result: ValidationResult) -> bool:
    return result.verdict in ("APPROVE_AUTO_MERGE", "APPROVE_PR_ONLY")
