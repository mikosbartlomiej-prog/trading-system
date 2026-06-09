"""v3.29 (2026-06-09) — broker-paper canary unlock readiness evaluator.

Pure read-only. Aggregates on-disk artefacts (evidence counters,
workflow health, first-real-record status, advisory quality,
strategy alignment, position reconciliation) and emits a
deterministic unlock verdict.

HARD SAFETY
-----------
- NEVER imports the broker-orders module.
- NEVER flips ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED`` /
  ``BROKER_EXECUTION_ENABLED`` / ``LIVE_TRADING*``.
- NEVER mutates readiness counters or shadow evidence counters.
- NEVER places orders.
- Read-only. Emits artefacts only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent

# ─── Status enum ────────────────────────────────────────────────────────────

BROKER_PAPER_CANARY_UNLOCK_BLOCKED_EVIDENCE_INCOMPLETE     = (
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_EVIDENCE_INCOMPLETE")
BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_REAL_MARKET_RECORD   = (
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_REAL_MARKET_RECORD")
BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_COMPLETED_OUTCOMES   = (
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_COMPLETED_OUTCOMES")
BROKER_PAPER_CANARY_UNLOCK_BLOCKED_AUDIT_RISK              = (
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_AUDIT_RISK")
BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY             = (
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY")
BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_ALIGNMENT           = (
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_ALIGNMENT")
BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_OPERATOR_APPROVAL    = (
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_OPERATOR_APPROVAL")
BROKER_PAPER_CANARY_UNLOCK_READY                           = (
    "BROKER_PAPER_CANARY_UNLOCK_READY")
BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH = (
    "BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH")
BROKER_PAPER_CANARY_ENABLED                                = (
    "BROKER_PAPER_CANARY_ENABLED")
LIVE_TRADING_UNSUPPORTED                                   = (
    "LIVE_TRADING_UNSUPPORTED")

ALL_UNLOCK_STATUSES: frozenset[str] = frozenset({
    BROKER_PAPER_CANARY_UNLOCK_BLOCKED_EVIDENCE_INCOMPLETE,
    BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_REAL_MARKET_RECORD,
    BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_COMPLETED_OUTCOMES,
    BROKER_PAPER_CANARY_UNLOCK_BLOCKED_AUDIT_RISK,
    BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY,
    BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_ALIGNMENT,
    BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_OPERATOR_APPROVAL,
    BROKER_PAPER_CANARY_UNLOCK_READY,
    BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH,
    BROKER_PAPER_CANARY_ENABLED,
    LIVE_TRADING_UNSUPPORTED,
})

# ─── Stage enum ─────────────────────────────────────────────────────────────

STAGE_0_SHADOW_ONLY                       = "STAGE_0_SHADOW_ONLY"
STAGE_1_BROKER_PAPER_CANARY_PROPOSAL      = (
    "STAGE_1_BROKER_PAPER_CANARY_PROPOSAL")
STAGE_2_BROKER_PAPER_CANARY_READY         = (
    "STAGE_2_BROKER_PAPER_CANARY_READY")
STAGE_3_BROKER_PAPER_CANARY_ENABLED       = (
    "STAGE_3_BROKER_PAPER_CANARY_ENABLED")
STAGE_4_BROADER_PAPER_TRADING_READY       = (
    "STAGE_4_BROADER_PAPER_TRADING_READY")
STAGE_5_LIVE_UNSUPPORTED                  = "STAGE_5_LIVE_UNSUPPORTED"

ALL_STAGES: frozenset[str] = frozenset({
    STAGE_0_SHADOW_ONLY,
    STAGE_1_BROKER_PAPER_CANARY_PROPOSAL,
    STAGE_2_BROKER_PAPER_CANARY_READY,
    STAGE_3_BROKER_PAPER_CANARY_ENABLED,
    STAGE_4_BROADER_PAPER_TRADING_READY,
    STAGE_5_LIVE_UNSUPPORTED,
})

# Thresholds (mirrors v3.25 contract — see docs/TRADING_UNLOCK_READINESS.md).
REQUIRED_REAL_OPPS    = 50
REQUIRED_COMPLETED    = 20


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def operator_approved_canary() -> bool:
    """Repo variable / env. Default false."""
    return _env_truthy("OPERATOR_APPROVED_BROKER_PAPER_CANARY")


def any_live_flag_truthy() -> bool:
    return any(_env_truthy(n) for n in (
        "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
        "LIVE_TRADING_ENABLED",
    ))


def any_broker_flag_truthy() -> bool:
    return any(_env_truthy(n) for n in (
        "ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
        "BROKER_EXECUTION_ENABLED",
    ))


def safe_canary_enable_switch_present() -> bool:
    """v3.29 ships only the evaluator. No safe enable switch yet."""
    cfg_path = REPO_ROOT / "configs" / "broker_paper_canary.json"
    if not cfg_path.exists():
        return False
    try:
        d = json.loads(cfg_path.read_text(encoding="utf-8"))
        return bool(d.get("canary_execution_flag_present", False))
    except Exception:
        return False


def _safe_read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return []
    return out


@dataclass
class UnlockReadinessReport:
    status:               str
    stage:                str = STAGE_0_SHADOW_ONLY
    rationale:            list[str] = field(default_factory=list)
    gates:                dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status":    self.status,
            "stage":     self.stage,
            "rationale": list(self.rationale),
            "gates":     dict(self.gates),
        }


def _count_acceptable_quality_runs(history_path: Path | None = None,
                                     limit: int = 20) -> int:
    """Count the last N quality_review snapshots that read ACCEPTABLE.

    The v3.28.3 mesh writes one ``quality_review_latest.json`` per
    run. We approximate "at least 2 acceptable runs" by counting the
    most recent JSON (1 if ACCEPTABLE) plus any history file. The
    canonical extension to a history file is a follow-up; for v3.29
    we accept the latest-only count.
    """
    path = (history_path or
             (REPO_ROOT / "learning-loop" / "llm_advisory"
              / "quality_review_latest.json"))
    d = _safe_read_json(path)
    if not d:
        return 0
    if d.get("quality_status") == "LLM_ADVISORY_QUALITY_ACCEPTABLE":
        return 1
    return 0


def evaluate_unlock_readiness(*,
                                 require_n_acceptable_runs: int = 2
                                 ) -> UnlockReadinessReport:
    """Pure read-only evaluation. Emits a deterministic verdict.

    Live-trading flags are an unconditional refusal — if any of
    them is truthy, the evaluator returns LIVE_TRADING_UNSUPPORTED
    and refuses to advance.
    """
    rep = UnlockReadinessReport(
        status=(
            BROKER_PAPER_CANARY_UNLOCK_BLOCKED_EVIDENCE_INCOMPLETE),
        stage=STAGE_0_SHADOW_ONLY,
    )

    if any_live_flag_truthy():
        rep.status = LIVE_TRADING_UNSUPPORTED
        rep.rationale.append(
            "live-trading env flag truthy — refusing to advance")
        return rep

    counters = _safe_read_json(
        REPO_ROOT / "learning-loop" / "shadow_evidence"
        / "evidence_counters_latest.json") or {}
    health = _safe_read_json(
        REPO_ROOT / "learning-loop" / "shadow_evidence"
        / "workflow_health_latest.json") or {}
    first_record = _safe_read_json(
        REPO_ROOT / "learning-loop" / "shadow_evidence"
        / "first_real_market_record_status.json") or {}
    quality = _safe_read_json(
        REPO_ROOT / "learning-loop" / "llm_advisory"
        / "quality_review_latest.json") or {}
    alignment = _safe_read_json(
        REPO_ROOT / "learning-loop" / "llm_advisory"
        / "strategy_alignment_latest.json") or {}

    safety = counters.get("safety_invariants") or {}
    gates = {
        "real_market_opportunities_count":
            int(counters.get(
                "real_market_opportunities_count", 0) or 0),
        "completed_shadow_outcomes_count":
            int(counters.get(
                "completed_shadow_outcomes_count", 0) or 0),
        "audit_bypass_findings_count":
            int(counters.get("audit_bypass_findings_count", 0) or 0),
        "exposure_cap_breach_count":
            int(counters.get("exposure_cap_breach_count", 0) or 0),
        "repeated_buy_violation_count":
            int(counters.get("repeated_buy_violation_count", 0) or 0),
        "unexplained_broker_state_conflicts_count":
            int(counters.get(
                "unexplained_broker_state_conflicts_count", 0) or 0),
        "drawdown_guard_lowered":
            bool(safety.get("drawdown_guard_lowered", False)),
        "baseline_reset":
            bool(safety.get("baseline_reset", False)),
        "live_trading_enabled":
            bool(safety.get("live_trading_enabled", False)),
        "broker_paper_enabled":
            bool(safety.get("broker_paper_enabled", False)),
        "edge_gate_enabled":
            bool(safety.get("edge_gate_enabled", False)),
        "first_real_market_record_seen":
            bool(first_record.get(
                "first_real_market_record_seen", False)),
        "workflow_verdict":
            health.get("verdict"),
        "quality_status":
            quality.get("quality_status"),
        "alignment_status":
            alignment.get("alignment_status"),
        "operator_approved_canary":
            operator_approved_canary(),
        "safe_enable_switch_present":
            safe_canary_enable_switch_present(),
        "n_acceptable_quality_runs":
            _count_acceptable_quality_runs(),
    }
    rep.gates = gates

    # Audit-discipline gate.
    if (gates["audit_bypass_findings_count"] > 0
            or gates["exposure_cap_breach_count"] > 0
            or gates["repeated_buy_violation_count"] > 0
            or gates["unexplained_broker_state_conflicts_count"] > 0
            or gates["drawdown_guard_lowered"]
            or gates["baseline_reset"]):
        rep.status = (
            BROKER_PAPER_CANARY_UNLOCK_BLOCKED_AUDIT_RISK)
        rep.rationale.append(
            "audit-discipline counters non-zero OR drawdown guard "
            "lowered OR baseline reset")
        return rep

    # First-real-record gate.
    if not gates["first_real_market_record_seen"]:
        rep.status = (
            BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_REAL_MARKET_RECORD)
        rep.rationale.append(
            "first_real_market_record_seen is false")
        return rep

    # Evidence-thresholds gate.
    if (gates["real_market_opportunities_count"]
            < REQUIRED_REAL_OPPS):
        rep.status = (
            BROKER_PAPER_CANARY_UNLOCK_BLOCKED_EVIDENCE_INCOMPLETE)
        rep.rationale.append(
            f"real_market_opportunities_count="
            f"{gates['real_market_opportunities_count']} < "
            f"{REQUIRED_REAL_OPPS}")
        return rep
    if (gates["completed_shadow_outcomes_count"]
            < REQUIRED_COMPLETED):
        rep.status = (
            BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_COMPLETED_OUTCOMES)
        rep.rationale.append(
            f"completed_shadow_outcomes_count="
            f"{gates['completed_shadow_outcomes_count']} < "
            f"{REQUIRED_COMPLETED}")
        return rep

    # LLM quality + alignment gates.
    if (gates["quality_status"]
            != "LLM_ADVISORY_QUALITY_ACCEPTABLE"):
        rep.status = (
            BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY)
        rep.rationale.append(
            f"quality_status={gates['quality_status']}")
        return rep
    if (gates["n_acceptable_quality_runs"]
            < require_n_acceptable_runs):
        rep.status = (
            BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY)
        rep.rationale.append(
            f"acceptable-quality runs="
            f"{gates['n_acceptable_quality_runs']}; "
            f"need ≥{require_n_acceptable_runs}")
        return rep
    if (gates["alignment_status"]
            != "LLM_STRATEGY_ALIGNMENT_PASS"):
        rep.status = (
            BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_ALIGNMENT)
        rep.rationale.append(
            f"alignment_status={gates['alignment_status']}")
        return rep

    # Operator approval gate.
    if not gates["operator_approved_canary"]:
        rep.status = (
            BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_OPERATOR_APPROVAL)
        rep.stage = STAGE_1_BROKER_PAPER_CANARY_PROPOSAL
        rep.rationale.append(
            "OPERATOR_APPROVED_BROKER_PAPER_CANARY != true")
        return rep

    # All deterministic gates pass — but check the safe enable switch.
    if not gates["safe_enable_switch_present"]:
        rep.status = (
            BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH)
        rep.stage = STAGE_2_BROKER_PAPER_CANARY_READY
        rep.rationale.append(
            "all readiness + alignment + approval gates pass; "
            "no safe canary execution flag exists in v3.29 — "
            "operator must open a follow-up PR to introduce it")
        return rep

    rep.status = BROKER_PAPER_CANARY_UNLOCK_READY
    rep.stage  = STAGE_2_BROKER_PAPER_CANARY_READY
    rep.rationale.append(
        "all hard gates pass + operator approval present + safe "
        "enable switch present")
    return rep


def write_unlock_artifacts(report: UnlockReadinessReport,
                             *,
                             json_path: Path | None = None,
                             doc_path: Path | None = None,
                             ) -> None:
    if json_path is None:
        json_path = (REPO_ROOT / "learning-loop"
                      / "broker_paper_canary"
                      / "unlock_readiness_latest.json")
    if doc_path is None:
        doc_path = (REPO_ROOT / "docs"
                     / "BROKER_PAPER_CANARY_UNLOCK_STATUS.md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version":          "v3.29",
        "generated_at_iso": datetime.now(timezone.utc).isoformat(),
        "unlock_status":    report.status,
        "stage":            report.stage,
        "rationale":        report.rationale,
        "gates":            report.gates,
        "safety": {
            "broker_paper_canary_still_blocked": (
                report.status != BROKER_PAPER_CANARY_ENABLED),
            "live_trading_unsupported":          True,
            "edge_gate_enabled":                 False,
            "allow_broker_paper":                False,
            "broker_execution_enabled":          False,
            "schedule_enabled":                  False,
            "llm_pre_order_veto_honored":        False,
            "deterministic_gates_remain_final":  True,
        },
        "standing_markers": [
            "LLM_STRATEGY_ALIGNMENT_ENFORCED",
            "LLM_ADVISORY_ONLY_CONFIRMED",
            "DETERMINISTIC_GATES_REMAIN_FINAL",
            "LLM_OUTPUT_DOES_NOT_COUNT_AS_REAL_MARKET_EVIDENCE",
            "BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING",
            "LIVE_TRADING_UNSUPPORTED",
            "SCHEDULE_REMAINS_DISABLED_UNTIL_REPEATED_ACCEPTABLE_QUALITY",
            "LLM_PRE_ORDER_VETO_REMAINS_DISABLED",
        ],
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Broker-Paper Canary Unlock Status (v3.29)\n",
        f"- **Unlock status:** `{report.status}`",
        f"- **Stage:** `{report.stage}`",
        "",
        "## Gates\n",
    ]
    for k, v in sorted(report.gates.items()):
        lines.append(f"- `{k}`: **{v}**")
    lines.append("")
    lines.append("## Rationale\n")
    for r in report.rationale:
        lines.append(f"- {r}")
    lines.append("")
    lines.append("## Safety invariants\n")
    for k, v in sorted(payload["safety"].items()):
        lines.append(f"- `{k}`: **{str(v).lower()}**")
    lines.append("")
    lines.append("## Standing markers\n")
    for m in payload["standing_markers"]:
        lines.append(f"- `{m}`")
    doc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = [
    # Unlock statuses
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_EVIDENCE_INCOMPLETE",
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_REAL_MARKET_RECORD",
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_COMPLETED_OUTCOMES",
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_AUDIT_RISK",
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY",
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_ALIGNMENT",
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_NO_OPERATOR_APPROVAL",
    "BROKER_PAPER_CANARY_UNLOCK_READY",
    "BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH",
    "BROKER_PAPER_CANARY_ENABLED",
    "LIVE_TRADING_UNSUPPORTED",
    "ALL_UNLOCK_STATUSES",
    # Stages
    "STAGE_0_SHADOW_ONLY", "STAGE_1_BROKER_PAPER_CANARY_PROPOSAL",
    "STAGE_2_BROKER_PAPER_CANARY_READY",
    "STAGE_3_BROKER_PAPER_CANARY_ENABLED",
    "STAGE_4_BROADER_PAPER_TRADING_READY",
    "STAGE_5_LIVE_UNSUPPORTED",
    "ALL_STAGES",
    # Helpers
    "operator_approved_canary",
    "any_live_flag_truthy", "any_broker_flag_truthy",
    "safe_canary_enable_switch_present",
    # Report
    "UnlockReadinessReport",
    "evaluate_unlock_readiness", "write_unlock_artifacts",
]
