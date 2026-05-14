"""Spec §5 — daily learning-loop generates next-day allocation plan.

  - learning-loop/analyzer.py exists and writes to learning-loop/allocations/.
  - shared/allocator.py has save_plan / execute_orders.
  - daily-learning.yml runs before morning-allocator.yml.
  - allocation plan structure matches spec (date, equity, deltas, reason, regime).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Evidence, Finding
from ..utils import list_workflows, read_text, rel


CATEGORY  = "learning_loop_allocator"
PRINCIPLE = "LEARNING_LOOP_TO_ALLOCATION_PLAN"

REQUIRED_PLAN_FIELDS = (
    "date", "equity", "positions", "target_weights", "delta",
    "regime", "reason",
)


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    # 1. analyzer + allocator exist
    analyzer = root / "learning-loop" / "analyzer.py"
    alloc    = root / "shared" / "allocator.py"
    if not analyzer.exists():
        out.append(Finding(
            id="LLA_ANALYZER_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="learning-loop/analyzer.py is missing.",
            recommendation="Restore the daily-learning analyzer.",
        ))
    if not alloc.exists():
        out.append(Finding(
            id="LLA_ALLOCATOR_MISSING",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message="shared/allocator.py missing — analyzer has nowhere to send the plan.",
            recommendation="Add shared/allocator.py with save_plan(plan) and execute_orders(plan).",
        ))
    if not analyzer.exists() or not alloc.exists():
        return out

    out.append(Finding(
        id="LLA_MODULES_PRESENT",
        category=CATEGORY, severity="PASS", status="PASS",
        principle=PRINCIPLE,
        message="learning-loop/analyzer.py + shared/allocator.py present.",
    ))

    # 2. analyzer.py calls allocator
    atext = read_text(analyzer)
    if "save_plan" not in atext and "build_plan" not in atext:
        out.append(Finding(
            id="LLA_ANALYZER_NOT_CALLING_ALLOCATOR",
            category=CATEGORY, severity="FAIL", status="FAIL",
            principle=PRINCIPLE,
            message="analyzer.py does not call save_plan / build_plan.",
            expected="analyzer ends with a save_plan() OR build_plan() call",
            observed="no such call detected",
            recommendation="Wire allocator.save_plan(plan) into analyzer's main path.",
            evidence=[Evidence(file=str(rel(analyzer)))],
        ))
    else:
        out.append(Finding(
            id="LLA_ANALYZER_CALLS_ALLOCATOR",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="analyzer.py wires into the allocator.",
        ))

    # 3. allocator emits all the required plan fields
    atext_alloc = read_text(alloc)
    missing = [f for f in REQUIRED_PLAN_FIELDS if f not in atext_alloc]
    if missing:
        out.append(Finding(
            id="LLA_PLAN_FIELDS_INCOMPLETE",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"Allocator plan output missing fields: {', '.join(missing)}.",
            expected="All: " + ", ".join(REQUIRED_PLAN_FIELDS),
            observed="missing: " + ", ".join(missing),
            recommendation="Include every required field in the saved plan JSON.",
            evidence=[Evidence(file=str(rel(alloc)))],
        ))
    else:
        out.append(Finding(
            id="LLA_PLAN_FIELDS_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="Allocator plan covers all required fields.",
        ))

    # 4. plan storage directory referenced
    if "allocations" not in atext_alloc and "allocations/" not in atext_alloc:
        out.append(Finding(
            id="LLA_NO_PLAN_PERSISTENCE",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="Allocator does not write plans to learning-loop/allocations/.",
            recommendation="Persist plans for next-morning consumption.",
        ))

    # 5. execute_orders path exists (not plan-only)
    if "execute_orders" not in atext_alloc and "execute_one" not in atext_alloc \
       and "_execute_one" not in atext_alloc:
        out.append(Finding(
            id="LLA_PLAN_ONLY_MODE",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message="Allocator appears plan-only (no execute_orders function).",
            expected="execute_orders(plan) OR _execute_one(order) implementation",
            observed="no execution function found",
            recommendation="Add execute_orders so morning-allocator can fire orders deterministically.",
            evidence=[Evidence(file=str(rel(alloc)))],
        ))
    else:
        out.append(Finding(
            id="LLA_EXECUTE_ORDERS_PRESENT",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="Allocator has execute_orders / _execute_one path.",
        ))

    # 6. Workflow wiring: daily-learning then morning-allocator
    wf_daily = root / ".github" / "workflows" / "daily-learning.yml"
    wf_morning = root / ".github" / "workflows" / "morning-allocator.yml"
    if wf_daily.exists() and not wf_morning.exists():
        # Check template — may not be deployed yet
        tpl_morning = root / "scripts" / "workflow-templates" / "morning-allocator.yml"
        if tpl_morning.exists():
            out.append(Finding(
                id="LLA_MORNING_WORKFLOW_PENDING_DEPLOY",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="morning-allocator.yml exists only as a template; not deployed to .github/workflows/.",
                recommendation="Run workflow-sync (or paste via UI) to deploy.",
            ))
        else:
            out.append(Finding(
                id="LLA_MORNING_WORKFLOW_MISSING",
                category=CATEGORY, severity="FAIL", status="FAIL",
                principle=PRINCIPLE,
                message="morning-allocator.yml missing — evening plans have no executor.",
                recommendation="Create morning-allocator.yml.",
            ))
    elif wf_morning.exists():
        out.append(Finding(
            id="LLA_MORNING_WORKFLOW_PRESENT",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="morning-allocator.yml deployed.",
        ))

    return out
