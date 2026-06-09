#!/usr/bin/env python3
"""v3.30.1 (2026-06-09) — self-gated LLM quality calibration precheck.

Decides whether the calibration workflow should consume a Gemini call
this tick. Exit codes are intentionally 0 in all branches — this is a
status reporter, not a workflow gate by itself.

v3.30.1 contract change
-----------------------
The precheck no longer requires a manually-set
``LLM_QUALITY_CALIBRATION_ENABLED`` repo variable. The workflow is now
self-gated by the following deterministic rules (priority order):

  1. broker-flag truthy            → CALIBRATION_SKIPPED_BROKER_FLAG_TRUTHY
  2. LLM_AGENTS_SCHEDULED truthy   → CALIBRATION_SKIPPED_PRODUCTION_SCHEDULE_ENABLED
  3. LLM_QUALITY_CALIBRATION_DISABLED truthy
                                    → CALIBRATION_SKIPPED_DISABLED_BY_OPERATOR
  4. LLM_PROVIDER != gemini OR LLM_FREE_ONLY != true
                                    → CALIBRATION_SKIPPED_NON_FREE_PROVIDER
  5. GEMINI_API_KEY empty          → CALIBRATION_SKIPPED_NO_GEMINI_KEY
  6. accepted_quality_runs >= 2    → CALIBRATION_SKIPPED_ALREADY_CALIBRATED
  7. budget exhausted              → CALIBRATION_SKIPPED_BUDGET_EXHAUSTED
  8. else                          → CALIBRATION_PROCEEDING

HARD SAFETY
-----------
- NEVER imports the broker-orders module.
- NEVER calls submit_order / place_order / safe_close.
- NEVER mutates readiness counters / shadow evidence counters.
- NEVER places orders.
- NEVER reveals the value of GEMINI_API_KEY (only whether it is set).
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

# ─── Status enum (v3.30.1: 8 statuses) ──────────────────────────────────────

CALIBRATION_PROCEEDING                                = (
    "CALIBRATION_PROCEEDING")
CALIBRATION_SKIPPED_ALREADY_CALIBRATED                = (
    "CALIBRATION_SKIPPED_ALREADY_CALIBRATED")
CALIBRATION_SKIPPED_DISABLED_BY_OPERATOR              = (
    "CALIBRATION_SKIPPED_DISABLED_BY_OPERATOR")
CALIBRATION_SKIPPED_BUDGET_EXHAUSTED                  = (
    "CALIBRATION_SKIPPED_BUDGET_EXHAUSTED")
CALIBRATION_SKIPPED_NO_GEMINI_KEY                     = (
    "CALIBRATION_SKIPPED_NO_GEMINI_KEY")
CALIBRATION_SKIPPED_NON_FREE_PROVIDER                 = (
    "CALIBRATION_SKIPPED_NON_FREE_PROVIDER")
CALIBRATION_SKIPPED_PRODUCTION_SCHEDULE_ENABLED       = (
    "CALIBRATION_SKIPPED_PRODUCTION_SCHEDULE_ENABLED")
CALIBRATION_SKIPPED_BROKER_FLAG_TRUTHY                = (
    "CALIBRATION_SKIPPED_BROKER_FLAG_TRUTHY")

ALL_PRECHECK_STATUSES = frozenset({
    CALIBRATION_PROCEEDING,
    CALIBRATION_SKIPPED_ALREADY_CALIBRATED,
    CALIBRATION_SKIPPED_DISABLED_BY_OPERATOR,
    CALIBRATION_SKIPPED_BUDGET_EXHAUSTED,
    CALIBRATION_SKIPPED_NO_GEMINI_KEY,
    CALIBRATION_SKIPPED_NON_FREE_PROVIDER,
    CALIBRATION_SKIPPED_PRODUCTION_SCHEDULE_ENABLED,
    CALIBRATION_SKIPPED_BROKER_FLAG_TRUTHY,
})

_STANDING_MARKERS = [
    "NO_MANUAL_REPO_VARIABLE_REQUIRED_FOR_CALIBRATION",
    "STALE_MOCK_QUALITY_NEVER_COUNTS_AS_ACCEPTABLE",
    "CALIBRATION_BOUNDED_FREE_ONLY_GEMINI",
    "PRODUCTION_LLM_SCHEDULE_REMAINS_DISABLED",
    "LLM_PRE_ORDER_VETO_REMAINS_DISABLED",
    "CANARY_PRE_EXECUTOR_PREFLIGHT_ONLY",
    "NO_ORDER_PLACEMENT",
    "BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING",
    "LIVE_TRADING_UNSUPPORTED",
    "DETERMINISTIC_GATES_REMAIN_FINAL",
]

# ─── Helpers ────────────────────────────────────────────────────────────────


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def _broker_flags_safe() -> bool:
    """True iff none of the 7 broker-execution / live env flags is
    truthy.
    """
    for name in (
        "ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
        "BROKER_EXECUTION_ENABLED",
        "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
        "LIVE_TRADING_ENABLED",
    ):
        if _env_truthy(name):
            return False
    return True


def _gemini_key_present() -> bool:
    v = os.environ.get("GEMINI_API_KEY", "").strip()
    return bool(v)


def _count_accepted_quality_runs() -> int:
    """Delegate to the broker-paper canary unlock module so the
    counting rule (history + accepted_for_unlock_counting flag) is the
    single source of truth.
    """
    try:
        try:
            import broker_paper_canary_unlock as _bp  # type: ignore
        except ImportError:
            from shared import broker_paper_canary_unlock as _bp  # type: ignore
        return _bp._count_acceptable_quality_runs()
    except Exception:
        return 0


def _latest_quality_snapshot() -> tuple[str | None, str | None]:
    """Returns (quality_status_top, latest_run_id)."""
    p = (REPO_ROOT / "learning-loop" / "llm_advisory"
          / "quality_review_latest.json")
    if not p.exists():
        return None, None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None, None
    return d.get("quality_status"), d.get("run_id")


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


def _decide_status() -> tuple[str, str]:
    """Returns (status, next_action)."""
    if not _broker_flags_safe():
        return (
            CALIBRATION_SKIPPED_BROKER_FLAG_TRUTHY,
            "One of the 7 broker-execution / live env flags is "
            "truthy. Calibration refuses to consume a Gemini call.",
        )
    if _env_truthy("LLM_AGENTS_SCHEDULED"):
        return (
            CALIBRATION_SKIPPED_PRODUCTION_SCHEDULE_ENABLED,
            "Production LLM schedule is enabled "
            "(LLM_AGENTS_SCHEDULED=true). Calibration skipped to "
            "preserve daily budget.",
        )
    if _env_truthy("LLM_QUALITY_CALIBRATION_DISABLED"):
        return (
            CALIBRATION_SKIPPED_DISABLED_BY_OPERATOR,
            "Operator opted out via "
            "LLM_QUALITY_CALIBRATION_DISABLED=true.",
        )
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    free_only = os.environ.get(
        "LLM_FREE_ONLY", "").strip().lower() in ("true", "1", "yes",
                                                   "on")
    if provider != "gemini" or not free_only:
        return (
            CALIBRATION_SKIPPED_NON_FREE_PROVIDER,
            f"LLM_PROVIDER={provider!r} or LLM_FREE_ONLY="
            f"{free_only!r}; calibration requires "
            "gemini + free-only.",
        )
    if not _gemini_key_present():
        return (
            CALIBRATION_SKIPPED_NO_GEMINI_KEY,
            "GEMINI_API_KEY is empty / unset. Calibration cannot "
            "proceed without a Gemini key.",
        )
    accepted = _count_accepted_quality_runs()
    if accepted >= 2:
        return (
            CALIBRATION_SKIPPED_ALREADY_CALIBRATED,
            "Quality history already has >= 2 accepted runs. No "
            "further calibration needed.",
        )
    budget = _budget_status()
    if budget != "LLM_BUDGET_ALLOWED":
        return (
            CALIBRATION_SKIPPED_BUDGET_EXHAUSTED,
            f"Daily LLM budget exhausted or unavailable "
            f"(budget_status={budget}). Next run after daily reset.",
        )
    return (
        CALIBRATION_PROCEEDING,
        "Proceed to Gemini smoke + bounded mesh run with per-run "
        "budget override = 11.",
    )


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
        "# LLM Quality Calibration Status (v3.30.1)\n",
        f"- **Precheck status:** `{payload.get('precheck_status')}`",
        f"- **Should call provider:** "
        f"{str(payload.get('should_call_provider', False)).lower()}",
        f"- **Accepted quality runs:** "
        f"{payload.get('accepted_quality_runs', 0)} / "
        f"{payload.get('target_accepted_quality_runs', 2)}",
        f"- **Budget status:** `{payload.get('budget_status')}`",
        f"- **Provider:** `{payload.get('provider')}`",
        f"- **Free-only:** "
        f"{str(payload.get('free_only', False)).lower()}",
        f"- **Production LLM schedule enabled:** "
        f"{str(payload.get('production_llm_schedule_enabled', False)).lower()}",
        f"- **Broker flags safe:** "
        f"{str(payload.get('broker_flags_safe', False)).lower()}",
        f"- **Gemini key present:** "
        f"{str(payload.get('gemini_key_present', False)).lower()}",
        f"- **Calibration disabled by operator:** "
        f"{str(payload.get('calibration_disabled_by_operator', False)).lower()}",
        f"- **Latest quality status:** "
        f"`{payload.get('latest_quality_status')}`",
        f"- **Latest run_id:** `{payload.get('latest_run_id')}`",
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
        description="LLM quality calibration precheck (v3.30.1).")
    parser.add_argument("--write-artifacts", action="store_true",
                          default=True)
    args = parser.parse_args(argv)

    status, next_action = _decide_status()
    accepted = _count_accepted_quality_runs()
    budget = _budget_status()
    provider = os.environ.get("LLM_PROVIDER", "offline_mock")
    free_only = os.environ.get(
        "LLM_FREE_ONLY", "").strip().lower() in ("true", "1", "yes",
                                                   "on")
    schedule_on = _env_truthy("LLM_AGENTS_SCHEDULED")
    broker_safe = _broker_flags_safe()
    key_present = _gemini_key_present()
    calib_disabled = _env_truthy("LLM_QUALITY_CALIBRATION_DISABLED")
    latest_qs, latest_rid = _latest_quality_snapshot()

    payload = {
        "version":                            "v3.30.1",
        "generated_at_iso":                   datetime.now(
            timezone.utc).isoformat(),
        "precheck_status":                    status,
        "should_call_provider":               (
            status == CALIBRATION_PROCEEDING),
        "accepted_quality_runs":              accepted,
        "target_accepted_quality_runs":       2,
        "budget_status":                      budget,
        "provider":                           provider,
        "free_only":                          free_only,
        "production_llm_schedule_enabled":    schedule_on,
        "broker_flags_safe":                  broker_safe,
        "gemini_key_present":                 key_present,
        "calibration_disabled_by_operator":   calib_disabled,
        "latest_quality_status":              latest_qs,
        "latest_run_id":                      latest_rid,
        "model":                              os.environ.get(
            "GEMINI_MODEL", ""),
        "next_action":                        next_action,
        "broker_paper_canary_still_blocked":  True,
        "live_trading_unsupported":           True,
        "safety": {
            "broker_paper_canary_still_blocked": True,
            "live_trading_unsupported":          True,
            "edge_gate_enabled":                 False,
            "allow_broker_paper":                False,
            "broker_execution_enabled":          False,
            "schedule_enabled":                  False,
            "llm_pre_order_veto_honored":        False,
            "deterministic_gates_remain_final":  True,
            "no_order_placement_in_v3301":       True,
        },
        "standing_markers":                   list(_STANDING_MARKERS),
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
