"""Options safety. Spec §7."""

from __future__ import annotations

from pathlib import Path

from ..models import Finding
from ..utils import read_text


CATEGORY = "options_safety"
PRINCIPLE = "OPTIONS_SAFETY"


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    # 1. OPTIONS_ENABLED default false in runtime_config.
    # v3.5 update: options_enabled() is now profile-driven —
    # AGGRESSIVE_PAPER → True (paper-only invariant + IntradayProfitGovernor
    # protects giveback), other profiles → False by default. Either pattern
    # is acceptable as long as the profile-gated logic is explicit.
    rc = root / "shared" / "runtime_config.py"
    if rc.exists():
        text = read_text(rc)
        # v3.4 pattern: hard False default
        default_false = '_bool("OPTIONS_ENABLED", False)' in text
        # v3.5 pattern: profile-driven default
        profile_driven = (
            "profile_default = (risk_profile() == \"AGGRESSIVE_PAPER\")" in text
            and '_bool("OPTIONS_ENABLED", profile_default)' in text
        )
        ok = default_false or profile_driven
        findings.append(Finding(
            id="OPTIONS_DEFAULT_DISABLED",
            category=CATEGORY,
            severity="PASS" if ok else "FAIL",
            status="PASS" if ok else "FAIL",
            message=(
                "OPTIONS_ENABLED has profile-driven default (AGGRESSIVE_PAPER → True, others → False)."
                if profile_driven else
                ("OPTIONS_ENABLED defaults to False." if default_false
                 else "OPTIONS_ENABLED default not clearly false or profile-driven.")
            ),
            principle=PRINCIPLE,
            recommendation="Make OPTIONS_ENABLED default False, or profile-driven via risk_profile()." if not ok else "",
            blocking=not ok,
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
    # v3.11.3 (2026-05-30) — fix audit rule: real code uses dict syntax
    # `params={"status": "open", ...}` and `already_has_open_sell()` helper,
    # not the old literal f-string `"status=open"`. Match either pattern.
    oem = root / "options-exit-monitor" / "monitor.py"
    if oem.exists():
        text = read_text(oem)
        # Modern pattern (post-2026-05): dedup via params dict + helper fn
        has_modern_dedup = (
            ("already_has_open_sell" in text)
            or ('"status": "open"' in text and 'side' in text)
            or ("'status': 'open'" in text and "side" in text)
        )
        # Legacy pattern (pre-2026-05 if anyone still uses inline f-strings)
        has_legacy_dedup = "status=open" in text and "side" in text
        has_dedup = has_modern_dedup or has_legacy_dedup
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
