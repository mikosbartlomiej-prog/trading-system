"""Spec §8 — momentum scoring.

`shared/momentum_score.py` must exist; entry monitors must rank tickers
via the composite score rather than scanning a static list.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Evidence, Finding
from ..utils import read_text, rel


CATEGORY  = "momentum_scoring"
PRINCIPLE = "MOMENTUM_RANKING_NOT_STATIC_LIST"

REQUIRED_SCORE_INPUTS = (
    "momentum_5d", "momentum_10d", "momentum_20d",
    "relative_strength", "volume_expansion", "breakout",
    "trend_filter",
)


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    ms = root / "shared" / "momentum_score.py"
    if not ms.exists():
        out.append(Finding(
            id="MS_MODULE_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="shared/momentum_score.py missing — strategy has no ranking module.",
            recommendation="Add shared/momentum_score.py with score_symbol().",
        ))
        return out

    text = read_text(ms)
    out.append(Finding(
        id="MS_MODULE_PRESENT",
        category=CATEGORY, severity="PASS", status="PASS",
        principle=PRINCIPLE,
        message="shared/momentum_score.py present.",
    ))

    # 1. score_symbol or equivalent
    if "score_symbol" not in text and "compute_score" not in text:
        out.append(Finding(
            id="MS_NO_SCORE_FUNCTION",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message="No score_symbol / compute_score function found.",
            recommendation="Expose score_symbol(symbol, bars) -> float.",
            evidence=[Evidence(file=str(rel(ms)))],
        ))
    else:
        out.append(Finding(
            id="MS_SCORE_FUNCTION_PRESENT",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="score_symbol / compute_score present.",
        ))

    # 2. Required composite inputs
    miss = [s for s in REQUIRED_SCORE_INPUTS if s not in text]
    if miss:
        out.append(Finding(
            id="MS_SCORE_INPUTS_INCOMPLETE",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"Composite score missing inputs: {', '.join(miss)}.",
            expected="All of: " + ", ".join(REQUIRED_SCORE_INPUTS),
            observed="missing: " + ", ".join(miss),
            recommendation="Add the missing inputs (or document why they're skipped).",
            evidence=[Evidence(file=str(rel(ms)))],
        ))
    else:
        out.append(Finding(
            id="MS_SCORE_INPUTS_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="Composite score includes all required inputs.",
        ))

    # 3. Volatility penalty exists somewhere
    if "volatility_penalty" not in text and "vol_penalty" not in text:
        out.append(Finding(
            id="MS_NO_VOLATILITY_PENALTY",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="No volatility penalty term — high-beta tickers may be over-scored.",
            recommendation="Subtract a volatility penalty from the score.",
            evidence=[Evidence(file=str(rel(ms)))],
        ))

    # 4. Entry monitor consumes scoring (price-monitor / options-monitor)
    pm = root / "price-monitor" / "monitor.py"
    if pm.exists():
        pmt = read_text(pm)
        if "momentum_score" in pmt or "score_symbol" in pmt:
            out.append(Finding(
                id="MS_PRICE_MONITOR_WIRED",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="price-monitor imports the momentum scorer.",
            ))
        else:
            out.append(Finding(
                id="MS_PRICE_MONITOR_NOT_WIRED",
                category=CATEGORY, severity="FAIL", status="FAIL",
                principle=PRINCIPLE,
                message="price-monitor does NOT consult the momentum scorer.",
                expected="from momentum_score import ...",
                observed="no import",
                recommendation="Wire score_symbol() into the ticker pre-rank step.",
                evidence=[Evidence(file=str(rel(pm)))],
            ))

    # 5. min_score_for_entry in aggressive_profile.json
    from ..utils import read_json
    cfg = read_json(root / "config" / "aggressive_profile.json") or {}
    scoring = (cfg.get("scoring") or {}) if isinstance(cfg, dict) else {}
    if "min_score_for_entry" not in scoring:
        out.append(Finding(
            id="MS_NO_MIN_SCORE_CONFIG",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="aggressive_profile.json scoring.min_score_for_entry missing.",
            recommendation="Set min_score_for_entry to ~0.30-0.40.",
        ))
    return out
