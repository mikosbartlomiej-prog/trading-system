"""v3.19.0 (2026-06-04) — Strategy Disable / Degrade Rules (ETAP 8).

WHY
---
Per audit-board verdict + iron contract: no LLM in the trading critical
path, no auto-disabling at runtime, and no mixing of backtest / replay
evidence with paper evidence. Yet operators need conservative,
deterministic disable / degrade rules they can apply with confidence.

This module emits RECOMMENDATIONS only:
  KEEP                       — no rule triggered; strategy continues
  OBSERVE                    — soft signal; keep but watch closely
  DEGRADE                    — degrade to OBSERVE_ONLY priority
  DISABLE_CANDIDATE          — strong evidence; operator should disable
  MANUAL_REVIEW_REQUIRED     — risk violation or anomaly; operator gate

The recommendation is chosen by SEVERITY:
  MANUAL_REVIEW_REQUIRED > DISABLE_CANDIDATE > DEGRADE > OBSERVE > KEEP

CONTRACT
--------
- evaluate_disable_rules(strategy, metrics, ...) is a PURE function.
  Same input → same output. No I/O except the optional audit emission.
- NEVER mutates state.json.
- NEVER changes risk limits, exposure caps, or kill-switch state.
- NEVER auto-disables anything at runtime — only emits the
  recommendation + triggered_rules list for human action.

CONSERVATIVE RULES
------------------
Each rule below is intentionally conservative; multiple weak signals
must combine before reaching DISABLE_CANDIDATE.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─── Recommendation enum ────────────────────────────────────────────────────

KEEP                   = "KEEP"
OBSERVE                = "OBSERVE"
DEGRADE                = "DEGRADE"
DISABLE_CANDIDATE      = "DISABLE_CANDIDATE"
MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"

# Severity order: index 0 = lowest, index 4 = highest.
_SEVERITY_ORDER = [
    KEEP,                    # 0
    OBSERVE,                 # 1
    DEGRADE,                 # 2
    DISABLE_CANDIDATE,       # 3
    MANUAL_REVIEW_REQUIRED,  # 4
]


def _severity(recommendation: str) -> int:
    try:
        return _SEVERITY_ORDER.index(recommendation)
    except ValueError:
        return 0


def _combine(current: str, candidate: str) -> str:
    """Return the more severe of the two."""
    return candidate if _severity(candidate) > _severity(current) else current


# ─── Thresholds (conservative) ──────────────────────────────────────────────

# Rule thresholds — these are intentionally small modules so audit
# tools + tests can introspect them directly.
WR_MIN_FOR_DEGRADE         = 0.30
N_FOR_WR_DEGRADE           = 20
PF_MIN_FOR_DISABLE         = 0.80
N_FOR_PF_DISABLE           = 30
MAX_DD_TRIGGER_PCT         = 30.0    # >30% drawdown
HIGH_SLIPPAGE_BPS          = 50.0    # avg > 50 bps
HIGH_REJECTED_PCT          = 40.0    # rejected_signals_pct > 40%
SINGLE_INSTR_CONC_PCT      = 80.0    # single instrument > 80% of trades
RECENT_WR_THRESHOLD        = 0.30
RECENT_N                   = 20


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


# ─── Individual rules (each returns (triggered, severity, reason)) ──────────

def _rule_low_win_rate(metrics: Mapping[str, Any]) -> tuple[bool, str, str]:
    n = _safe_int(metrics.get("n_closed"))
    wr = _safe_float(metrics.get("win_rate"))
    if n >= N_FOR_WR_DEGRADE and wr < WR_MIN_FOR_DEGRADE:
        return True, DEGRADE, (
            f"n_closed={n} >= {N_FOR_WR_DEGRADE} and WR={wr:.1%} "
            f"< {WR_MIN_FOR_DEGRADE:.0%}"
        )
    return False, KEEP, ""


def _rule_low_profit_factor(metrics: Mapping[str, Any]) -> tuple[bool, str, str]:
    n = _safe_int(metrics.get("n_closed"))
    pf = _safe_float(metrics.get("profit_factor"))
    if n >= N_FOR_PF_DISABLE and pf < PF_MIN_FOR_DISABLE:
        return True, DISABLE_CANDIDATE, (
            f"n_closed={n} >= {N_FOR_PF_DISABLE} and PF={pf:.2f} "
            f"< {PF_MIN_FOR_DISABLE}"
        )
    return False, KEEP, ""


def _rule_negative_expectancy_after_fees(metrics: Mapping[str, Any]
                                         ) -> tuple[bool, str, str]:
    exp = metrics.get("expectancy_after_fees")
    if exp is None:
        # Fall back to fee_adjusted_expectancy or net_pnl_after_fees_slippage
        # divided by n.
        if metrics.get("fee_adjusted_expectancy") is not None:
            exp = metrics["fee_adjusted_expectancy"]
        else:
            net = _safe_float(metrics.get("net_pnl_after_fees_slippage"))
            n = _safe_int(metrics.get("n_closed"))
            exp = (net / n) if n else 0.0
    exp_f = _safe_float(exp)
    if exp_f < 0:
        return True, DEGRADE, (
            f"expectancy_after_fees={exp_f:.4f} < 0 (negative net expectancy)"
        )
    return False, KEEP, ""


def _rule_max_drawdown(metrics: Mapping[str, Any]) -> tuple[bool, str, str]:
    """max_dd may be reported as fraction (0..1) or percent (0..100).
    We treat values >1 as percent.
    """
    dd_raw = metrics.get("max_drawdown_pct")
    if dd_raw is None:
        dd_raw = metrics.get("max_drawdown")
    dd = _safe_float(dd_raw)
    dd_pct = dd if dd > 1.0 else dd * 100.0
    if dd_pct > MAX_DD_TRIGGER_PCT:
        return True, DEGRADE, (
            f"max_drawdown={dd_pct:.1f}% > {MAX_DD_TRIGGER_PCT:.0f}%"
        )
    return False, KEEP, ""


def _rule_risk_violations(recent_violations: int) -> tuple[bool, str, str]:
    if recent_violations > 0:
        return True, MANUAL_REVIEW_REQUIRED, (
            f"{recent_violations} recent risk violation(s) — operator gate"
        )
    return False, KEEP, ""


def _rule_calibration_quality(calibration_quality: str) -> tuple[bool, str, str]:
    if str(calibration_quality or "").lower() == "uncalibrated":
        return True, DEGRADE, "confidence calibration_quality=uncalibrated"
    return False, KEEP, ""


def _rule_instrument_concentration(metrics: Mapping[str, Any],
                                   instrument_breakdown:
                                       Mapping[str, Any] | None
                                   ) -> tuple[bool, str, str]:
    # Concentration may be supplied directly as a fraction or computed
    # from instrument_breakdown (count per symbol).
    conc_raw = metrics.get("instrument_concentration")
    if conc_raw is None and isinstance(instrument_breakdown, Mapping) and instrument_breakdown:
        counts = []
        for _, v in instrument_breakdown.items():
            if isinstance(v, Mapping):
                counts.append(_safe_int(v.get("n_closed")))
            else:
                counts.append(_safe_int(v))
        tot = sum(counts)
        if tot > 0:
            conc_raw = max(counts) / float(tot)
    conc = _safe_float(conc_raw)
    conc_pct = conc if conc > 1.0 else conc * 100.0
    if conc_pct > SINGLE_INSTR_CONC_PCT:
        return True, MANUAL_REVIEW_REQUIRED, (
            f"single-instrument concentration={conc_pct:.1f}% > "
            f"{SINGLE_INSTR_CONC_PCT:.0f}% — operator must confirm symbol mix"
        )
    return False, KEEP, ""


def _rule_high_slippage(metrics: Mapping[str, Any]) -> tuple[bool, str, str]:
    slip = _safe_float(metrics.get("avg_slippage_bps"))
    if slip > HIGH_SLIPPAGE_BPS:
        return True, DEGRADE, (
            f"avg_slippage_bps={slip:.1f} > {HIGH_SLIPPAGE_BPS:.0f}"
        )
    return False, KEEP, ""


def _rule_rejected_signals(metrics: Mapping[str, Any]) -> tuple[bool, str, str]:
    raw = metrics.get("rejected_signals_pct")
    rate = _safe_float(raw)
    rate_pct = rate if rate > 1.0 else rate * 100.0
    if rate_pct > HIGH_REJECTED_PCT:
        return True, DEGRADE, (
            f"rejected_signals_pct={rate_pct:.1f}% > {HIGH_REJECTED_PCT:.0f}%"
        )
    return False, KEEP, ""


def _rule_recent_degradation(metrics: Mapping[str, Any]
                             ) -> tuple[bool, str, str]:
    last_n = _safe_int(metrics.get("recent_window_n"), RECENT_N)
    if last_n <= 0:
        last_n = RECENT_N
    wr = _safe_float(metrics.get("last_20_win_rate"))
    n = _safe_int(metrics.get("n_closed"))
    if n >= last_n and wr < RECENT_WR_THRESHOLD:
        return True, DEGRADE, (
            f"last_{last_n}_win_rate={wr:.1%} < {RECENT_WR_THRESHOLD:.0%}"
        )
    return False, KEEP, ""


# ─── Audit emission ──────────────────────────────────────────────────────────

def _emit_disable_rule_audit(strategy: str, recommendation: str,
                             triggered_rules: list[str],
                             rationale: str) -> None:
    """Emit a non-blocking JSONL audit row. Fail-soft."""
    try:
        from shared.audit import write_audit_event  # type: ignore
        from shared.autonomy import make_decision    # type: ignore
    except Exception:
        try:
            from audit import write_audit_event       # type: ignore
            from autonomy import make_decision        # type: ignore
        except Exception:
            return
    try:
        decision_type = "PAUSE_STRATEGY" if recommendation in (
            DEGRADE, DISABLE_CANDIDATE, MANUAL_REVIEW_REQUIRED) else "RESUME_STRATEGY"
        d = make_decision(
            decision_type=decision_type,
            decision=recommendation,
            reason=f"learning_recommendation (disable_rules): {rationale}",
            actor="strategy-disable-rules",
            strategy=strategy,
            risk_metrics={"triggered_rules": ",".join(triggered_rules) or "-"},
            reversible=True,
        )
        write_audit_event(d, kind="trading")
    except Exception:
        return


# ─── Public API ──────────────────────────────────────────────────────────────

def evaluate_disable_rules(strategy: str,
                           metrics: Mapping[str, Any] | None,
                           recent_violations: int = 0,
                           calibration_quality: str = "unknown",
                           instrument_breakdown:
                               Mapping[str, Any] | None = None,
                           *,
                           emit_audit: bool = True) -> dict:
    """Evaluate conservative disable / degrade rules.

    Returns a dict with:
      - recommendation: one of (KEEP, OBSERVE, DEGRADE,
        DISABLE_CANDIDATE, MANUAL_REVIEW_REQUIRED)
      - triggered_rules: list[str] of rule identifiers
      - rationale: concise human-readable summary

    NEVER raises. NEVER mutates state. NEVER auto-disables anything.
    """
    if not isinstance(metrics, Mapping):
        metrics = {}
    triggered: list[str] = []
    reasons: list[str] = []
    recommendation = KEEP

    rules: list[tuple[str, tuple[bool, str, str]]] = []
    try:
        rules.append(("low_win_rate", _rule_low_win_rate(metrics)))
        rules.append(("low_profit_factor", _rule_low_profit_factor(metrics)))
        rules.append(("negative_expectancy_after_fees",
                      _rule_negative_expectancy_after_fees(metrics)))
        rules.append(("max_drawdown", _rule_max_drawdown(metrics)))
        rules.append(("risk_violations", _rule_risk_violations(
            _safe_int(recent_violations))))
        rules.append(("calibration_quality", _rule_calibration_quality(
            calibration_quality)))
        rules.append(("instrument_concentration",
                      _rule_instrument_concentration(
                          metrics, instrument_breakdown)))
        rules.append(("high_slippage", _rule_high_slippage(metrics)))
        rules.append(("rejected_signals", _rule_rejected_signals(metrics)))
        rules.append(("recent_degradation", _rule_recent_degradation(metrics)))
    except Exception as e:
        # Last-ditch fallback: never raise.
        rules.append(("internal_error", (True, MANUAL_REVIEW_REQUIRED,
                                         f"internal_error={e}")))

    for rule_name, (fired, sev, reason) in rules:
        if not fired:
            continue
        triggered.append(rule_name)
        reasons.append(f"{rule_name}: {reason}")
        recommendation = _combine(recommendation, sev)

    rationale = "; ".join(reasons) if reasons else "no rules triggered"

    if emit_audit:
        _emit_disable_rule_audit(
            strategy=str(strategy or "?"),
            recommendation=recommendation,
            triggered_rules=triggered,
            rationale=rationale,
        )

    return {
        "strategy":         str(strategy or "?"),
        "recommendation":   recommendation,
        "triggered_rules":  triggered,
        "rationale":        rationale,
    }


__all__ = [
    # Recommendations
    "KEEP", "OBSERVE", "DEGRADE", "DISABLE_CANDIDATE",
    "MANUAL_REVIEW_REQUIRED",
    # Thresholds (exported for introspection)
    "WR_MIN_FOR_DEGRADE", "N_FOR_WR_DEGRADE",
    "PF_MIN_FOR_DISABLE", "N_FOR_PF_DISABLE",
    "MAX_DD_TRIGGER_PCT", "HIGH_SLIPPAGE_BPS",
    "HIGH_REJECTED_PCT", "SINGLE_INSTR_CONC_PCT",
    "RECENT_WR_THRESHOLD", "RECENT_N",
    # API
    "evaluate_disable_rules",
]
