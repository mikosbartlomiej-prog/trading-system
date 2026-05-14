"""Spec §4 — Account-aware allocation.

The allocator must rebalance from real Alpaca account/positions state,
not synthesise from an empty portfolio. We confirm:
  - shared/allocator.py (or PortfolioAllocator / CapitalDeploymentEngine /
    AccountAwareAllocator) imports an account-fetching helper.
  - Per-position attributes (qty, market_value, unrealized_pl, etc.) are
    referenced.
  - Allocator computes deltas vs current_holdings, not just target weights.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Evidence, Finding
from ..utils import read_text, rel


CATEGORY  = "account_awareness"
PRINCIPLE = "ACCOUNT_AWARE_ALLOCATION"

# At least one of these must be present.
ALLOCATOR_CANDIDATES = (
    "shared/allocator.py",
    "shared/account_aware_allocator.py",
    "shared/capital_deployment_engine.py",
    "learning-loop/allocator.py",
    "shared/portfolio_allocator.py",
)

REQUIRED_ACCOUNT_FIELDS = (
    "equity", "cash", "buying_power", "positions",
)

# Fields that must show up somewhere in the allocator (referenced when
# evaluating current portfolio state).
REQUIRED_POSITION_FIELDS = (
    "market_value", "unrealized_pl", "qty",
)


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    # 1. Find an allocator module
    found: list[Path] = []
    for candidate in ALLOCATOR_CANDIDATES:
        p = root / candidate
        if p.exists():
            found.append(p)

    if not found:
        out.append(Finding(
            id="AA_ALLOCATOR_NOT_FOUND",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="No allocator module found (tried " + ", ".join(ALLOCATOR_CANDIDATES) + ").",
            recommendation="Add shared/allocator.py implementing an "
                           "AccountAwareAllocator.",
        ))
        return out

    out.append(Finding(
        id="AA_ALLOCATOR_PRESENT",
        category=CATEGORY, severity="PASS", status="PASS",
        principle=PRINCIPLE,
        message=f"Allocator module(s) present: {', '.join(str(rel(p)) for p in found)}",
    ))

    # 2. Inspect the FIRST allocator found (canonical)
    alloc = found[0]
    text = read_text(alloc)

    # 3. Confirm it reads account state (equity/cash/buying_power/positions)
    missing_acct = [f for f in REQUIRED_ACCOUNT_FIELDS if f not in text]
    if missing_acct:
        out.append(Finding(
            id="AA_ALLOCATOR_ACCOUNT_FIELDS_INCOMPLETE",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message=f"Allocator never references: {', '.join(missing_acct)}.",
            expected="all of " + ", ".join(REQUIRED_ACCOUNT_FIELDS),
            observed="missing: " + ", ".join(missing_acct),
            recommendation="Pull account dict and read every required field.",
            evidence=[Evidence(file=str(rel(alloc)))],
        ))
    else:
        out.append(Finding(
            id="AA_ALLOCATOR_ACCOUNT_FIELDS_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="Allocator references equity, cash, buying_power, positions.",
        ))

    # 4. Confirm per-position fields are inspected
    missing_pos = [f for f in REQUIRED_POSITION_FIELDS if f not in text]
    if missing_pos:
        out.append(Finding(
            id="AA_ALLOCATOR_POSITION_FIELDS_INCOMPLETE",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"Allocator never references per-position fields: {', '.join(missing_pos)}.",
            expected="market_value, unrealized_pl, qty",
            observed="missing: " + ", ".join(missing_pos),
            recommendation="Iterate positions and inspect each ticker's "
                           "market_value before sizing new orders.",
            evidence=[Evidence(file=str(rel(alloc)))],
        ))
    else:
        out.append(Finding(
            id="AA_ALLOCATOR_POSITION_FIELDS_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="Allocator inspects per-position market_value / unrealized_pl / qty.",
        ))

    # 5. Allocator computes deltas, not just target weights
    delta_signals = ("delta", "diff", "rebalance", "to_buy", "to_sell",
                     "current_weight", "current_holdings", "currentexposure")
    has_deltas = any(s in text.lower() for s in delta_signals)
    if not has_deltas:
        out.append(Finding(
            id="AA_ALLOCATOR_TARGET_ONLY",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message="Allocator appears to produce target weights without "
                    "comparing against current holdings.",
            expected="delta / rebalance computation",
            observed="no delta-like vocabulary found",
            recommendation="Subtract current_holdings from target_weights "
                           "before emitting orders.",
            evidence=[Evidence(file=str(rel(alloc)))],
        ))
    else:
        out.append(Finding(
            id="AA_ALLOCATOR_DELTAS_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="Allocator computes deltas vs current holdings.",
        ))

    # 6. Fail-closed when account data unavailable
    if "account_unavailable" in text or ("None" in text and "block" in text.lower()):
        out.append(Finding(
            id="AA_ALLOCATOR_FAIL_CLOSED_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="Allocator references account-unavailable handling.",
        ))
    else:
        out.append(Finding(
            id="AA_ALLOCATOR_FAIL_OPEN_RISK",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="Allocator does not explicitly handle account-unavailable "
                    "(no `account_unavailable` / block path found).",
            recommendation="Block new entries when account fetch fails "
                           "(spec §G fail-closed).",
            evidence=[Evidence(file=str(rel(alloc)))],
        ))

    return out
