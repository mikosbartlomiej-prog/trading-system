"""Paper-trading invariant. Spec §1."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Evidence, Finding
from ..utils import grep_pattern, rel, repo_root, walk_files, read_text


CATEGORY = "paper_only"
PRINCIPLE = "PAPER_TRADING_ONLY"

LIVE_ENDPOINT = re.compile(r"https?://api\.alpaca\.markets(?!/paper)", re.I)
LIVE_TRADING_FLAG = re.compile(r"(LIVE_TRADING|LIVE_ENABLED)\s*=\s*['\"]?true", re.I)
PAPER_ENDPOINT = re.compile(r"https?://paper-api\.alpaca\.markets", re.I)

# Files that are intentionally allowed to mention live URL strings as
# discussion (docs explaining why we forbid them, agent code that scans
# for them, etc.).
EXEMPT_PATHS = (
    "docs/",
    "tests/",
    "tools/system_consistency_agent/",
    "scripts/audit_workflows.py",
    "scripts/secret_scan_light.py",
    "learning-loop/patch_validator.py",
    ".github/workflows/security-audit.yml",
    "CLAUDE.md",
    "shared/autonomy.py",
    # v3.29 — LLM strategy alignment + canary unlock evaluator both
    # carry live-trading literals as SAFETY BLACKLISTS (they detect
    # such patterns in LLM output / runtime env and refuse to
    # advance). They never assign or enable live trading.
    "shared/llm_strategy_alignment.py",
    "shared/broker_paper_canary_unlock.py",
    "scripts/evaluate_broker_paper_canary_unlock.py",
    "scripts/smoke_test_gemini_provider.py",
)


def _is_exempt(path: Path) -> bool:
    rp = str(rel(path))
    return any(rp.startswith(p) or rp == p.rstrip("/") for p in EXEMPT_PATHS)


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    # 1. No live endpoint URL in non-exempt files
    code_paths = [p for p in walk_files(root, include_globs=("*.py", "*.yml"))
                  if not _is_exempt(p)]
    live_hits = grep_pattern(LIVE_ENDPOINT, code_paths)
    findings.append(Finding(
        id="PAPER_ONLY_NO_LIVE_ENDPOINT",
        category=CATEGORY,
        severity="FAIL" if live_hits else "PASS",
        status="FAIL" if live_hits else "PASS",
        message=("Found live Alpaca endpoint references outside docs/tests."
                 if live_hits
                 else "No live Alpaca endpoint references in code paths."),
        principle=PRINCIPLE,
        evidence=live_hits[:10],
        recommendation=("Replace api.alpaca.markets with paper-api.alpaca.markets, "
                        "or move the reference to docs/ if explaining what is forbidden.")
                       if live_hits else "",
        blocking=bool(live_hits),
    ))

    # 2. No LIVE_TRADING / LIVE_ENABLED flag set true
    flag_hits = grep_pattern(LIVE_TRADING_FLAG, code_paths)
    findings.append(Finding(
        id="PAPER_ONLY_NO_LIVE_FLAG",
        category=CATEGORY,
        severity="FAIL" if flag_hits else "PASS",
        status="FAIL" if flag_hits else "PASS",
        message=("Found LIVE_TRADING/LIVE_ENABLED flag set true."
                 if flag_hits
                 else "No live-enable flag found."),
        principle=PRINCIPLE,
        evidence=flag_hits[:10],
        recommendation="Remove the flag — system is paper-only forever." if flag_hits else "",
        blocking=bool(flag_hits),
    ))

    # 3. shared/autonomy.py exposes assert_paper_only
    autonomy_py = root / "shared" / "autonomy.py"
    if autonomy_py.exists():
        text = read_text(autonomy_py)
        has_guard = "assert_paper_only" in text and "PaperOnlyViolation" in text
        findings.append(Finding(
            id="PAPER_ONLY_GUARD_EXISTS",
            category=CATEGORY,
            severity="PASS" if has_guard else "FAIL",
            status="PASS" if has_guard else "FAIL",
            message=("shared/autonomy.py exports assert_paper_only + PaperOnlyViolation."
                     if has_guard
                     else "shared/autonomy.py missing paper-only guard."),
            principle=PRINCIPLE,
            recommendation="Re-add assert_paper_only / PaperOnlyViolation." if not has_guard else "",
            blocking=not has_guard,
        ))
    else:
        findings.append(Finding(
            id="PAPER_ONLY_GUARD_EXISTS",
            category=CATEGORY,
            severity="FAIL",
            status="FAIL",
            message="shared/autonomy.py is missing.",
            principle=PRINCIPLE,
            recommendation="Restore shared/autonomy.py from git history.",
            blocking=True,
        ))

    # 4. emergency_engine + remediation call assert_paper_only
    for mod_rel in ("shared/emergency_engine.py", "shared/remediation.py"):
        p = root / mod_rel
        if not p.exists():
            continue
        text = read_text(p)
        uses_guard = "assert_paper_only" in text
        findings.append(Finding(
            id=f"PAPER_ONLY_GUARD_USED_{mod_rel.replace('/', '_').upper()}",
            category=CATEGORY,
            severity="PASS" if uses_guard else "FAIL",
            status="PASS" if uses_guard else "FAIL",
            message=f"{mod_rel} {'invokes' if uses_guard else 'does NOT invoke'} assert_paper_only.",
            principle=PRINCIPLE,
            recommendation=f"Add assert_paper_only(ALPACA_BASE_URL) before HTTP calls in {mod_rel}.",
            blocking=not uses_guard,
        ))

    # 5. ALPACA_BASE_URL constants point at paper
    base_url_hits = []
    for p in walk_files(root, include_globs=("*.py",)):
        if _is_exempt(p):
            continue
        text = read_text(p)
        if "ALPACA_BASE_URL" not in text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if "ALPACA_BASE_URL" in line and "=" in line and "alpaca.markets" in line:
                if "paper-api.alpaca.markets" not in line and "PAPER_BASE_URL" not in line:
                    base_url_hits.append(Evidence(file=str(rel(p)), line=i,
                                                    snippet=line.strip()[:160]))
    findings.append(Finding(
        id="PAPER_ONLY_BASE_URL_IS_PAPER",
        category=CATEGORY,
        severity="FAIL" if base_url_hits else "PASS",
        status="FAIL" if base_url_hits else "PASS",
        message=("ALPACA_BASE_URL assigned to a non-paper URL." if base_url_hits
                 else "All ALPACA_BASE_URL assignments point at paper."),
        principle=PRINCIPLE,
        evidence=base_url_hits[:10],
        recommendation="Set ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'." if base_url_hits else "",
        blocking=bool(base_url_hits),
    ))

    return findings
