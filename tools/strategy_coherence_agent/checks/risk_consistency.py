"""Spec §13, §15, §16 — risk discipline & fail behavior.

Cross-checks:
  - Drawdown limits (daily / weekly / defensive / full-stop) consistent
    across STRATEGY.md and aggressive_profile.json.
  - Gross exposure caps coherent (target ≤ max ≤ emergency_hard_cap).
  - kill_switch / defensive_mode modules exist.
  - Fail behavior: account-unavailable / portfolio-risk-unavailable
    block new entries (NOT fail-open).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Evidence, Finding
from ..utils import read_json, read_text, rel


CATEGORY  = "risk_consistency"
PRINCIPLE = "RISK_MANAGEMENT_WINS_OVER_DEPLOYMENT"


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    cfg = read_json(root / "config" / "aggressive_profile.json") or {}
    cfg_path = root / "config" / "aggressive_profile.json"
    rl = cfg.get("risk_limits") or {}
    cap = cfg.get("capital") or {}
    ipp_block = cfg.get("intraday_profit_protection") or {}
    expo = cfg.get("intraday_exposure_reduction") or {}

    # 1. Drawdown limits sensible: daily < weekly < defensive < full_stop
    daily = rl.get("max_daily_loss_pct_equity")
    weekly = rl.get("max_weekly_loss_pct_equity")
    defensive = rl.get("max_drawdown_defensive_mode_pct")
    full_stop = rl.get("max_drawdown_full_stop_pct")
    if all(v is not None for v in (daily, weekly, defensive, full_stop)):
        # Stored as positive fractions e.g. 0.03 / 0.07 / 0.12 / 0.20.
        ordered = daily <= weekly <= defensive <= full_stop
        if not ordered:
            out.append(Finding(
                id="RC_DRAWDOWN_ORDER_VIOLATED",
                category=CATEGORY, severity="FAIL", status="FAIL",
                principle=PRINCIPLE,
                message=f"Drawdown thresholds out of order: daily={daily}, "
                        f"weekly={weekly}, defensive={defensive}, full_stop={full_stop}.",
                expected="daily ≤ weekly ≤ defensive ≤ full_stop",
                observed=f"daily={daily} weekly={weekly} defensive={defensive} full_stop={full_stop}",
                recommendation="Reorder thresholds so each level is wider than the prior.",
                evidence=[Evidence(file=str(rel(cfg_path)))],
            ))
        else:
            out.append(Finding(
                id="RC_DRAWDOWN_ORDER_OK",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message=f"Drawdown thresholds correctly ordered: {daily} ≤ {weekly} ≤ {defensive} ≤ {full_stop}.",
            ))
    else:
        missing = [k for k, v in (
            ("daily", daily), ("weekly", weekly),
            ("defensive", defensive), ("full_stop", full_stop)
        ) if v is None]
        out.append(Finding(
            id="RC_DRAWDOWN_KEYS_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"Drawdown keys missing: {', '.join(missing)}.",
            recommendation="Declare every drawdown threshold in aggressive_profile.json.",
        ))

    # 2. Gross exposure consistency: normal ≤ ipp.giveback_warn ≤ profit_lock ≤ defend_day ≤ red_after_green is INVERTED:
    # we want exposure to monotonically SHRINK from normal to red_after_green.
    normal = expo.get("normal_max_gross") or cap.get("max_gross_exposure")
    warn   = expo.get("giveback_warn_max_gross")
    lock   = expo.get("profit_lock_max_gross")
    defend = expo.get("defend_day_max_gross")
    red    = expo.get("red_after_green_max_gross")
    seq = [("normal", normal), ("giveback_warn", warn), ("profit_lock", lock),
           ("defend_day", defend), ("red_after_green", red)]
    vals_present = [v for _, v in seq if v is not None]
    if len(vals_present) >= 4:
        # Check monotonically non-increasing
        monot = all(seq[i][1] >= seq[i+1][1]
                    for i in range(len(seq)-1)
                    if seq[i][1] is not None and seq[i+1][1] is not None)
        if not monot:
            out.append(Finding(
                id="RC_EXPOSURE_NOT_SHRINKING",
                category=CATEGORY, severity="FAIL", status="FAIL",
                principle=PRINCIPLE,
                message=f"intraday_exposure_reduction is not monotonically shrinking: {seq}",
                expected="normal ≥ giveback_warn ≥ profit_lock ≥ defend_day ≥ red_after_green",
                observed=str(seq),
                recommendation="Ensure each step tightens.",
                evidence=[Evidence(file=str(rel(cfg_path)))],
            ))
        else:
            out.append(Finding(
                id="RC_EXPOSURE_SHRINKS_OK",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="intraday_exposure_reduction tightens monotonically.",
            ))
    else:
        out.append(Finding(
            id="RC_EXPOSURE_LADDER_INCOMPLETE",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="intraday_exposure_reduction missing fields.",
            recommendation="Declare normal / giveback_warn / profit_lock / defend_day / red_after_green ratios.",
        ))

    # 3. kill_switch + defensive_mode modules
    ks = root / "shared" / "defensive_mode.py"
    if not ks.exists():
        out.append(Finding(
            id="RC_KILL_SWITCH_MODULE_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message="shared/defensive_mode.py missing — no kill-switch coordinator.",
            recommendation="Add shared/defensive_mode.py with arm/disarm + is_active().",
        ))
    else:
        out.append(Finding(
            id="RC_KILL_SWITCH_PRESENT",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="shared/defensive_mode.py present.",
        ))

    # 4. Fail-closed behavior — account-unavailable must block new entries
    rg = root / "shared" / "risk_guards.py"
    if rg.exists():
        rgt = read_text(rg)
        # Heuristic: a fail-OPEN comment near account error path is bad
        # for new entries. Verify shared/alpaca_orders.py has the
        # account_unavailable block.
        ao = root / "shared" / "alpaca_orders.py"
        ao_text = read_text(ao) if ao.exists() else ""
        if "account_unavailable" not in ao_text and "block_new_entries" not in ao_text:
            out.append(Finding(
                id="RC_FAIL_OPEN_FOR_NEW_ENTRIES",
                category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
                principle=PRINCIPLE,
                message="No account_unavailable / block_new_entries handling in "
                        "alpaca_orders — new entries may fail-OPEN.",
                expected="account-unavailable → reject new entries; "
                         "portfolio-risk-unavailable → reject new BUY/SHORT",
                observed="no such handling",
                recommendation="Hook account_unavailable into the pre-trade gate.",
                evidence=[Evidence(file=str(rel(ao)))],
            ))
        else:
            out.append(Finding(
                id="RC_FAIL_CLOSED_FOR_NEW_ENTRIES",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="alpaca_orders blocks new entries when account state is unavailable.",
            ))

    # 5. STRATEGY.md vs config drawdown declarations
    strat = root / "docs" / "STRATEGY.md"
    if strat.exists():
        st = read_text(strat)
        # Look for a single canonical statement of daily drawdown
        m = re.search(r'Daily P&L\s*≤?\s*-?(\d+(?:\.\d+)?)\s*%', st, re.I)
        if m and daily is not None:
            doc_daily = float(m.group(1)) / 100.0
            if abs(doc_daily - daily) > 0.005:
                out.append(Finding(
                    id="RC_DOC_VS_CFG_DAILY_LOSS_MISMATCH",
                    category=CATEGORY, severity="WARN", status="WARN",
                    principle=PRINCIPLE,
                    message=f"STRATEGY.md says daily loss -{m.group(1)}%, config has {daily*100:.1f}%.",
                    expected="same value in both",
                    observed=f"docs={doc_daily}, config={daily}",
                    recommendation="Reconcile docs vs config.",
                    evidence=[Evidence(file=str(rel(strat)), line=0, snippet=m.group(0))],
                ))

    # 6. shared/risk_guards.py declares the canonical guard set.
    # The guards are the deterministic gates that block / size every
    # pre-trade decision. Missing one of them means a downstream check
    # (e.g. concentration_ok) is effectively dead code.
    rg = root / "shared" / "risk_guards.py"
    if not rg.exists():
        out.append(Finding(
            id="RC_RISK_GUARDS_MODULE_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="shared/risk_guards.py missing — no portfolio-level guards.",
            recommendation="Restore shared/risk_guards.py with daily_drawdown_guard, "
                           "vix_guard, has_open_position, concentration_ok, get_account_status.",
        ))
    else:
        rgt = read_text(rg)
        needed = ("daily_drawdown_guard", "vix_guard", "has_open_position",
                  "concentration_ok", "get_account_status")
        missing_guards = [n for n in needed if n not in rgt]
        if missing_guards:
            out.append(Finding(
                id="RC_GUARDS_INCOMPLETE",
                category=CATEGORY, severity="FAIL", status="FAIL",
                principle=PRINCIPLE,
                message=f"shared/risk_guards.py missing guards: {', '.join(missing_guards)}.",
                expected="All canonical guards declared",
                observed="missing: " + ", ".join(missing_guards),
                recommendation="Add the missing guard functions.",
                evidence=[Evidence(file=str(rel(rg)))],
            ))
        else:
            out.append(Finding(
                id="RC_GUARDS_OK",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="All canonical risk guards declared in shared/risk_guards.py.",
            ))

    # 7. shared/portfolio_risk.py exposes evaluate_portfolio_risk — the
    # canonical bucket/gross/single-position gate. If this module exists
    # but the API doesn't, alpaca_orders._portfolio_risk_gate fails open.
    pr = root / "shared" / "portfolio_risk.py"
    if pr.exists():
        prt = read_text(pr)
        if "evaluate_portfolio_risk" not in prt:
            out.append(Finding(
                id="RC_PORTFOLIO_RISK_API_MISSING",
                category=CATEGORY, severity="FAIL", status="FAIL",
                principle=PRINCIPLE,
                message="portfolio_risk.py does not declare evaluate_portfolio_risk().",
                expected="canonical evaluate_portfolio_risk(proposed_trade, account, ...)",
                observed="function absent",
                recommendation="Add evaluate_portfolio_risk so alpaca_orders gate "
                               "doesn't fail-open on import error.",
                evidence=[Evidence(file=str(rel(pr)))],
            ))
        else:
            out.append(Finding(
                id="RC_PORTFOLIO_RISK_API_OK",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="portfolio_risk.evaluate_portfolio_risk present.",
            ))

    # 8. shared/risk_officer.evaluate_trade is wired into entry placement.
    # Without this, the per-trade R:R / size / SL checks never run.
    ro = root / "shared" / "risk_officer.py"
    ao = root / "shared" / "alpaca_orders.py"
    if ro.exists() and ao.exists():
        aot = read_text(ao)
        if "evaluate_trade" in aot:
            out.append(Finding(
                id="RC_RISK_OFFICER_WIRED",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="alpaca_orders invokes risk_officer.evaluate_trade().",
            ))
        else:
            out.append(Finding(
                id="RC_RISK_OFFICER_NOT_WIRED",
                category=CATEGORY, severity="FAIL", status="FAIL",
                principle=PRINCIPLE,
                message="risk_officer module exists but alpaca_orders does NOT invoke "
                        "evaluate_trade — per-trade R:R / size / SL checks are dead code.",
                expected="evaluate_trade(...) call in place_stock_bracket / place_crypto_order",
                observed="no evaluate_trade reference",
                recommendation="Wire risk_officer.evaluate_trade into every entry placement.",
                evidence=[Evidence(file=str(rel(ao)))],
            ))

    return out
