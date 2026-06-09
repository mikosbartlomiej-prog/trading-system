"""v3.29.1 (2026-06-09) — real-market evidence acceleration analyzer.

Reads the shadow-evidence artefacts and recommends SAFE actions to
increase real-market shadow opportunity collection — without broker
execution, without fake evidence, and without counting LLM output as
real-market data.

HARD SAFETY
-----------
- NEVER imports the broker-orders module.
- NEVER mutates readiness counters or shadow evidence counters.
- NEVER places orders.
- NEVER fabricates records or P&L.
- Read-only. Emits recommendation artefacts only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# ─── Status / recommendation enum ───────────────────────────────────────────

REAL_MARKET_EVIDENCE_HEALTHY                      = (
    "REAL_MARKET_EVIDENCE_HEALTHY")
REAL_MARKET_EVIDENCE_BLOCKED_NO_BARS              = (
    "REAL_MARKET_EVIDENCE_BLOCKED_NO_BARS")
REAL_MARKET_EVIDENCE_BLOCKED_INSUFFICIENT_BARS    = (
    "REAL_MARKET_EVIDENCE_BLOCKED_INSUFFICIENT_BARS")
REAL_MARKET_EVIDENCE_BLOCKED_AUTH_FAILED          = (
    "REAL_MARKET_EVIDENCE_BLOCKED_AUTH_FAILED")
REAL_MARKET_EVIDENCE_BLOCKED_PROVIDER_ERROR       = (
    "REAL_MARKET_EVIDENCE_BLOCKED_PROVIDER_ERROR")
REAL_MARKET_EVIDENCE_BLOCKED_GENERATOR_RESTRICTIVE = (
    "REAL_MARKET_EVIDENCE_BLOCKED_GENERATOR_RESTRICTIVE")
REAL_MARKET_EVIDENCE_BLOCKED_OUTSIDE_SESSION      = (
    "REAL_MARKET_EVIDENCE_BLOCKED_OUTSIDE_SESSION")
REAL_MARKET_EVIDENCE_BLOCKED_INSUFFICIENT_RUNS    = (
    "REAL_MARKET_EVIDENCE_BLOCKED_INSUFFICIENT_RUNS")
REAL_MARKET_EVIDENCE_ACCELERATION_READY           = (
    "REAL_MARKET_EVIDENCE_ACCELERATION_READY")

ALL_ACCEL_STATUSES: frozenset[str] = frozenset({
    REAL_MARKET_EVIDENCE_HEALTHY,
    REAL_MARKET_EVIDENCE_BLOCKED_NO_BARS,
    REAL_MARKET_EVIDENCE_BLOCKED_INSUFFICIENT_BARS,
    REAL_MARKET_EVIDENCE_BLOCKED_AUTH_FAILED,
    REAL_MARKET_EVIDENCE_BLOCKED_PROVIDER_ERROR,
    REAL_MARKET_EVIDENCE_BLOCKED_GENERATOR_RESTRICTIVE,
    REAL_MARKET_EVIDENCE_BLOCKED_OUTSIDE_SESSION,
    REAL_MARKET_EVIDENCE_BLOCKED_INSUFFICIENT_RUNS,
    REAL_MARKET_EVIDENCE_ACCELERATION_READY,
})

# ─── Allowed / forbidden action enums (operator-visible) ────────────────────

# These are RECOMMENDATIONS the analyzer may produce — not changes it
# applies. The evaluator script writes them to an artefact for the
# operator to review.
ALLOWED_ACTIONS: tuple[str, ...] = (
    "EXPAND_READ_ONLY_SYMBOL_UNIVERSE",
    "EXPAND_LOOKBACK_KEEPING_22_BAR_FLOOR",
    "ADD_DETERMINISTIC_SHADOW_STRATEGY_CANDIDATES",
    "ADD_NO_TRADE_OBSERVATION_RECORDS_IF_SCHEMA_SAFE",
    "IMPROVE_DIAGNOSTICS",
    "INCREASE_WORKFLOW_VISIBILITY",
    "INCREASE_CRON_EVALUATION_WINDOWS",
    "ADD_MARKET_SESSIONS_READ_ONLY_ONLY",
)

FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "LOWER_SAFETY_THRESHOLDS_TO_CREATE_FAKE_SIGNALS",
    "COUNT_NO_SIGNAL_AS_OPPORTUNITY",
    "COUNT_SCAFFOLD_OR_HALT_AS_REAL_MARKET",
    "MUTATE_READINESS_COUNTERS",
    "USE_LLM_OUTPUT_AS_EVIDENCE",
    "PLACE_BROKER_ORDERS",
    "ENABLE_BROKER_PAPER",
)


def _safe_read_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl(p: Path) -> list[dict]:
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


@dataclass
class AccelerationReport:
    status:                       str
    rationale:                    list[str] = field(default_factory=list)
    counters_snapshot:            dict = field(default_factory=dict)
    dominant_diagnostic_token:    str | None = None
    successful_runs_observed:     int = 0
    recommended_actions:          list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status":                    self.status,
            "rationale":                 list(self.rationale),
            "counters_snapshot":         dict(self.counters_snapshot),
            "dominant_diagnostic_token": self.dominant_diagnostic_token,
            "successful_runs_observed":  self.successful_runs_observed,
            "recommended_actions":       list(self.recommended_actions),
        }


def evaluate_acceleration() -> AccelerationReport:
    """Pure read-only analysis of the shadow-evidence artefacts.

    Precedence:
    1. Insufficient successful runs → BLOCKED_INSUFFICIENT_RUNS.
    2. AUTH_FAILED dominates → BLOCKED_AUTH_FAILED.
    3. PROVIDER_ERROR dominates → BLOCKED_PROVIDER_ERROR.
    4. INSUFFICIENT_BARS dominates → BLOCKED_INSUFFICIENT_BARS.
    5. MARKET_CLOSED dominates → BLOCKED_OUTSIDE_SESSION.
    6. REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL dominates →
       BLOCKED_GENERATOR_RESTRICTIVE.
    7. Otherwise → HEALTHY.
    """
    rep = AccelerationReport(status=REAL_MARKET_EVIDENCE_HEALTHY)

    counters = _safe_read_json(
        REPO_ROOT / "learning-loop" / "shadow_evidence"
        / "evidence_counters_latest.json") or {}
    first_record = _safe_read_json(
        REPO_ROOT / "learning-loop" / "shadow_evidence"
        / "first_real_market_record_status.json") or {}
    health_latest = _safe_read_json(
        REPO_ROOT / "learning-loop" / "shadow_evidence"
        / "workflow_health_latest.json") or {}
    history = _read_jsonl(
        REPO_ROOT / "learning-loop" / "shadow_evidence"
        / "workflow_health_history.jsonl")

    rep.counters_snapshot = {
        "real_market_opportunities_count":
            int(counters.get(
                "real_market_opportunities_count", 0) or 0),
        "completed_shadow_outcomes_count":
            int(counters.get(
                "completed_shadow_outcomes_count", 0) or 0),
        "scaffold_no_market_data_records_count":
            int(counters.get(
                "scaffold_no_market_data_records_count", 0) or 0),
        "halt_path_records_count":
            int(counters.get("halt_path_records_count", 0) or 0),
        "first_real_market_record_seen":
            bool(first_record.get(
                "first_real_market_record_seen", False)),
        "latest_workflow_verdict":
            health_latest.get("verdict"),
    }
    successful = [h for h in history
                  if h.get("workflow_conclusion") == "success"]
    rep.successful_runs_observed = len(successful)
    if rep.successful_runs_observed < 2:
        rep.status = REAL_MARKET_EVIDENCE_BLOCKED_INSUFFICIENT_RUNS
        rep.rationale.append(
            f"only {rep.successful_runs_observed} successful "
            f"workflow runs in history")
        rep.recommended_actions.append(
            "IMPROVE_DIAGNOSTICS")
        rep.recommended_actions.append(
            "INCREASE_WORKFLOW_VISIBILITY")
        return rep

    # Aggregate token distribution across the last 5 successful runs.
    token_counts: dict[str, int] = {}
    for h in successful[-5:]:
        for tok, c in (h.get("diagnostic_token_counts") or {}).items():
            try:
                token_counts[tok] = token_counts.get(tok, 0) + int(c)
            except Exception:
                continue
    if token_counts:
        rep.dominant_diagnostic_token = max(
            token_counts.items(), key=lambda kv: kv[1])[0]
    dom = rep.dominant_diagnostic_token

    if dom == "MARKET_DATA_AUTH_FAILED":
        rep.status = REAL_MARKET_EVIDENCE_BLOCKED_AUTH_FAILED
        rep.rationale.append(
            "auth failures dominate diagnostics over the last 5 "
            "successful runs")
        rep.recommended_actions.append(
            "IMPROVE_DIAGNOSTICS")
        return rep
    if dom == "MARKET_DATA_PROVIDER_ERROR":
        rep.status = REAL_MARKET_EVIDENCE_BLOCKED_PROVIDER_ERROR
        rep.rationale.append("provider errors dominate diagnostics")
        rep.recommended_actions.append(
            "IMPROVE_DIAGNOSTICS")
        return rep
    if dom == "INSUFFICIENT_BARS_FOR_SIGNAL":
        rep.status = REAL_MARKET_EVIDENCE_BLOCKED_INSUFFICIENT_BARS
        rep.rationale.append("insufficient bars dominate diagnostics")
        rep.recommended_actions.extend([
            "EXPAND_LOOKBACK_KEEPING_22_BAR_FLOOR",
            "IMPROVE_DIAGNOSTICS",
        ])
        return rep
    if dom == "MARKET_CLOSED_OR_NO_BARS":
        rep.status = REAL_MARKET_EVIDENCE_BLOCKED_OUTSIDE_SESSION
        rep.rationale.append(
            "market-closed dominates diagnostics — consider "
            "expanding read-only cron windows so the workflow has "
            "more chances to fire during US session")
        rep.recommended_actions.extend([
            "INCREASE_CRON_EVALUATION_WINDOWS",
            "ADD_MARKET_SESSIONS_READ_ONLY_ONLY",
        ])
        return rep
    if dom == "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL":
        rep.status = (
            REAL_MARKET_EVIDENCE_BLOCKED_GENERATOR_RESTRICTIVE)
        rep.rationale.append(
            "data is fresh and bars are sufficient but signal "
            "generator did not fire — the generator is likely too "
            "restrictive")
        rep.recommended_actions.extend([
            "ADD_DETERMINISTIC_SHADOW_STRATEGY_CANDIDATES",
            "EXPAND_READ_ONLY_SYMBOL_UNIVERSE",
            "ADD_NO_TRADE_OBSERVATION_RECORDS_IF_SCHEMA_SAFE",
        ])
        return rep

    rep.status = REAL_MARKET_EVIDENCE_HEALTHY
    rep.rationale.append(
        "no dominant blocker — pipeline appears to be making "
        "progress")
    return rep


def write_artifacts(report: AccelerationReport,
                      *,
                      json_path: Path | None = None,
                      doc_path: Path | None = None,
                      ) -> None:
    if json_path is None:
        json_path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                      / "acceleration_latest.json")
    if doc_path is None:
        doc_path = (REPO_ROOT / "docs"
                     / "REAL_MARKET_EVIDENCE_ACCELERATION.md")
    payload = {
        "version":          "v3.29.1",
        "generated_at_iso": datetime.now(timezone.utc).isoformat(),
        "acceleration_status":    report.status,
        "rationale":              report.rationale,
        "counters_snapshot":      report.counters_snapshot,
        "dominant_diagnostic_token": report.dominant_diagnostic_token,
        "successful_runs_observed": report.successful_runs_observed,
        "recommended_actions":    report.recommended_actions,
        "allowed_actions_enum":   list(ALLOWED_ACTIONS),
        "forbidden_actions_enum": list(FORBIDDEN_ACTIONS),
        "safety": {
            "broker_paper_canary_still_blocked": True,
            "live_trading_unsupported":          True,
            "edge_gate_enabled":                 False,
            "allow_broker_paper":                False,
            "deterministic_gates_remain_final":  True,
            "this_analyzer_never_mutates_counters": True,
            "this_analyzer_never_places_orders":   True,
            "llm_output_does_not_count_as_real_market_evidence":
                True,
        },
        "standing_markers": [
            "LLM_STRATEGY_ALIGNMENT_ENFORCED",
            "LLM_OUTPUT_DOES_NOT_COUNT_AS_REAL_MARKET_EVIDENCE",
            "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
            "QUALITY_SOURCE_MISMATCH_BLOCKS_UNLOCK",
            "BROKER_PAPER_CANARY_ONLY_NOT_BROAD_TRADING",
            "LIVE_TRADING_UNSUPPORTED",
            "DETERMINISTIC_GATES_REMAIN_FINAL",
        ],
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Real-Market Evidence Acceleration (v3.29.1)\n",
        f"- **Acceleration status:** `{report.status}`",
        f"- **Successful runs observed:** "
        f"{report.successful_runs_observed}",
        f"- **Dominant diagnostic token:** "
        f"`{report.dominant_diagnostic_token}`",
        "",
        "## Counters snapshot\n",
    ]
    for k, v in sorted(report.counters_snapshot.items()):
        lines.append(f"- `{k}`: **{v}**")
    lines.append("")
    lines.append("## Rationale\n")
    for r in report.rationale:
        lines.append(f"- {r}")
    lines.append("")
    lines.append("## Recommended actions (operator-visible only)\n")
    if report.recommended_actions:
        for a in report.recommended_actions:
            lines.append(f"- `{a}`")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Forbidden actions (NEVER applied by this analyzer)\n")
    for a in FORBIDDEN_ACTIONS:
        lines.append(f"- `{a}`")
    lines.append("")
    lines.append("## Safety invariants\n")
    for k, v in sorted(payload["safety"].items()):
        lines.append(f"- `{k}`: **{str(v).lower()}**")
    doc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = [
    "REAL_MARKET_EVIDENCE_HEALTHY",
    "REAL_MARKET_EVIDENCE_BLOCKED_NO_BARS",
    "REAL_MARKET_EVIDENCE_BLOCKED_INSUFFICIENT_BARS",
    "REAL_MARKET_EVIDENCE_BLOCKED_AUTH_FAILED",
    "REAL_MARKET_EVIDENCE_BLOCKED_PROVIDER_ERROR",
    "REAL_MARKET_EVIDENCE_BLOCKED_GENERATOR_RESTRICTIVE",
    "REAL_MARKET_EVIDENCE_BLOCKED_OUTSIDE_SESSION",
    "REAL_MARKET_EVIDENCE_BLOCKED_INSUFFICIENT_RUNS",
    "REAL_MARKET_EVIDENCE_ACCELERATION_READY",
    "ALL_ACCEL_STATUSES",
    "ALLOWED_ACTIONS", "FORBIDDEN_ACTIONS",
    "AccelerationReport",
    "evaluate_acceleration", "write_artifacts",
]
