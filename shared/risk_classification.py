"""shared/risk_classification.py — unified intraday-first risk verdict taxonomy.

v3.10 (2026-05-27): single source of truth for risk decisions across all
risk gates (risk_officer, portfolio_risk, pdt_guard, intraday_governor,
risk_guards, signal_confirmation, safe_close).

DESIGN PRINCIPLE (intraday-first):
Risk decisions are NOT binary (APPROVE/REJECT). The system optimises for
intraday flow + autonomous operation. A guard that returns generic "human-
in-the-loop" verdicts or unconditionally fails closed paralyzes the system.
Instead, every risk decision is classified into ONE of 5 verdicts below,
with explicit semantics:

  BLOCK       — krytyczny brak kontroli ryzyka, NIGDY nie wolno wykonać
                (np. account_blocked=true, paper-only invariant violation,
                buying_power < size, off-whitelist). Hard refusal.
  DEFER       — chwilowy brak danych lub market closed; retry next cron.
                Edge może być nadal dopuszczalny, tylko nie teraz.
                (Alpaca API outage, snapshot stale, pre-market for intraday signal)
  DOWNSIZE    — częściowa niepewność, ale edge nadal w grze.
                Zmniejsz sizing (e.g. 0.5×, 0.3×) i fire-and-forget.
                (partial confirmation, mid-range R:R, soft VIX warning)
  ALLOW       — komplet danych + risk pass, normalny sizing.
  ALERT_ONLY  — sygnał ciekawy ale bez pełnego potwierdzenia.
                NIE umieszczaj ordera; wyślij email + audit dla operator
                visibility. Często stosowane dla weak news signals.

EMERGENCY EXITS — never blocked by this taxonomy.
  Emergency closes (SL hit, hard_loss, PROFIT_LOCK, RED_DAY_AFTER_GREEN,
  REGIME mismatch options PUT) BYPASS all checks and proceed immediately.
  Reason: position management must always be able to dispose risk.

USAGE:
  from risk_classification import RiskVerdict, RiskDecision, new_decision_id

  verdict = decide_risk(...)
  if verdict.verdict == RiskVerdict.BLOCK:
      return
  if verdict.verdict == RiskVerdict.DEFER:
      return  # next cron will retry
  if verdict.verdict == RiskVerdict.DOWNSIZE:
      size *= verdict.size_multiplier
  if verdict.verdict == RiskVerdict.ALERT_ONLY:
      notify_alert(...); return  # no order
  # ALLOW → place order
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ─── Verdict enum ─────────────────────────────────────────────────────────────

class RiskVerdict(str, Enum):
    """Risk decision verdict — 5 mutually exclusive classes."""

    BLOCK       = "BLOCK"        # hard refusal; never place order
    DEFER       = "DEFER"        # transient unavailability; retry next cycle
    DOWNSIZE    = "DOWNSIZE"     # partial uncertainty; reduce size + proceed
    ALLOW       = "ALLOW"        # all checks passed; normal size
    ALERT_ONLY  = "ALERT_ONLY"   # interesting but unconfirmed; email + no order

    @property
    def is_terminal(self) -> bool:
        """BLOCK and ALERT_ONLY are terminal (no order). DEFER retries.
        DOWNSIZE and ALLOW proceed to order placement."""
        return self in (RiskVerdict.BLOCK, RiskVerdict.ALERT_ONLY)

    @property
    def allows_order(self) -> bool:
        """True iff caller should proceed to order placement."""
        return self in (RiskVerdict.ALLOW, RiskVerdict.DOWNSIZE)


# Severity ordering — for combining multiple verdicts (worst wins)
_SEVERITY_RANK: dict[RiskVerdict, int] = {
    RiskVerdict.ALLOW:      0,
    RiskVerdict.ALERT_ONLY: 1,
    RiskVerdict.DOWNSIZE:   2,
    RiskVerdict.DEFER:      3,
    RiskVerdict.BLOCK:      4,
}


def worst(*verdicts: RiskVerdict) -> RiskVerdict:
    """Return the most-restrictive verdict from the input list.
    BLOCK > DEFER > DOWNSIZE > ALERT_ONLY > ALLOW.
    Used when combining multiple risk checks (e.g. VIX + drawdown + PDT)."""
    if not verdicts:
        return RiskVerdict.ALLOW
    return max(verdicts, key=lambda v: _SEVERITY_RANK[v])


# ─── Decision ID ──────────────────────────────────────────────────────────────

def new_decision_id() -> str:
    """Generate a sortable, unique decision ID for audit correlation.

    Format: <ts_compact_with_us>-<rand8>
    Example: 20260527T193045123456-a3f9b1c2
    Microsecond timestamp + 32 random bits = collision-resistant for 10^6+
    calls/second (birthday paradox safe to ~65k IDs/sec).

    Original 24-bit random was caught by test_uniqueness CI failure at
    1000 IDs/run (~3% collision rate)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    rand = secrets.token_hex(4)  # 8 hex chars = 32 bits
    return f"{ts}-{rand}"


