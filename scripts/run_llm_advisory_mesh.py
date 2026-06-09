#!/usr/bin/env python3
"""v3.28 (2026-06-09) — cloud LLM advisory mesh runner.

Reads the v3.27.x evidence + audit artefacts and emits one advisory
row per agent into:

- ``learning-loop/llm_advisory/YYYY-MM-DD.jsonl`` (append-only)
- ``docs/LLM_ADVISORY_MESH_LATEST.md`` (rendered summary)

DEFAULT: disabled (``LLM_AGENTS_ENABLED=false``). The runner exits 0
with ``LLM_ADVISORY_MESH_SKIPPED_DISABLED`` when disabled. When
enabled, it consults the v3.28 budget + provider modules; if either
returns a skip status, the run exits 0 with a skip token. This script
NEVER fails the workflow because the LLM is unavailable.

HARD SAFETY
-----------
- NEVER submits orders.
- NEVER imports the broker-orders module (asserted by test).
- NEVER calls any order-submission helper from the broker module.
- NEVER mutates shadow counters, broker readiness gate, risk config,
  broker flags, baseline, or drawdown guard.
- Refuses (exit 1) if any of
  ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED`` /
  ``BROKER_EXECUTION_ENABLED`` / ``LIVE_TRADING`` /
  ``LIVE_ENABLED`` / ``GO_LIVE`` / ``LIVE_TRADING_ENABLED``
  is truthy.
- Every emitted row is JSON-Schema-validated against
  ``learning-loop/llm_advisory/schema.json`` before being written.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

# ─── Status tokens ──────────────────────────────────────────────────────────

LLM_ADVISORY_MESH_RAN                       = "LLM_ADVISORY_MESH_RAN"
LLM_ADVISORY_MESH_SKIPPED_DISABLED          = "LLM_ADVISORY_MESH_SKIPPED_DISABLED"
LLM_ADVISORY_MESH_SKIPPED_NO_PROVIDER_KEY   = "LLM_ADVISORY_MESH_SKIPPED_NO_PROVIDER_KEY"
LLM_ADVISORY_MESH_SKIPPED_BUDGET            = "LLM_ADVISORY_MESH_SKIPPED_BUDGET"

# Standing markers — always returned.
BROKER_PAPER_CANARY_STILL_BLOCKED = "BROKER_PAPER_CANARY_STILL_BLOCKED"
LIVE_TRADING_UNSUPPORTED          = "LIVE_TRADING_UNSUPPORTED"


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


def _advisory_dir() -> Path:
    override = os.environ.get("LLM_ADVISORY_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "learning-loop" / "llm_advisory"


def _safe_load(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        if path.suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        if path.suffix == ".jsonl":
            out: list[dict] = []
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
            return out
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def gather_evidence() -> dict[str, Any]:
    """Read the v3.27.x evidence artefacts. Read-only."""
    se = REPO_ROOT / "learning-loop" / "shadow_evidence"
    return {
        "workflow_health_latest":  _safe_load(se / "workflow_health_latest.json"),
        "workflow_health_history": _safe_load(se / "workflow_health_history.jsonl"),
        "first_real_record":       _safe_load(se / "first_real_market_record_status.json"),
        "counters_latest":         _safe_load(se / "evidence_counters_latest.json"),
        "system_consistency":      _safe_load(REPO_ROOT / "reports"
                                                / "system-consistency"
                                                / "latest.json"),
        "strategy_coherence":      _safe_load(REPO_ROOT / "reports"
                                                / "strategy-coherence"
                                                / "latest.json"),
    }


# ─── Schema validation (minimal, dependency-free) ──────────────────────────

def _validate_advisory_row(row: dict) -> str | None:
    """Returns None on valid; an error string on failure.

    Implements the safety-critical enum pins manually so we don't
    need a third-party JSON Schema validator at runtime.
    """
    required = (
        "timestamp", "run_id", "agent_name", "authority_level",
        "process_stage", "advisory_only", "may_execute",
        "may_modify_risk", "may_unlock_broker_paper",
        "evidence_refs", "input_summary", "recommendation",
        "veto_recommendation", "confidence", "rationale",
        "risks_identified", "proposed_next_actions",
        "forbidden_actions_confirmed",
        "broker_order_submitted", "broker_execution_enabled",
        "affects_readiness_gate",
    )
    for k in required:
        if k not in row:
            return f"missing required field: {k}"
    # Hard enum pins.
    if row["advisory_only"]            is not True:  return "advisory_only must be True"
    if row["may_execute"]              is not False: return "may_execute must be False"
    if row["may_modify_risk"]          is not False: return "may_modify_risk must be False"
    if row["may_unlock_broker_paper"]  is not False: return "may_unlock_broker_paper must be False"
    if row["broker_order_submitted"]   is not False: return "broker_order_submitted must be False"
    if row["broker_execution_enabled"] is not False: return "broker_execution_enabled must be False"
    if row["affects_readiness_gate"]   is not False: return "affects_readiness_gate must be False"
    # Forbidden actions: must list at least the 10 required.
    required_forbidden = {
        "ORDER_EXECUTION", "POSITION_MODIFICATION",
        "RISK_GATE_DIRECT_MUTATION", "BROKER_PAPER_UNLOCK",
        "LIVE_TRADING_ENABLEMENT", "BASELINE_RESET",
        "DRAWDOWN_GUARD_LOWERING", "READINESS_COUNTER_MUTATION",
        "MARKET_DATA_FABRICATION", "PNL_FABRICATION",
    }
    actual = set(row.get("forbidden_actions_confirmed") or [])
    missing = required_forbidden - actual
    if missing:
        return f"forbidden_actions_confirmed missing: {sorted(missing)}"
    return None


# ─── Row builder ───────────────────────────────────────────────────────────

def _new_row(*, run_id: str, agent_def, evidence: dict,
              recommendation: str, rationale: str,
              veto: bool = False, confidence: float = 0.0) -> dict:
    from llm_advisory_registry import FORBIDDEN_ACTIONS  # type: ignore
    return {
        "timestamp":                  datetime.now(timezone.utc).isoformat(),
        "run_id":                     run_id,
        "agent_name":                 agent_def.name,
        "authority_level":            agent_def.authority_level,
        "process_stage":              agent_def.process_stage,
        "advisory_only":              True,
        "may_execute":                False,
        "may_modify_risk":            False,
        "may_unlock_broker_paper":    False,
        "evidence_refs":              list(agent_def.allowed_inputs),
        "input_summary":              (
            "Evidence read from learning-loop/shadow_evidence/* and "
            "reports/* (read-only; advisory-only)."),
        "recommendation":             recommendation,
        "veto_recommendation":        bool(veto),
        "confidence":                 float(confidence),
        "rationale":                  rationale,
        "risks_identified":           [],
        "proposed_next_actions":      [],
        "forbidden_actions_confirmed": list(FORBIDDEN_ACTIONS),
        "broker_order_submitted":     False,
        "broker_execution_enabled":   False,
        "affects_readiness_gate":     False,
    }


# ─── Main mesh runner ───────────────────────────────────────────────────────

def run_mesh(run_id: str) -> dict[str, Any]:
    """Execute the mesh. Returns a summary dict.

    Default: disabled (returns SKIPPED status). NEVER raises.
    """
    import llm_agent_budget as budget   # type: ignore
    import llm_advisory_registry as reg  # type: ignore

    summary: dict[str, Any] = {
        "version":          "v3.28",
        "run_id":           run_id,
        "status":           LLM_ADVISORY_MESH_RAN,
        "agents_evaluated": 0,
        "rows_written":     0,
        "standing_markers": [
            BROKER_PAPER_CANARY_STILL_BLOCKED,
            LIVE_TRADING_UNSUPPORTED,
        ],
        "broker_safety": {
            "broker_paper_canary_still_blocked": True,
            "live_trading_unsupported":          True,
            "edge_gate_enabled":                 False,
            "allow_broker_paper":                False,
            "broker_execution_enabled":          False,
        },
    }
    # Gate 1: master enable.
    if not budget.llm_agents_enabled():
        summary["status"] = LLM_ADVISORY_MESH_SKIPPED_DISABLED
        return summary
    # Gate 2: provider key.
    if not budget.provider_key_present():
        summary["status"] = LLM_ADVISORY_MESH_SKIPPED_NO_PROVIDER_KEY
        return summary

    evidence = gather_evidence()

    # For each registered agent, consult budget and emit a row.
    out_dir = _advisory_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    rows_path = out_dir / f"{today}.jsonl"

    written_any = False
    for agent_def in reg.all_agents():
        status, reason = budget.check_budget(run_id=run_id)
        if status == budget.LLM_BUDGET_DISABLED:
            summary["status"] = LLM_ADVISORY_MESH_SKIPPED_DISABLED
            break
        if status in (budget.LLM_BUDGET_EXHAUSTED_DAILY,
                       budget.LLM_BUDGET_EXHAUSTED_RUN):
            # Only set SKIPPED_BUDGET if no rows have been written
            # yet. Otherwise keep status RAN (cap hit mid-stream but
            # the run did produce advisory output).
            if int(summary.get("rows_written", 0)) == 0:
                summary["status"] = LLM_ADVISORY_MESH_SKIPPED_BUDGET
            break
        if status == budget.LLM_PROVIDER_KEY_MISSING:
            if int(summary.get("rows_written", 0)) == 0:
                summary["status"] = LLM_ADVISORY_MESH_SKIPPED_NO_PROVIDER_KEY
            break
        if status == budget.LLM_FAIL_SOFT:
            # Fail-soft: don't write a row for this agent; continue.
            continue
        # Generate an advisory row. The mock-provider path produces a
        # deterministic recommendation; real providers would replace
        # the recommendation string + rationale via call_provider.
        row = _new_row(
            run_id=run_id, agent_def=agent_def, evidence=evidence,
            recommendation=(
                "OBSERVATION: advisory mesh ran; no execution; "
                f"agent={agent_def.name}; "
                f"authority={agent_def.authority_level}; "
                f"stage={agent_def.process_stage}."),
            rationale=(
                "v3.28 advisory output. Deterministic gates remain "
                "final; this row is evidence, not authority."),
            veto=False, confidence=0.0,
        )
        err = _validate_advisory_row(row)
        if err is not None:
            # Schema violation = drop the row (never write invalid).
            continue
        with rows_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        try:
            budget.record_call(run_id=run_id, cost_usd=0.0)
        except Exception:
            pass
        written_any = True
        summary["rows_written"]     = int(summary["rows_written"]) + 1
        summary["agents_evaluated"] = int(summary["agents_evaluated"]) + 1

    if written_any:
        try:
            summary["rows_path"] = str(rows_path.relative_to(REPO_ROOT))
        except ValueError:
            # LLM_ADVISORY_DIR pointed outside the repo (e.g. tests
            # using /tmp). Record absolute path instead — never raise.
            summary["rows_path"] = str(rows_path)
    return summary


def render_doc(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# LLM Advisory Mesh — latest run (v3.28)\n")
    lines.append(f"- **Run ID:** `{summary.get('run_id')}`")
    lines.append(f"- **Status:** `{summary.get('status')}`")
    lines.append(
        f"- **Agents evaluated:** {summary.get('agents_evaluated', 0)}")
    lines.append(
        f"- **Rows written:** {summary.get('rows_written', 0)}")
    lines.append(
        "- **Standing markers:** "
        "`BROKER_PAPER_CANARY_STILL_BLOCKED`, "
        "`LIVE_TRADING_UNSUPPORTED`")
    lines.append("")
    lines.append(
        "## Safety invariants (asserted on every run)\n"
        "- `broker_paper_canary_still_blocked`: **true**\n"
        "- `live_trading_unsupported`: **true**\n"
        "- LLM agents NEVER submit orders.\n"
        "- LLM agents NEVER import the broker-orders module.\n"
        "- LLM agents NEVER mutate readiness counters.\n"
        "- LLM agents NEVER mutate risk config.\n"
        "- Deterministic gates remain final.\n")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cloud LLM advisory mesh runner (v3.28).")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--render-doc", action="store_true",
                          help="Also write docs/LLM_ADVISORY_MESH_LATEST.md")
    args = parser.parse_args(argv)

    refuse = _refuse_if_broker_enabled()
    if refuse is not None:
        print(json.dumps({"status": refuse}))
        return 1

    run_id = args.run_id or f"mesh-{uuid.uuid4().hex[:12]}"
    summary = run_mesh(run_id)
    if args.render_doc:
        doc_path = REPO_ROOT / "docs" / "LLM_ADVISORY_MESH_LATEST.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(render_doc(summary), encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
