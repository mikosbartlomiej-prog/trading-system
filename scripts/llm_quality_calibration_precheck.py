#!/usr/bin/env python3
"""v3.30 (2026-06-09) — bounded LLM quality calibration precheck.

Decides whether the calibration workflow should consume a Gemini call
this tick. Exit codes are intentionally 0 in both branches — this is a
status reporter, not a workflow gate by itself.

HARD SAFETY
-----------
- NEVER imports the broker-orders module.
- NEVER mutates readiness counters / shadow evidence counters.
- NEVER places orders.
- NEVER sets the production schedule / LLM_PRE_ORDER_VETO_HONORED /
  OPERATOR_APPROVED_BROKER_PAPER_CANARY / broker flags.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

CALIBRATION_PROCEEDING                 = "CALIBRATION_PROCEEDING"
CALIBRATION_SKIPPED_ALREADY_CALIBRATED = (
    "CALIBRATION_SKIPPED_ALREADY_CALIBRATED")
CALIBRATION_SKIPPED_DISABLED            = (
    "CALIBRATION_SKIPPED_DISABLED")
CALIBRATION_SKIPPED_BUDGET_EXHAUSTED    = (
    "CALIBRATION_SKIPPED_BUDGET_EXHAUSTED")


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


def _count_accepted_quality_runs() -> int:
    try:
        try:
            import broker_paper_canary_unlock as _bp  # type: ignore
        except ImportError:
            from shared import broker_paper_canary_unlock as _bp  # type: ignore
        return _bp._count_acceptable_quality_runs()
    except Exception:
        return 0


def _budget_status() -> str:
    try:
        try:
            import llm_agent_budget as _b  # type: ignore
        except ImportError:
            from shared import llm_agent_budget as _b  # type: ignore
        st, _ = _b.check_budget(run_id="calibration-precheck")
        return st
    except Exception:
        return "UNKNOWN"


def _write_status_artifact(payload: dict) -> None:
    json_path = (REPO_ROOT / "learning-loop" / "llm_advisory"
                  / "calibration_status_latest.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    doc_path = REPO_ROOT / "docs" / "LLM_QUALITY_CALIBRATION_STATUS.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# LLM Quality Calibration Status (v3.30)\n",
        f"- **Precheck status:** `{payload.get('precheck_status')}`",
        f"- **Calibration enabled:** "
        f"{str(payload.get('calibration_enabled', False)).lower()}",
        f"- **Accepted quality runs:** "
        f"{payload.get('accepted_quality_runs', 0)}",
        f"- **Budget status:** `{payload.get('budget_status')}`",
        f"- **Provider:** `{payload.get('provider')}`",
        f"- **Model:** `{payload.get('model')}`",
        f"- **Next action:** {payload.get('next_action', 'n/a')}",
        "",
        "## Safety invariants\n",
    ]
    for k, v in sorted((payload.get("safety") or {}).items()):
        lines.append(f"- `{k}`: **{str(v).lower()}**")
    lines.append("")
    lines.append("## Standing markers\n")
    for m in payload.get("standing_markers") or []:
        lines.append(f"- `{m}`")
    doc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="LLM quality calibration precheck (v3.30).")
    parser.add_argument("--write-artifacts", action="store_true",
                          default=True)
    args = parser.parse_args(argv)

    refuse = _refuse_if_broker_enabled()
    if refuse is not None:
        print(json.dumps({"status": refuse}))
        return 1

    enabled = _env_truthy("LLM_QUALITY_CALIBRATION_ENABLED")
    accepted = _count_accepted_quality_runs()
    budget = _budget_status()
    if not enabled:
        status = CALIBRATION_SKIPPED_DISABLED
        next_action = ("Set LLM_QUALITY_CALIBRATION_ENABLED=true "
                         "(repo variable) to opt in.")
    elif accepted >= 2:
        status = CALIBRATION_SKIPPED_ALREADY_CALIBRATED
        next_action = ("Quality history already has ≥2 accepted "
                         "runs. No further calibration needed.")
    elif budget != "LLM_BUDGET_ALLOWED":
        status = CALIBRATION_SKIPPED_BUDGET_EXHAUSTED
        next_action = ("Daily LLM budget exhausted or unavailable. "
                         "Next run after daily reset.")
    else:
        status = CALIBRATION_PROCEEDING
        next_action = ("Proceed to Gemini smoke + bounded mesh run "
                         "with per-run budget override = 11.")

    payload = {
        "version":                "v3.30",
        "generated_at_iso":       datetime.now(timezone.utc).isoformat(),
        "precheck_status":        status,
        "calibration_enabled":    enabled,
        "accepted_quality_runs":  accepted,
        "budget_status":          budget,
        "provider":               os.environ.get(
            "LLM_PROVIDER", "offline_mock"),
        "model":                  os.environ.get(
            "GEMINI_MODEL", ""),
        "latest_quality_status":  None,
        "latest_run_id":          None,
        "next_action":            next_action,
        "schedule_production_enabled":      False,
        "llm_pre_order_veto_honored":       False,
        "broker_paper_canary_still_blocked": True,
        "live_trading_unsupported":          True,
        "safety": {
            "broker_paper_canary_still_blocked": True,
            "live_trading_unsupported":          True,
            "edge_gate_enabled":                 False,
            "allow_broker_paper":                False,
            "broker_execution_enabled":          False,
            "schedule_enabled":                  False,
            "llm_pre_order_veto_honored":        False,
            "deterministic_gates_remain_final":  True,
        },
        "standing_markers": [
            "LLM_ADVISORY_ONLY_CONFIRMED",
            "CALIBRATION_SCHEDULE_BOUNDED",
            "PRODUCTION_LLM_SCHEDULE_REMAINS_DISABLED",
            "LLM_PRE_ORDER_VETO_REMAINS_DISABLED",
            "BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING",
            "LIVE_TRADING_UNSUPPORTED",
            "DETERMINISTIC_GATES_REMAIN_FINAL",
        ],
    }
    if args.write_artifacts:
        try:
            _write_status_artifact(payload)
        except Exception as e:
            print(f"  [calibration-precheck] artifact failed: {e}")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
