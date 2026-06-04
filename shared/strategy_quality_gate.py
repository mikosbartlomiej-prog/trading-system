"""v3.18.0 (2026-06-04) — Strategy Quality Gate.

Closes audit-board STRAT-003 readiness for EDGE_GATE_ENABLED.

WHY
---
Audit-board verdict 2026-06-02: "NOT_SAFE_FOR_LIVE_TRADING; APPROVE PAPER
TRADING WITH WARNINGS". The system has no empirical evidence of edge.
EDGE_GATE_ENABLED therefore stays false. The gate decision must be
deterministic, auditable, and never auto-flip true.

This module provides:
  * classify_strategy(strategy, metrics, ...) → status string
  * edge_gate_decision(per_strategy_status) → (allow_flip_true, blockers)

It NEVER calls the broker. It NEVER recommends LIVE trading.
It NEVER flips EDGE_GATE_ENABLED itself — only reports readiness.

CONTRACT
--------
Statuses (closed enum):
  DISABLED                      — registry says NOT_APPLICABLE OR recent
                                  degradation (last 20 trades WR < 30%).
  REJECTED                      — audit incomplete OR recent risk violation.
  OBSERVE_ONLY                  — n_closed < 10.
  PAPER_CANDIDATE               — 10 ≤ n_closed < 50.
  PAPER_ENABLED                 — n_closed ≥ 30 AND PF ≥ 1.0.
  EDGE_CANDIDATE                — n_closed ≥ 50 AND PF ≥ 1.1, but missing
                                  stability across regimes / drawdown bad.
  EDGE_APPROVED_FOR_EXPERIMENT  — n_closed ≥ 50 AND WR ≥ 50% AND PF ≥ 1.3
                                  AND positive net P&L after fees/slippage
                                  AND max_dd < 25% AND positive in ≥ 2 regimes.

LIVE_APPROVED is intentionally NOT in this set.

OPERATOR OVERRIDE
-----------------
Even with all criteria met, EDGE_GATE_ENABLED only flips true when:
  1. At least 2 strategies classified EDGE_APPROVED_FOR_EXPERIMENT.
  2. No strategies REJECTED.
  3. All audit-board P0/P1 findings cleared (best-effort check).
  4. Operator explicitly sets env var (NOT this module).

EVERY classification emits a JSONL audit line so future humans can
reconstruct why a status was chosen.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─── Statuses ─────────────────────────────────────────────────────────────────

DISABLED                      = "DISABLED"
REJECTED                      = "REJECTED"
OBSERVE_ONLY                  = "OBSERVE_ONLY"
PAPER_CANDIDATE               = "PAPER_CANDIDATE"
PAPER_ENABLED                 = "PAPER_ENABLED"
EDGE_CANDIDATE                = "EDGE_CANDIDATE"
EDGE_APPROVED_FOR_EXPERIMENT  = "EDGE_APPROVED_FOR_EXPERIMENT"

ALL_STATUSES = frozenset({
    DISABLED, REJECTED, OBSERVE_ONLY, PAPER_CANDIDATE,
    PAPER_ENABLED, EDGE_CANDIDATE, EDGE_APPROVED_FOR_EXPERIMENT,
})


# ─── Thresholds (deterministic) ───────────────────────────────────────────────

MIN_TRADES_FOR_DECISION    = 10
MIN_TRADES_FOR_PAPER       = 50
MIN_TRADES_FOR_PAPER_KEEP  = 30
MIN_WR_FOR_EDGE            = 0.50
MIN_PF_FOR_EDGE            = 1.30
MIN_PF_FOR_CANDIDATE       = 1.10
MIN_PF_FOR_KEEP            = 1.00
MAX_DD_FOR_EDGE            = 0.25
MIN_REGIMES_FOR_EDGE       = 2
RECENT_DEGRADATION_TRADES  = 20
RECENT_DEGRADATION_WR      = 0.30


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except (TypeError, ValueError):
        return default


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _emit_audit(strategy: str, status: str, reason: str,
                metrics: dict[str, Any] | None) -> None:
    """Emit a non-fatal JSONL audit entry for a classification decision.

    Fail-soft: if audit module is unavailable, return silently.
    """
    try:
        from shared.audit import write_audit_event   # type: ignore
        from shared.autonomy import make_decision    # type: ignore
    except Exception:
        try:
            from audit import write_audit_event       # type: ignore
            from autonomy import make_decision        # type: ignore
        except Exception:
            return

    # PAUSE_STRATEGY / RESUME_STRATEGY map well; we use them as the
    # canonical decision_type for strategy lifecycle.
    decision_type = "PAUSE_STRATEGY" if status in (
        DISABLED, REJECTED) else "RESUME_STRATEGY"
    try:
        d = make_decision(
            decision_type=decision_type,
            decision=status,
            reason=f"strategy-quality-gate: {reason}",
            actor="strategy-quality-gate",
            strategy=strategy,
            risk_metrics={
                "n_closed":      _safe_int((metrics or {}).get("n_closed")),
                "win_rate":      _safe_float((metrics or {}).get("win_rate")),
                "profit_factor": _safe_float((metrics or {}).get("profit_factor")),
                "max_drawdown":  _safe_float((metrics or {}).get("max_drawdown")),
            },
            reversible=True,
        )
        write_audit_event(d, kind="trading")
    except Exception:
        # Audit must never break classification.
        return


def _registry_lookup(strategy: str):
    """Best-effort registry lookup. Returns object or None."""
    try:
        from backtest.strategy_registry import REGISTRY  # type: ignore
        return REGISTRY.get(strategy)
    except Exception:
        return None


def _is_not_applicable(strategy: str) -> bool:
    reg = _registry_lookup(strategy)
    if reg is None:
        return False
    return getattr(reg, "readiness", "") == "NOT_APPLICABLE"


# ─── Public API: classify_strategy ────────────────────────────────────────────

def classify_strategy(
    strategy: str,
    metrics: dict[str, Any] | None,
    *,
    paper_metrics: dict[str, Any] | None = None,
    backtest_metrics: dict[str, Any] | None = None,
    audit_complete: bool = True,
    risk_violations_recent: int = 0,
    emit_audit: bool = True,
) -> str:
    """Return a single status string from ALL_STATUSES.

    Parameters
    ----------
    strategy : str
        Strategy name (must match registry / paper_experiment ledger).
    metrics : dict
        Default metrics dict (typically equal to paper_metrics).
    paper_metrics : dict, optional
        Explicit paper metrics from compute_strategy_metrics. Falls back
        to `metrics` when None.
    backtest_metrics : dict, optional
        Optional offline backtest summary (not required for classification;
        used for diagnostic only).
    audit_complete : bool
        If False → REJECTED (no decision without an audit run).
    risk_violations_recent : int
        Count of P0/P1 risk violations in last 7 days. >0 → REJECTED.
    emit_audit : bool
        Default True; set False in unit tests that already mock the
        audit module.
    """
    # ── Default-conservative classification ──────────────────────────────
    if not strategy or not isinstance(strategy, str):
        status = REJECTED
        reason = "missing strategy name"
        if emit_audit:
            _emit_audit("?", status, reason, metrics)
        return status

    # Registry NOT_APPLICABLE → DISABLED (admin tags, no signal)
    if _is_not_applicable(strategy):
        status = DISABLED
        reason = "registry NOT_APPLICABLE"
        if emit_audit:
            _emit_audit(strategy, status, reason, metrics)
        return status

    # ── Hard rejects ─────────────────────────────────────────────────────
    if not audit_complete:
        status = REJECTED
        reason = "audit incomplete"
        if emit_audit:
            _emit_audit(strategy, status, reason, metrics)
        return status

    if _safe_int(risk_violations_recent) > 0:
        status = REJECTED
        reason = f"recent risk violations ({risk_violations_recent})"
        if emit_audit:
            _emit_audit(strategy, status, reason, metrics)
        return status

    m = paper_metrics if paper_metrics is not None else (metrics or {})
    if not isinstance(m, dict):
        status = REJECTED
        reason = "metrics not a dict"
        if emit_audit:
            _emit_audit(strategy, status, reason, metrics)
        return status

    n = _safe_int(m.get("n_closed"))
    wr = _safe_float(m.get("win_rate"))
    pf = _safe_float(m.get("profit_factor"))
    max_dd = _safe_float(m.get("max_drawdown"))
    net_pnl = _safe_float(m.get("net_pnl_after_fees_slippage"))
    last_20_wr = _safe_float(m.get("last_20_win_rate"))

    # ── Recent degradation → DISABLED (only if we have enough data) ─────
    if n >= RECENT_DEGRADATION_TRADES and last_20_wr < RECENT_DEGRADATION_WR:
        status = DISABLED
        reason = (f"recent degradation: last_20_win_rate "
                  f"{last_20_wr:.0%} < {RECENT_DEGRADATION_WR:.0%}")
        if emit_audit:
            _emit_audit(strategy, status, reason, m)
        return status

    # ── Tiered evidence ladder ──────────────────────────────────────────
    if n < MIN_TRADES_FOR_DECISION:
        status = OBSERVE_ONLY
        reason = f"n_closed={n} < {MIN_TRADES_FOR_DECISION}"
        if emit_audit:
            _emit_audit(strategy, status, reason, m)
        return status

    if n < MIN_TRADES_FOR_PAPER:
        status = PAPER_CANDIDATE
        reason = (f"n_closed={n} in [10,50) — collecting evidence; "
                  f"WR={wr:.0%} PF={pf:.2f}")
        if emit_audit:
            _emit_audit(strategy, status, reason, m)
        return status

    # n >= 50 — check for full edge approval.
    regime_count = _count_positive_regimes(m)

    edge_ok = (
        wr      >= MIN_WR_FOR_EDGE
        and pf      >= MIN_PF_FOR_EDGE
        and net_pnl >  0.0
        and max_dd  <  MAX_DD_FOR_EDGE
        and regime_count >= MIN_REGIMES_FOR_EDGE
    )

    if edge_ok:
        status = EDGE_APPROVED_FOR_EXPERIMENT
        reason = (f"n={n} WR={wr:.0%} PF={pf:.2f} netPnL={net_pnl:+.2f} "
                  f"maxDD={max_dd:.0%} regimes={regime_count}")
        if emit_audit:
            _emit_audit(strategy, status, reason, m)
        return status

    if pf >= MIN_PF_FOR_CANDIDATE:
        status = EDGE_CANDIDATE
        reason = (f"n={n} PF={pf:.2f}>={MIN_PF_FOR_CANDIDATE} but "
                  f"WR={wr:.0%}, regimes={regime_count}, maxDD={max_dd:.0%}, "
                  f"netPnL={net_pnl:+.2f}")
        if emit_audit:
            _emit_audit(strategy, status, reason, m)
        return status

    # Still trading paper at this point — PAPER_ENABLED if PF doesn't sink.
    if n >= MIN_TRADES_FOR_PAPER_KEEP and pf >= MIN_PF_FOR_KEEP:
        status = PAPER_ENABLED
        reason = f"n={n} PF={pf:.2f}>={MIN_PF_FOR_KEEP} — keep collecting"
        if emit_audit:
            _emit_audit(strategy, status, reason, m)
        return status

    # n >= 50 but PF < 1.0 → DISABLED (worse than coin flip after costs)
    status = DISABLED
    reason = (f"n={n} PF={pf:.2f}<1.0 — negative expectancy after costs "
              f"(netPnL={net_pnl:+.2f})")
    if emit_audit:
        _emit_audit(strategy, status, reason, m)
    return status


def _count_positive_regimes(metrics: dict[str, Any]) -> int:
    """Number of regimes with positive expectancy AND ≥ 10 trades."""
    per_regime = metrics.get("per_regime") or {}
    if not isinstance(per_regime, dict):
        return 0
    count = 0
    for label, sub in per_regime.items():
        if not isinstance(sub, dict):
            continue
        if label in ("unknown", None, ""):
            continue
        n = _safe_int(sub.get("n_closed"))
        exp = _safe_float(sub.get("expectancy"))
        net = _safe_float(sub.get("net_pnl_after_fees_slippage"))
        if n >= 10 and (exp > 0 or net > 0):
            count += 1
    return count


# ─── Backlog readiness (audit-board P0/P1 cleared?) ────────────────────────

def _audit_findings_cleared() -> tuple[bool, list[str]]:
    """Best-effort check whether all audit-board P0/P1 findings are cleared.

    The current repo does not yet ship structured P0/P1 backlog. We make
    a conservative best-effort attempt: read agents/reports/ if present
    and look for the latest final_decision_*.md. Absence of the file is
    treated as "no run" → NOT cleared.
    """
    blockers: list[str] = []
    reports_dir = _REPO_ROOT / "agents" / "reports"
    if not reports_dir.exists():
        blockers.append("agents/reports/ does not exist — no audit run yet")
        return False, blockers

    # Look for latest final_decision_<date>.md
    candidates = sorted(reports_dir.glob("final_decision_*.md"), reverse=True)
    if not candidates:
        blockers.append("no final_decision_*.md report — audit-board never ran")
        return False, blockers

    latest = candidates[0]
    try:
        text = latest.read_text(encoding="utf-8")
    except OSError:
        blockers.append(f"cannot read {latest.name}")
        return False, blockers

    # Conservative heuristics: look for "P0" or "P1" markers without an
    # accompanying "RESOLVED" marker on the same line.
    issues: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if ("P0" in upper or "P1" in upper) and "RESOLVED" not in upper:
            issues.append(line)
    if issues:
        blockers.append(
            f"final_decision_{latest.stem.split('_', 2)[-1]} still references "
            f"{len(issues)} P0/P1 finding(s)"
        )
        return False, blockers
    return True, blockers


# ─── Public API: edge_gate_decision ───────────────────────────────────────────

def edge_gate_decision(per_strategy_status: dict[str, str]
                       ) -> tuple[bool, list[str]]:
    """Should EDGE_GATE_ENABLED be allowed to flip to true?

    Returns (allow_flip, blockers).

    HARD RULES:
      1. >= 2 strategies in EDGE_APPROVED_FOR_EXPERIMENT
      2. 0 strategies REJECTED
      3. Latest audit-board final_decision has no unresolved P0/P1
      4. Caller (operator) MUST still set env var manually — this function
         does NOT auto-flip.

    NOTE: returning True does NOT enable live trading. It only signals
    that the operator MAY override `EDGE_GATE_ENABLED=true` in env.
    """
    blockers: list[str] = []
    if not isinstance(per_strategy_status, dict):
        blockers.append("per_strategy_status not a dict")
        return False, blockers

    rejected = [s for s, st in per_strategy_status.items()
                if st == REJECTED]
    if rejected:
        blockers.append(
            f"{len(rejected)} strategy/strategies REJECTED: "
            f"{', '.join(sorted(rejected))}"
        )

    approved = [s for s, st in per_strategy_status.items()
                if st == EDGE_APPROVED_FOR_EXPERIMENT]
    if len(approved) < 2:
        blockers.append(
            f"need ≥2 EDGE_APPROVED_FOR_EXPERIMENT strategies, "
            f"have {len(approved)} ({', '.join(sorted(approved)) or '–'})"
        )

    audit_ok, audit_blockers = _audit_findings_cleared()
    if not audit_ok:
        blockers.extend(audit_blockers)

    return (len(blockers) == 0), blockers


# ─── Quick aggregator for the report ──────────────────────────────────────────

def classify_all(per_strategy_metrics: dict[str, dict],
                 *, audit_complete: bool = True,
                 emit_audit: bool = False) -> dict[str, str]:
    """Classify every strategy provided and return name → status map."""
    out: dict[str, str] = {}
    for name, m in (per_strategy_metrics or {}).items():
        try:
            out[name] = classify_strategy(
                name, m,
                paper_metrics=m,
                audit_complete=audit_complete,
                emit_audit=emit_audit,
            )
        except Exception:
            out[name] = REJECTED
    return out


__all__ = [
    # statuses
    "DISABLED", "REJECTED", "OBSERVE_ONLY", "PAPER_CANDIDATE",
    "PAPER_ENABLED", "EDGE_CANDIDATE", "EDGE_APPROVED_FOR_EXPERIMENT",
    "ALL_STATUSES",
    # thresholds (exported for test introspection)
    "MIN_TRADES_FOR_DECISION", "MIN_TRADES_FOR_PAPER",
    "MIN_TRADES_FOR_PAPER_KEEP",
    "MIN_WR_FOR_EDGE", "MIN_PF_FOR_EDGE", "MIN_PF_FOR_CANDIDATE",
    "MIN_PF_FOR_KEEP", "MAX_DD_FOR_EDGE", "MIN_REGIMES_FOR_EDGE",
    "RECENT_DEGRADATION_TRADES", "RECENT_DEGRADATION_WR",
    # API
    "classify_strategy", "edge_gate_decision", "classify_all",
]
