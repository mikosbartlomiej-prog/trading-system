"""v3.29 ETAP 6 (2026-06-16) — LLM Advisory Mesh orchestrator.

10 advisory agents, all hard-pinned advisory-only. Each agent:

1. Loads a fixed list of input artefacts (read-only).
2. Builds a structured prompt with explicit "advisory-only" framing.
3. Calls the existing LLM provider via ``shared/llm_provider_client.py``
   (if a key is present), or returns a deterministic fallback stub
   (when the provider is unavailable / dry-run).
4. Parses the response into an ``LLMAdvisoryOutput`` via
   ``shared/llm_advisory_authority.py``.
5. Validates via ``llm_advisory_authority.validate_output`` BEFORE
   anything is written to disk.
6. Writes the row to
   ``learning-loop/llm_advisory/<role>_latest.json``
   and appends to ``journal/autonomy/<date>.jsonl``.

HARD INVARIANTS
---------------
* NEVER imports ``shared/alpaca_orders.py``.
* NEVER calls any broker function (``submit_order`` / ``place_order``
  / ``safe_close`` / ``cancel_order`` / ``close_position`` /
  ``place_stock_order`` / ``place_crypto_order`` /
  ``place_option_order``).
* NEVER mutates ``runtime_state``, ``safe_mode``,
  ``broker_repair_required``, ``allocator gate state``, readiness
  counters, or any "live trading" / "broker paper" flag.
* NEVER writes to any file outside
  ``learning-loop/llm_advisory/`` and ``journal/autonomy/``.
* Every LLM response is passed through
  ``llm_advisory_authority.redact_secrets`` before being persisted.
* Budget cap is enforced via ``shared/llm_agent_budget.py``.
* Deterministic fallback returns ``recommendation=ALLOW``,
  ``risk_level=LOW``, ``confidence=LOW`` — LLM unavailability NEVER
  blocks trading by itself; deterministic gates remain final.

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_MODULE``
- ``NO_LLM_STATE_MUTATION``
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Local imports — keep advisory authority module first; never import
# alpaca_orders or any broker module.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "shared"))

from llm_advisory_authority import (              # noqa: E402
    ADVISORY_ROLES,
    AUTHORITY_LEVEL_ADVISORY,
    AUTHORITY_LEVEL_VETO_RECOMMEND,
    FORBIDDEN_OUTPUTS,
    STANDING_MARKERS,
    LLMAdvisoryOutput,
    make_advisory_output,
    redact_secrets,
    validate_output,
)

# ─── Status enum ────────────────────────────────────────────────────────────

MESH_STATUS_OK                  = "MESH_STATUS_OK"
MESH_STATUS_DRY_RUN             = "MESH_STATUS_DRY_RUN"
MESH_STATUS_PROVIDER_UNAVAILABLE = "MESH_STATUS_PROVIDER_UNAVAILABLE"
MESH_STATUS_BUDGET_EXHAUSTED    = "MESH_STATUS_BUDGET_EXHAUSTED"
MESH_STATUS_DETERMINISTIC_FALLBACK = "MESH_STATUS_DETERMINISTIC_FALLBACK"
# v3.30 (2026-06-16) — provider call status tokens surfaced into the
# audit row so the operator can attribute every advisory row to its
# provider behaviour.
PROVIDER_USED                  = "PROVIDER_USED"
PROVIDER_NOT_INVOKED           = "PROVIDER_NOT_INVOKED"
PROVIDER_TIMEOUT               = "PROVIDER_TIMEOUT"
PROVIDER_FAILED_FAIL_SOFT      = "PROVIDER_FAILED_FAIL_SOFT"


class _MarkLowQuality(Exception):
    """Internal control-flow marker used by ``run_agent`` to break out
    of the OK-branch when the v3.30 quality gate rejects the LLM
    response. Never propagated outside the module."""
    pass

# ─── Default input artefacts per agent ──────────────────────────────────────

_DEFAULT_INPUTS_PER_AGENT: dict[str, tuple[str, ...]] = {
    "INCIDENT_REVIEW": (
        "journal/autonomy/<today>.jsonl",
        "learning-loop/incidents/latest.json",
    ),
    "RISK_REVIEW": (
        "learning-loop/runtime_state.json",
        "learning-loop/risk_budget_latest.json",
    ),
    "STRATEGY_REVIEW": (
        "learning-loop/state.json",
        "reports/strategy-coherence/latest.json",
    ),
    "NO_SIGNAL_DIAGNOSTIC": (
        "learning-loop/shadow_evidence/workflow_health_latest.json",
        "learning-loop/shadow_evidence/evidence_counters_latest.json",
    ),
    "SHADOW_CANDIDATE_REVIEW": (
        "learning-loop/shadow_candidate_queue/latest.json",
        "learning-loop/shadow_evidence/evidence_counters_latest.json",
    ),
    "TRIGGER_WATCHLIST_REVIEW": (
        "learning-loop/trigger_watchlist/latest.json",
    ),
    "DAILY_BRIEF": (
        "learning-loop/system_activation_status_latest.json",
        "learning-loop/runtime_state.json",
        "learning-loop/equity_gap_report_latest.json",
    ),
    "ALLOCATOR_PLAN_CRITIC": (
        "learning-loop/allocator_plan_latest.json",
        "learning-loop/allocator_gate_latest.json",
    ),
    "EQUITY_RECONCILIATION_CRITIC": (
        "learning-loop/equity_gap_report_latest.json",
        "learning-loop/safe_mode_consistency_latest.json",
    ),
    "FINAL_ARBITER": (
        "learning-loop/llm_advisory/INCIDENT_REVIEW_latest.json",
        "learning-loop/llm_advisory/RISK_REVIEW_latest.json",
        "learning-loop/llm_advisory/STRATEGY_REVIEW_latest.json",
        "learning-loop/llm_advisory/DAILY_BRIEF_latest.json",
    ),
}


# ─── Per-agent prompt templates (advisory-only) ────────────────────────────

_PROMPT_HEADER = (
    "You are an ADVISORY ONLY agent inside a paper-trading risk system.\n"
    "Your role: {role}.\n"
    "Authority: {auth}. You CANNOT execute orders, modify risk\n"
    "thresholds, clear safe_mode, flip broker flags, place orders,\n"
    "promote variants, or override any deterministic gate.\n"
    "Your output is read-only advice for an operator and for the\n"
    "deterministic gates. The deterministic gates remain final.\n"
)

_PROMPT_FOOTER = (
    "\nReturn ONE JSON object — no prose outside — with these keys:\n"
    "{\n"
    "  \"findings\":            <one short paragraph>,\n"
    "  \"risk_level\":          \"LOW\" | \"MEDIUM\" | \"HIGH\" | \"CRITICAL\",\n"
    "  \"recommendation\":      \"ALLOW\" | \"REVIEW\" | \"WATCH\" | \"CAUTION\" | \"BLOCK_RECOMMENDED\",\n"
    "  \"veto_recommendation\": true | false,\n"
    "  \"confidence\":          \"LOW\" | \"MEDIUM\" | \"HIGH\",\n"
    "  \"limitations\":         <one short paragraph>\n"
    "}\n"
    "You MUST NOT include any of the following tokens in any field:\n"
    "EXECUTE_ORDER, PLACE_ORDER, CLEAR_SAFE_MODE, FLIP_BROKER_FLAG,\n"
    "MUTATE_THRESHOLD, PROMOTE_VARIANT, OVERRIDE_GATE.\n"
)


def _build_prompt(role: str, evidence: dict, authority_level: str) -> str:
    """Render a structured prompt for ``role`` given ``evidence``."""
    head = _PROMPT_HEADER.format(role=role, auth=authority_level)
    body = "\nEvidence (read-only, may be partial):\n"
    try:
        body += json.dumps(evidence, sort_keys=True, default=str)[:3000]
    except Exception:
        body += "{}"
    return head + body + _PROMPT_FOOTER


# ─── Helpers ────────────────────────────────────────────────────────────────

def _safe_load(path: Path) -> Any:
    """Read JSON / JSONL / text; return None on any error. NEVER raises."""
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
            return out[-50:]  # truncate
        return path.read_text(encoding="utf-8")[:5000]
    except Exception:
        return None


def _gather_evidence_for_role(role: str) -> dict:
    """Load all default-input artefacts for ``role`` (read-only)."""
    today = datetime.now(timezone.utc).date().isoformat()
    evidence: dict[str, Any] = {}
    for spec in _DEFAULT_INPUTS_PER_AGENT.get(role, ()):
        path_str = spec.replace("<today>", today)
        p = REPO_ROOT / path_str
        value = _safe_load(p)
        evidence[path_str] = value if value is not None else None
    return evidence


def _advisory_out_dir() -> Path:
    override = os.environ.get("LLM_ADVISORY_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "learning-loop" / "llm_advisory"


def _journal_dir() -> Path:
    override = os.environ.get("AUTONOMY_JOURNAL_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "journal" / "autonomy"


def _parse_llm_response_to_fields(text: str) -> dict[str, Any]:
    """Extract advisory fields from a free-form LLM response. Returns
    a dict with safe defaults. NEVER raises.

    v3.30 (2026-06-16) — also surfaces ``parsed_raw`` (the raw dict
    parsed from the JSON object) so the quality enforcement layer can
    inspect list-shaped fields directly.
    """
    out = {
        "findings":            "",
        "risk_level":          "LOW",
        "recommendation":      "REVIEW",
        "veto_recommendation": False,
        "confidence":          "LOW",
        "limitations":         "",
        # v3.30 — pass parsed JSON through for quality eval.
        "parsed_raw":          {},
    }
    if not text:
        return out
    # Try a direct JSON parse.
    parsed: dict | None = None
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        v = json.loads(stripped)
        if isinstance(v, dict):
            parsed = v
    except Exception:
        first = stripped.find("{")
        last  = stripped.rfind("}")
        if first >= 0 and last > first:
            try:
                v = json.loads(stripped[first:last + 1])
                if isinstance(v, dict):
                    parsed = v
            except Exception:
                parsed = None
    if parsed is None:
        out["findings"] = stripped[:600] or "insufficient evidence"
        return out
    # Map fields with safe fallbacks.
    out["findings"] = str(parsed.get("findings") or "")[:1500]
    out["limitations"] = str(parsed.get("limitations") or "")[:1500]
    rl = str(parsed.get("risk_level") or "LOW").upper()
    if rl in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        out["risk_level"] = rl
    rec = str(parsed.get("recommendation") or "REVIEW").upper()
    if rec in {"ALLOW", "REVIEW", "WATCH", "CAUTION",
                "BLOCK_RECOMMENDED"}:
        out["recommendation"] = rec
    veto = parsed.get("veto_recommendation", False)
    out["veto_recommendation"] = bool(veto) if isinstance(
        veto, (bool, int)) else False
    conf = str(parsed.get("confidence") or "LOW").upper()
    if conf in {"LOW", "MEDIUM", "HIGH"}:
        out["confidence"] = conf
    out["parsed_raw"] = parsed
    return out


def _deterministic_fallback(role: str,
                              input_artifacts: tuple[str, ...]
                              ) -> LLMAdvisoryOutput:
    """Build a deterministic-fallback advisory output.

    fail-OPEN at the advisory layer: ``recommendation=ALLOW`` so LLM
    unavailability NEVER blocks trading by itself. Deterministic
    gates still control the system.

    v3.30 (2026-06-16) — the ``findings`` field is now a semicolon-joined
    triple of structured points and ``limitations`` is the v3.30 stub
    text, so the persisted row meets the quality thresholds when the
    LLM is unavailable.
    """
    try:
        try:
            from llm_advisory_quality_v3300 import (
                deterministic_stub_lists)
        except ImportError:
            from shared.llm_advisory_quality_v3300 import (
                deterministic_stub_lists)
        stub = deterministic_stub_lists(role)
        findings_str = " ; ".join(stub["findings_list"])
        limitations_str = stub["limitations"]
    except Exception:
        findings_str = (
            f"LLM provider unavailable for {role}; deterministic "
            "fallback active. Deterministic gates remain final.")
        limitations_str = (
            "This output is a deterministic placeholder. It carries no "
            "model evaluation and no evidence inference. Operators "
            "and deterministic gates should rely on the existing "
            "deterministic stack.")
    return make_advisory_output(
        agent_name=role,
        authority_level=AUTHORITY_LEVEL_ADVISORY,
        input_artifacts=input_artifacts,
        findings=findings_str,
        risk_level="LOW",
        recommendation="ALLOW",
        veto_recommendation=False,
        confidence="LOW",
        limitations=limitations_str,
    )


def _budget_allows(agent_name: str | None = None) -> bool:
    """Best-effort budget gate. Returns True when the call may proceed.

    NEVER raises. Falls back to True if the budget module is absent
    (the deterministic fallback path will still emit an ALLOW stub).

    v3.30 (2026-06-16) — when ``agent_name`` is provided, also enforces
    the per-agent per-day cap.
    """
    try:
        import llm_agent_budget as budget  # type: ignore
    except Exception:
        return True
    try:
        if not budget.llm_agents_enabled():
            return False
        status, _reason = budget.check_budget(
            run_id=f"mesh-{uuid.uuid4().hex[:8]}")
        if status in (
            getattr(budget, "LLM_BUDGET_DISABLED", "DISABLED"),
            getattr(budget, "LLM_BUDGET_EXHAUSTED_DAILY", "EX_D"),
            getattr(budget, "LLM_BUDGET_EXHAUSTED_RUN", "EX_R"),
            getattr(budget, "LLM_PROVIDER_KEY_MISSING", "NK"),
        ):
            return False
        # v3.30 — per-agent budget.
        if agent_name and hasattr(budget, "check_per_agent_budget"):
            try:
                pa_status, _pa_reason = budget.check_per_agent_budget(
                    agent_name=agent_name)
                if pa_status == getattr(
                        budget, "LLM_BUDGET_EXHAUSTED_PER_AGENT",
                        "PA_EX"):
                    return False
            except Exception:
                # Fail-soft: per-agent check error never blocks the run.
                pass
        return True
    except Exception:
        return True


# v3.30 — module-level rate-limiter state. Single process, single
# wall-clock timestamp. NEVER persisted to disk (the rate limit is a
# safety throttle, not budget accounting).
_LAST_PROVIDER_CALL_TS: float = 0.0


def _apply_rate_limit() -> None:
    """Sleep just enough to honour the configured minimum gap between
    consecutive provider calls. NEVER raises."""
    global _LAST_PROVIDER_CALL_TS
    try:
        import llm_agent_budget as budget  # type: ignore
        min_gap = budget.min_seconds_between_calls()
    except Exception:
        min_gap = 6.0
    if min_gap <= 0:
        _LAST_PROVIDER_CALL_TS = time.monotonic()
        return
    now = time.monotonic()
    delta = now - _LAST_PROVIDER_CALL_TS
    if _LAST_PROVIDER_CALL_TS > 0 and delta < min_gap:
        try:
            time.sleep(min_gap - delta)
        except Exception:
            pass
    _LAST_PROVIDER_CALL_TS = time.monotonic()


def _resolve_provider_timeout() -> float:
    try:
        import llm_agent_budget as budget  # type: ignore
        return float(budget.per_call_timeout_seconds())
    except Exception:
        return 60.0


def _call_provider_safe(prompt: str) -> tuple[str, str]:
    """Call the LLM provider in a fully fail-soft manner.

    Returns ``(status, text)``. ``status`` is either
    ``"PROVIDER_OK"`` (text is the model output) or
    ``"PROVIDER_UNAVAILABLE"`` (text is empty / diagnostic).

    v3.30 (2026-06-16) — honours per-call timeout + rate limit.
    """
    try:
        import llm_provider_client as _p  # type: ignore
    except Exception:
        return ("PROVIDER_UNAVAILABLE", "")
    _apply_rate_limit()
    timeout_s = _resolve_provider_timeout()
    try:
        resp = _p.call_provider(
            prompt=prompt, max_tokens=512,
            timeout_seconds=timeout_s,
        )
    except Exception:
        return ("PROVIDER_UNAVAILABLE", "")
    if resp.status == getattr(_p, "LLM_PROVIDER_CALL_OK", "OK"):
        # v3.30 — even on OK status, redact secret-shaped tokens before
        # returning to the caller. The mesh redacts again on disk write
        # (belt-and-braces).
        return ("PROVIDER_OK", redact_secrets(resp.text or ""))
    return ("PROVIDER_UNAVAILABLE", "")


# ─── Public API ─────────────────────────────────────────────────────────────

def run_agent(role: str, *, dry_run: bool = False) -> LLMAdvisoryOutput:
    """Run a single advisory agent and return its validated output.

    HARD INVARIANTS
    ---------------
    * NEVER calls broker.
    * NEVER mutates state.
    * Writes only to ``learning-loop/llm_advisory/<role>_latest.json``
      and appends to ``journal/autonomy/<date>.jsonl``.
    * Falls back to ``_deterministic_fallback`` if anything fails.
    """
    if role not in ADVISORY_ROLES:
        raise ValueError(
            f"unknown advisory role: {role!r}; must be one of "
            f"{sorted(ADVISORY_ROLES)}")
    input_artifacts = _DEFAULT_INPUTS_PER_AGENT.get(role, ())
    # Decide which authority level applies. INCIDENT_REVIEW,
    # ALLOCATOR_PLAN_CRITIC, EQUITY_RECONCILIATION_CRITIC and
    # FINAL_ARBITER may recommend a veto (L1); the rest are L0.
    if role in {"INCIDENT_REVIEW", "ALLOCATOR_PLAN_CRITIC",
                  "EQUITY_RECONCILIATION_CRITIC", "FINAL_ARBITER"}:
        authority_level = AUTHORITY_LEVEL_VETO_RECOMMEND
    else:
        authority_level = AUTHORITY_LEVEL_ADVISORY

    # v3.30 (2026-06-16) — quality verdict + provider-call audit fields,
    # initialised so they're always present on the persisted row.
    quality_verdict_dict: dict = {
        "verdict": "LLM_ADVISORY_QUALITY_EMPTY",
        "rationale": ["no provider call attempted"],
        "findings_count": 0,
        "risks_count": 0,
        "next_actions_count": 0,
        "limitations_len": 0,
    }
    provider_called    = False
    provider_status    = "PROVIDER_NOT_INVOKED"
    parsed_lists: dict = {"findings_list": [], "risks_list": [],
                          "next_actions_list": []}

    # v3.30 — quality module import. NEVER raises out of this block;
    # failure routes to the deterministic fallback path.
    try:
        try:
            import llm_advisory_quality_v3300 as _qual  # type: ignore
        except ImportError:
            from shared import llm_advisory_quality_v3300 as _qual  # type: ignore
    except Exception:
        _qual = None  # type: ignore

    if dry_run:
        output = _deterministic_fallback(role, input_artifacts)
    elif not _budget_allows(agent_name=role):
        output = _deterministic_fallback(role, input_artifacts)
    else:
        evidence = _gather_evidence_for_role(role)
        prompt = _build_prompt(role, evidence, authority_level)
        provider_called = True
        status, text = _call_provider_safe(prompt)
        provider_status = status
        if status != "PROVIDER_OK" or not text:
            # v3.30 — empty text with status=OK is functionally a
            # failure; downgrade the audit attribution so the persisted
            # row distinguishes a real successful response from an
            # empty one.
            if status == "PROVIDER_OK" and not text:
                provider_status = "PROVIDER_EMPTY_RESPONSE"
            output = _deterministic_fallback(role, input_artifacts)
        else:
            redacted = redact_secrets(text)
            fields = _parse_llm_response_to_fields(redacted)
            try:
                # v3.30 — quality gate BEFORE building the dataclass.
                if _qual is not None:
                    parsed_raw = fields.get("parsed_raw") or {}
                    parsed_lists = _qual.extract_lists_from_parsed(
                        parsed_raw)
                    verdict = _qual.evaluate(
                        parsed_raw,
                        limitations=fields["limitations"])
                    quality_verdict_dict = verdict.to_dict()
                    if verdict.verdict != \
                            _qual.LLM_ADVISORY_QUALITY_ACCEPTABLE:
                        # Low-quality / empty -> deterministic fallback.
                        output = _deterministic_fallback(
                            role, input_artifacts)
                        # Skip the rest of the OK branch.
                        raise _MarkLowQuality()
                output = make_advisory_output(
                    agent_name=role,
                    authority_level=authority_level,
                    input_artifacts=input_artifacts,
                    findings=fields["findings"],
                    risk_level=fields["risk_level"],
                    recommendation=fields["recommendation"],
                    veto_recommendation=fields["veto_recommendation"],
                    confidence=fields["confidence"],
                    limitations=fields["limitations"],
                )
                # Belt-and-braces — re-validate.
                errs = validate_output(output)
                if errs:
                    output = _deterministic_fallback(
                        role, input_artifacts)
            except _MarkLowQuality:
                # already handled; output is the fallback
                pass
            except Exception:
                output = _deterministic_fallback(
                    role, input_artifacts)

    # Persist. Validation has already run via __post_init__; one more
    # validate_output() call gives us a guard in case of future drift.
    errs = validate_output(output)
    if errs:
        # If the rendered output cannot validate, drop the row entirely
        # and emit a deterministic fallback so the disk artefact
        # remains schema-correct.
        output = _deterministic_fallback(role, input_artifacts)

    payload = output.to_dict()
    payload["run_id"]     = f"mesh-{uuid.uuid4().hex[:12]}"
    payload["generated_at_iso"] = datetime.now(timezone.utc).isoformat()
    payload["dry_run"]    = bool(dry_run)
    # Final redaction sweep on the assembled dict.
    payload["findings"]    = redact_secrets(payload.get("findings", ""))
    payload["limitations"] = redact_secrets(
        payload.get("limitations", ""))
    # v3.30 (2026-06-16) — quality verdict + provider attribution +
    # parsed-list mirror so downstream audits can inspect what the
    # gate decided.
    payload["quality_verdict"]  = quality_verdict_dict.get(
        "verdict") or "LLM_ADVISORY_QUALITY_EMPTY"
    payload["quality_report"]   = quality_verdict_dict
    payload["provider_status"]  = (
        PROVIDER_USED if provider_status == "PROVIDER_OK"
        else PROVIDER_NOT_INVOKED if not provider_called
        else PROVIDER_FAILED_FAIL_SOFT)
    # v3.30 — when a provider returned OK with empty text, surface the
    # PROVIDER_FAILED_FAIL_SOFT audit token (we never set PROVIDER_USED
    # for an empty response).
    if provider_status == "PROVIDER_EMPTY_RESPONSE":
        payload["provider_status"] = PROVIDER_FAILED_FAIL_SOFT
    payload["provider_called"]  = bool(provider_called)
    payload["findings_list"]    = list(
        parsed_lists.get("findings_list") or [])
    payload["risks_list"]       = list(
        parsed_lists.get("risks_list") or [])
    payload["next_actions_list"] = list(
        parsed_lists.get("next_actions_list") or [])

    # If the persisted output came from the deterministic fallback,
    # mirror the stub list-fields into the payload so the row meets the
    # v3.30 list contract end-to-end.
    if not payload["findings_list"] and not payload["risks_list"] \
            and not payload["next_actions_list"]:
        try:
            try:
                from llm_advisory_quality_v3300 import (
                    deterministic_stub_lists)
            except ImportError:
                from shared.llm_advisory_quality_v3300 import (
                    deterministic_stub_lists)
            stub = deterministic_stub_lists(role)
            payload["findings_list"]     = list(stub["findings_list"])
            payload["risks_list"]        = list(stub["risks_list"])
            payload["next_actions_list"] = list(stub["next_actions_list"])
        except Exception:
            pass

    out_dir = _advisory_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    latest_path = out_dir / f"{role}_latest.json"
    latest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    # v3.30 — record the call against the per-agent budget when the
    # provider actually produced a usable response. NEVER raises.
    if provider_called and provider_status == "PROVIDER_OK":
        try:
            try:
                import llm_agent_budget as _budget  # type: ignore
            except Exception:
                _budget = None  # type: ignore
            if _budget is not None and hasattr(_budget, "record_call"):
                _budget.record_call(
                    run_id=payload["run_id"],
                    cost_usd=0.0,
                    agent_name=role,
                )
        except Exception:
            pass

    # Append to journal/autonomy/<date>.jsonl (append-only audit log).
    jdir = _journal_dir()
    jdir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    jpath = jdir / f"{today}.jsonl"
    journal_row = {
        "event":        "LLM_ADVISORY_OUTPUT",
        "agent_name":   role,
        "advisory_only": True,
        "must_not_execute_orders": True,
        "broker_order_submitted":  False,
        "recommendation": payload.get("recommendation"),
        "risk_level":     payload.get("risk_level"),
        "confidence":     payload.get("confidence"),
        "dry_run":        bool(dry_run),
        "standing_markers": list(STANDING_MARKERS),
        # v3.30 audit attribution.
        "quality_verdict":  payload["quality_verdict"],
        "provider_status":  payload["provider_status"],
        "provider_called":  payload["provider_called"],
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with jpath.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(journal_row, sort_keys=True) + "\n")
    except Exception:
        pass

    return output


def run_mesh(*, dry_run: bool = False) -> list[LLMAdvisoryOutput]:
    """Run every agent in ``ADVISORY_ROLES`` and return the list of
    validated outputs. NEVER raises.
    """
    outputs: list[LLMAdvisoryOutput] = []
    for role in sorted(ADVISORY_ROLES):
        try:
            out = run_agent(role, dry_run=dry_run)
        except Exception:
            out = _deterministic_fallback(
                role, _DEFAULT_INPUTS_PER_AGENT.get(role, ()))
            try:
                payload = out.to_dict()
                payload["run_id"] = f"mesh-{uuid.uuid4().hex[:12]}"
                payload["generated_at_iso"] = (
                    datetime.now(timezone.utc).isoformat())
                payload["dry_run"] = bool(dry_run)
                out_dir = _advisory_out_dir()
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"{role}_latest.json").write_text(
                    json.dumps(payload, indent=2, sort_keys=True) +
                    "\n", encoding="utf-8")
            except Exception:
                pass
        outputs.append(out)
    return outputs


def enumerate_agents() -> tuple[str, ...]:
    """Return the canonical sorted tuple of advisory role names."""
    return tuple(sorted(ADVISORY_ROLES))


__all__ = [
    "MESH_STATUS_OK",
    "MESH_STATUS_DRY_RUN",
    "MESH_STATUS_PROVIDER_UNAVAILABLE",
    "MESH_STATUS_BUDGET_EXHAUSTED",
    "MESH_STATUS_DETERMINISTIC_FALLBACK",
    # v3.30
    "PROVIDER_USED",
    "PROVIDER_NOT_INVOKED",
    "PROVIDER_TIMEOUT",
    "PROVIDER_FAILED_FAIL_SOFT",
    "run_agent",
    "run_mesh",
    "enumerate_agents",
]
