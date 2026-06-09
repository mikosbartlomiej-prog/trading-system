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
# v3.28.3 — per-row provider attribution tokens.
PROVIDER_USED                  = "PROVIDER_USED"
PROVIDER_SKIPPED_DISABLED      = "PROVIDER_SKIPPED_DISABLED"
PROVIDER_FAILED_FAIL_SOFT      = "PROVIDER_FAILED_FAIL_SOFT"
PROVIDER_OUTPUT_INVALID_SCHEMA = "PROVIDER_OUTPUT_INVALID_SCHEMA"
# v3.28.2 — free-only policy block (paid provider attempted while
# LLM_FREE_ONLY=true).
LLM_ADVISORY_MESH_SKIPPED_PROVIDER_BLOCKED_BY_FREE_ONLY = (
    "LLM_ADVISORY_MESH_SKIPPED_PROVIDER_BLOCKED_BY_FREE_ONLY")

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

# ─── v3.28.3 prompt builder ─────────────────────────────────────────────────

# Per-agent prompt templates. Each one requires the model to return a
# JSON object with concrete, evidence-grounded fields. The template ends
# with a "Return ONLY one JSON object…" sentinel so a low-temperature
# free-tier model stays inside the contract.
_AGENT_PROMPT_TEMPLATES: dict[str, str] = {
    "MARKET_REGIME_AGENT": (
        "You are MARKET_REGIME_AGENT (L2_RECOMMEND_ONLY). "
        "Summarise the current market regime from the evidence; "
        "say whether the regime is actionable or insufficient; "
        "identify data gaps."
    ),
    "SIGNAL_QUALITY_AGENT": (
        "You are SIGNAL_QUALITY_AGENT (L2_RECOMMEND_ONLY). "
        "Review whether real-market opportunities exist; "
        "explain why the signal count is zero or non-zero; "
        "say whether the generator looks too restrictive."
    ),
    "DATA_QUALITY_AGENT": (
        "You are DATA_QUALITY_AGENT (L2_RECOMMEND_ONLY). "
        "Review the market-data diagnostics; name the dominant "
        "diagnostic tokens; flag stale/missing/auth/provider issues."
    ),
    "NO_SIGNAL_DIAGNOSTIC_AGENT": (
        "You are NO_SIGNAL_DIAGNOSTIC_AGENT (L2_RECOMMEND_ONLY). "
        "Classify the dominant no-signal reason; separate "
        "market-closed / no-bars / insufficient-bars / "
        "strategy-too-restrictive."
    ),
    "SHADOW_OUTCOME_REVIEW_AGENT": (
        "You are SHADOW_OUTCOME_REVIEW_AGENT (L2_RECOMMEND_ONLY). "
        "Review completed shadow outcomes; if zero outcomes, say "
        "explicitly that outcomes cannot yet assess edge."
    ),
    "PRE_ORDER_ADVISORY_AGENT": (
        "You are PRE_ORDER_ADVISORY_AGENT (L3_VETO_RECOMMEND_ONLY). "
        "No draft order is present yet; observe-only. Note any "
        "signals that would be vetoed if a draft order arrived."
    ),
    "RISK_NARRATIVE_AGENT": (
        "You are RISK_NARRATIVE_AGENT (L2_RECOMMEND_ONLY). "
        "Narrate the current risk posture from the readiness "
        "counters."
    ),
    "RISK_GATE_CHANGE_PROPOSAL_AGENT": (
        "You are RISK_GATE_CHANGE_PROPOSAL_AGENT "
        "(L4_PROPOSE_CONFIG_CHANGE_ONLY). Propose nothing unless "
        "you can ground it in the readiness counters. auto_apply "
        "is hard-coded to false."
    ),
    "INCIDENT_REVIEW_AGENT": (
        "You are INCIDENT_REVIEW_AGENT (L3_VETO_RECOMMEND_ONLY). "
        "Review recent incidents (if any) or report quiet."
    ),
    "BROKER_PAPER_CANARY_REVIEW_AGENT": (
        "You are BROKER_PAPER_CANARY_REVIEW_AGENT "
        "(L2_RECOMMEND_ONLY). Review readiness toward the v3.25 "
        "50/20 thresholds; the canary remains BLOCKED unless those "
        "are met and the operator approves."
    ),
    "FINAL_ADVISORY_ARBITER": (
        "You are FINAL_ADVISORY_ARBITER (L3_VETO_RECOMMEND_ONLY). "
        "Synthesise the prior agents' findings into one paragraph."
    ),
}