# ─── Decision record ──────────────────────────────────────────────────────────

@dataclass
class RiskDecision:
    """Output of a risk check. Carries verdict + context for downstream
    audit + sizing adjustment.

    Fields:
      verdict:         RiskVerdict enum value
      reason:          human-readable explanation (≤200 chars typical)
      gate:            which check produced this (e.g. "risk_officer",
                       "pdt_guard", "signal_confirmation")
      size_multiplier: only meaningful when verdict==DOWNSIZE (else 1.0)
      decision_id:     unique ID for audit correlation
      timestamp:       ISO8601 UTC
      metadata:        additional context (snapshot hashes, signal data, etc.)
      retry_after_s:   only for DEFER — hint how soon to retry (default 60s)
    """

    verdict: RiskVerdict
    reason: str
    gate: str = "unknown"
    size_multiplier: float = 1.0
    decision_id: str = field(default_factory=new_decision_id)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)
    retry_after_s: Optional[int] = None

    def __post_init__(self):
        # Clamp size_multiplier to [0.0, 2.0] for safety
        if self.verdict == RiskVerdict.DOWNSIZE:
            self.size_multiplier = max(0.1, min(2.0, float(self.size_multiplier)))
        else:
            self.size_multiplier = 1.0
        # DEFER must have retry_after_s
        if self.verdict == RiskVerdict.DEFER and self.retry_after_s is None:
            self.retry_after_s = 60

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), default=str, sort_keys=True)

    @property
    def allows_order(self) -> bool:
        return self.verdict.allows_order


# ─── Convenience constructors ─────────────────────────────────────────────────

def allow(reason: str = "all checks passed", gate: str = "unknown",
          **metadata: Any) -> RiskDecision:
    return RiskDecision(
        verdict=RiskVerdict.ALLOW, reason=reason, gate=gate, metadata=metadata
    )


def block(reason: str, gate: str = "unknown", **metadata: Any) -> RiskDecision:
    return RiskDecision(
        verdict=RiskVerdict.BLOCK, reason=reason, gate=gate, metadata=metadata
    )


def defer(reason: str, gate: str = "unknown", retry_after_s: int = 60,
          **metadata: Any) -> RiskDecision:
    return RiskDecision(
        verdict=RiskVerdict.DEFER, reason=reason, gate=gate,
        retry_after_s=retry_after_s, metadata=metadata,
    )


def downsize(reason: str, size_multiplier: float = 0.5, gate: str = "unknown",
             **metadata: Any) -> RiskDecision:
    return RiskDecision(
        verdict=RiskVerdict.DOWNSIZE, reason=reason, gate=gate,
        size_multiplier=size_multiplier, metadata=metadata,
    )


def alert_only(reason: str, gate: str = "unknown",
               **metadata: Any) -> RiskDecision:
    return RiskDecision(
        verdict=RiskVerdict.ALERT_ONLY, reason=reason, gate=gate,
        metadata=metadata,
    )


# ─── Helper: combine multiple decisions ──────────────────────────────────────

def combine(*decisions: RiskDecision) -> RiskDecision:
    """Combine multiple risk decisions into one final verdict.

    Logic:
      - Worst verdict wins (BLOCK > DEFER > DOWNSIZE > ALERT_ONLY > ALLOW)
      - If multiple DOWNSIZE → final size_multiplier = product (all reduce)
      - reason = concatenated (truncated to 300 chars)
      - decision_id = new (this is a composite decision)
      - gate = "combined"
      - metadata aggregates all input metadata under per-gate keys
    """
    if not decisions:
        return allow(reason="no gates evaluated", gate="combined")

    final_verdict = worst(*[d.verdict for d in decisions])

    # Combine size multipliers (only meaningful for DOWNSIZE)
    size_mult = 1.0
    for d in decisions:
        if d.verdict == RiskVerdict.DOWNSIZE:
            size_mult *= d.size_multiplier
    size_mult = max(0.05, min(2.0, size_mult))

    # Pick the dominant decision's reason (worst verdict tie-broken by gate name)
    dominant = max(decisions, key=lambda d: (_SEVERITY_RANK[d.verdict], d.gate))
    reasons = [f"[{d.gate}] {d.reason}" for d in decisions
               if d.verdict != RiskVerdict.ALLOW]
    composite_reason = " ; ".join(reasons)[:300] or dominant.reason

    # Aggregate metadata under gate names
    meta = {d.gate: d.metadata for d in decisions if d.metadata}

    retry_s = max(
        (d.retry_after_s for d in decisions if d.retry_after_s is not None),
        default=None,
    )

    return RiskDecision(
        verdict=final_verdict,
        reason=composite_reason,
        gate="combined",
        size_multiplier=size_mult if final_verdict == RiskVerdict.DOWNSIZE else 1.0,
        retry_after_s=retry_s if final_verdict == RiskVerdict.DEFER else None,
        metadata=meta,
    )
