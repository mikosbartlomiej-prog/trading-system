"""Shared helpers: file walking, repo introspection, grep primitives."""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Iterable, Iterator

from .models import Evidence


def repo_root() -> Path:
    """The trading-system repo root (file is at tools/system_consistency_agent/utils.py)."""
    return Path(__file__).resolve().parent.parent.parent


def git_sha(repo: Path | None = None) -> str:
    """Best-effort HEAD SHA. Returns 'unknown' on failure."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True,
            cwd=str(repo or repo_root()), timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


DEFAULT_EXCLUDE_DIRS = (
    ".git", ".venv", "__pycache__", "node_modules",
    "reports", ".pytest_cache", ".mypy_cache",
)


def walk_files(
    root: Path | None = None,
    *,
    include_globs: Iterable[str] = ("*.py", "*.md", "*.yml", "*.yaml", "*.json"),
    exclude_dirs: Iterable[str] = DEFAULT_EXCLUDE_DIRS,
) -> Iterator[Path]:
    """Walk repo, yield files matching include_globs and outside exclude_dirs."""
    base = root or repo_root()
    excl = set(exclude_dirs)
    for cur_root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in excl]
        for fname in files:
            if any(fnmatch.fnmatch(fname, g) for g in include_globs):
                yield Path(cur_root) / fname


def read_text(path: Path) -> str:
    """Safe read — never raises. Returns '' if unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def grep_pattern(
    pattern: re.Pattern,
    paths: Iterable[Path],
    *,
    case_insensitive: bool = False,
    max_per_file: int = 5,
) -> list[Evidence]:
    """Return Evidence rows for every match of `pattern` in `paths`."""
    out: list[Evidence] = []
    for p in paths:
        text = read_text(p)
        if not text:
            continue
        hits_in_file = 0
        for i, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                out.append(Evidence(
                    file=str(rel(p)),
                    line=i,
                    snippet=line.strip()[:160],
                ))
                hits_in_file += 1
                if hits_in_file >= max_per_file:
                    break
    return out


def rel(p: Path, base: Path | None = None) -> Path:
    """Path relative to repo root (for stable Evidence.file values)."""
    try:
        return p.relative_to(base or repo_root())
    except ValueError:
        return p


def file_contains(path: Path, needle: str, *, case_insensitive: bool = False) -> bool:
    text = read_text(path)
    if not text:
        return False
    if case_insensitive:
        return needle.lower() in text.lower()
    return needle in text


def must_exist(*relpaths: str) -> tuple[list[str], list[str]]:
    """Returns (existing, missing) — used by category checks."""
    root = repo_root()
    existing: list[str] = []
    missing: list[str] = []
    for r in relpaths:
        if (root / r).exists():
            existing.append(r)
        else:
            missing.append(r)
    return existing, missing


def list_workflows(root: Path | None = None) -> list[Path]:
    """All YAML files under .github/workflows/ relative to `root`."""
    wf_dir = (root or repo_root()) / ".github" / "workflows"
    if not wf_dir.exists():
        return []
    return sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml"))


def python_modules_under(*dirs: str) -> list[Path]:
    """Python files under any of the given relative dirs."""
    root = repo_root()
    out: list[Path] = []
    for d in dirs:
        p = root / d
        if not p.exists():
            continue
        for f in p.rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            out.append(f)
    return sorted(out)
