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
# v3.29.1 — quality artifact disagrees with itself / with the doc /
# with the latest advisory JSONL. Block unlock until reconciled.
BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH = (
    "BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH")
BROKER_PAPER_CANARY_UNLOCK_READY                           = (
    "BROKER_PAPER_CANARY_UNLOCK_READY")
BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH = (
    "BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH")
# v3.30 — every deterministic gate is green AND a safe enable
# *switch* exists (canary_execution_flag_present=true) BUT only the
# pre-executor (preflight-only) has been shipped — actual order
# placement is still deferred. This status is the v3.30 maximum-
# readiness terminal state; broker-paper trading still does not
# happen.
BROKER_PAPER_CANARY_UNLOCK_READY_PRE_EXECUTOR_ONLY         = (
    "BROKER_PAPER_CANARY_UNLOCK_READY_PRE_EXECUTOR_ONLY")
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
    BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH,
    BROKER_PAPER_CANARY_UNLOCK_READY,
    BROKER_PAPER_CANARY_UNLOCK_READY_BUT_NO_SAFE_ENABLE_SWITCH,
    BROKER_PAPER_CANARY_UNLOCK_READY_PRE_EXECUTOR_ONLY,
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
    """v3.29 shipped only the evaluator; v3.30 flips the flag to true
    once the pre-executor (preflight-only) lands.
    """
    cfg_path = REPO_ROOT / "configs" / "broker_paper_canary.json"
    if not cfg_path.exists():
        return False
    try:
        d = json.loads(cfg_path.read_text(encoding="utf-8"))
        return bool(d.get("canary_execution_flag_present", False))
    except Exception:
        return False


def canary_executor_mode() -> str:
    """v3.30 — return the canary_executor_mode declared in the config.
    Defaults to ``"unknown"`` when missing.
    """
    cfg_path = REPO_ROOT / "configs" / "broker_paper_canary.json"
    if not cfg_path.exists():
        return "unknown"
    try:
        d = json.loads(cfg_path.read_text(encoding="utf-8"))
        return str(d.get("canary_executor_mode", "unknown"))
    except Exception:
        return "unknown"


def canary_order_placement_implemented() -> bool:
    """v3.30 — declared in the config; stays false in v3.30."""
    cfg_path = REPO_ROOT / "configs" / "broker_paper_canary.json"
    if not cfg_path.exists():
        return False
    try:
        d = json.loads(cfg_path.read_text(encoding="utf-8"))
        return bool(d.get("canary_order_placement_implemented", False))
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


def _quality_row_passes_anti_mock(qrep: dict) -> bool:
    """v3.29.1 — extra guards so a status of ACCEPTABLE in the
    artefact cannot count toward the unlock gate unless the
    underlying metrics actually demonstrate real provider use.

    Even if quality_status reads ACCEPTABLE, this function returns
    False when:
    - rows_with_provider_used <= 0 (no row carried PROVIDER_USED),
    - secret_leak_hits > 0,
    - unsafe_phrase_hits > 0,
    - every row had empty risks AND every row had empty next-actions
      AND every row had zero confidence (i.e. the response was
      "schema-shaped but empty").
    """
    if not qrep or not isinstance(qrep, dict):
        return False
    if int(qrep.get("rows_with_provider_used", 0) or 0) <= 0:
        return False
    if int(qrep.get("secret_leak_hits", 0) or 0) > 0:
        return False
    if int(qrep.get("unsafe_phrase_hits", 0) or 0) > 0:
        return False
    rows_seen = int(qrep.get("rows_seen", 0) or 0)
    if rows_seen <= 0:
        return False
    if (int(qrep.get("empty_risks_count", 0) or 0) == rows_seen
            and int(qrep.get("empty_next_actions_count", 0) or 0)
                == rows_seen
            and int(qrep.get("zero_confidence_count", 0) or 0)
                == rows_seen):
        return False
    return True


def _read_quality_history(history_path: Path | None = None
                            ) -> list[dict]:
    """v3.29.1 — read append-only quality history JSONL."""
    p = (history_path or
          (REPO_ROOT / "learning-loop" / "llm_advisory"
           / "quality_history.jsonl"))
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
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


def _quality_source_mismatch_detected() -> tuple[bool, str]:
    """v3.29.1 — verify the quality artefact is internally consistent
    and that the latest history entry matches.

    Returns (mismatch, reason).
    """
    latest = _safe_read_json(
        REPO_ROOT / "learning-loop" / "llm_advisory"
        / "quality_review_latest.json")
    if not latest:
        return False, "no quality_review_latest.json — nothing to "\
                       "mismatch (downstream gates handle absence)"
    status_top  = latest.get("quality_status")
    qrep        = latest.get("quality_report") or {}
    status_rep  = qrep.get("status")
    # Self-consistency: top-level status must equal the embedded
    # report's status.
    if status_top is not None and status_rep is not None and \
            status_top != status_rep:
        return True, (
            f"quality_review_latest mismatch: "
            f"top={status_top} vs report={status_rep}")
    # History must contain the latest run_id (if quality_history.jsonl
    # exists) so a stale "ACCEPTABLE" snapshot left over from a prior
    # run cannot count silently.
    run_id = latest.get("run_id")
    hist = _read_quality_history()
    if hist and run_id and not any(
            h.get("run_id") == run_id for h in hist):
        return True, (
            f"quality_history.jsonl missing run_id={run_id}; "
            f"latest snapshot may be stale")
    return False, "no mismatch"


