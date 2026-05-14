"""Spec §9, §10 — Intraday profit protection (the +$5,000 → -$2,000 contract).

Verifies that the system actually defends a large intraday peak P&L:
  - `shared/intraday_governor.py` (or peak_tracker extension) exists.
  - 7-state FSM names appear (FLAT, GREEN, STRONG_GREEN, GIVEBACK_WARN,
    PROFIT_LOCK, DEFEND_DAY, RED_DAY_AFTER_GREEN).
  - `config/aggressive_profile.json::intraday_profit_protection` is enabled
    with all required keys.
  - `exit-monitor` consults the module on every cron tick.
  - `alpaca_orders`-level entry gate blocks new entries during DEFEND_DAY /
    RED_DAY_AFTER_GREEN.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Evidence, Finding
from ..utils import (
    file_contains, first_line_with, read_json, read_text, rel,
)


CATEGORY  = "intraday_profit_protection"
PRINCIPLE = "INTRADAY_PROFIT_PROTECTION"

REQUIRED_FSM_STATES = (
    "FLAT", "GREEN", "STRONG_GREEN",
    "GIVEBACK_WARN", "PROFIT_LOCK",
    "DEFEND_DAY", "RED_DAY_AFTER_GREEN",
)

REQUIRED_CONFIG_KEYS = (
    "enabled",
    "min_profit_to_arm_usd",
    "giveback_warn_pct_of_peak",
    "profit_lock_pct_of_peak",
    "defend_day_pct_of_peak",
    "red_after_green_pct_of_peak",
    "block_new_entries_on_defend_day",
    "block_new_entries_on_red_after_green",
    "reduce_options_first",
    "reduce_weak_positions_first",
)

REQUIRED_SNAPSHOT_FIELDS = (
    "session_start_equity", "current_equity", "intraday_peak_equity",
    "intraday_peak_pnl", "current_intraday_pnl",
    "giveback_usd", "giveback_pct_of_peak", "pnl_state",
)


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    # 1. Governor module exists (intraday_governor preferred; peak_tracker
    # extension acceptable).
    gov_path = root / "shared" / "intraday_governor.py"
    peak_path = root / "shared" / "peak_tracker.py"
    gov_exists = gov_path.exists()
    peak_exists = peak_path.exists()

    if not gov_exists and not peak_exists:
        out.append(Finding(
            id="IPP_MODULE_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="Neither shared/intraday_governor.py nor shared/peak_tracker.py exists.",
            expected="shared/intraday_governor.py with a 7-state FSM",
            observed="both files missing",
            recommendation="Create shared/intraday_governor.py per docs/INTRADAY_PROTECTION.md.",
        ))
        return out

    target = gov_path if gov_exists else peak_path
    text = read_text(target)

    out.append(Finding(
        id="IPP_MODULE_PRESENT",
        category=CATEGORY, severity="PASS", status="PASS",
        principle=PRINCIPLE,
        message=f"{rel(target)} present.",
        evidence=[Evidence(file=str(rel(target)))],
    ))

    # 2. FSM states are declared in the module
    missing_states = [s for s in REQUIRED_FSM_STATES
                      if f"STATE_{s}" not in text and f'"{s}"' not in text]
    if missing_states:
        out.append(Finding(
            id="IPP_FSM_STATES_INCOMPLETE",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message=f"FSM module missing states: {', '.join(missing_states)}.",
            expected="All 7 states: " + ", ".join(REQUIRED_FSM_STATES),
            observed="missing: " + ", ".join(missing_states),
            recommendation="Add the missing STATE_* constants and wire them "
                           "into _compute_state().",
            evidence=[Evidence(file=str(rel(target)))],
        ))
    else:
        out.append(Finding(
            id="IPP_FSM_STATES_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="All 7 FSM states (FLAT … RED_DAY_AFTER_GREEN) declared.",
        ))

    # 3. Snapshot fields tracked
    missing_fields = [s for s in REQUIRED_SNAPSHOT_FIELDS if s not in text]
    if missing_fields:
        out.append(Finding(
            id="IPP_SNAPSHOT_FIELDS_INCOMPLETE",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"Snapshot dataclass missing fields: {', '.join(missing_fields)}.",
            expected="All snapshot fields per spec §3",
            observed="missing: " + ", ".join(missing_fields),
            recommendation="Extend IntradaySnapshot to track every field "
                           "the operator email needs.",
        ))
    else:
        out.append(Finding(
            id="IPP_SNAPSHOT_FIELDS_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="IntradaySnapshot tracks every required field.",
        ))

    # 4. Config block exists with all required keys
    cfg_path = root / "config" / "aggressive_profile.json"
    cfg = read_json(cfg_path) or {}
    block = (cfg.get("intraday_profit_protection") or {}) if isinstance(cfg, dict) else {}
    if not block:
        out.append(Finding(
            id="IPP_CONFIG_BLOCK_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="config/aggressive_profile.json missing intraday_profit_protection.",
            expected="intraday_profit_protection block with required keys",
            observed="block absent",
            recommendation="Add the block per docs/INTRADAY_PROTECTION.md.",
            evidence=[Evidence(file=str(rel(cfg_path)))],
        ))
    else:
        # Has block — check enabled + key coverage
        if not block.get("enabled", False):
            out.append(Finding(
                id="IPP_CONFIG_DISABLED",
                category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
                principle=PRINCIPLE,
                message="intraday_profit_protection.enabled is false — "
                        "production must run with this on.",
                expected="enabled: true",
                observed=f"enabled: {block.get('enabled')!r}",
                recommendation="Set intraday_profit_protection.enabled=true.",
                evidence=[Evidence(file=str(rel(cfg_path)))],
            ))
        missing = [k for k in REQUIRED_CONFIG_KEYS if k not in block]
        if missing:
            out.append(Finding(
                id="IPP_CONFIG_KEYS_INCOMPLETE",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message=f"Config block missing keys: {', '.join(missing)}.",
                expected="All required keys per spec §14",
                observed="missing: " + ", ".join(missing),
                recommendation="Add the missing keys to the config block.",
                evidence=[Evidence(file=str(rel(cfg_path)))],
            ))
        else:
            out.append(Finding(
                id="IPP_CONFIG_KEYS_OK",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="intraday_profit_protection has all required keys.",
            ))

        # Verify entry-block flags are TRUE (otherwise the protection has
        # no teeth in DEFEND_DAY / RED_DAY_AFTER_GREEN).
        if block.get("block_new_entries_on_defend_day") is False:
            out.append(Finding(
                id="IPP_DEFEND_DAY_NOT_BLOCKING",
                category=CATEGORY, severity="FAIL", status="FAIL",
                principle=PRINCIPLE,
                message="block_new_entries_on_defend_day is false.",
                expected="true",
                observed="false",
                recommendation="Flip the flag — DEFEND_DAY must block new entries.",
                evidence=[Evidence(file=str(rel(cfg_path)))],
            ))
        if block.get("block_new_entries_on_red_after_green") is False:
            out.append(Finding(
                id="IPP_RED_AFTER_GREEN_NOT_BLOCKING",
                category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
                principle=PRINCIPLE,
                message="block_new_entries_on_red_after_green is false.",
                expected="true",
                observed="false",
                recommendation="Flip the flag — RED_DAY_AFTER_GREEN must "
                               "absolutely block new entries.",
                evidence=[Evidence(file=str(rel(cfg_path)))],
            ))

    # 5. exit-monitor consults the governor on every cron tick
    em_path = root / "exit-monitor" / "monitor.py"
    if em_path.exists():
        em_text = read_text(em_path)
        has_call = ("intraday_governor" in em_text
                    or "from peak_tracker" in em_text
                    and "update_peak" in em_text)
        # Stronger signal: real call site of update()/update_peak()
        invokes_update = ("ig_update(" in em_text
                          or "update_peak(" in em_text
                          or "intraday_governor.update(" in em_text)
        if not has_call:
            out.append(Finding(
                id="IPP_EXIT_MONITOR_NOT_WIRED",
                category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
                principle=PRINCIPLE,
                message="exit-monitor/monitor.py does not import "
                        "intraday_governor or peak_tracker.",
                expected="import + per-tick update() call",
                observed="no import found",
                recommendation="Wire intraday_governor.update(account) into "
                               "run_exit_check().",
                evidence=[Evidence(file=str(rel(em_path)))],
            ))
        elif not invokes_update:
            out.append(Finding(
                id="IPP_EXIT_MONITOR_NOT_INVOKING",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="exit-monitor imports the governor but no update() call is detected.",
                expected="explicit per-tick update()",
                observed="import only",
                recommendation="Call intraday_governor.update(account) at the "
                               "top of run_exit_check().",
                evidence=[Evidence(file=str(rel(em_path)))],
            ))
        else:
            out.append(Finding(
                id="IPP_EXIT_MONITOR_WIRED",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="exit-monitor invokes the governor every tick.",
            ))
    else:
        out.append(Finding(
            id="IPP_EXIT_MONITOR_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="exit-monitor/monitor.py missing — primary cron has no profit protection.",
            recommendation="Restore exit-monitor/monitor.py.",
        ))

    # 6. options-exit-monitor consults the governor
    oem_path = root / "options-exit-monitor" / "monitor.py"
    if oem_path.exists():
        oem_text = read_text(oem_path)
        if "intraday_governor" in oem_text and ("GOVERNOR" in oem_text or "options-first" in oem_text):
            out.append(Finding(
                id="IPP_OPTIONS_EXIT_WIRED",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="options-exit-monitor honors the governor (GOVERNOR decision / options-first).",
            ))
        else:
            out.append(Finding(
                id="IPP_OPTIONS_EXIT_NOT_WIRED",
                category=CATEGORY, severity="FAIL", status="FAIL",
                principle=PRINCIPLE,
                message="options-exit-monitor/monitor.py does not consult the governor.",
                expected="GOVERNOR decision tag in evaluate() OR explicit "
                         "options-first reduction during PROFIT_LOCK.",
                observed="no reference to intraday_governor",
                recommendation="Add governor priority check in evaluate() so "
                               "options close FIRST under PROFIT_LOCK/DEFEND_DAY.",
                evidence=[Evidence(file=str(rel(oem_path)))],
            ))

    # 7. alpaca_orders has the pre-trade entry gate
    ao_path = root / "shared" / "alpaca_orders.py"
    if ao_path.exists():
        ao_text = read_text(ao_path)
        if "_intraday_governor_gate" in ao_text or "block_new_entries" in ao_text:
            out.append(Finding(
                id="IPP_ENTRY_GATE_WIRED",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="alpaca_orders has an intraday-governor entry gate.",
                evidence=[
                    first_line_with(ao_path, "_intraday_governor_gate")
                    or first_line_with(ao_path, "block_new_entries")
                    or Evidence(file=str(rel(ao_path)))
                ],
            ))
        else:
            out.append(Finding(
                id="IPP_ENTRY_GATE_MISSING",
                category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
                principle=PRINCIPLE,
                message="shared/alpaca_orders.py has no intraday-governor gate.",
                expected="_intraday_governor_gate() call in place_stock_bracket / "
                         "place_crypto_order / place_simple_buy",
                observed="no gate function",
                recommendation="Add the entry gate so DEFEND_DAY / "
                               "RED_DAY_AFTER_GREEN deterministically block new entries.",
                evidence=[Evidence(file=str(rel(ao_path)))],
            ))

    # 8. Profit-floor block exists in config
    if cfg:
        floor = cfg.get("profit_floor") or {}
        if not floor.get("enabled", False):
            out.append(Finding(
                id="IPP_PROFIT_FLOOR_DISABLED",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="profit_floor.enabled is false or missing.",
                expected="enabled: true with tier_1/tier_2/tier_3 ladder",
                observed=f"enabled={floor.get('enabled')!r}",
                recommendation="Enable profit_floor and define 3 tiers.",
                evidence=[Evidence(file=str(rel(cfg_path)))],
            ))
        else:
            out.append(Finding(
                id="IPP_PROFIT_FLOOR_OK",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="profit_floor ladder configured.",
            ))

    # 9. Docs reference the protection — INTRADAY_PROTECTION.md or STRATEGY mention
    docs = root / "docs" / "INTRADAY_PROTECTION.md"
    if not docs.exists():
        strat = root / "docs" / "STRATEGY.md"
        if not (strat.exists() and "intraday" in read_text(strat).lower()
                and "profit_lock" in read_text(strat).lower()):
            out.append(Finding(
                id="IPP_DOCS_MISSING",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="No documentation for intraday profit protection.",
                expected="docs/INTRADAY_PROTECTION.md OR a section in docs/STRATEGY.md",
                observed="neither present",
                recommendation="Document the FSM + actions per state.",
            ))
        else:
            out.append(Finding(
                id="IPP_DOCS_PARTIAL",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="docs/STRATEGY.md references the protection (but a dedicated doc is recommended).",
            ))
    else:
        out.append(Finding(
            id="IPP_DOCS_PRESENT",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="docs/INTRADAY_PROTECTION.md present.",
        ))

    return out
