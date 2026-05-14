"""Options safety. Spec §7."""

from __future__ import annotations

from pathlib import Path

from ..models import Finding
from ..utils import read_text


CATEGORY = "options_safety"
PRINCIPLE = "OPTIONS_SAFETY"


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    # 1. OPTIONS_ENABLED default false in runtime_config
    rc = root / "shared" / "runtime_config.py"
    if rc.exists():
        text = read_text(rc)
        default_false = '_bool("OPTIONS_ENABLED", False)' in text
        findings.append(Finding(
            id="OPTIONS_DEFAULT_DISABLED",
            category=CATEGORY,
            severity="PASS" if default_false else "FAIL",
            status="PASS" if default_false else "FAIL",
            message="OPTIONS_ENABLED defaults to False." if default_false
                    else "OPTIONS_ENABLED default not clearly false.",
            principle=PRINCIPLE,
            recommendation="Make OPTIONS_ENABLED default False in runtime_config." if not default_false else "",
            blocking=not default_false,
        ))

    # 2. options-monitor has OPTIONS_ENABLED gate + liquidity check
    om = root / "options-monitor" / "monitor.py"
    if om.exists():
        text = read_text(om)
        has_gate = "options_enabled" in text
        has_liquidity = "check_options_liquidity" in text or "spread_pct" in text
        findings.append(Finding(
            id="OPTIONS_ENTRY_HAS_GATE",
            category=CATEGORY,
            severity="PASS" if has_gate else "FAIL",
            status="PASS" if has_gate else "FAIL",
            message="options-monitor reads OPTIONS_ENABLED gate." if has_gate
                    else "options-monitor missing OPTIONS_ENABLED gate.",
            principle=PRINCIPLE,
            recommendation="Add `if not options_enabled(): return` at start of run_scan." if not has_gate else "",
            blocking=not has_gate,
        ))
        findings.append(Finding(
            id="OPTIONS_LIQUIDITY_CHECK_PRESENT",
            category=CATEGORY,
            severity="PASS" if has_liquidity else "FAIL",
            status="PASS" if has_liquidity else "FAIL",
            message="options-monitor checks liquidity (spread / bid / ask)." if has_liquidity
                    else "options-monitor does NOT check liquidity.",
            principle=PRINCIPLE,
            recommendation="Add check_options_liquidity() before placing order." if not has_liquidity else "",
            blocking=not has_liquidity,
        ))

    # 3. panic_close_options has autonomous mode
    pc = root / "scripts" / "panic_close_options.py"
    if pc.exists():
        text = read_text(pc)
        has_autonomous = "AUTONOMOUS_PANIC_CLOSE_OPTIONS" in text
        findings.append(Finding(
            id="OPTIONS_PANIC_AUTONOMOUS_MODE",
            category=CATEGORY,
            severity="PASS" if has_autonomous else "FAIL",
            status="PASS" if has_autonomous else "FAIL",
            message="panic_close_options.py honours AUTONOMOUS_PANIC_CLOSE_OPTIONS." if has_autonomous
                    else "panic_close_options.py only supports manual confirm.",
            principle=PRINCIPLE,
            recommendation="Accept AUTONOMOUS_PANIC_CLOSE_OPTIONS=true env." if not has_autonomous else "",
        ))

    # 4. options-exit-monitor has dedup of SELL orders
    oem = root / "options-exit-monitor" / "monitor.py"
    if oem.exists():
        text = read_text(oem)
        has_dedup = "status=open" in text and "side" in text
        findings.append(Finding(
            id="OPTIONS_EXIT_DEDUP",
            category=CATEGORY,
            severity="PASS" if has_dedup else "WARN",
            status="PASS" if has_dedup else "WARN",
            message="options-exit-monitor dedupes SELL orders." if has_dedup
                    else "options-exit-monitor may stack duplicate SELLs.",
            principle=PRINCIPLE,
            recommendation="Filter open orders by symbol+side before placing SELL." if not has_dedup else "",
        ))

    return findings
