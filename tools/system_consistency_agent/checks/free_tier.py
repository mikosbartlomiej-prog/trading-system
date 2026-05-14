"""Free-first architecture. Spec §4."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Finding
from ..utils import grep_pattern, read_text, repo_root, walk_files, rel


CATEGORY = "free_tier"
PRINCIPLE = "FREE_FIRST"

# Known paid SaaS markers — discovery is heuristic
PAID_INDICATORS = re.compile(
    r"\b(stripe\.|cloudflare-paid|datadog|sentry\.io|new-?relic|"
    r"redis(?:cloud|labs)|supabase|render-paid|aws-rds|"
    r"gcp\.run\.[a-z]+\.app|azure\.com)\b", re.I)


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    # 1. LLM_ENABLED defaults to false (spec §A.1 + free-tier rule)
    rc = root / "shared" / "runtime_config.py"
    if rc.exists():
        text = read_text(rc)
        # Default value should be False — checked by parsing the default arg
        # to llm_enabled()
        default_false = "_bool(\"LLM_ENABLED\", False)" in text
        findings.append(Finding(
            id="FREE_LLM_DEFAULT_DISABLED",
            category=CATEGORY,
            severity="PASS" if default_false else "WARN",
            status="PASS" if default_false else "WARN",
            message="LLM_ENABLED defaults to False (free-tier safe)." if default_false
                    else "LLM_ENABLED default not clearly false.",
            principle=PRINCIPLE,
            recommendation="Default LLM_ENABLED to False so paper trading works without Anthropic budget." if not default_false else "",
        ))

    # 2. docs/FREE_TIER_LIMITS.md exists
    doc = root / "docs" / "FREE_TIER_LIMITS.md"
    findings.append(Finding(
        id="FREE_TIER_DOCS_EXIST",
        category=CATEGORY,
        severity="PASS" if doc.exists() else "WARN",
        status="PASS" if doc.exists() else "WARN",
        message="docs/FREE_TIER_LIMITS.md present." if doc.exists()
                else "docs/FREE_TIER_LIMITS.md missing — operator can't see free-tier failure modes.",
        principle=PRINCIPLE,
        recommendation="Restore docs/FREE_TIER_LIMITS.md describing free-tier assumptions." if not doc.exists() else "",
    ))

    # 3. requirements.txt has no obvious paid SaaS deps
    req = root / "requirements.txt"
    if req.exists():
        text = read_text(req)
        hits = []
        for i, line in enumerate(text.splitlines(), 1):
            if PAID_INDICATORS.search(line) and not line.lstrip().startswith("#"):
                hits.append(f"line {i}: {line.strip()}")
        findings.append(Finding(
            id="FREE_NO_PAID_DEPS_IN_REQUIREMENTS",
            category=CATEGORY,
            severity="FAIL" if hits else "PASS",
            status="FAIL" if hits else "PASS",
            message=f"Found paid-service deps: {hits}" if hits
                    else "requirements.txt has no obvious paid-service deps.",
            principle=PRINCIPLE,
            recommendation="Remove paid SaaS deps." if hits else "",
            blocking=bool(hits),
        ))

    # 4. Execution path does NOT require LLM (alpaca_orders.py independent)
    ao = root / "shared" / "alpaca_orders.py"
    if ao.exists():
        text = read_text(ao)
        needs_llm = "import anthropic" in text or "openai" in text
        findings.append(Finding(
            id="FREE_EXECUTION_INDEPENDENT_OF_LLM",
            category=CATEGORY,
            severity="FAIL" if needs_llm else "PASS",
            status="FAIL" if needs_llm else "PASS",
            message="shared/alpaca_orders.py imports an LLM SDK." if needs_llm
                    else "Execution path is independent of any LLM SDK.",
            principle=PRINCIPLE,
            recommendation="Remove LLM SDK import from alpaca_orders.py." if needs_llm else "",
            blocking=needs_llm,
        ))

    # 5. Anthropic Routine budget gate present (v3.7, 2026-05-14)
    # Verifies shared/routine_budget.py exists and is wired into all
    # known routine call sites so the 15/day Anthropic limit cannot be
    # silently breached.
    budget = root / "shared" / "routine_budget.py"
    if not budget.exists():
        findings.append(Finding(
            id="FREE_ROUTINE_BUDGET_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="No shared/routine_budget.py — daily Anthropic 15-call cap not enforced.",
            recommendation="Implement routine_budget.py with priority-tiered cap.",
        ))
    else:
        b_text = read_text(budget)
        # Required surface area
        has_can_call    = "def can_call" in b_text
        has_record_call = "def record_call" in b_text
        has_tiers       = "P0_essential" in b_text and "P1_important" in b_text and "P2_optional" in b_text
        # Call sites
        llm_client = root / "learning-loop" / "llm_client.py"
        reddit_curator = root / "reddit-monitor" / "llm_curator.py"
        crypto_curator = root / "crypto-monitor" / "llm_curator.py"
        wired = []
        unwired = []
        for site in [llm_client, reddit_curator, crypto_curator]:
            if not site.exists():
                continue
            t = read_text(site)
            if "routine_budget" in t or "check_and_record" in t:
                wired.append(str(rel(site)))
            else:
                unwired.append(str(rel(site)))

        passed = has_can_call and has_record_call and has_tiers and not unwired
        findings.append(Finding(
            id="FREE_ROUTINE_BUDGET_WIRED",
            category=CATEGORY,
            severity="PASS" if passed else "WARN",
            status="PASS" if passed else "WARN",
            principle=PRINCIPLE,
            message=(
                f"routine_budget present with 3 tiers; wired in: {wired}"
                if passed else
                f"routine_budget gaps: "
                f"can_call={has_can_call}, record_call={has_record_call}, "
                f"tiers={has_tiers}, unwired sites={unwired}"
            ),
            recommendation=(
                "" if passed else
                "Wire shared.routine_budget.check_and_record() into every Routine "
                "POST site so the 15/day Anthropic cap is enforced client-side."
            ),
        ))

        # Config file present
        cfg = root / "config" / "routine_budget.json"
        findings.append(Finding(
            id="FREE_ROUTINE_BUDGET_CONFIG",
            category=CATEGORY,
            severity="PASS" if cfg.exists() else "WARN",
            status="PASS" if cfg.exists() else "WARN",
            principle=PRINCIPLE,
            message=(
                "config/routine_budget.json present (tier caps configurable)."
                if cfg.exists() else
                "config/routine_budget.json missing — caps hardcoded in module."
            ),
            recommendation=(
                "" if cfg.exists() else
                "Add config/routine_budget.json so operators can adjust tier caps without code change."
            ),
        ))

    return findings
