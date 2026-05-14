"""Spec §21 — documentation parity.

Compares numeric settings across:
  - config/aggressive_profile.json
  - config/instrument_windows.json
  - docs/STRATEGY.md, docs/RISK_PROFILE.md, docs/INTRADAY_PROTECTION.md,
    docs/PRODUCT.md
  - shared/intraday_governor.py, shared/risk_guards.py, shared/risk_officer.py

A "conflict" = the same canonical setting name appears in ≥2 files with
different numeric values AND the difference isn't trivially explained
(e.g. nested key names colliding).

The orchestrator surfaces conflicts BOTH as findings in this category
AND as a flat top-level `conflicting_values` array in the JSON report.
"""

from __future__ import annotations

from pathlib import Path

from ..models import ConflictingValue, Evidence, Finding
from ..utils import extract_numeric_settings, read_text, rel


CATEGORY  = "documentation_parity"
PRINCIPLE = "DOC_CONFIG_CODE_PARITY"


# Canonical settings we expect to see consistent across files.
# (key, expected_default_str_for_aggressive)
CANONICAL_SETTINGS: dict[str, str] = {
    "cash_reserve_pct_equity":              "0.00",
    "target_invested_ratio":                "1.00",
    "min_invested_ratio":                   "0.98",
    "max_idle_cash_ratio":                  "0.02",
    "operational_cash_buffer_ratio":        "<= 0.005",
    "max_gross_exposure":                   "1.50",
    "max_single_position_pct_equity":       "0.20",
    "max_sector_exposure_pct_equity":       "0.55",
    "max_crypto_exposure_pct_equity":       "0.20",
    "max_options_premium_pct_equity":       "0.25",
    "max_daily_loss_pct_equity":            "0.03",
    "max_weekly_loss_pct_equity":           "0.07",
    "max_drawdown_defensive_mode_pct":      "0.12",
    "max_drawdown_full_stop_pct":           "0.20",
    "min_profit_to_arm_usd":                "1000",
    "giveback_warn_pct_of_peak":            "0.25",
    "profit_lock_pct_of_peak":              "0.35",
    "defend_day_pct_of_peak":               "0.50",
    "red_after_green_pct_of_peak":          "0.60",
}


# Files we scan (relative to repo root).
PARITY_FILES = (
    "config/aggressive_profile.json",
    "config/instrument_windows.json",
    "docs/STRATEGY.md",
    "docs/RISK_PROFILE.md",
    "docs/INTRADAY_PROTECTION.md",
    "docs/PRODUCT.md",
    "shared/intraday_governor.py",
    "shared/risk_guards.py",
    "shared/risk_officer.py",
)


def scan_conflicting_values(root: Path) -> list[ConflictingValue]:
    """Return ConflictingValue objects for each canonical setting that
    appears with diverging values across `PARITY_FILES`.

    Imported by the orchestrator (`checks/__init__.collect_conflicting_values`)
    so the report can surface them as a top-level array as well.
    """
    by_setting: dict[str, list[dict]] = {k: [] for k in CANONICAL_SETTINGS}

    for relp in PARITY_FILES:
        p = root / relp
        if not p.exists():
            continue
        found = extract_numeric_settings(p)
        for key in by_setting:
            for line_no, val_str in found.get(key, []):
                by_setting[key].append({
                    "file":  str(rel(p)),
                    "line":  line_no,
                    "value": val_str,
                    "kind":  p.suffix.lstrip(".") or "py",
                })

    conflicts: list[ConflictingValue] = []
    for setting, occs in by_setting.items():
        if len(occs) < 2:
            continue
        values = {o["value"] for o in occs}
        # Single value across all occurrences = no conflict
        if len(values) == 1:
            continue
        # Normalise trivially different formats (e.g. 0.5 vs 0.50)
        try:
            normed = {f"{float(v):.4f}" for v in values}
        except ValueError:
            normed = values
        if len(normed) == 1:
            continue
        conflicts.append(ConflictingValue(
            name=setting,
            occurrences=occs,
            expected=CANONICAL_SETTINGS[setting],
            severity="WARN" if setting not in ("cash_reserve_pct_equity",
                                                "target_invested_ratio",
                                                "profit_lock_pct_of_peak",
                                                "defend_day_pct_of_peak")
                     else "FAIL",
        ))
    return conflicts


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []
    conflicts = scan_conflicting_values(root)

    if not conflicts:
        out.append(Finding(
            id="DP_NO_CONFLICTS",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="No conflicting numeric settings across config + docs + code.",
        ))
        return out

    # One finding per conflict — orchestrator also exposes the array.
    for cv in conflicts:
        # Build compact evidence rows from the first 4 occurrences
        ev = [Evidence(file=o["file"], line=o.get("line", 0),
                       snippet=f"{cv.name} = {o['value']}")
              for o in cv.occurrences[:4]]
        severity = cv.severity
        status   = severity if severity in ("FAIL", "WARN") else "WARN"
        out.append(Finding(
            id=f"DP_CONFLICT_{cv.name.upper()}",
            category=CATEGORY, severity=severity, status=status,
            principle=PRINCIPLE,
            message=f"Setting `{cv.name}` declared with {len(set(o['value'] for o in cv.occurrences))} "
                    f"different values across {len(cv.occurrences)} files.",
            expected=cv.expected,
            observed=", ".join(f"{o['value']}@{o['file']}" for o in cv.occurrences[:6]),
            recommendation=f"Pick one value for {cv.name} and propagate it. "
                           f"`config/aggressive_profile.json` is the canonical source.",
            evidence=ev,
        ))

    return out