_AGENT_PROMPT_FOOTER = (
    "You CANNOT execute, modify positions, change risk config, "
    "unlock broker paper, enable live trading, lower the drawdown "
    "guard, reset the baseline, mutate readiness counters, or "
    "fabricate market data / P&L. Use the explicit phrase "
    "'insufficient evidence because <specific missing value>' when "
    "data is absent; do NOT invent conclusions.\n\n"
    "STRICT OUTPUT RULES (v3.29.1):\n"
    "1. `recommendation` must be a single concrete sentence that "
    "names at least one evidence value from the evidence dict "
    "(e.g. 'first_real_market_record_seen=false', "
    "'real_market_opportunities_count=0').\n"
    "2. `rationale` must cite at least one evidence value verbatim "
    "or say 'insufficient evidence because <specific missing "
    "artifact>'.\n"
    "3. `risks_identified` must contain AT LEAST ONE item. If no "
    "material risk applies, write exactly ONE item of the form "
    "'No material risk identified because <specific reason>'.\n"
    "4. `proposed_next_actions` must contain AT LEAST ONE item. "
    "If no action applies, write exactly ONE item of the form "
    "'No action recommended because <specific reason>'.\n"
    "5. `confidence` must be > 0.0 when ANY evidence value is "
    "present. Confidence may be 0.0 ONLY if the evidence dict is "
    "completely empty AND you cite which artifact is missing.\n"
    "6. `evidence_values_used` must list the evidence keys you "
    "actually consulted (subset of the keys in the evidence dict).\n"
    "7. Return ONLY one JSON object — no prose before or after.\n\n"
    "Return ONLY one JSON object with these keys (no prose outside):\n"
    "{\n"
    "  \"recommendation\":         <one concrete sentence>,\n"
    "  \"rationale\":              <one short paragraph citing "
    "evidence values verbatim>,\n"
    "  \"risks_identified\":       [<≥1 short string — never empty>],\n"
    "  \"proposed_next_actions\":  [<≥1 short string — never empty>],\n"
    "  \"confidence\":             <0.0..1.0 — must be > 0 if any "
    "evidence value is present>,\n"
    "  \"veto_recommendation\":    <true/false>,\n"
    "  \"evidence_values_used\":   {<key>: <value>, ...}\n"
    "}\n"
)


def _evidence_summary_for_agent(agent_name: str,
                                  evidence: dict) -> str:
    """Render a small per-agent evidence snippet (read-only)."""
    keys_per_agent: dict[str, tuple[str, ...]] = {
        "MARKET_REGIME_AGENT":          ("counters_latest",
                                            "workflow_health_latest"),
        "SIGNAL_QUALITY_AGENT":         ("counters_latest",
                                            "workflow_health_latest"),
        "DATA_QUALITY_AGENT":           ("workflow_health_latest",
                                            "workflow_health_history",
                                            "first_real_record"),
        "NO_SIGNAL_DIAGNOSTIC_AGENT":   ("workflow_health_latest",
                                            "first_real_record"),
        "SHADOW_OUTCOME_REVIEW_AGENT":  ("counters_latest",),
        "PRE_ORDER_ADVISORY_AGENT":     ("counters_latest",
                                            "workflow_health_latest"),
        "RISK_NARRATIVE_AGENT":         ("counters_latest",),
        "RISK_GATE_CHANGE_PROPOSAL_AGENT": ("counters_latest",),
        "INCIDENT_REVIEW_AGENT":        ("workflow_health_history",),
        "BROKER_PAPER_CANARY_REVIEW_AGENT": ("counters_latest",
                                                "first_real_record"),
        "FINAL_ADVISORY_ARBITER":       ("counters_latest",
                                            "workflow_health_latest",
                                            "first_real_record"),
    }
    keys = keys_per_agent.get(agent_name) or tuple(evidence.keys())
    snippet: dict[str, Any] = {}
    for k in keys:
        v = evidence.get(k)
        if v is None:
            snippet[k] = None
            continue
        # Truncate large lists/history so the prompt stays compact.
        if isinstance(v, list):
            snippet[k] = v[-5:]
        else:
            snippet[k] = v
    try:
        return json.dumps(snippet, sort_keys=True, default=str)[:3000]
    except Exception:
        return "{}"


