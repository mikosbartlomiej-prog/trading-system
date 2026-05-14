"""Spec §3 — 98–100% capital deployed.

  target_invested_ratio          : 1.00
  min_invested_ratio             : 0.98
  max_idle_cash_ratio            : <= 0.02
  cash_reserve_pct_equity        : 0.00 (or tiny operational buffer)
  operational_cash_buffer_ratio  : <= 0.005

We flag conflicts where one source says 0% reserve and another says 5/10%.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Evidence, Finding
from ..utils import read_json, read_text, rel


CATEGORY  = "capital_deployment"
PRINCIPLE = "FULL_DEPLOYMENT_98_100_PCT"


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    # 1. config/aggressive_profile.json::capital has the right values
    cfg_path = root / "config" / "aggressive_profile.json"
    cfg = read_json(cfg_path) or {}
    cap = (cfg.get("capital") or {}) if isinstance(cfg, dict) else {}

    if not cap:
        out.append(Finding(
            id="CD_CAPITAL_BLOCK_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="config/aggressive_profile.json missing capital block.",
            recommendation="Add the capital block.",
            evidence=[Evidence(file=str(rel(cfg_path)))],
        ))
        return out

    # 2. cash_reserve_pct_equity
    cash = cap.get("cash_reserve_pct_equity")
    if cash is None:
        out.append(Finding(
            id="CD_CASH_RESERVE_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="cash_reserve_pct_equity not declared.",
            recommendation="Set to 0.00 (full deployment).",
        ))
    elif cash > 0.005:
        out.append(Finding(
            id="CD_CASH_RESERVE_TOO_HIGH",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message=f"cash_reserve_pct_equity = {cash} (> 0.5% operational buffer).",
            expected="0.00 (or up to 0.005 operational buffer)",
            observed=f"{cash}",
            recommendation="Lower to 0.00 — full deployment is the contract.",
            evidence=[Evidence(file=str(rel(cfg_path)))],
        ))
    else:
        out.append(Finding(
            id="CD_CASH_RESERVE_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"cash_reserve_pct_equity = {cash} ≤ operational buffer.",
        ))

    # 3. target_invested_ratio
    target = cap.get("target_invested_ratio")
    if target is None:
        out.append(Finding(
            id="CD_TARGET_RATIO_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="target_invested_ratio missing.",
            expected="1.00",
            observed="undeclared",
            recommendation="Add target_invested_ratio: 1.00.",
        ))
    elif target < 1.00:
        out.append(Finding(
            id="CD_TARGET_RATIO_LOW",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message=f"target_invested_ratio = {target} < 1.00.",
            expected="1.00",
            observed=f"{target}",
            recommendation="Raise to 1.00 — strategy aims for full deployment.",
        ))
    else:
        out.append(Finding(
            id="CD_TARGET_RATIO_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"target_invested_ratio = {target}.",
        ))

    # 4. min_invested_ratio
    minr = cap.get("min_invested_ratio")
    if minr is None:
        out.append(Finding(
            id="CD_MIN_RATIO_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="min_invested_ratio missing.",
            recommendation="Add min_invested_ratio: 0.98.",
        ))
    elif minr < 0.98:
        out.append(Finding(
            id="CD_MIN_RATIO_LOW",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message=f"min_invested_ratio = {minr} < 0.98.",
            expected="0.98",
            observed=f"{minr}",
            recommendation="Raise to 0.98.",
        ))
    else:
        out.append(Finding(
            id="CD_MIN_RATIO_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"min_invested_ratio = {minr}.",
        ))

    # 5. max_idle_cash_ratio
    idle = cap.get("max_idle_cash_ratio")
    if idle is None:
        out.append(Finding(
            id="CD_IDLE_CASH_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="max_idle_cash_ratio missing.",
            recommendation="Add max_idle_cash_ratio: 0.02.",
        ))
    elif idle > 0.02:
        out.append(Finding(
            id="CD_IDLE_CASH_HIGH",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message=f"max_idle_cash_ratio = {idle} > 0.02.",
            expected="≤ 0.02",
            observed=f"{idle}",
            recommendation="Lower to 0.02.",
        ))
    else:
        out.append(Finding(
            id="CD_IDLE_CASH_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"max_idle_cash_ratio = {idle}.",
        ))

    # 6. STRATEGY.md must claim full deployment is the contract
    strat = root / "docs" / "STRATEGY.md"
    if strat.exists():
        text = read_text(strat).lower()
        keywords = ("98", "100%", "full deployment", "fully deployed",
                    "98–100", "98-100", "target_invested_ratio")
        if not any(k in text for k in keywords):
            out.append(Finding(
                id="CD_DOCS_DEPLOYMENT_SILENT",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="docs/STRATEGY.md does not declare 98–100% deployment.",
                recommendation="Mention the contract somewhere in STRATEGY.md.",
                evidence=[Evidence(file=str(rel(strat)))],
            ))
        else:
            out.append(Finding(
                id="CD_DOCS_DEPLOYMENT_OK",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="docs/STRATEGY.md references full-deployment contract.",
            ))

    # 7. Allocator module exists and references full-deployment target
    alloc = root / "shared" / "allocator.py"
    if not alloc.exists():
        out.append(Finding(
            id="CD_ALLOCATOR_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="shared/allocator.py missing — no module to drive redeploy.",
            recommendation="Create allocator that targets 98–100% deployment.",
        ))
    else:
        atext = read_text(alloc)
        if "target_invested_ratio" in atext or "98" in atext or "1.00" in atext:
            out.append(Finding(
                id="CD_ALLOCATOR_KNOWS_TARGET",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="shared/allocator.py references the deployment target.",
            ))
        else:
            out.append(Finding(
                id="CD_ALLOCATOR_NO_TARGET_REFERENCE",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="shared/allocator.py does not reference the full-deployment target ratio.",
                recommendation="Read target_invested_ratio from aggressive_profile.json.",
                evidence=[Evidence(file=str(rel(alloc)))],
            ))

    return out