def _count_acceptable_quality_runs(history_path: Path | None = None
                                     ) -> int:
    """v3.29.1 — count distinct prior quality runs that genuinely
    qualify as ACCEPTABLE.

    Counts entries from
    ``learning-loop/llm_advisory/quality_history.jsonl`` where:
    - ``quality_status == LLM_ADVISORY_QUALITY_ACCEPTABLE``, AND
    - ``accepted_for_unlock_counting == True`` (writer is responsible
      for the anti-mock check at append time).

    Falls back to the latest snapshot only when no history exists,
    applying the anti-mock check inline so a mock or stale snapshot
    cannot bootstrap the counter.
    """
    history = _read_quality_history(history_path)
    if history:
        # Distinct run_ids that explicitly cleared the anti-mock gate.
        seen: set[str] = set()
        for h in history:
            if h.get("quality_status") != (
                    "LLM_ADVISORY_QUALITY_ACCEPTABLE"):
                continue
            if not h.get("accepted_for_unlock_counting", False):
                continue
            rid = h.get("run_id")
            if rid:
                seen.add(rid)
        return len(seen)
    # Fallback: latest-only.
    path = (REPO_ROOT / "learning-loop" / "llm_advisory"
             / "quality_review_latest.json")
    d = _safe_read_json(path) or {}
    if d.get("quality_status") != "LLM_ADVISORY_QUALITY_ACCEPTABLE":
        return 0
    qrep = d.get("quality_report") or {}
    if not _quality_row_passes_anti_mock(qrep):
        return 0
    return 1


def append_quality_history(*,
                              run_id: str,
                              quality_status: str,
                              quality_report: dict,
                              selected_provider: str | None,
                              selected_model: str | None,
                              free_only: bool,
                              history_path: Path | None = None,
                              ) -> dict:
    """v3.29.1 — append-only quality history. Idempotent on run_id.

    Returns the appended entry (or the existing one if a duplicate).
    Never raises.
    """
    p = (history_path or
          (REPO_ROOT / "learning-loop" / "llm_advisory"
           / "quality_history.jsonl"))
    existing = _read_quality_history(p)
    for h in existing:
        if h.get("run_id") == run_id:
            return h
    entry = {
        "appended_at_iso":           datetime.now(timezone.utc).isoformat(),
        "run_id":                    run_id,
        "quality_status":            quality_status,
        "rows_seen":                 int(quality_report.get(
            "rows_seen", 0) or 0),
        "rows_with_provider_used":   int(quality_report.get(
            "rows_with_provider_used", 0) or 0),
        "empty_risks_count":         int(quality_report.get(
            "empty_risks_count", 0) or 0),
        "empty_next_actions_count":  int(quality_report.get(
            "empty_next_actions_count", 0) or 0),
        "zero_confidence_count":     int(quality_report.get(
            "zero_confidence_count", 0) or 0),
        "secret_leak_hits":          int(quality_report.get(
            "secret_leak_hits", 0) or 0),
        "unsafe_phrase_hits":        int(quality_report.get(
            "unsafe_phrase_hits", 0) or 0),
        "selected_provider":         selected_provider,
        "selected_model":            selected_model,
        "free_only":                 bool(free_only),
        "accepted_for_unlock_counting": (
            quality_status == "LLM_ADVISORY_QUALITY_ACCEPTABLE"
            and _quality_row_passes_anti_mock(quality_report)),
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


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

    # v3.29.1 — quality-source mismatch detection runs BEFORE the
    # other LLM-quality gates so we never count a self-inconsistent
    # artefact as ACCEPTABLE.
    mismatch, mismatch_reason = _quality_source_mismatch_detected()
    if mismatch:
        rep.status = (
            BROKER_PAPER_CANARY_UNLOCK_BLOCKED_LLM_QUALITY_SOURCE_MISMATCH)
        rep.rationale.append(mismatch_reason)
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
        # v3.30 — pre-executor flags from configs/broker_paper_canary.json.
        "canary_executor_mode":
            canary_executor_mode(),
        "canary_order_placement_implemented":
            canary_order_placement_implemented(),
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
            "no safe canary execution flag exists yet — "
            "operator must open a follow-up PR to introduce it")
        return rep

    # v3.30 — switch is present but only the pre-executor has shipped.
    if (gates["canary_executor_mode"] == "preflight_only"
            or not gates["canary_order_placement_implemented"]):
        rep.status = (
            BROKER_PAPER_CANARY_UNLOCK_READY_PRE_EXECUTOR_ONLY)
        rep.stage = STAGE_2_BROKER_PAPER_CANARY_READY
        rep.rationale.append(
            "all hard gates pass + operator approval present + safe "
            "enable switch present; canary executor is in "
            "preflight-only mode and order placement is NOT "
            "implemented — broker-paper trading still does not "
            "happen in v3.30")
        return rep

    rep.status = BROKER_PAPER_CANARY_UNLOCK_READY
    rep.stage  = STAGE_2_BROKER_PAPER_CANARY_READY
    rep.rationale.append(
        "all hard gates pass + operator approval present + safe "
        "enable switch present + order placement implemented")
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
        "version":          "v3.30",
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
            "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
            "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
            "CANARY_PRE_EXECUTOR_PREFLIGHT_ONLY",
            "NO_ORDER_PLACEMENT_IN_V330",
        ],
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Broker-Paper Canary Unlock Status (v3.30)\n",
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
    "BROKER_PAPER_CANARY_UNLOCK_READY_PRE_EXECUTOR_ONLY",
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