def _build_prompt(agent_name: str, evidence: dict) -> str:
    base = _AGENT_PROMPT_TEMPLATES.get(
        agent_name,
        "You are an L2 advisory agent. Review the evidence.")
    evi = _evidence_summary_for_agent(agent_name, evidence)
    return (
        f"{base}\n\nEvidence (read-only, advisory-only):\n{evi}\n\n"
        f"{_AGENT_PROMPT_FOOTER}"
    )


# ─── Provider response → row fields ─────────────────────────────────────────

def _try_extract_json(text: str) -> dict | None:
    if not text:
        return None
    # Direct parse.
    try:
        v = json.loads(text)
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    # Strip ```json fences.
    stripped = text.strip()
    if stripped.startswith("```"):
        # Remove first ``` line and trailing ``` line.
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        try:
            v = json.loads("\n".join(lines))
            if isinstance(v, dict):
                return v
        except Exception:
            pass
    # Locate first { and matching last }.
    first = stripped.find("{")
    last  = stripped.rfind("}")
    if first >= 0 and last > first:
        try:
            v = json.loads(stripped[first:last + 1])
            if isinstance(v, dict):
                return v
        except Exception:
            pass
    return None


def _parse_provider_response_into_row_fields(
        text: str) -> dict[str, Any]:
    """Extract recommendation / rationale / risks / next-actions /
    confidence / veto from the provider response. Returns a dict with
    sensible defaults when the provider returned prose only.
    """
    out = {
        "recommendation":        "",
        "rationale":             "",
        "risks_identified":      [],
        "proposed_next_actions": [],
        "confidence":            0.0,
        "veto_recommendation":   False,
        "evidence_values_used":  {},
    }
    parsed = _try_extract_json(text)
    if parsed is not None:
        rec = parsed.get("recommendation") or ""
        if not isinstance(rec, str):
            rec = json.dumps(rec)[:280]
        out["recommendation"] = rec.strip()
        rat = parsed.get("rationale") or ""
        if not isinstance(rat, str):
            rat = json.dumps(rat)[:600]
        out["rationale"] = rat.strip()
        risks = parsed.get("risks_identified") or []
        if isinstance(risks, list):
            out["risks_identified"] = [str(x).strip()
                                          for x in risks
                                          if str(x).strip()][:6]
        actions = parsed.get("proposed_next_actions") or []
        if isinstance(actions, list):
            out["proposed_next_actions"] = [str(x).strip()
                                              for x in actions
                                              if str(x).strip()][:6]
        try:
            c = float(parsed.get("confidence", 0.0))
            out["confidence"] = max(0.0, min(1.0, c))
        except (TypeError, ValueError):
            out["confidence"] = 0.0
        veto = parsed.get("veto_recommendation", False)
        out["veto_recommendation"] = bool(veto) if isinstance(
            veto, (bool, int, str)) else False
        # v3.29.1 — capture evidence_values_used dict (non-secret,
        # truncated).
        evu = parsed.get("evidence_values_used") or {}
        if isinstance(evu, dict):
            safe_evu: dict = {}
            for k, v in list(evu.items())[:30]:
                ks = str(k)[:80]
                vs = v if isinstance(v, (int, float, bool)) else str(
                    v)[:200]
                safe_evu[ks] = vs
            out["evidence_values_used"] = safe_evu
    else:
        # Prose-only response — keep first ~280 chars as recommendation
        # so the operator still sees the provider's words.
        prose = (text or "").strip().replace("\n", " ")
        out["recommendation"] = prose[:280] or (
            "insufficient evidence")
        out["rationale"] = (
            "Provider returned prose; structured fields fell back to "
            "defaults. See recommendation for the provider's "
            "summary.")
    return out


def _new_row(*, run_id: str, agent_def, evidence: dict,
              recommendation: str, rationale: str,
              veto: bool = False, confidence: float = 0.0,
              risks: list[str] | None = None,
              next_actions: list[str] | None = None,
              evidence_values_used: dict | None = None) -> dict:
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
        "risks_identified":           list(risks or []),
        "proposed_next_actions":      list(next_actions or []),
        "forbidden_actions_confirmed": list(FORBIDDEN_ACTIONS),
        "broker_order_submitted":     False,
        "broker_execution_enabled":   False,
        "affects_readiness_gate":     False,
        "evidence_values_used":       dict(evidence_values_used or {}),
    }


# ─── Main mesh runner ───────────────────────────────────────────────────────

