"""Read-only helpers for strategy-coherence checks.

Mostly file walkers, AST/regex/JSON/YAML parsers and a couple of small
heuristics. Deliberately no shared state with `system_consistency_agent`
so the two agents can be edited independently.
"""

from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Iterable, Iterator

from .models import Evidence


# ─── Repo locators ──────────────────────────────────────────────────────────

def repo_root() -> Path:
    """tools/strategy_coherence_agent/utils.py → repo root."""
    return Path(__file__).resolve().parent.parent.parent


def git_sha(repo: Path | None = None) -> str:
    """Best-effort HEAD SHA; returns 'unknown' on failure."""
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


def rel(p: Path, base: Path | None = None) -> Path:
    """Path relative to repo root (for stable Evidence.file values)."""
    try:
        return p.relative_to(base or repo_root())
    except ValueError:
        return p


# ─── File walking ───────────────────────────────────────────────────────────

DEFAULT_EXCLUDE_DIRS = (
    ".git", ".venv", "__pycache__", "node_modules",
    "reports", ".pytest_cache", ".mypy_cache", "dist", "build",
)


def walk_files(
    root: Path | None = None,
    *,
    include_globs: Iterable[str] = ("*.py", "*.md", "*.yml", "*.yaml", "*.json"),
    exclude_dirs: Iterable[str] = DEFAULT_EXCLUDE_DIRS,
) -> Iterator[Path]:
    base = root or repo_root()
    excl = set(exclude_dirs)
    for cur_root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in excl]
        for fname in files:
            if any(fnmatch.fnmatch(fname, g) for g in include_globs):
                yield Path(cur_root) / fname


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def read_json(path: Path) -> dict | None:
    """Parse a JSON file safely. Returns None on any failure."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def read_yaml(path: Path) -> dict | None:
    """Best-effort YAML reader. Falls back to None if PyYAML isn't installed."""
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# ─── Grep / pattern matching ────────────────────────────────────────────────

def grep_pattern(
    pattern: re.Pattern,
    paths: Iterable[Path],
    *,
    max_per_file: int = 5,
) -> list[Evidence]:
    out: list[Evidence] = []
    for p in paths:
        text = read_text(p)
        if not text:
            continue
        hits_in_file = 0
        for i, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                out.append(Evidence(file=str(rel(p)), line=i,
                                    snippet=line.strip()[:200]))
                hits_in_file += 1
                if hits_in_file >= max_per_file:
                    break
    return out


def file_contains(path: Path, needle: str, *, case_insensitive: bool = False) -> bool:
    text = read_text(path)
    if not text:
        return False
    if case_insensitive:
        return needle.lower() in text.lower()
    return needle in text


def first_line_with(path: Path, needle: str) -> Evidence | None:
    text = read_text(path)
    if not text:
        return None
    for i, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return Evidence(file=str(rel(path)), line=i, snippet=line.strip()[:200])
    return None


# ─── Existence helpers ──────────────────────────────────────────────────────

def must_exist(*relpaths: str) -> tuple[list[str], list[str]]:
    """Returns (existing, missing)."""
    root = repo_root()
    existing: list[str] = []
    missing: list[str]  = []
    for r in relpaths:
        if (root / r).exists():
            existing.append(r)
        else:
            missing.append(r)
    return existing, missing


def list_workflows(root: Path | None = None) -> list[Path]:
    wf_dir = (root or repo_root()) / ".github" / "workflows"
    if not wf_dir.exists():
        return []
    return sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml"))


def python_modules_under(*dirs: str) -> list[Path]:
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


# ─── AST helpers ────────────────────────────────────────────────────────────

def parse_python(path: Path) -> ast.Module | None:
    """Parse a Python file. Returns None on syntax error."""
    text = read_text(path)
    if not text:
        return None
    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError:
        return None


def function_names(path: Path) -> set[str]:
    """Top-level + class-method names in a Python file (for wiring checks)."""
    tree = parse_python(path)
    if tree is None:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def imports_module(path: Path, module: str) -> bool:
    """True if the file imports `module` (top-level or `from <module> import …`)."""
    tree = parse_python(path)
    if tree is None:
        # Fallback to text scan.
        return module in read_text(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(n.name == module or n.name.startswith(module + ".") for n in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == module
                                or node.module.startswith(module + ".")):
                return True
    return False


# ─── Numeric extraction (for value-conflict detection) ──────────────────────

# Catches things like:
#   `"max_gross_exposure": 1.50,`        ← JSON / Markdown table
#   `"max_gross_exposure": 1.50`         ← end of line / inline doc
#   `MAX_GROSS = 1.5`                    ← Python module constant
# Word-boundary after the number lets the pattern terminate at EOL, comma,
# whitespace, or brace.
_NUMERIC_PATTERNS = (
    re.compile(r'"([a-z_][a-z0-9_]*)"\s*:\s*([0-9]+(?:\.[0-9]+)?)\b', re.I),
    re.compile(r'^\s*([A-Z][A-Z0-9_]+)\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*$', re.M),
)


def extract_numeric_settings(path: Path) -> dict[str, list[tuple[int, str]]]:
    """Return {key: [(line, value_str), ...]} for known-shape numeric settings.

    Both dictionary keys (JSON-like) and ALL_CAPS Python constants are
    captured. Used by `documentation_parity` to compare same-named keys
    across config files and docs.
    """
    text = read_text(path)
    if not text:
        return {}
    out: dict[str, list[tuple[int, str]]] = {}
    # Capture line numbers by walking lines.
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        for pat in _NUMERIC_PATTERNS:
            for m in pat.finditer(line):
                k = m.group(1)
                v = m.group(2)
                out.setdefault(k, []).append((i, v))
    return out


# ─── Tiny markdown table parser (heading → snippet) ────────────────────────

def md_section(path: Path, heading: str) -> str:
    """Return the text under a Markdown heading until the next heading.

    Looks for `## heading` or `### heading` (case-insensitive). Returns
    empty string if not found.
    """
    text = read_text(path)
    if not text:
        return ""
    lines = text.splitlines()
    in_section = False
    out: list[str] = []
    target = heading.strip().lower()
    for line in lines:
        if line.startswith("#"):
            if in_section:
                break
            if line.lstrip("# ").strip().lower().startswith(target):
                in_section = True
                continue
        if in_section:
            out.append(line)
    return "\n".join(out)


# ─── Misc tiny helpers ──────────────────────────────────────────────────────

def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def fmt_set(items: Iterable[str]) -> str:
    return ", ".join(sorted(set(items)))
