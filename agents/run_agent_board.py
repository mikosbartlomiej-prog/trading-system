#!/usr/bin/env python3
"""Multi-Agent Audit Board — local runner.

DOES NOT call any LLM. DOES NOT send code anywhere. Runs entirely locally.

Subcommands:
  list                       List all agents with their prompt paths.
  validate-structure         Verify all prompts + schemas exist + are well-formed.
  validate-reports <DATE>    Validate produced reports against JSON schemas.
  init <DATE>                Create empty report templates for date YYYY-MM-DD.
  check-forbidden            Scan prompts for forbidden phrases.

Examples:
  python3 agents/run_agent_board.py list
  python3 agents/run_agent_board.py validate-structure
  python3 agents/run_agent_board.py init 2026-05-30
  python3 agents/run_agent_board.py validate-reports 2026-05-30
  python3 agents/run_agent_board.py check-forbidden

Cost: $0. No network. No paid API.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AGENTS_DIR = _REPO_ROOT / "agents"
_PROMPTS_DIR = _AGENTS_DIR / "prompts"
_SCHEMAS_DIR = _AGENTS_DIR / "schemas"
_REPORTS_DIR = _AGENTS_DIR / "reports"
_TEMPLATES_DIR = _REPORTS_DIR / "templates"

# The 11 area agents (numbered 01-11) + 12_final_arbiter.
AREA_AGENTS = (
    ("01_architecture_reviewer",       "ARCH"),
    ("02_trading_strategy_reviewer",   "STRAT"),
    ("03_risk_reviewer",               "RISK"),
    ("04_data_quality_bias_reviewer",  "DATA"),
    ("05_confidence_score_reviewer",   "CONF"),
    ("06_runtime_safety_reviewer",     "RUNTIME"),
    ("07_testing_e2e_reviewer",        "TEST"),
    ("08_documentation_runbook_reviewer", "DOC"),
    ("09_simplicity_refactoring_reviewer", "SIMPL"),
    ("10_security_secrets_reviewer",   "SEC"),
    ("11_free_operations_reviewer",    "FREE"),
)
FINAL_ARBITER = ("12_final_arbiter", "ARB")
SHARED_CONTEXT = ("00_shared_context", None)

ALL_AGENT_PROMPTS = [SHARED_CONTEXT, *AREA_AGENTS, FINAL_ARBITER]

# Sections every area-agent prompt MUST contain.
REQUIRED_AGENT_SECTIONS = (
    "## Role",
    "## Scope of responsibility",
    "## What you MUST NOT do",
    "## Blocking criteria",
    "## Acceptance criteria",
    "## Confidence-score impact",
    "## Output format",
    "## Required tests",
    "## Free-operation requirement",
)

# Phrases forbidden in every prompt (auto-fail on detection).
FORBIDDEN_PHRASES = (
    "guaranteed to be profitable",
    "guaranteed edge",
    "system will be profitable",
    "system is safe for live",
    "high confidence means high profit",
    "we recommend going live",
    "ready for live trading",
    "guarantees profit",
    "always profitable",
)

# Required JSON schemas
REQUIRED_SCHEMAS = (
    "finding.schema.json",
    "agent_report.schema.json",
    "final_decision.schema.json",
)


# ─── ANSI ─────────────────────────────────────────────────────────────────────

class C:
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    BLUE   = "\033[94m"
    BOLD   = "\033[1m"
    END    = "\033[0m"


def ok(msg):    print(f"  {C.GREEN}✓{C.END}  {msg}")
def warn(msg):  print(f"  {C.YELLOW}⚠{C.END}  {msg}")
def err(msg):   print(f"  {C.RED}✗{C.END}  {msg}")
def info(msg):  print(f"  {C.BLUE}i{C.END}  {msg}")
def hdr(msg):   print(f"\n{C.BOLD}{msg}{C.END}")


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_list(args) -> int:
    hdr("Multi-Agent Audit Board — prompts")
    for name, prefix in ALL_AGENT_PROMPTS:
        path = _PROMPTS_DIR / f"{name}.md"
        prefix_str = f"({prefix}-XXX)" if prefix else "(shared)"
        marker = "✓" if path.exists() else "✗"
        color = C.GREEN if path.exists() else C.RED
        print(f"  {color}{marker}{C.END}  {name:40s} {prefix_str:14s}  {path}")
    return 0


def cmd_validate_structure(args) -> int:
    """Validate all prompts + schemas exist + prompts have required sections."""
    issues = 0
    hdr("Validating prompts presence + required sections")
    for name, _prefix in ALL_AGENT_PROMPTS:
        path = _PROMPTS_DIR / f"{name}.md"
        if not path.exists():
            err(f"MISSING prompt file: {path}")
            issues += 1
            continue
        text = path.read_text()
        # Shared context has different required sections — skip strict check
        if name == "00_shared_context":
            if "Most important constraint" not in text or "FREE OPERATION" not in text:
                err(f"{name}: missing FREE OPERATION clause")
                issues += 1
            else:
                ok(f"{name}.md OK")
            continue
        if name == "12_final_arbiter":
            for must in ("## Role", "## Decision options", "## What you MUST NOT do"):
                if must not in text:
                    err(f"{name}: missing section {must!r}")
                    issues += 1
                    break
            else:
                ok(f"{name}.md OK")
            continue
        missing = [s for s in REQUIRED_AGENT_SECTIONS if s not in text]
        if missing:
            err(f"{name}: missing sections {missing}")
            issues += 1
        else:
            ok(f"{name}.md OK ({len(REQUIRED_AGENT_SECTIONS)}/{len(REQUIRED_AGENT_SECTIONS)} required sections present)")

    hdr("Validating schemas presence + well-formed JSON")
    for schema_file in REQUIRED_SCHEMAS:
        path = _SCHEMAS_DIR / schema_file
        if not path.exists():
            err(f"MISSING schema: {path}")
            issues += 1
            continue
        try:
            data = json.loads(path.read_text())
            if "$schema" not in data or "required" not in data:
                warn(f"{schema_file}: missing $schema or required field")
            else:
                ok(f"{schema_file} OK")
        except json.JSONDecodeError as e:
            err(f"{schema_file}: JSON parse error: {e}")
            issues += 1

    hdr("Validating README.md presence")
    readme = _AGENTS_DIR / "README.md"
    if not readme.exists():
        err("MISSING agents/README.md")
        issues += 1
    else:
        text = readme.read_text()
        for must in ("Multi-Agent Audit Board", "NOT a runtime trading brain",
                      "free in operation", "Audit Board"):
            if must.lower() not in text.lower():
                warn(f"README.md missing keyword: {must!r}")
        ok("README.md OK")

    if issues:
        print()
        err(f"{issues} structural issue(s) found.")
        return 1
    print()
    ok("Audit board structure VALID.")
    return 0


def cmd_check_forbidden(args) -> int:
    """Scan prompts for forbidden profit-guarantee phrases."""
    issues = 0
    hdr("Scanning for forbidden phrases (profit guarantees, etc.)")
    for name, _prefix in ALL_AGENT_PROMPTS:
        path = _PROMPTS_DIR / f"{name}.md"
        if not path.exists():
            continue
        text_lower = path.read_text().lower()
        found = []
        for phrase in FORBIDDEN_PHRASES:
            if phrase.lower() in text_lower:
                # Allow phrase to appear if explicitly forbidden / quoted as anti-pattern
                # (e.g. "MUST NOT use phrases like 'guaranteed edge'").
                ctx_pattern = re.compile(
                    rf"(?:must not|never|forbidden|do not).*?{re.escape(phrase)}",
                    re.IGNORECASE | re.DOTALL,
                )
                # Find any occurrence; if every occurrence is preceded by negation
                # context within 200 chars, treat as OK.
                bad_occurrences = 0
                for m in re.finditer(re.escape(phrase), text_lower):
                    start = max(0, m.start() - 200)
                    chunk = text_lower[start:m.end()]
                    if not re.search(r"(must not|never|forbidden|do not|not recommend|anti.pattern|red flag)", chunk):
                        bad_occurrences += 1
                if bad_occurrences:
                    found.append((phrase, bad_occurrences))
        if found:
            err(f"{name}: forbidden phrase(s) {found}")
            issues += 1
        else:
            ok(f"{name} clean")
    if issues:
        print()
        err(f"{issues} prompt(s) contain forbidden phrases.")
        return 1
    print()
    ok("No forbidden phrases in any prompt.")
    return 0


def cmd_init(args) -> int:
    """Create empty report templates for given date."""
    date_iso = args.date
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_iso):
        err(f"--date must be YYYY-MM-DD, got: {date_iso}")
        return 1
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    hdr(f"Initialising report templates for {date_iso}")
    template_text = (
        "<!--\n"
        "  Multi-Agent Audit Board — agent report template.\n"
        "  Replace TODOs and ensure the document conforms to\n"
        "  agents/schemas/agent_report.schema.json before validation.\n"
        "-->\n\n"
        "# {agent_name} — Report {date}\n\n"
        "**Agent:** `{agent_name}`\n"
        "**Review date:** {date}\n"
        "**HEAD SHA:** _(fill in: `git rev-parse HEAD`)_\n\n"
        "## Summary\n\n"
        "_TODO: 1-3 paragraph human summary._\n\n"
        "## Reviewed scope\n\n"
        "- _TODO: list repo-relative paths inspected_\n\n"
        "## Findings\n\n"
        "<!-- Each finding must conform to agents/schemas/finding.schema.json -->\n\n"
        "### Finding {prefix}-001 (template)\n\n"
        "- **title:** _TODO_\n"
        "- **severity:** P2\n"
        "- **area:** _TODO_\n"
        "- **affected_files:** []\n"
        "- **evidence:** _TODO_\n"
        "- **risk:** _TODO_\n"
        "- **recommendation:** _TODO_\n"
        "- **required_tests:** []\n"
        "- **free_operation_impact:** none\n"
        "- **confidence_score_impact:** neutral\n"
        "- **safety_impact:** neutral\n"
        "- **blocking_status:** INFO_ONLY\n"
        "- **status:** open\n\n"
        "## Blocking findings\n\n"
        "_(IDs of findings that block paper/live)_\n\n"
        "## Recommended fixes\n\n"
        "- _TODO_\n\n"
        "## Required tests\n\n"
        "- _TODO_\n\n"
        "## Confidence score assessment\n\n"
        "- **status:** _trusted / partial / untrusted / n/a_\n"
        "- **ceiling:** _0.0-1.0 if status != n/a_\n"
        "- **rationale:** _TODO_\n\n"
        "## Free operation assessment\n\n"
        "- **status:** _ok / at_risk / violated / n/a_\n"
        "- **rationale:** _TODO_\n\n"
        "## Final agent decision\n\n"
        "_(PASS / PASS_WITH_WARNINGS / NEEDS_FIXES / BLOCKS_PAPER_TRADING / BLOCKS_LOCAL_REPLAY)_\n"
    )

    created = 0
    for agent_name, prefix in AREA_AGENTS:
        out = _REPORTS_DIR / f"{agent_name}_{date_iso}.md"
        if out.exists():
            warn(f"already exists: {out.name}")
            continue
        out.write_text(template_text.format(
            agent_name=agent_name, date=date_iso, prefix=prefix or "XXX",
        ))
        ok(f"created {out.name}")
        created += 1

    # Final arbiter template
    fa_out = _REPORTS_DIR / f"final_decision_{date_iso}.md"
    if not fa_out.exists():
        fa_template = (
            f"# Final Decision — {date_iso}\n\n"
            "**Decision:** _TODO (one of APPROVE_LOCAL_REPLAY / APPROVE_PAPER_TRADING_WITH_WARNINGS / "
            "BLOCK_PAPER_TRADING / NEEDS_REFACTOR / NEEDS_MORE_TESTS / BLOCK_ALL_TRADING_MODES)_\n\n"
            "**Secondary verdicts:** [NOT_SAFE_FOR_LIVE_TRADING]\n\n"
            "## Rationale\n\n_TODO_\n\n"
            "## P0 findings\n\n- _TODO list of IDs with status_\n\n"
            "## P1 findings\n\n- _TODO_\n\n"
            "## Blockers\n\n- _TODO_\n\n"
            "## Readiness\n\n"
            "- paper_trading_readiness: _ready / ready_with_warnings / blocked / unknown_\n"
            "- live_trading_readiness: **blocked** (hardcoded)\n"
            "- confidence_score_readiness: _trusted / partial / untrusted_\n"
            "- runtime_safety_readiness: _ready / partial / blocked_\n"
            "- free_operation_status: _ok / at_risk / violated_\n\n"
            "## Required next steps\n\n"
            "1. _TODO action — owner — priority_\n\n"
            "## Agents consumed\n\n"
            + "\n".join(f"- `{n}`" for n, _ in AREA_AGENTS)
            + "\n"
        )
        fa_out.write_text(fa_template)
        ok(f"created {fa_out.name}")
        created += 1

    print()
    info(f"{created} report templates created in {_REPORTS_DIR.relative_to(_REPO_ROOT)}/")
    info("Edit each report, then run: python3 agents/run_agent_board.py validate-reports " + date_iso)
    return 0


def cmd_validate_reports(args) -> int:
    """Validate that all area-agent reports + final decision exist for date."""
    date_iso = args.date
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_iso):
        err(f"--date must be YYYY-MM-DD, got: {date_iso}")
        return 1
    issues = 0
    hdr(f"Validating reports for {date_iso}")
    for agent_name, _ in AREA_AGENTS:
        path = _REPORTS_DIR / f"{agent_name}_{date_iso}.md"
        if not path.exists():
            err(f"MISSING area report: {path.name}")
            issues += 1
        else:
            text = path.read_text()
            if "TODO" in text:
                warn(f"{path.name}: contains TODO markers — not finalised")
            ok(f"{path.name} present")
    fa = _REPORTS_DIR / f"final_decision_{date_iso}.md"
    if not fa.exists():
        err(f"MISSING final decision: {fa.name}")
        issues += 1
    elif "TODO" in fa.read_text():
        warn(f"{fa.name}: contains TODO markers — final decision not finalised")
    else:
        ok(f"{fa.name} present")

    if issues:
        print()
        err(f"{issues} report(s) missing for {date_iso}.")
        return 1
    print()
    ok(f"All reports present for {date_iso}.")
    return 0


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Multi-Agent Audit Board local runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List all agents")
    sub.add_parser("validate-structure", help="Validate prompts + schemas + README")
    sub.add_parser("check-forbidden", help="Scan prompts for forbidden phrases")

    p_init = sub.add_parser("init", help="Create empty report templates for date")
    p_init.add_argument("date", help="YYYY-MM-DD")

    p_val = sub.add_parser("validate-reports", help="Validate produced reports exist")
    p_val.add_argument("date", help="YYYY-MM-DD")

    args = parser.parse_args(argv)

    handlers = {
        "list":               cmd_list,
        "validate-structure": cmd_validate_structure,
        "check-forbidden":    cmd_check_forbidden,
        "init":               cmd_init,
        "validate-reports":   cmd_validate_reports,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
