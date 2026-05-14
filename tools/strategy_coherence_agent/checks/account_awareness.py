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

    # 7. PDT-aware sizing — v3.8 intent-aware Pattern-Day-Trader protection.
    # Verifies shared/pdt_guard.py implements the v3.8 decision matrix
    # (OPEN never blocked by PDT count; CLOSE budget-aware with crypto
    # exemption + overnight-position bypass) and is wired into all order
    # paths with explicit intent.
    pdt_path = root / "shared" / "pdt_guard.py"
    if not pdt_path.exists():
        out.append(Finding(
            id="AA_PDT_GUARD_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="No shared/pdt_guard.py — sub-$25k account has no proactive "
                    "Pattern-Day-Trader protection.",
            recommendation="Implement pdt_guard.py with daytrade_count classification "
                           "and wire into alpaca_orders / allocator / exit-monitor.",
        ))
    else:
        pdt_text = read_text(pdt_path)
        # 4 mode names — deterministic classification
        modes_present = all(m in pdt_text for m in ("OK", "CAUTION", "RESTRICTED", "LOCKED"))
        # Public API — single gate
        api_present = "def evaluate_order" in pdt_text
        # v3.8 features
        intent_aware = "INTENT_SWING" in pdt_text and "INTENT_INTRADAY" in pdt_text and "INTENT_EMERGENCY" in pdt_text
        crypto_exempt = "_is_crypto" in pdt_text and "crypto exempt" in pdt_text
        # OPEN never blocked by PDT count (the v3.8 key fix)
        open_not_blocked = '"OPEN allowed"' in pdt_text or "OPEN allowed in" in pdt_text
        # Wiring into all 5 order paths
        alpaca_text     = read_text(root / "shared" / "alpaca_orders.py")
        wired_alpaca    = "pdt_guard" in alpaca_text or "_pdt_gate" in alpaca_text
        wired_allocator = "pdt_guard" in text or "_pdt_eval" in text
        em_path         = root / "exit-monitor" / "monitor.py"
        wired_exit      = em_path.exists() and "pdt_guard" in read_text(em_path)
        oem_path        = root / "options-exit-monitor" / "monitor.py"
        wired_options_exit = oem_path.exists() and "pdt_guard" in read_text(oem_path)
        # Callers pass intent
        intent_in_alpaca = "intent=" in alpaca_text or "intent =" in alpaca_text
        intent_in_exit   = em_path.exists() and ("intent=" in read_text(em_path) or "close_intent" in read_text(em_path))
        intent_in_oem    = oem_path.exists() and ("intent=" in read_text(oem_path) or "close_intent" in read_text(oem_path))

        all_ok = (modes_present and api_present and intent_aware and crypto_exempt
                  and open_not_blocked and wired_alpaca and wired_allocator
                  and wired_exit and wired_options_exit
                  and intent_in_alpaca and intent_in_exit and intent_in_oem)

        if all_ok:
            out.append(Finding(
                id="AA_PDT_GUARD_OK",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="pdt_guard v3.8: 4 modes + intent enum + crypto exempt + "
                        "OPEN never blocks on PDT count + wired into 5 order paths "
                        "(alpaca_orders, allocator, exit-monitor, options-exit-monitor) "
                        "with explicit intent at every call site.",
            ))
        else:
            details = []
            if not modes_present:        details.append("missing modes")
            if not api_present:          details.append("no evaluate_order()")
            if not intent_aware:         details.append("missing INTENT_* enum (v3.8 design)")
            if not crypto_exempt:        details.append("crypto not exempt")
            if not open_not_blocked:     details.append("OPEN still blocked by PDT count (v3.7 anti-pattern)")
            if not wired_alpaca:         details.append("not wired in alpaca_orders")
            if not wired_allocator:      details.append("not wired in allocator")
            if not wired_exit:           details.append("not wired in exit-monitor")
            if not wired_options_exit:   details.append("not wired in options-exit-monitor")
            if not intent_in_alpaca:     details.append("alpaca_orders missing intent= argument")
            if not intent_in_exit:       details.append("exit-monitor missing intent=/close_intent")
            if not intent_in_oem:        details.append("options-exit-monitor missing intent=/close_intent")
            out.append(Finding(
                id="AA_PDT_GUARD_INCOMPLETE",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message=f"pdt_guard.py present but: {', '.join(details)}.",
                recommendation="Complete pdt_guard v3.8 wiring; all 5 order paths must "
                               "pass intent= and the engine must NOT block OPEN actions "
                               "on PDT count alone.",
                evidence=[Evidence(file=str(rel(pdt_path)))],
            ))

    return out
