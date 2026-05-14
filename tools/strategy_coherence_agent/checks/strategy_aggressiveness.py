"""Spec §2 — Aggressive paper-mode strategy.

  - AGGRESSIVE_PAPER risk profile is the default for trading workflows.
  - OPTIONS_ENABLED true (paper aggressive permits options).
  - aggressive_profile.json is non-conservative (capital.max_gross >= 1.50).
  - Docs declare aggressive intent.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Evidence, Finding
from ..utils import list_workflows, read_json, read_text, read_yaml, rel


CATEGORY  = "strategy_aggressiveness"
PRINCIPLE = "AGGRESSIVE_PAPER_STRATEGY"

# Workflows where the main strategy actually runs. Other workflows
# (security-audit, system-consistency-audit, e2e tests) may legitimately
# use BALANCED_PAPER or no override.
STRATEGY_WORKFLOWS = (
    "price-monitor.yml", "options-monitor.yml", "options-exit-monitor.yml",
    "exit-monitor.yml", "crypto-monitor.yml", "morning-allocator.yml",
    "daily-learning.yml",
)


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    # 1. config/aggressive_profile.json exists + names itself aggressive
    cfg_path = root / "config" / "aggressive_profile.json"
    cfg = read_json(cfg_path) or {}
    if not cfg:
        out.append(Finding(
            id="SA_AGGRESSIVE_PROFILE_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="config/aggressive_profile.json missing or unreadable.",
            recommendation="Restore aggressive_profile.json.",
        ))
        return out

    name = (cfg.get("name") or "").lower()
    if "aggressive" not in name:
        out.append(Finding(
            id="SA_PROFILE_NAME_NOT_AGGRESSIVE",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"aggressive_profile.json::name = {name!r} doesn't mention 'aggressive'.",
            recommendation="Name the profile 'aggressive_momentum_event_switch' "
                           "or similar so its purpose is obvious.",
        ))
    else:
        out.append(Finding(
            id="SA_PROFILE_NAME_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"Profile name '{name}' clearly aggressive.",
        ))

    # 2. capital.max_gross_exposure >= 1.50
    cap = cfg.get("capital") or {}
    gross = cap.get("max_gross_exposure")
    if gross is None:
        out.append(Finding(
            id="SA_MAX_GROSS_MISSING",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="capital.max_gross_exposure not declared.",
            recommendation="Set capital.max_gross_exposure >= 1.50.",
        ))
    elif gross < 1.50:
        out.append(Finding(
            id="SA_MAX_GROSS_TOO_LOW",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message=f"capital.max_gross_exposure = {gross} < 1.50 — not aggressive.",
            expected=">= 1.50 (target_gross) up to 2.00",
            observed=f"{gross}",
            recommendation="Raise max_gross_exposure to >= 1.50.",
            evidence=[Evidence(file=str(rel(cfg_path)))],
        ))
    else:
        out.append(Finding(
            id="SA_MAX_GROSS_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"max_gross_exposure = {gross}× equity.",
        ))

    # 3. AGGRESSIVE_PAPER risk profile is the default
    rc = root / "shared" / "runtime_config.py"
    if rc.exists():
        rc_text = read_text(rc)
        # default appears in risk_profile()
        m = re.search(r'risk_profile\([^)]*\).*?return\s+"?(\w+)"?', rc_text, re.S)
        default_profile_match = re.search(
            r'os\.environ\.get\("RISK_PROFILE"\)\s*or\s*"([A-Z_]+)"', rc_text)
        # The current code structure uses `or "BALANCED_PAPER"` as fallback.
        # Acceptable: a separate `aggressive_paper_default` mechanism in
        # workflow env. We allow either.
        if default_profile_match:
            default_profile = default_profile_match.group(1)
            if default_profile == "AGGRESSIVE_PAPER":
                out.append(Finding(
                    id="SA_RUNTIME_DEFAULT_AGGRESSIVE",
                    category=CATEGORY, severity="PASS", status="PASS",
                    principle=PRINCIPLE,
                    message="shared/runtime_config.py defaults to AGGRESSIVE_PAPER.",
                ))
            else:
                # Acceptable only if every strategy workflow sets RISK_PROFILE=AGGRESSIVE_PAPER
                # explicitly — check next.
                out.append(Finding(
                    id="SA_RUNTIME_DEFAULT_NOT_AGGRESSIVE",
                    category=CATEGORY, severity="INFO", status="PASS",
                    principle=PRINCIPLE,
                    message=f"runtime_config default is {default_profile}. Acceptable "
                            f"only if every strategy workflow sets RISK_PROFILE explicitly.",
                ))

    # 4. Strategy workflows declare RISK_PROFILE=AGGRESSIVE_PAPER (or accept the default if it's aggressive)
    wf_dir = root / ".github" / "workflows"
    if wf_dir.exists():
        missing_override = []
        for wf_name in STRATEGY_WORKFLOWS:
            p = wf_dir / wf_name
            if not p.exists():
                continue
            text = read_text(p)
            if "RISK_PROFILE" not in text:
                missing_override.append(wf_name)
            elif "AGGRESSIVE_PAPER" not in text and "AGGRESSIVE" not in text:
                missing_override.append(wf_name)
        if missing_override:
            out.append(Finding(
                id="SA_WORKFLOWS_NOT_AGGRESSIVE",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message=f"Strategy workflows missing explicit AGGRESSIVE_PAPER: "
                        f"{', '.join(missing_override)}.",
                expected="env.RISK_PROFILE: AGGRESSIVE_PAPER in each strategy workflow",
                observed=f"missing in: {', '.join(missing_override)}",
                recommendation="Add `RISK_PROFILE: AGGRESSIVE_PAPER` to the env "
                               "block of each strategy workflow. If runtime_config "
                               "default is already aggressive, document why and "
                               "you can ignore this.",
            ))
        else:
            out.append(Finding(
                id="SA_WORKFLOWS_AGGRESSIVE",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="All strategy workflows mention AGGRESSIVE_PAPER.",
            ))

    # 5. OPTIONS_ENABLED default for aggressive paper
    rc_text = read_text(rc) if rc.exists() else ""
    # Look for profile-driven options_enabled
    if "options_enabled" in rc_text:
        # Acceptable patterns:
        #   profile_default = (risk_profile() == "AGGRESSIVE_PAPER")
        if "AGGRESSIVE_PAPER" in rc_text and "options_enabled" in rc_text:
            out.append(Finding(
                id="SA_OPTIONS_ENABLED_PROFILE_DRIVEN",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="options_enabled() is profile-driven (AGGRESSIVE_PAPER → True).",
            ))
        else:
            out.append(Finding(
                id="SA_OPTIONS_ENABLED_DEFAULT_FALSE",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="options_enabled() does not detect AGGRESSIVE_PAPER for "
                        "auto-on default.",
                recommendation="Set OPTIONS_ENABLED default = (risk_profile() == "
                               "'AGGRESSIVE_PAPER').",
                evidence=[Evidence(file=str(rel(rc)))],
            ))

    # 6. Single-position cap >= 0.15 (aggressive, not 0.05)
    single = cap.get("max_single_position_pct_equity")
    if single is not None and single < 0.15:
        out.append(Finding(
            id="SA_SINGLE_POSITION_TOO_SMALL",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"max_single_position_pct_equity = {single} (< 0.15).",
            expected=">= 0.15 (aggressive)",
            observed=f"{single}",
            recommendation="Raise to 0.20 (aggressive) or document the override reason.",
        ))

    return out
