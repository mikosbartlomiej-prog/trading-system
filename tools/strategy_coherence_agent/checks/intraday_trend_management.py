"""Spec §12 — Intraday trend reinterpretation.

This is a P2 capability (VWAP/ORH-based intraday signals), so most
findings here are WARN-level unless the module is claimed but missing.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Evidence, Finding
from ..utils import read_text, rel


CATEGORY  = "intraday_trend_management"
PRINCIPLE = "INTRADAY_TREND_REINTERPRETATION"

TREND_FN_HINTS = (
    "intraday_trend_state", "intraday_trend", "trend_state",
    "vwap_state", "compute_intraday_trend",
)

TREND_STATE_NAMES = (
    "TREND_CONTINUES", "MOMENTUM_WEAKENING", "FAILED_BREAKOUT",
    "REVERSAL_CONFIRMED", "CHOP_NO_EDGE",
)

INPUT_SIGNALS = ("vwap", "opening_range", "5min", "5_min", "15min", "15_min",
                 "relative_strength")


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    candidates = (
        root / "shared" / "intraday_trend.py",
        root / "shared" / "trend_state.py",
        root / "shared" / "intraday_governor.py",
    )

    fn_found = False
    states_found = 0
    inputs_found = 0
    evidence_file: Path | None = None

    for c in candidates:
        if not c.exists():
            continue
        text = read_text(c)
        if any(h in text for h in TREND_FN_HINTS):
            fn_found = True
            evidence_file = c
        states_found = max(states_found, sum(1 for s in TREND_STATE_NAMES if s in text))
        inputs_found = max(inputs_found, sum(1 for i in INPUT_SIGNALS if i in text.lower()))

    if not fn_found:
        out.append(Finding(
            id="ITM_FUNCTION_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="No intraday_trend_state() / vwap-based trend module found.",
            expected="shared/intraday_trend.py with intraday_trend_state(symbol)",
            observed="no candidate module declares any of " + ", ".join(TREND_FN_HINTS),
            recommendation="Add a VWAP/ORH-aware intraday trend evaluator. "
                           "P2 in current iteration but increasingly important.",
        ))
    else:
        out.append(Finding(
            id="ITM_FUNCTION_PRESENT",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"Intraday trend module found in {rel(evidence_file)}.",
        ))

    if states_found < 3:
        out.append(Finding(
            id="ITM_STATES_FEW",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"Fewer than 3 of the 5 trend states detected ({states_found}/5).",
            expected="At least 3 of " + ", ".join(TREND_STATE_NAMES),
            observed=f"{states_found} detected",
            recommendation="Define TREND_CONTINUES / MOMENTUM_WEAKENING / "
                           "FAILED_BREAKOUT / REVERSAL_CONFIRMED / CHOP_NO_EDGE.",
        ))
    else:
        out.append(Finding(
            id="ITM_STATES_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"{states_found}/5 trend states declared.",
        ))

    if inputs_found < 2:
        out.append(Finding(
            id="ITM_INPUTS_FEW",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"Trend module uses fewer than 2 of expected inputs (vwap / opening_range / 5min / 15min / relative_strength).",
            recommendation="Add VWAP and at least one momentum-window input.",
        ))

    # Does exit-monitor consume the trend state?
    em = root / "exit-monitor" / "monitor.py"
    if em.exists():
        emt = read_text(em)
        if any(h in emt for h in TREND_FN_HINTS):
            out.append(Finding(
                id="ITM_EXIT_MONITOR_CONSUMES_TREND",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="exit-monitor references the intraday trend module.",
            ))
        else:
            out.append(Finding(
                id="ITM_EXIT_MONITOR_DOES_NOT_CONSUME_TREND",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="exit-monitor does not consume an intraday trend state.",
                recommendation="Add a check that escalates exits when "
                               "intraday_trend_state(symbol) is REVERSAL_CONFIRMED.",
                evidence=[Evidence(file=str(rel(em)))],
            ))

    return out