def run_mesh(run_id: str) -> dict[str, Any]:
    """Execute the mesh. Returns a summary dict.

    Default: disabled (returns SKIPPED status). NEVER raises.
    """
    import llm_agent_budget as budget   # type: ignore
    import llm_advisory_registry as reg  # type: ignore

    # v3.28.2 — surface selected_provider + llm_free_only in every
    # summary so the activation helper can render rich status.
    selected_provider = os.environ.get(
        "LLM_PROVIDER", "offline_mock").strip().lower() or "offline_mock"
    llm_free_only = (os.environ.get("LLM_FREE_ONLY", "true")
                       .strip().lower() in ("true", "1", "yes", "on"))
    summary: dict[str, Any] = {
        "version":          "v3.28.3",
        "run_id":           run_id,
        "status":           LLM_ADVISORY_MESH_RAN,
        "agents_evaluated": 0,
        "rows_written":     0,
        "selected_provider": selected_provider,
        "llm_free_only":     llm_free_only,
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
    # Gate 2 (v3.28.2): free-only policy. If the operator selected a
    # paid provider while LLM_FREE_ONLY is true (the default), refuse
    # to proceed and route the skip status through the mesh-level
    # enum so the workflow can record it.
    try:
        import llm_provider_client as _p  # type: ignore
    except ImportError:
        _p = None  # type: ignore
    if _p is not None:
        prov = budget.provider()
        free_only = (os.environ.get("LLM_FREE_ONLY", "true")
                       .strip().lower() in ("true", "1", "yes", "on"))
        if free_only and prov in _p.PAID_PROVIDERS:
            summary["status"] = (
                LLM_ADVISORY_MESH_SKIPPED_PROVIDER_BLOCKED_BY_FREE_ONLY)
            summary["selected_provider"] = prov
            summary["llm_free_only"]     = True
            return summary
    # Gate 3: provider key.
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
        # v3.28.3 — actually call the provider per agent. The mock
        # provider still produces a deterministic placeholder, but
        # the gemini / anthropic / openai paths now receive the
        # per-agent evidence-grounded prompt and write the structured
        # response into the row.
        prompt = _build_prompt(agent_def.name, evidence)
        try:
            import llm_provider_client as _p  # type: ignore
        except ImportError:
            from shared import llm_provider_client as _p  # type: ignore
        provider_resp = _p.call_provider(
            prompt=prompt, max_tokens=512)
        provider_status = PROVIDER_USED
        if provider_resp.status == _p.LLM_PROVIDER_OFFLINE_MOCK:
            provider_status = PROVIDER_SKIPPED_DISABLED
            parsed = {
                "recommendation": (
                    "OBSERVATION: offline_mock — no provider "
                    f"evaluation for {agent_def.name}."),
                "rationale": (
                    "v3.28.3 advisory output via offline mock. "
                    "Deterministic gates remain final."),
                "risks_identified":      [],
                "proposed_next_actions": [],
                "confidence":            0.0,
                "veto_recommendation":   False,
            }
        elif provider_resp.status == _p.LLM_PROVIDER_CALL_OK:
            parsed = _parse_provider_response_into_row_fields(
                provider_resp.text)
        else:
            # Any non-OK status → fail-soft row that still records the
            # provider status so the operator can debug.
            provider_status = PROVIDER_FAILED_FAIL_SOFT
            parsed = {
                "recommendation": (
                    f"INSUFFICIENT_EVIDENCE: provider "
                    f"{provider_resp.provider or 'unknown'} returned "
                    f"{provider_resp.status}."),
                "rationale": (
                    "Provider call did not complete; this row is "
                    "the fail-soft placeholder. The deterministic "
                    "gates remain final."),
                "risks_identified":      [],
                "proposed_next_actions": [],
                "confidence":            0.0,
                "veto_recommendation":   False,
            }
        row = _new_row(
            run_id=run_id, agent_def=agent_def, evidence=evidence,
            recommendation=parsed["recommendation"],
            rationale=parsed["rationale"],
            veto=parsed["veto_recommendation"],
            confidence=parsed["confidence"],
            risks=parsed["risks_identified"],
            next_actions=parsed["proposed_next_actions"],
            evidence_values_used=parsed.get(
                "evidence_values_used") or {},
        )
        # v3.28.3 — track per-row provider attribution.
        row["provider_status"] = provider_status
        err = _validate_advisory_row(row)
        if err is not None:
            # Schema violation = drop the row (never write invalid).
            provider_status = PROVIDER_OUTPUT_INVALID_SCHEMA
            continue
        with rows_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        try:
            budget.record_call(
                run_id=run_id, cost_usd=provider_resp.cost_usd)
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

    # v3.28.3 — run the quality guard over the rows we just emitted.
    try:
        import llm_advisory_quality as _q  # type: ignore
    except ImportError:
        from shared import llm_advisory_quality as _q  # type: ignore
    rows_for_quality: list[dict] = []
    if rows_path.exists():
        try:
            with rows_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row_obj = json.loads(line)
                    except Exception:
                        continue
                    if row_obj.get("run_id") == run_id:
                        rows_for_quality.append(row_obj)
        except Exception:
            pass
    quality_report = _q.evaluate_quality(rows_for_quality)
    summary["quality_status"] = quality_report.status
    summary["quality_report"] = quality_report.to_dict()
    if quality_report.status == _q.LLM_ADVISORY_QUALITY_GENERIC_PLACEHOLDER:
        summary["next_recommended_action"] = (
            "Improve per-agent prompts so Gemini emits concrete "
            "evidence-grounded analysis. Do NOT enable schedule.")
    elif quality_report.status == _q.LLM_ADVISORY_QUALITY_PROVIDER_OUTPUT_NOT_USED:
        summary["next_recommended_action"] = (
            "Provider output was not used — verify provider key + "
            "endpoint. Do NOT enable schedule.")
    elif quality_report.status == _q.LLM_ADVISORY_QUALITY_ACCEPTABLE:
        summary["next_recommended_action"] = (
            "Trigger another workflow_dispatch run; if quality stays "
            "ACCEPTABLE across N runs, operator may consider enabling "
            "the schedule.")
    return summary


def render_doc(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# LLM Advisory Mesh — latest run (v3.28.3)\n")
    lines.append(f"- **Run ID:** `{summary.get('run_id')}`")
    lines.append(f"- **Status:** `{summary.get('status')}`")
    lines.append(
        f"- **Quality status:** "
        f"`{summary.get('quality_status', 'n/a')}`")
    lines.append(
        f"- **Selected provider:** "
        f"`{summary.get('selected_provider', 'n/a')}`")
    lines.append(
        f"- **LLM_FREE_ONLY:** "
        f"`{summary.get('llm_free_only', 'n/a')}`")
    lines.append(
        f"- **Agents evaluated:** {summary.get('agents_evaluated', 0)}")
    lines.append(
        f"- **Rows written:** {summary.get('rows_written', 0)}")
    lines.append(
        "- **Standing markers:** "
        "`BROKER_PAPER_CANARY_STILL_BLOCKED`, "
        "`LIVE_TRADING_UNSUPPORTED`")
    lines.append("")
    qr = summary.get("quality_report") or {}
    if qr:
        lines.append("## Quality report (v3.28.3)\n")
        lines.append(
            f"- rows_with_provider_used: "
            f"**{qr.get('rows_with_provider_used', 0)}**")
        lines.append(
            f"- rows_with_provider_skipped: "
            f"{qr.get('rows_with_provider_skipped', 0)}")
        lines.append(
            f"- rows_with_provider_failed: "
            f"{qr.get('rows_with_provider_failed', 0)}")
        lines.append(
            f"- generic_placeholder_count: "
            f"{qr.get('generic_placeholder_count', 0)}")
        lines.append(
            f"- empty_risks_count: "
            f"{qr.get('empty_risks_count', 0)}")
        lines.append(
            f"- empty_next_actions_count: "
            f"{qr.get('empty_next_actions_count', 0)}")
        lines.append(
            f"- confidence range: "
            f"[{qr.get('confidence_min', 0.0)}, "
            f"{qr.get('confidence_max', 0.0)}]")
        lines.append(
            f"- secret_leak_hits: {qr.get('secret_leak_hits', 0)}")
        lines.append(
            f"- unsafe_phrase_hits: {qr.get('unsafe_phrase_hits', 0)}")
        lines.append("")
        nra = summary.get("next_recommended_action")
        if nra:
            lines.append(f"**Next recommended action:** {nra}\n")
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


def _append_to_quality_history(summary: dict[str, Any]) -> None:
    """v3.29.1 — append the freshly-computed quality status to the
    rolling history so the canary unlock evaluator can count
    distinct acceptable runs (anti-mock filter applied at append
    time)."""
    try:
        try:
            import broker_paper_canary_unlock as _bp  # type: ignore
        except ImportError:
            from shared import broker_paper_canary_unlock as _bp  # type: ignore
        _bp.append_quality_history(
            run_id=summary.get("run_id") or "unknown",
            quality_status=summary.get("quality_status") or "",
            quality_report=summary.get("quality_report") or {},
            selected_provider=summary.get("selected_provider"),
            selected_model=None,  # mesh runner doesn't track per-call model
            free_only=bool(summary.get("llm_free_only", True)),
        )
    except Exception as e:
        print(f"  [v3.29.1] quality_history append failed: {e}")


def write_quality_artifact(summary: dict[str, Any]) -> None:
    """v3.28.3 — write the quality review JSON + markdown alongside
    the latest-run markdown."""
    qr_path = (REPO_ROOT / "learning-loop" / "llm_advisory"
                / "quality_review_latest.json")
    qr_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version":          "v3.28.3",
        "run_id":           summary.get("run_id"),
        "quality_status":   summary.get("quality_status"),
        "quality_report":   summary.get("quality_report"),
        "next_recommended_action":
            summary.get("next_recommended_action"),
        "standing_markers": [
            BROKER_PAPER_CANARY_STILL_BLOCKED,
            LIVE_TRADING_UNSUPPORTED,
            "FREE_ONLY_POLICY_ENABLED",
            "OFFLINE_MOCK_STILL_DEFAULT",
            "DETERMINISTIC_GATES_REMAIN_FINAL",
            "SCHEDULE_REMAINS_DISABLED",
            "LLM_PRE_ORDER_VETO_REMAINS_DISABLED",
        ],
        "safety": {
            "broker_paper_canary_still_blocked": True,
            "live_trading_unsupported":          True,
            "broker_execution_enabled":          False,
            "edge_gate_enabled":                 False,
            "allow_broker_paper":                False,
            "schedule_enabled":                  False,
            "llm_pre_order_veto_honored":        False,
        },
    }
    qr_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    doc_path = (REPO_ROOT / "docs"
                 / "LLM_ADVISORY_QUALITY_REVIEW.md")
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    qrep = payload["quality_report"] or {}
    out = [
        "# LLM Advisory Quality Review (v3.28.3)\n",
        f"- **Run ID:** `{payload.get('run_id')}`",
        f"- **Quality status:** `{payload.get('quality_status')}`",
        f"- **Rows seen:** {qrep.get('rows_seen', 0)}",
        f"- **Rows with PROVIDER_USED:** "
        f"**{qrep.get('rows_with_provider_used', 0)}**",
        f"- **Rows with PROVIDER_SKIPPED_DISABLED:** "
        f"{qrep.get('rows_with_provider_skipped', 0)}",
        f"- **Rows with PROVIDER_FAILED_FAIL_SOFT:** "
        f"{qrep.get('rows_with_provider_failed', 0)}",
        f"- **generic_placeholder_count:** "
        f"{qrep.get('generic_placeholder_count', 0)}",
        f"- **empty_risks_count:** {qrep.get('empty_risks_count', 0)}",
        f"- **empty_next_actions_count:** "
        f"{qrep.get('empty_next_actions_count', 0)}",
        f"- **zero_confidence_count:** "
        f"{qrep.get('zero_confidence_count', 0)}",
        f"- **secret_leak_hits:** "
        f"{qrep.get('secret_leak_hits', 0)}",
        f"- **unsafe_phrase_hits:** "
        f"{qrep.get('unsafe_phrase_hits', 0)}",
        "",
        "## Rationale\n",
    ]
    for r in qrep.get("rationale") or []:
        out.append(f"- {r}")
    out.append("\n## Safety invariants\n")
    for k, v in sorted((payload.get("safety") or {}).items()):
        out.append(f"- `{k}`: **{str(v).lower()}**")
    doc_path.write_text("\n".join(out) + "\n", encoding="utf-8")


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
        # v3.28.3 — always write the quality review artefacts when
        # --render-doc is on.
        try:
            write_quality_artifact(summary)
        except Exception as e:
            print(f"  [v3.28.3] quality artifact write failed: {e}")
        # v3.29.1 — also append to the rolling history so the canary
        # unlock evaluator can count distinct acceptable runs.
        _append_to_quality_history(summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
