"""v3.28 (2026-06-09) — LLM pre-order advisory module.

Provides a deterministic advisory layer that callers MAY consult
before constructing an order. The advisory layer NEVER executes —
it returns one of seven verdicts and the deterministic risk_officer
remains the final authority.

HARD SAFETY (cannot be opted out of)
------------------------------------
- NEVER imports the broker-orders module (asserted by test).
- NEVER calls any order-submission helper from the broker module.
- NEVER returns an ``EXECUTE`` verdict — the verdict enum does not
  include it.
- ``VETO_RECOMMENDED`` may block or downgrade ONLY when the
  deterministic config flag ``LLM_PRE_ORDER_VETO_HONORED=true`` is
  set; otherwise the verdict is observational.
- ``PASS`` CANNOT force a trade — the caller still runs all
  deterministic gates.
- ``SKIPPED_*`` CANNOT block safety-critical deterministic gates.
- ``ERROR_FAIL_SOFT`` always returns PASS-equivalent semantics:
  caller behaves exactly as if the advisory had not been consulted.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ─── Verdict enum ───────────────────────────────────────────────────────────

ADVISORY_PASS                   = "ADVISORY_PASS"
ADVISORY_WARN                   = "ADVISORY_WARN"
ADVISORY_VETO_RECOMMENDED       = "ADVISORY_VETO_RECOMMENDED"
ADVISORY_SKIPPED_DISABLED       = "ADVISORY_SKIPPED_DISABLED"
ADVISORY_SKIPPED_BUDGET         = "ADVISORY_SKIPPED_BUDGET"
ADVISORY_SKIPPED_NO_PROVIDER    = "ADVISORY_SKIPPED_NO_PROVIDER"
ADVISORY_ERROR_FAIL_SOFT        = "ADVISORY_ERROR_FAIL_SOFT"

ALL_ADVISORY_VERDICTS: frozenset[str] = frozenset({
    ADVISORY_PASS, ADVISORY_WARN, ADVISORY_VETO_RECOMMENDED,
    ADVISORY_SKIPPED_DISABLED, ADVISORY_SKIPPED_BUDGET,
    ADVISORY_SKIPPED_NO_PROVIDER, ADVISORY_ERROR_FAIL_SOFT,
})

# Verdicts that downstream callers must treat as "do not let me block
# deterministic safety gates" — i.e. anything that is NOT a hard
# advisory veto.
NON_BLOCKING_VERDICTS: frozenset[str] = frozenset({
    ADVISORY_PASS, ADVISORY_WARN,
    ADVISORY_SKIPPED_DISABLED, ADVISORY_SKIPPED_BUDGET,
    ADVISORY_SKIPPED_NO_PROVIDER, ADVISORY_ERROR_FAIL_SOFT,
})


# ─── Result dataclass ──────────────────────────────────────────────────────

@dataclass
class AdvisoryResult:
    verdict:        str
    reason:         str
    agent_name:     str  = "PRE_ORDER_ADVISORY_AGENT"
    authority_level: str = "L3_VETO_RECOMMEND_ONLY"
    confidence:     float = 0.0
    risks:          list[str] = field(default_factory=list)
    rationale:      str   = ""

    def to_dict(self) -> dict:
        return {
            "verdict":          self.verdict,
            "reason":           self.reason,
            "agent_name":       self.agent_name,
            "authority_level":  self.authority_level,
            "confidence":       self.confidence,
            "risks":            list(self.risks),
            "rationale":        self.rationale,
            # Hard-coded advisory contract.
            "advisory_only":          True,
            "may_execute":            False,
            "may_modify_risk":        False,
            "may_unlock_broker_paper": False,
            "broker_order_submitted":  False,
            "broker_execution_enabled": False,
            "affects_readiness_gate":  False,
        }


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


def pre_order_veto_honored() -> bool:
    """Deterministic config flag.

    When ``true``, callers are permitted to downgrade or block based
    on a ``VETO_RECOMMENDED`` verdict. When ``false`` (default), the
    verdict is observational only — the deterministic risk_officer
    remains the final authority.
    """
    return _env_bool("LLM_PRE_ORDER_VETO_HONORED", False)


# ─── Decision API ──────────────────────────────────────────────────────────

def consult(
    *,
    draft_order_context: dict | None,
    run_id: str = "preorder-default",
) -> AdvisoryResult:
    """Run the pre-order advisory check. Returns a verdict.

    ``draft_order_context`` is a structured dict the caller passes
    in — symbol, side, size_usd, current_price, risk_envelope, etc.
    The advisory module NEVER mutates it and NEVER persists it.

    Decision flow:

    1. If ``LLM_AGENTS_ENABLED=false`` → ``ADVISORY_SKIPPED_DISABLED``.
    2. If budget exhausted or provider missing → ``SKIPPED_*``.
    3. If offline_mock provider → ``ADVISORY_PASS`` (mock cannot
       evaluate context).
    4. Otherwise, the caller's wrapper would invoke a real provider;
       this module returns a structured result for that wrapper.
    5. Any exception → ``ADVISORY_ERROR_FAIL_SOFT`` with PASS-equivalent
       semantics.
    """
    try:
        try:
            import llm_agent_budget as _b  # type: ignore
        except ImportError:
            from shared import llm_agent_budget as _b  # type: ignore
        status, reason = _b.check_budget(run_id=run_id)
        if status == _b.LLM_BUDGET_DISABLED:
            return AdvisoryResult(
                verdict=ADVISORY_SKIPPED_DISABLED,
                reason=reason, confidence=0.0)
        if status == _b.LLM_PROVIDER_KEY_MISSING:
            return AdvisoryResult(
                verdict=ADVISORY_SKIPPED_NO_PROVIDER,
                reason=reason, confidence=0.0)
        if status in (_b.LLM_BUDGET_EXHAUSTED_DAILY,
                       _b.LLM_BUDGET_EXHAUSTED_RUN):
            return AdvisoryResult(
                verdict=ADVISORY_SKIPPED_BUDGET,
                reason=reason, confidence=0.0)
        if status == _b.LLM_FAIL_SOFT:
            return AdvisoryResult(
                verdict=ADVISORY_ERROR_FAIL_SOFT,
                reason=reason, confidence=0.0)
        # status == LLM_BUDGET_ALLOWED → may proceed.
        try:
            import llm_provider_client as _p  # type: ignore
        except ImportError:
            from shared import llm_provider_client as _p  # type: ignore
        # Mock provider yields a PASS with a comment — no real call.
        if _b.provider() == "offline_mock":
            return AdvisoryResult(
                verdict=ADVISORY_PASS,
                reason="offline_mock provider — no real evaluation",
                confidence=0.0,
                rationale=("Caller should treat this as 'advisory "
                            "consulted but provider is mock'."),
            )
        # Real provider — render a short structured prompt and call.
        prompt = (
            "You are PRE_ORDER_ADVISORY_AGENT. Authority: "
            "L3_VETO_RECOMMEND_ONLY. You CANNOT execute. Review "
            "the draft-order context and respond ONLY with one of: "
            "ADVISORY_PASS | ADVISORY_WARN | ADVISORY_VETO_RECOMMENDED. "
            "Draft order context (advisory-only, no execution): "
            f"{json.dumps(draft_order_context or {}, sort_keys=True)[:1500]}"
        )
        resp = _p.call_provider(prompt=prompt, max_tokens=256)
        if resp.status == _p.LLM_PROVIDER_OFFLINE_MOCK:
            return AdvisoryResult(
                verdict=ADVISORY_PASS,
                reason="offline_mock", confidence=0.0)
        if resp.status != _p.LLM_PROVIDER_CALL_OK:
            return AdvisoryResult(
                verdict=ADVISORY_ERROR_FAIL_SOFT,
                reason=resp.status, confidence=0.0)
        try:
            _b.record_call(run_id=run_id, cost_usd=resp.cost_usd)
        except Exception:
            pass
        text = (resp.text or "").upper()
        if "VETO_RECOMMENDED" in text or "ADVISORY_VETO" in text:
            verdict = ADVISORY_VETO_RECOMMENDED
        elif "WARN" in text:
            verdict = ADVISORY_WARN
        else:
            verdict = ADVISORY_PASS
        return AdvisoryResult(
            verdict=verdict, reason="provider responded",
            confidence=0.5, rationale=resp.text[:300])
    except Exception as e:
        return AdvisoryResult(
            verdict=ADVISORY_ERROR_FAIL_SOFT,
            reason=f"{type(e).__name__}: {e}", confidence=0.0)


def is_blocking(verdict: str) -> bool:
    """Returns True iff the caller may block / downgrade based on
    this verdict — and only when the deterministic config flag
    ``LLM_PRE_ORDER_VETO_HONORED`` is set."""
    return (verdict == ADVISORY_VETO_RECOMMENDED
            and pre_order_veto_honored())


__all__ = [
    "ADVISORY_PASS", "ADVISORY_WARN",
    "ADVISORY_VETO_RECOMMENDED",
    "ADVISORY_SKIPPED_DISABLED", "ADVISORY_SKIPPED_BUDGET",
    "ADVISORY_SKIPPED_NO_PROVIDER", "ADVISORY_ERROR_FAIL_SOFT",
    "ALL_ADVISORY_VERDICTS", "NON_BLOCKING_VERDICTS",
    "AdvisoryResult",
    "pre_order_veto_honored",
    "consult", "is_blocking",
]
