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

    return findings
