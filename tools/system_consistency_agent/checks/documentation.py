"""Documentation coherence. Spec §15."""

from __future__ import annotations

from pathlib import Path

from ..models import Finding
from ..utils import read_text


CATEGORY = "documentation"
PRINCIPLE = "DOCUMENTATION_COHERENCE"

REQUIRED_DOCS = [
    "docs/AUTONOMY_CONTRACT.md",
    "docs/CODE_AUTONOMY_CONTRACT.md",
    "docs/FREE_TIER_LIMITS.md",
    "docs/RISK_PROFILE.md",
    "docs/OPERATIONS_RUNBOOK.md",
    "docs/ARCHITECTURE_VNEXT.md",
]


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    for d in REQUIRED_DOCS:
        p = root / d
        findings.append(Finding(
            id=f"DOC_EXISTS_{d.replace('/', '_').replace('.md','').upper()}",
            category=CATEGORY,
            severity="PASS" if p.exists() else "WARN",
            status="PASS" if p.exists() else "WARN",
            message=f"{d} present." if p.exists() else f"{d} missing.",
            principle=PRINCIPLE,
            recommendation=f"Restore {d}." if not p.exists() else "",
        ))

    # Coherence: AUTONOMY_CONTRACT.md mentions paper-only + no approval
    ac = root / "docs" / "AUTONOMY_CONTRACT.md"
    if ac.exists():
        text = read_text(ac)
        ok = ("paper" in text.lower()
              and ("no human approval" in text.lower() or "no operator approval" in text.lower()
                   or "no approval" in text.lower()))
        findings.append(Finding(
            id="DOC_AUTONOMY_CONTRACT_CONSISTENT",
            category=CATEGORY,
            severity="PASS" if ok else "WARN",
            status="PASS" if ok else "WARN",
            message="AUTONOMY_CONTRACT.md confirms paper-only + no-approval." if ok
                    else "AUTONOMY_CONTRACT.md missing key invariant wording.",
            principle=PRINCIPLE,
            recommendation="Reaffirm 'paper-only forever' and 'no human approval' explicitly." if not ok else "",
        ))

    # Coherence: CODE_AUTONOMY_CONTRACT.md mentions LOW/MEDIUM/HIGH_RISK
    cc = root / "docs" / "CODE_AUTONOMY_CONTRACT.md"
    if cc.exists():
        text = read_text(cc)
        ok = all(k in text for k in ("LOW_RISK", "MEDIUM_RISK", "HIGH_RISK"))
        findings.append(Finding(
            id="DOC_CODE_AUTONOMY_RISK_CATEGORIES",
            category=CATEGORY,
            severity="PASS" if ok else "WARN",
            status="PASS" if ok else "WARN",
            message="CODE_AUTONOMY_CONTRACT.md documents 3 risk categories." if ok
                    else "Risk categories not enumerated in CODE_AUTONOMY_CONTRACT.md.",
            principle=PRINCIPLE,
            recommendation="Document LOW_RISK / MEDIUM_RISK / HIGH_RISK explicitly." if not ok else "",
        ))

    # PRODUCT.md cross-check (optional — present in repo as docs/PRODUCT.md)
    product = root / "docs" / "PRODUCT.md"
    if product.exists():
        text = read_text(product)
        # Reasonable cross-check: shouldn't claim live or require approval as
        # default. We can't fully assert this without semantics; surface as
        # INFO/WARN if the words appear.
        if "live trading" in text.lower() and "paper" not in text.lower():
            findings.append(Finding(
                id="DOC_PRODUCT_NO_LIVE_CLAIM",
                category=CATEGORY,
                severity="WARN", status="WARN",
                message="PRODUCT.md mentions live trading without clarifying paper-only invariant.",
                principle=PRINCIPLE,
                recommendation="Add a note that PRODUCT.md describes a paper-only system.",
            ))

    return findings
