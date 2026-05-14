"""Deterministic execution gates. Spec §5."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Evidence, Finding
from ..utils import read_text, rel


CATEGORY = "deterministic_execution"
PRINCIPLE = "DETERMINISTIC_EXECUTION"


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    # 1. alpaca_orders.py calls portfolio_risk before placing the order
    ao = root / "shared" / "alpaca_orders.py"
    if ao.exists():
        text = read_text(ao)
        has_gate = ("_portfolio_risk_gate" in text
                    and "evaluate_portfolio_risk" in text)
        findings.append(Finding(
            id="DET_EXEC_ALPACA_HAS_PORTFOLIO_GATE",
            category=CATEGORY,
            severity="PASS" if has_gate else "FAIL",
            status="PASS" if has_gate else "FAIL",
            message="shared/alpaca_orders.py invokes portfolio_risk gate." if has_gate
                    else "shared/alpaca_orders.py does NOT invoke portfolio_risk gate.",
            principle=PRINCIPLE,
            recommendation="Wire evaluate_portfolio_risk() before order POST." if not has_gate else "",
            blocking=not has_gate,
        ))
        # 2. risk_officer gate present
        has_officer = "evaluate_trade" in text or "risk_officer" in text
        findings.append(Finding(
            id="DET_EXEC_ALPACA_HAS_RISK_OFFICER",
            category=CATEGORY,
            severity="PASS" if has_officer else "FAIL",
            status="PASS" if has_officer else "FAIL",
            message="shared/alpaca_orders.py invokes risk_officer." if has_officer
                    else "shared/alpaca_orders.py does NOT invoke risk_officer.",
            principle=PRINCIPLE,
            recommendation="Call risk_officer.evaluate_trade() before order POST." if not has_officer else "",
            blocking=not has_officer,
        ))

    # 3. shared/signal_confirmation.py exists
    sc = root / "shared" / "signal_confirmation.py"
    findings.append(Finding(
        id="DET_EXEC_SIGNAL_CONFIRMATION_EXISTS",
        category=CATEGORY,
        severity="PASS" if sc.exists() else "FAIL",
        status="PASS" if sc.exists() else "FAIL",
        message="shared/signal_confirmation.py present." if sc.exists()
                else "shared/signal_confirmation.py missing.",
        principle=PRINCIPLE,
        recommendation="Restore shared/signal_confirmation.py." if not sc.exists() else "",
    ))

    # 4. LLM client honours LLM_ENABLED toggle
    llm = root / "learning-loop" / "llm_client.py"
    if llm.exists():
        text = read_text(llm)
        honours_flag = "LLM_ENABLED" in text or "_llm_is_enabled" in text or "USE_LLM" in text
        findings.append(Finding(
            id="DET_EXEC_LLM_HAS_KILL_SWITCH",
            category=CATEGORY,
            severity="PASS" if honours_flag else "FAIL",
            status="PASS" if honours_flag else "FAIL",
            message="learning-loop/llm_client.py honours LLM kill switch." if honours_flag
                    else "learning-loop/llm_client.py does NOT honour LLM kill switch.",
            principle=PRINCIPLE,
            recommendation="Check LLM_ENABLED / USE_LLM before contacting the routine." if not honours_flag else "",
        ))

    # 5. Analyzer wires safe_apply_overrides + validation.py
    az = root / "learning-loop" / "analyzer.py"
    if az.exists():
        text = read_text(az)
        wired = "safe_apply_overrides" in text and "validate_adaptation" in text
        findings.append(Finding(
            id="DET_EXEC_LLM_OVERRIDES_VALIDATED",
            category=CATEGORY,
            severity="PASS" if wired else "FAIL",
            status="PASS" if wired else "FAIL",
            message="analyzer.py runs validate_adaptation after safe_apply_overrides." if wired
                    else "analyzer.py does NOT run validate_adaptation after LLM overrides.",
            principle=PRINCIPLE,
            recommendation="Chain validate_adaptation after safe_apply_overrides in analyzer." if not wired else "",
            blocking=not wired,
        ))

    return findings
