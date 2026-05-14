#!/usr/bin/env python3
"""
Lightweight secret scanner — free, regex-based, zero deps.

Not a replacement for trufflehog / gitleaks; this is a CI guard that
catches the most common slip-ups before a commit lands on main:

  - Alpaca keys (AK...20-char base64)
  - Anthropic keys (sk-ant-...)
  - GitHub tokens (ghp_, gho_, github_pat_)
  - AWS access keys (AKIA...)
  - Bearer tokens in shell strings
  - Gmail app passwords (16-char a-z)
  - Cloudflare API tokens
  - Generic `apikey=` / `password=` literals

Skips:
  - tests/  (uses fake fixtures)
  - .venv/, node_modules/, __pycache__/
  - This file itself + audit_workflows.py / SECURITY docs
  - Any file matching .gitignore entries

Exits 0 on clean, 1 on any finding. Designed to run from
.github/workflows/security-audit.yml on every push.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent

# Common false-positive paths
SKIP_PATTERNS = [
    ".venv/", "node_modules/", "__pycache__/", ".git/",
    "tests/", "scripts/secret_scan_light.py",
    "scripts/audit_workflows.py", "docs/",
    ".github/workflows/security-audit.yml",
    "learning-loop/event_cache.json", "learning-loop/state.json",
]


# (name, pattern, min entropy approx). Patterns are conservative — they
# match shape, not entropy. We accept some false positives over silent
# misses.

# Order matters: more specific patterns first so they win the labeling.
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("anthropic_key",     re.compile(r"sk-ant-[A-Za-z0-9_-]{40,}")),
    ("github_pat",        re.compile(r"\b(ghp_|gho_|github_pat_)[A-Za-z0-9]{30,}")),
    ("aws_access_key",    re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai_key",        re.compile(r"\bsk-[A-Za-z0-9]{30,}\b")),
    ("alpaca_key",        re.compile(r"\bAK[A-Z0-9]{18,20}\b")),
    ("bearer_in_string",  re.compile(r"Authorization\s*[:=]\s*['\"]?Bearer\s+[A-Za-z0-9_.\-]{20,}")),
    # Gmail app password: prose contains 4-letter words too, so we narrow
    # to the canonical Google UI format `xxxx xxxx xxxx xxxx` (4 groups
    # of 4, single spaces) in an assignment/quote context — OR a 16-char
    # contiguous lowercase token immediately after `=` / `:` / quote.
    ("gmail_app_pass_spaced",
     re.compile(r"['\"=]\s*[a-z]{4}\s[a-z]{4}\s[a-z]{4}\s[a-z]{4}['\"]?\s*$", re.M)),
    ("gmail_app_pass_contig",
     re.compile(r"(?:GMAIL_APP_PASSWORD|app[_-]?password)\s*[=:]\s*['\"]?[a-z]{16}['\"]?", re.I)),
    ("cloudflare_token",  re.compile(r"\bcf-[A-Za-z0-9_]{20,}\b")),
    ("generic_apikey",    re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*['\"][A-Za-z0-9_.\-]{16,}['\"]")),
]

# Inline allow-list. Lines containing these tokens are treated as known
# placeholders / docs and skipped (e.g. tests use fake keys).
ALLOW_TOKENS = {
    "FAKE_", "fake_", "<placeholder", "EXAMPLE_", "example_",
    "your_api_key", "your-api-key", "REDACTED", "REPLACE_ME",
    "AKIAEXAMPLE", "ghp_example",
}


def _should_skip(path: Path) -> bool:
    rel = str(path.relative_to(REPO_ROOT))
    for pat in SKIP_PATTERNS:
        if rel.startswith(pat) or rel == pat.rstrip("/"):
            return True
    return False


def _is_allowed(line: str) -> bool:
    for tok in ALLOW_TOKENS:
        if tok in line:
            return True
    return False


def scan_file(path: Path) -> list[dict]:
    findings: list[dict] = []
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return findings
    for i, line in enumerate(text.splitlines(), start=1):
        if _is_allowed(line):
            continue
        for name, pat in PATTERNS:
            if pat.search(line):
                findings.append({
                    "file": str(path.relative_to(REPO_ROOT)),
                    "line": i,
                    "kind": name,
                    "snippet": line.strip()[:120],
                })
                break  # one finding per line is enough
    return findings


def iter_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if _should_skip(p):
                continue
            # Skip binary-ish
            if p.suffix in (".png", ".jpg", ".gif", ".pdf", ".pyc", ".woff",
                            ".ttf", ".ico"):
                continue
            yield p


def mask(s: str) -> str:
    """Mask a string to first 4 + last 2 chars (used by logging helpers)."""
    if not s or not isinstance(s, str):
        return ""
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}***{s[-2:]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=str(REPO_ROOT),
                        help="Path to scan (default: repo root)")
    parser.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON")
    args = parser.parse_args()

    target = Path(args.path).resolve()
    if not target.exists():
        print(f"FATAL: path {target} does not exist", file=sys.stderr)
        return 2

    findings: list[dict] = []
    for path in iter_files([target]):
        findings.extend(scan_file(path))

    if args.json:
        import json
        print(json.dumps({"findings": findings, "count": len(findings)}, indent=2))
    else:
        if not findings:
            print(f"=== secret-scan OK (0 findings in {target}) ===")
        else:
            print(f"=== secret-scan FAILED ({len(findings)} findings) ===\n")
            for f in findings:
                print(f"  {f['file']}:{f['line']} [{f['kind']}] {f['snippet']}")

    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
