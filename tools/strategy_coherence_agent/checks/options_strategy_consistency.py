"""Spec §14 — options consistency.

Separates the 3 distinct percentages:
  - max_options_premium_deployed_pct       (capital exposure)
  - max_options_premium_at_risk_pct        (P&L exposure)
  - max_loss_per_option_position_pct_of_premium

Plus checks options-exit-monitor wires profit protection / regime
mismatch / NEARDTH / liquidity checks.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Evidence, Finding
from ..utils import read_json, read_text, rel


CATEGORY  = "options_strategy_consistency"
PRINCIPLE = "OPTIONS_LIMITS_AND_WIRING"


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    cfg = read_json(root / "config" / "aggressive_profile.json") or {}
    capital = cfg.get("capital") or {}
    options = cfg.get("options_intraday") or cfg.get("options") or {}
    exits = (cfg.get("exits") or {}).get("options") or {}

    cfg_path = root / "config" / "aggressive_profile.json"

    # 1. max_options_premium_deployed_pct
    deployed = capital.get("max_options_premium_pct_equity")
    if deployed is None:
        out.append(Finding(
            id="OS_DEPLOYED_PCT_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="capital.max_options_premium_pct_equity not declared.",
            recommendation="Set to 0.20-0.25 (aggressive).",
        ))
    elif deployed > 0.35:
        out.append(Finding(
            id="OS_DEPLOYED_PCT_TOO_HIGH",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"max_options_premium_pct_equity = {deployed} (>0.35).",
            recommendation="Lower to <=0.30 unless options-only strategy.",
            evidence=[Evidence(file=str(rel(cfg_path)))],
        ))
    else:
        out.append(Finding(
            id="OS_DEPLOYED_PCT_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"max_options_premium_pct_equity = {deployed}.",
        ))

    # 2. at-risk vs deployed clearly distinguished
    at_risk = options.get("max_options_premium_at_risk_pct")
    if at_risk is None:
        out.append(Finding(
            id="OS_AT_RISK_PCT_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="max_options_premium_at_risk_pct not declared.",
            expected="0.05-0.10 (much lower than deployed)",
            observed="undeclared",
            recommendation="Add max_options_premium_at_risk_pct so deployed vs "
                           "at-risk are distinguishable.",
            evidence=[Evidence(file=str(rel(cfg_path)))],
        ))
    elif deployed is not None and at_risk >= deployed:
        out.append(Finding(
            id="OS_AT_RISK_VS_DEPLOYED_INCONSISTENT",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message=f"at_risk ({at_risk}) >= deployed ({deployed}) — definitions are reversed.",
            expected="at_risk < deployed",
            observed=f"at_risk={at_risk}, deployed={deployed}",
            recommendation="Tighten at_risk: deployed is capital, at_risk is P&L exposure.",
        ))
    else:
        out.append(Finding(
            id="OS_AT_RISK_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"at-risk={at_risk}, deployed={deployed}.",
        ))

    # 3. max_loss_per_option_position_pct_of_premium
    per_pos = options.get("max_loss_per_option_position_pct_of_premium") \
              or exits.get("max_loss_pct_premium")
    if per_pos is None:
        out.append(Finding(
            id="OS_PER_POSITION_LOSS_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="No max_loss_per_option_position_pct_of_premium declared.",
            recommendation="Set to 0.35-0.40.",
        ))

    # 4. options-exit-monitor wires governor + regime + NEARDTH
    oem = root / "options-exit-monitor" / "monitor.py"
    if not oem.exists():
        out.append(Finding(
            id="OS_OPTIONS_EXIT_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="options-exit-monitor/monitor.py missing — no TP/SL polling for options.",
            recommendation="Restore options-exit-monitor.",
        ))
        return out

    oemt = read_text(oem)
    wired = {
        "profit_protection": "intraday_governor" in oemt or "PROFIT_LOCK" in oemt,
        "regime_mismatch":   "_check_regime_mismatch" in oemt or "regime_mismatch" in oemt,
        "neardth":           "NEARDTH" in oemt or "near-expiry" in oemt.lower(),
        "trailing_stop":     "trailing_stop" in oemt or "TRAIL" in oemt,
    }
    missing = [k for k, v in wired.items() if not v]
    if missing:
        out.append(Finding(
            id="OS_OPTIONS_EXIT_WIRING_INCOMPLETE",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"options-exit-monitor missing wiring: {', '.join(missing)}.",
            recommendation="Wire each missing branch into evaluate().",
            evidence=[Evidence(file=str(rel(oem)))],
        ))
    else:
        out.append(Finding(
            id="OS_OPTIONS_EXIT_WIRED_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="options-exit-monitor wires governor + regime + NEARDTH + trailing.",
        ))

    # 5. liquidity / earnings checks for options-monitor (entry side)
    om = root / "options-monitor" / "monitor.py"
    if om.exists():
        omt = read_text(om)
        if "liquidity" not in omt.lower() and "open_interest" not in omt.lower() and "spread" not in omt.lower():
            out.append(Finding(
                id="OS_OPTIONS_MONITOR_NO_LIQUIDITY_CHECK",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="options-monitor lacks liquidity/spread check.",
                recommendation="Reject contracts with bid-ask spread > X% or open_interest below threshold.",
            ))
        if "earnings" not in omt.lower():
            out.append(Finding(
                id="OS_OPTIONS_MONITOR_NO_EARNINGS_SKIP",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="options-monitor doesn't reference earnings — binary-event filter may be missing.",
                recommendation="Skip option entries ±1 day around earnings.",
            ))

    return out
