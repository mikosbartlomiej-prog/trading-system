"""Spec §6 (auto-execution) + §17 (LLM not on execution path).

  - No forbidden "approval needed" wording in trading lifecycle code.
  - LLM never bypasses risk gates (LLM_EXECUTION_INFLUENCE_ENABLED default off).
  - Deterministic state names used (PAUSE_STRATEGY, BLOCK_NEW_ENTRIES,
    FULL_STOP_ARMED, DEFEND_DAY, RED_DAY_AFTER_GREEN, RESUME_STRATEGY).
  - Allocator can auto-execute (not plan-only) in aggressive paper mode.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import Evidence, Finding
from ..utils import grep_pattern, read_text, rel, walk_files


CATEGORY  = "autonomy_and_determinism"
PRINCIPLE = "DETERMINISTIC_AUTONOMOUS_TRADING"


# Forbidden wording — case insensitive (spec §6).
FORBIDDEN_PATTERNS = (
    re.compile(r"manual\s+approval", re.I),
    re.compile(r"manual\s+confirm(?:ation)?", re.I),
    re.compile(r"waiting\s+for\s+human", re.I),
    re.compile(r"approval\s+needed", re.I),
    re.compile(r"please\s+approve", re.I),
    re.compile(r"operator\s+decides", re.I),
    re.compile(r"manual\s+review\s+required", re.I),
    re.compile(r"pending\s+user\s+approval", re.I),
)

# Files where forbidden wording is OK (docs explaining why, audit agent
# code that scans for it, this agent itself).
EXEMPT_FOR_FORBIDDEN = (
    "docs/",
    "CLAUDE.md",
    "tests/",
    "tools/strategy_coherence_agent/",
    "tools/system_consistency_agent/",
    "scripts/strategy_coherence_agent.py",
    "scripts/system_consistency_agent.py",
    "shared/autonomy.py",
    "learning-loop/patch_validator.py",
    "learning-loop/routine-prompts.md",
    "learning-loop/challenger-prompts.md",
)

# Trading-lifecycle code paths where forbidden wording is most damaging.
LIFECYCLE_GLOB = (
    "shared/alpaca_orders.py",
    "shared/risk_officer.py",
    "shared/risk_guards.py",
    "shared/portfolio_risk.py",
    "shared/intraday_governor.py",
    "shared/allocator.py",
    "shared/remediation.py",
    "shared/emergency_engine.py",
    "exit-monitor/monitor.py",
    "options-exit-monitor/monitor.py",
    "price-monitor/monitor.py",
    "options-monitor/monitor.py",
    "crypto-monitor/monitor.py",
)


DETERMINISTIC_STATE_NAMES = (
    "PAUSE_STRATEGY", "BLOCK_NEW_ENTRIES", "FULL_STOP_ARMED",
    "DEFEND_DAY", "RED_DAY_AFTER_GREEN", "RESUME_STRATEGY",
)


def _is_exempt(path: Path) -> bool:
    rp = str(rel(path))
    return any(rp.startswith(p) or rp == p.rstrip("/") for p in EXEMPT_FOR_FORBIDDEN)


def run(root: Path) -> list[Finding]:
    out: list[Finding] = []

    # 1. Forbidden wording in lifecycle code
    lifecycle_paths = [root / r for r in LIFECYCLE_GLOB if (root / r).exists()]
    hits_all: list = []
    for pattern in FORBIDDEN_PATTERNS:
        hits = grep_pattern(pattern, lifecycle_paths, max_per_file=3)
        hits_all.extend(hits)
    # Deduplicate
    seen = set()
    deduped = []
    for h in hits_all:
        key = (h.file, h.line, h.snippet)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(h)

    if deduped:
        out.append(Finding(
            id="AAD_FORBIDDEN_WORDING_IN_LIFECYCLE",
            category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
            principle=PRINCIPLE,
            message=f"Found {len(deduped)} occurrence(s) of forbidden "
                    f"approval-needed wording in trading-lifecycle files.",
            expected="No 'manual approval' / 'waiting for human' / 'please "
                     "approve' wording in trading code paths.",
            observed=f"{len(deduped)} hits",
            recommendation="Replace with deterministic states "
                           "(PAUSE_STRATEGY / BLOCK_NEW_ENTRIES / DEFEND_DAY).",
            evidence=deduped[:8],
        ))
    else:
        out.append(Finding(
            id="AAD_NO_FORBIDDEN_WORDING",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message="No forbidden approval wording in trading-lifecycle code.",
        ))

    # 2. Forbidden wording in any non-exempt file (broader scan)
    code_paths = [p for p in walk_files(root, include_globs=("*.py", "*.yml"))
                  if not _is_exempt(p)]
    broader_hits = []
    for pattern in FORBIDDEN_PATTERNS:
        broader_hits.extend(grep_pattern(pattern, code_paths, max_per_file=1))
    # Filter out lifecycle hits (already reported)
    lifecycle_files = {str(rel(p)) for p in lifecycle_paths}
    broader_hits = [h for h in broader_hits if h.file not in lifecycle_files]
    if broader_hits:
        out.append(Finding(
            id="AAD_FORBIDDEN_WORDING_IN_NON_LIFECYCLE",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"Forbidden wording in non-lifecycle code: {len(broader_hits)} hits.",
            recommendation="If the hit is in a doc or audit script, move it under "
                           "docs/ or add the file to the exempt list.",
            evidence=broader_hits[:6],
        ))

    # 3. Deterministic state names declared
    found_states = 0
    state_holders = (root / "shared" / "autonomy.py",
                     root / "shared" / "intraday_governor.py",
                     root / "shared" / "remediation.py")
    for sp in state_holders:
        if sp.exists():
            text = read_text(sp)
            found_states += sum(1 for n in DETERMINISTIC_STATE_NAMES if n in text)
    if found_states < 4:
        out.append(Finding(
            id="AAD_DETERMINISTIC_STATE_NAMES_FEW",
            category=CATEGORY, severity="WARN", status="WARN",
            principle=PRINCIPLE,
            message=f"Only {found_states} deterministic state names found.",
            expected="Most of " + ", ".join(DETERMINISTIC_STATE_NAMES),
            observed=f"{found_states} found",
            recommendation="Declare every deterministic state name as a constant.",
        ))
    else:
        out.append(Finding(
            id="AAD_DETERMINISTIC_STATE_NAMES_OK",
            category=CATEGORY, severity="PASS", status="PASS",
            principle=PRINCIPLE,
            message=f"{found_states} deterministic state names declared.",
        ))

    # 4. LLM influence flag off by default
    rc = root / "shared" / "runtime_config.py"
    if rc.exists():
        rct = read_text(rc)
        if "llm_execution_influence_enabled" not in rct:
            out.append(Finding(
                id="AAD_LLM_INFLUENCE_FLAG_MISSING",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="runtime_config.llm_execution_influence_enabled() not declared.",
                recommendation="Add the flag (default False) so tests can prove "
                               "execution is LLM-independent.",
                evidence=[Evidence(file=str(rel(rc)))],
            ))
        else:
            # Default must be False
            m = re.search(
                r'def\s+llm_execution_influence_enabled[^\n]*\n[^\n]*_bool\([^,]+,\s*(True|False)',
                rct, re.S,
            )
            if m and m.group(1) == "True":
                out.append(Finding(
                    id="AAD_LLM_INFLUENCE_DEFAULT_TRUE",
                    category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
                    principle=PRINCIPLE,
                    message="llm_execution_influence_enabled defaults to True.",
                    expected="default False",
                    observed="True",
                    recommendation="Flip the default to False. LLM may rank, never execute.",
                    evidence=[Evidence(file=str(rel(rc)))],
                ))
            else:
                out.append(Finding(
                    id="AAD_LLM_INFLUENCE_DEFAULT_OK",
                    category=CATEGORY, severity="PASS", status="PASS",
                    principle=PRINCIPLE,
                    message="llm_execution_influence_enabled defaults to False.",
                ))

    # 5. assert_paper_only available — boundary invariant
    ap = root / "shared" / "autonomy.py"
    if ap.exists():
        if "assert_paper_only" not in read_text(ap):
            out.append(Finding(
                id="AAD_PAPER_ONLY_GUARD_MISSING",
                category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
                principle=PRINCIPLE,
                message="shared/autonomy.py missing assert_paper_only.",
                recommendation="Add the invariant function.",
            ))

    # 6. Allocator can auto-execute orders (not plan-only)
    alloc = root / "shared" / "allocator.py"
    if alloc.exists():
        at = read_text(alloc)
        # auto_execute_rebalance flag often gates this
        if "auto_execute" not in at and "execute_orders" not in at:
            out.append(Finding(
                id="AAD_ALLOCATOR_PLAN_ONLY",
                category=CATEGORY, severity="WARN", status="WARN",
                principle=PRINCIPLE,
                message="Allocator has no auto-execute path.",
                recommendation="Add execute_orders + auto_execute_rebalance flag.",
                evidence=[Evidence(file=str(rel(alloc)))],
            ))

    # 7. LLM is NOT on the execution path. shared/alpaca_orders.py must not
    # import any LLM client. The LLM may rank candidates in the learning-
    # loop but never directly place orders. This is the principle (spec §17)
    # that lets us claim "deterministic execution" — without it the audit
    # chain becomes 'LLM said so'.
    ao = root / "shared" / "alpaca_orders.py"
    if ao.exists():
        aot = read_text(ao)
        llm_imports = (
            "from llm_client",
            "from anthropic",
            "import anthropic",
            "from openai",
            "import openai",
            "from learning_loop.llm_client",
            "call_routine(",
            "call_llm(",
        )
        leaked = [s for s in llm_imports if s in aot]
        if leaked:
            out.append(Finding(
                id="AAD_LLM_ON_EXECUTION_PATH",
                category=CATEGORY, severity="FAIL", status="FAIL", blocking=True,
                principle=PRINCIPLE,
                message=f"shared/alpaca_orders.py references LLM client(s): {leaked}.",
                expected="Execution path free of any LLM import / call",
                observed=f"found: {', '.join(leaked)}",
                recommendation="Remove every LLM import from the execution path. "
                               "LLM lives in learning-loop only.",
                evidence=[Evidence(file=str(rel(ao)))],
            ))
        else:
            out.append(Finding(
                id="AAD_LLM_NOT_ON_EXECUTION_PATH",
                category=CATEGORY, severity="PASS", status="PASS",
                principle=PRINCIPLE,
                message="shared/alpaca_orders.py free of LLM imports.",
            ))

    return out
