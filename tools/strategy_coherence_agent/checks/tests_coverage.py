"""Spec §20 — tests for strategy edge cases.

The agent scans `tests/` for test names that imply coverage of:
  - +5000 intraday peak → -2000 (RED_DAY_AFTER_GREEN protection)
  - +5000 → +2500 (PROFIT_LOCK / DEFEND_DAY)
  - account_unavailable → block new entries
  - options reduced first during profit lock
  - allocator account-aware empty/partial deployment
  - regime fallback (RISK_ON / INFLATION_SHOCK / RISK_OFF)
  - manual approval wording forbidden
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from ..models import Evidence, Finding
from ..utils import read_text, rel


CATEGORY  = "tests_coverage"
PRINCIPLE = "STRATEGY_TESTS"

# Each tuple: (id_suffix, label, regex). Tests are matched anywhere in
# tests/**/*.py — file names, class names, or function names.
PROBES = (
    ("RED_AFTER_GREEN",  "+5000 → -2000 protection",
     re.compile(r"(red.day.after.green|red_after_green|plus.?5000.*minus|"
                r"5000.*\-?2000)", re.I)),
    ("PROFIT_LOCK",      "+5000 → +2500 PROFIT_LOCK / DEFEND_DAY",
     re.compile(r"(profit.?lock|defend.?day|giveback.?cascade)", re.I)),
    ("ACCOUNT_UNAVAIL",  "account unavailable blocks new entries",
     re.compile(r"(account.?unavail|missing.?account.?blocks|"
                r"account.?none.?block)", re.I)),
    ("OPTIONS_FIRST",    "options reduced first during PROFIT_LOCK",
     re.compile(r"(options.?first|options.?reduced.?first|"
                r"options_intraday_first|options.?lock)", re.I)),
    ("ALLOCATOR_REBAL",  "allocator rebalances vs current holdings",
     re.compile(r"(allocator.*(rebal|delta|partial.?invested|empty.?account|"
                r"redeploy))", re.I)),
    ("REGIME_FALLBACK",  "regime fallback (RISK_ON / RISK_OFF / INFLATION_SHOCK)",
     re.compile(r"(regime.*(risk_on|risk_off|inflation.?shock|fallback))", re.I)),
    ("FORBIDDEN_WORDING", "manual approval wording forbidden",
     re.compile(r"(forbidden.?wording|manual.?approval.?forbidden|"
                r"approval_needed_forbidden|forbidden_text)", re.I)),
    ("CASH_RESERVE_CONFLICT", "conflicting cash reserve values",
     re.compile(r"(cash.?reserve.?conflict|conflict.*cash.?reserve)", re.I)),
    ("OPTIONS_PREMIUM_CONFLICT", "conflicting options premium limits",
     re.compile(r"(options.?premium.?conflict|conflict.*options.?premium)", re.I)),
)


def _all_test_files(root: Path) -> Iterable[Path]:
    base = root / "tests"
    if not base.exists():
        return []
    out: list[Path] = []
    for f in base.rglob("test_*.py"):
        if "__pycache__" in f.parts:
            continue
        out.append(f)
    return out


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    test_files = list(_all_test_files(root))
    if not test_files:
        out.append(Finding(
            id="TC_NO_TESTS",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message="No test files under tests/.",
            recommendation="Restore the test suite.",
        ))
        return out

    blob = ""
    for p in test_files:
        try:
            blob += "\n" + p.name + " " + read_text(p)
        except Exception:
            continue

    for suffix, label, regex in PROBES:
        if regex.search(blob):
            out.append(Finding(
                id=f"TC_{suffix}_OK",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message=f"Tests cover: {label}.",
            ))
        else:
            out.append(Finding(
                id=f"TC_{suffix}_MISSING",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message=f"No test references {label}.",
                expected=f"A test_* file with the {label} scenario",
                observed="no match",
                recommendation=f"Add a test exercising '{label}'.",
            ))

    return out
