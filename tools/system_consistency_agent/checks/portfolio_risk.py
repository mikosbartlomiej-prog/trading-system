"""Portfolio-level risk engine present and wired. Spec §6."""

from __future__ import annotations

from pathlib import Path

from ..models import Finding
from ..utils import read_text


CATEGORY = "portfolio_risk"
PRINCIPLE = "PORTFOLIO_RISK"


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    pr = root / "shared" / "portfolio_risk.py"
    if not pr.exists():
        findings.append(Finding(
            id="PORTFOLIO_RISK_MODULE_EXISTS",
            category=CATEGORY, severity="FAIL", status="FAIL",
            message="shared/portfolio_risk.py missing.",
            principle=PRINCIPLE,
            recommendation="Restore shared/portfolio_risk.py.",
            blocking=True,
        ))
        return findings

    text = read_text(pr)
    required_symbols = ["compute_exposure", "evaluate_portfolio_risk",
                        "CORRELATED_BUCKETS"]
    missing = [s for s in required_symbols if s not in text]
    findings.append(Finding(
        id="PORTFOLIO_RISK_API_PRESENT",
        category=CATEGORY,
        severity="PASS" if not missing else "FAIL",
        status="PASS" if not missing else "FAIL",
        message="compute_exposure + evaluate_portfolio_risk + CORRELATED_BUCKETS present." if not missing
                else f"Missing: {missing}",
        principle=PRINCIPLE,
        recommendation="Restore missing symbols in shared/portfolio_risk.py." if missing else "",
        blocking=bool(missing),
    ))

    # All key bucket names
    required_buckets = ["ai_semis", "nasdaq_beta", "crypto_beta", "defense",
                        "broad_market", "energy", "leveraged_3x"]
    missing_buckets = [b for b in required_buckets if b not in text]
    findings.append(Finding(
        id="PORTFOLIO_RISK_BUCKETS_PRESENT",
        category=CATEGORY,
        severity="PASS" if not missing_buckets else "WARN",
        status="PASS" if not missing_buckets else "WARN",
        message="All required correlated buckets defined." if not missing_buckets
                else f"Missing buckets: {missing_buckets}",
        principle=PRINCIPLE,
        recommendation=f"Add missing buckets to CORRELATED_BUCKETS: {missing_buckets}" if missing_buckets else "",
    ))

    # 3 profiles spec
    rc = root / "shared" / "runtime_config.py"
    if rc.exists():
        rc_text = read_text(rc)
        profiles_ok = all(p in rc_text for p in ["SAFE_FREE", "BALANCED_PAPER", "AGGRESSIVE_PAPER"])
        findings.append(Finding(
            id="PORTFOLIO_RISK_THREE_PROFILES",
            category=CATEGORY,
            severity="PASS" if profiles_ok else "FAIL",
            status="PASS" if profiles_ok else "FAIL",
            message="Three risk profiles (SAFE_FREE / BALANCED_PAPER / AGGRESSIVE_PAPER) defined." if profiles_ok
                    else "Risk profiles missing from runtime_config.",
            principle=PRINCIPLE,
            recommendation="Restore _PROFILE_LIMITS with all three profiles." if not profiles_ok else "",
        ))

    # 4. alpaca_orders.py invokes portfolio_risk
    ao = root / "shared" / "alpaca_orders.py"
    if ao.exists():
        ao_text = read_text(ao)
        wired = "evaluate_portfolio_risk" in ao_text or "_portfolio_risk_gate" in ao_text
        findings.append(Finding(
            id="PORTFOLIO_RISK_WIRED_INTO_ORDER_PATH",
            category=CATEGORY,
            severity="PASS" if wired else "FAIL",
            status="PASS" if wired else "FAIL",
            message="alpaca_orders.py calls portfolio_risk before placing order." if wired
                    else "alpaca_orders.py does NOT call portfolio_risk.",
            principle=PRINCIPLE,
            recommendation="Wire _portfolio_risk_gate before POST /v2/orders." if not wired else "",
            blocking=not wired,
        ))

    # 5. options-monitor invokes portfolio_risk
    om = root / "options-monitor" / "monitor.py"
    if om.exists():
        om_text = read_text(om)
        wired = "evaluate_portfolio_risk" in om_text
        findings.append(Finding(
            id="PORTFOLIO_RISK_WIRED_INTO_OPTIONS",
            category=CATEGORY,
            severity="PASS" if wired else "WARN",
            status="PASS" if wired else "WARN",
            message="options-monitor calls portfolio_risk before placing order." if wired
                    else "options-monitor does NOT call portfolio_risk.",
            principle=PRINCIPLE,
            recommendation="Add evaluate_portfolio_risk call in options-monitor execute_proposal." if not wired else "",
        ))

    return findings
