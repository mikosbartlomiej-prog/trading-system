#!/usr/bin/env python3
"""v3.29 (2026-06-09) — broker-paper canary unlock orchestrator.

Default mode is ``--evaluate-only`` — read-only verdict + artefacts.

``--apply-enable`` exists for completeness but in v3.29 it can ONLY
emit ``BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH``
because the safe canary execution flag is not present yet. A separate
audited PR is required.

HARD SAFETY
-----------
- NEVER imports the broker-orders module.
- NEVER flips ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED`` /
  ``BROKER_EXECUTION_ENABLED`` / ``LIVE_TRADING*``.
- NEVER mutates readiness counters or shadow evidence counters.
- NEVER places orders.
- Refuses (exit 1) if any of the 7 broker-execution env flags is
  truthy.
- ``--apply-enable`` further refuses unless:
    * all readiness gates pass,
    * ``OPERATOR_APPROVED_BROKER_PAPER_CANARY=true``,
    * current branch is main,
    * no live flags truthy,
    * a safe enable switch is present (v3.29: NOT present —
      always emits READY_BUT_NO_SAFE_ENABLE_SWITCH).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def _refuse_if_broker_enabled() -> str | None:
    for name in (
        "ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
        "BROKER_EXECUTION_ENABLED",
        "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
        "LIVE_TRADING_ENABLED",
    ):
        if _env_truthy(name):
            return f"REFUSED_{name}_IS_TRUTHY"
    return None


def _current_branch() -> str:
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False)
        return (cp.stdout or "").strip()
    except Exception:
        return ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Broker-paper canary unlock orchestrator (v3.29).")
    parser.add_argument("--evaluate-only", action="store_true",
                          default=True,
                          help="Default: read-only verdict.")
    parser.add_argument("--propose-enable", action="store_true",
                          help="Emit proposal artefact (no flag flip).")
    parser.add_argument("--apply-enable", action="store_true",
                          help="Refuses unless all hard gates pass "
                                "AND a safe enable switch is present "
                                "(v3.29: never present).")
    parser.add_argument("--require-n-acceptable-runs", type=int,
                          default=2)
    args = parser.parse_args(argv)

    refuse = _refuse_if_broker_enabled()
    if refuse is not None:
        print(json.dumps({"status": refuse}))
        return 1

    import broker_paper_canary_unlock as bp  # type: ignore
    report = bp.evaluate_unlock_readiness(
        require_n_acceptable_runs=args.require_n_acceptable_runs)
    bp.write_unlock_artifacts(report)

    # --apply-enable refusal chain.
    apply_refused_reason = None
    if args.apply_enable:
        if report.status != bp.BROKER_PAPER_CANARY_UNLOCK_READY:
            apply_refused_reason = (
                f"apply-enable refused: report.status="
                f"{report.status}")
        elif not bp.operator_approved_canary():
            apply_refused_reason = (
                "apply-enable refused: "
                "OPERATOR_APPROVED_BROKER_PAPER_CANARY != true")
        elif _current_branch() != "main":
            apply_refused_reason = (
                f"apply-enable refused: branch="
                f"{_current_branch()!r}; require 'main'")
        elif bp.any_live_flag_truthy():
            apply_refused_reason = (
                "apply-enable refused: live flag truthy")
        elif not bp.safe_canary_enable_switch_present():
            apply_refused_reason = (
                "apply-enable refused: no safe canary execution "
                "flag present in v3.29 — open a follow-up PR")
        # Even if every gate passes, this script NEVER flips a
        # broker flag in v3.29.

    out = {
        "version":          "v3.29",
        "unlock_status":    report.status,
        "stage":            report.stage,
        "operator_approved": bp.operator_approved_canary(),
        "live_flag_truthy": bp.any_live_flag_truthy(),
        "broker_flag_truthy": bp.any_broker_flag_truthy(),
        "safe_enable_switch_present":
            bp.safe_canary_enable_switch_present(),
        "applied":          False,
        "apply_refused_reason": apply_refused_reason,
        "standing_markers": [
            "LLM_STRATEGY_ALIGNMENT_ENFORCED",
            "LLM_ADVISORY_ONLY_CONFIRMED",
            "DETERMINISTIC_GATES_REMAIN_FINAL",
            "LLM_OUTPUT_DOES_NOT_COUNT_AS_REAL_MARKET_EVIDENCE",
            "BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING",
            "LIVE_TRADING_UNSUPPORTED",
        ],
    }
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
