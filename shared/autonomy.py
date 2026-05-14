"""
Autonomy Contract — single source of truth for autonomous trading decisions.

This module:
  1. Defines the closed enum of decisions the system may take.
  2. Defines the closed enum of FORBIDDEN states (approval-needed, etc.).
  3. Provides `make_decision(...)` that builds an audit-quality record.
  4. Provides `assert_paper_only(endpoint)` — every autonomous flow MUST
     call this before any broker side-effect.
  5. Provides `assert_no_forbidden_strings(text)` so monitors can self-
     verify they aren't about to emit "approval needed".

Per docs/AUTONOMY_CONTRACT.md: no trading code path requires human
approval. Every signal ends APPROVE or REJECT. Every position ends HOLD
or CLOSE. Every operational error ends REMEDIATE / PAUSE / BLOCK / LOG.

Paper-only contract is mechanical: the only allowed Alpaca base URL is
`https://paper-api.alpaca.markets`. If autonomy code ever sees a
different URL, `assert_paper_only` raises and the autonomous flow stops.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Iterable


# ─── Allowed decisions ────────────────────────────────────────────────────────

DECISION_TYPES: frozenset[str] = frozenset({
    # Entries / signals
    "APPROVE_ENTRY",
    "REJECT_ENTRY",
    # Position management
    "HOLD_POSITION",
    "CLOSE_POSITION",
    # Strategy lifecycle
    "PAUSE_STRATEGY",
    "RESUME_STRATEGY",
    "BLOCK_NEW_ENTRIES",
    # Order maintenance
    "CLEANUP_STALE_ORDERS",
    "RECREATE_EXIT_PLAN",
    # Emergencies
    "EMERGENCY_CLOSE",
    "PANIC_CLOSE_OPTIONS",
    # Code self-improvement (used by code autonomy loop)
    "PATCH_APPROVE",
    "PATCH_REJECT",
    "PATCH_AUTO_MERGE",
    "PATCH_ROLLBACK",
})


# ─── FORBIDDEN states (never appear in trading path) ──────────────────────────

FORBIDDEN_STATES: frozenset[str] = frozenset({
    "APPROVAL_NEEDED",
    "WAITING_FOR_HUMAN",
    "MANUAL_CONFIRM_REQUIRED",
    "PENDING_USER_APPROVAL",
})

# Free-text variants the grep test should flag. Case-insensitive search.
FORBIDDEN_TEXT_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"approval\s+needed", re.I),
    re.compile(r"waiting\s+for\s+human", re.I),
    re.compile(r"manual\s+confirm(?:ation)?\s+required", re.I),
    re.compile(r"pending\s+user\s+approval", re.I),
    re.compile(r"please\s+approve", re.I),
    re.compile(r"awaiting\s+operator", re.I),
)


# ─── Paper-only invariant ─────────────────────────────────────────────────────

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


class PaperOnlyViolation(RuntimeError):
    """Raised when autonomous code sees a non-paper Alpaca endpoint.

    The system MUST refuse to act when this fires. Caller is expected to
    transition to BLOCKED state and emit no orders.
    """


def assert_paper_only(endpoint: str | None) -> None:
    """
    Refuse to operate against anything except the canonical paper API.

    Accepts None (treated as "no endpoint supplied — caller is using
    library defaults"; library defaults are also paper, so this is fine).
    Strict on any deviation.
    """
    if endpoint is None:
        return
    if not isinstance(endpoint, str):
        raise PaperOnlyViolation(f"endpoint not str: {type(endpoint).__name__}")
    e = endpoint.strip().rstrip("/")
    if e != PAPER_BASE_URL:
        raise PaperOnlyViolation(
            f"non-paper endpoint refused: '{endpoint}' (only {PAPER_BASE_URL} allowed)"
        )


class ForbiddenStateError(RuntimeError):
    """Raised when code attempts to emit / decision into a forbidden state."""


def assert_no_forbidden_strings(text: str, where: str = "") -> None:
    """Raise if `text` contains any approval-needed-like wording."""
    if not isinstance(text, str):
        return
    for pat in FORBIDDEN_TEXT_PATTERNS:
        if pat.search(text):
            raise ForbiddenStateError(
                f"forbidden approval-needed wording in {where or 'text'}: "
                f"'{pat.pattern}' matched '{text[:80]}...'"
            )


# ─── Decision record ──────────────────────────────────────────────────────────

@dataclass
class Decision:
    """Audit-quality record of a single autonomous decision."""
    decision_type: str
    decision: str
    reason: str
    actor: str
    timestamp: str
    affected_symbols: list[str] = field(default_factory=list)
    strategy: str | None = None
    risk_metrics: dict[str, Any] = field(default_factory=dict)
    deterministic_inputs_hash: str = ""
    state_before_hash: str = ""
    state_after_hash: str = ""
    code_before_sha: str = ""
    code_after_sha: str = ""
    action_taken: str = ""
    result: str = ""
    audit_path: str = ""
    reversible: bool = True
    rollback_available: bool = True
    rollback_action: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), default=str, sort_keys=True)


def _inputs_hash(inputs: Any) -> str:
    """Stable SHA1 over JSON-serialised inputs (sort_keys for determinism)."""
    try:
        raw = json.dumps(inputs, default=str, sort_keys=True)
    except (TypeError, ValueError):
        raw = repr(inputs)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def make_decision(
    decision_type: str,
    decision: str,
    reason: str,
    actor: str,
    *,
    inputs: Any = None,
    affected_symbols: Iterable[str] = (),
    strategy: str | None = None,
    risk_metrics: dict[str, Any] | None = None,
    reversible: bool = True,
    rollback_action: str = "",
    code_before_sha: str = "",
    code_after_sha: str = "",
    state_before: dict | None = None,
    state_after: dict | None = None,
    action_taken: str = "",
    result: str = "",
    errors: Iterable[str] = (),
) -> Decision:
    """
    Build a Decision record. Will:
      - validate decision_type in DECISION_TYPES
      - validate `decision` and `reason` don't contain forbidden text
      - compute inputs_hash + state_before/after hashes

    Does NOT write to disk — caller passes the result to
    `shared.audit.write_audit_event` (which is the only allowed writer).
    """
    if decision_type not in DECISION_TYPES:
        raise ValueError(
            f"unknown decision_type '{decision_type}'. Allowed: {sorted(DECISION_TYPES)}"
        )
    assert_no_forbidden_strings(decision, where=f"decision_type={decision_type}")
    assert_no_forbidden_strings(reason, where=f"decision_type={decision_type} reason")

    return Decision(
        decision_type=decision_type,
        decision=decision,
        reason=reason,
        actor=actor,
        timestamp=datetime.now(timezone.utc).isoformat(),
        affected_symbols=list(affected_symbols),
        strategy=strategy,
        risk_metrics=dict(risk_metrics or {}),
        deterministic_inputs_hash=_inputs_hash(inputs),
        state_before_hash=_inputs_hash(state_before) if state_before is not None else "",
        state_after_hash=_inputs_hash(state_after) if state_after is not None else "",
        code_before_sha=code_before_sha,
        code_after_sha=code_after_sha,
        action_taken=action_taken,
        result=result,
        reversible=reversible,
        rollback_available=bool(rollback_action),
        rollback_action=rollback_action,
        errors=list(errors),
    )


# ─── Static repo scan for forbidden strings ──────────────────────────────────

def scan_repo_for_forbidden(
    repo_root: str,
    *,
    include_patterns: Iterable[str] = ("*.py", "*.md", "*.yml", "*.yaml"),
    exclude_dirs: Iterable[str] = (
        ".git", ".venv", "__pycache__", "node_modules",
        "tests/architecture_vnext",   # tests intentionally reference forbidden strings
        "tests/e2e",                  # E2E tests intentionally reference forbidden strings
        "tools/e2e_system_test_agent",  # agent docstrings reference the rule
        "tools/system_consistency_agent",  # consistency-agent docstrings reference the rule
        "docs",                       # docs may explain that these states do NOT exist
        "reports",                    # generated audit reports
    ),
    exclude_files: Iterable[str] = (
        # Files allowed to reference the forbidden strings:
        #  - CLAUDE.md: historical session log, narrative-only
        #  - shared/autonomy.py: this module DEFINES the rule
        "CLAUDE.md",
        "shared/autonomy.py",
    ),
) -> list[dict[str, Any]]:
    """
    Walk the repo and return a list of {file, line, pattern, snippet} for
    each occurrence of forbidden approval-needed wording in trading code.

    Test fixture: tests/architecture_vnext/test_autonomy.py runs this
    against repo root and asserts the list is empty (modulo docs/tests).
    """
    import fnmatch

    findings: list[dict[str, Any]] = []
    exclude_set = set(exclude_dirs)
    exclude_file_set = set(exclude_files)

    for root, dirs, files in os.walk(repo_root):
        # in-place prune of excluded dirs
        rel = os.path.relpath(root, repo_root)
        if rel == ".":
            rel = ""
        if any(rel == d or rel.startswith(d + os.sep) for d in exclude_set):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in exclude_set]

        for fname in files:
            if not any(fnmatch.fnmatch(fname, p) for p in include_patterns):
                continue
            path = os.path.join(root, fname)
            rel_path = os.path.relpath(path, repo_root)
            if rel_path in exclude_file_set:
                continue
            try:
                with open(path, errors="ignore") as f:
                    for i, line in enumerate(f, start=1):
                        for pat in FORBIDDEN_TEXT_PATTERNS:
                            if pat.search(line):
                                findings.append({
                                    "file":    os.path.relpath(path, repo_root),
                                    "line":    i,
                                    "pattern": pat.pattern,
                                    "snippet": line.strip()[:120],
                                })
                                break
            except OSError:
                continue

    return findings
