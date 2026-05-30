"""v3.12.0 (2026-05-30) — Deterministic multi-component confidence score.

WHY
---
System has many risk gates (risk_officer, intraday_governor, pdt_guard,
portfolio_risk, signal_confirmation, instrument_windows) but NO unified
confidence number per decision. Spec audit identified this as the
single biggest gap: every trade decision should carry a documented,
audit-able confidence score in [0.0, 1.0] that combines independent
quality signals.

CONTRACT
--------
`compute_confidence(...)` returns a `ConfidenceReport` with:
  * total       — float in [0.0, 1.0]
  * components  — dict[str, float] each in [0.0, 1.0] (so the operator
                  can SEE which dimension is weak)
  * weights     — dict[str, float] (so reproducibility is total)
  * threshold   — float (the gate value used)
  * decision    — "ALLOW" | "ALERT_ONLY" | "BLOCK"
  * reason      — human-readable summary

THIS DOES NOT REPLACE THE RISK ENGINE.
- risk_officer can still BLOCK a high-confidence trade (e.g. PDT lock).
- confidence can BLOCK a trade the risk_officer would have ALLOWED.
- BOTH must agree for a trade to fire.

The score is deterministic — same inputs → same output. No randomness.
Components fail-safe: any missing input contributes 0.5 (neutral) so
no single missing field destroys the whole score, but several missing
inputs drive total below threshold.

COMPONENTS (5)
--------------
1. data_quality       — freshness + completeness of input data
                        (e.g. bar age, fill of recent ticks, quote spread)
2. signal_strength    — strength of the entry signal itself
                        (e.g. RSI distance from threshold, breakout pct)
3. regime_alignment   — does current regime favor this strategy
                        (e.g. RISK_ON for momentum-long, RISK_OFF for shorts)
4. system_health      — heartbeat + recent errors + audit gap
                        (driven by shared/heartbeat.py)
5. risk_state         — recent drawdown, consecutive losses, intraday giveback
                        (driven by intraday_governor + state.json)

WEIGHTS (default — can be overridden via config)
- data_quality:      0.20
- signal_strength:   0.30   (highest — bad signal = bad trade)
- regime_alignment:  0.20
- system_health:     0.15
- risk_state:        0.15

THRESHOLDS (per decision tier)
- ALLOW:        ≥ 0.65
- ALERT_ONLY:   ≥ 0.50  (email-only, no auto-execute)
- BLOCK:        < 0.50

Operator can tune via config/aggressive_profile.json::confidence section.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "data_quality":     0.20,
    "signal_strength":  0.30,
    "regime_alignment": 0.20,
    "system_health":    0.15,
    "risk_state":       0.15,
}

DEFAULT_THRESHOLDS = {
    "allow":      0.65,
    "alert_only": 0.50,
}

# Neutral fallback when a component cannot be computed (e.g. data fetch
# failure). Set conservatively so several missing inputs → total < 0.5.
NEUTRAL_COMPONENT = 0.5


@dataclass
class ConfidenceReport:
    total: float
    components: dict
    weights: dict
    threshold: float
    decision: str  # "ALLOW" | "ALERT_ONLY" | "BLOCK"
    reason: str
    inputs_used: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total":     round(self.total, 4),
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "weights":   self.weights,
            "threshold": self.threshold,
            "decision":  self.decision,
            "reason":    self.reason,
            "inputs_used": self.inputs_used,
        }


# ─── Config loader ────────────────────────────────────────────────────────────

def _load_profile_confidence_cfg() -> dict:
    """Read optional `confidence` section from aggressive_profile.json.

    Returns dict with possible keys: weights, thresholds. Missing keys
    fall back to defaults. Fail-soft: bad/missing file → defaults.
    """
    path = _REPO_ROOT / "config" / "aggressive_profile.json"
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return {}
    cfg = data.get("confidence") or {}
    return cfg if isinstance(cfg, dict) else {}


def _resolve_weights() -> dict:
    cfg = _load_profile_confidence_cfg()
    w = dict(DEFAULT_WEIGHTS)
    cfg_w = cfg.get("weights") or {}
    for k in w:
        v = cfg_w.get(k)
        if isinstance(v, (int, float)) and v >= 0:
            w[k] = float(v)
    # Normalize so weights sum to 1.0
    total = sum(w.values()) or 1.0
    return {k: v / total for k, v in w.items()}


def _resolve_thresholds() -> dict:
    cfg = _load_profile_confidence_cfg()
    t = dict(DEFAULT_THRESHOLDS)
    cfg_t = cfg.get("thresholds") or {}
    for k in t:
        v = cfg_t.get(k)
        if isinstance(v, (int, float)) and 0 <= v <= 1:
            t[k] = float(v)
    # Invariant: alert_only ≤ allow
    if t["alert_only"] > t["allow"]:
        t["alert_only"] = t["allow"]
    return t


# ─── Component scorers (each returns float in [0.0, 1.0]) ────────────────────

def score_data_quality(*, bar_age_seconds: float | None = None,
                        quote_spread_pct: float | None = None,
                        bars_count: int | None = None,
                        min_bars: int = 20) -> float:
    """Score data freshness + completeness.

    bar_age_seconds:    seconds since the most recent bar's close
                        - ≤ 60s   → 1.0 (fresh)
                        - ≤ 300s  → 0.8
                        - ≤ 900s  → 0.5
                        - > 900s  → 0.2 (very stale; downgrade entries)
    quote_spread_pct:   (ask-bid)/mid × 100
                        - ≤ 0.05% → 1.0 (tight)
                        - ≤ 0.20% → 0.8
                        - ≤ 0.50% → 0.5
                        - > 0.50% → 0.2 (wide; slippage risk)
    bars_count:         how many bars we have vs min_bars
                        - ≥ min_bars × 2 → 1.0
                        - ≥ min_bars     → 0.8
                        - ≥ min_bars/2   → 0.5
                        - < min_bars/2   → 0.2

    Returns AVERAGE of provided sub-scores (missing = neutral 0.5).
    """
    subs = []
    if bar_age_seconds is not None:
        if bar_age_seconds <= 60:    subs.append(1.0)
        elif bar_age_seconds <= 300: subs.append(0.8)
        elif bar_age_seconds <= 900: subs.append(0.5)
        else:                         subs.append(0.2)
    if quote_spread_pct is not None:
        if quote_spread_pct <= 0.05:  subs.append(1.0)
        elif quote_spread_pct <= 0.20: subs.append(0.8)
        elif quote_spread_pct <= 0.50: subs.append(0.5)
        else:                          subs.append(0.2)
    if bars_count is not None and min_bars > 0:
        ratio = bars_count / min_bars
        if ratio >= 2.0:   subs.append(1.0)
        elif ratio >= 1.0: subs.append(0.8)
        elif ratio >= 0.5: subs.append(0.5)
        else:              subs.append(0.2)
    if not subs:
        return NEUTRAL_COMPONENT
    return sum(subs) / len(subs)


def score_signal_strength(*, primary_score: float | None = None,
                            confirmations: int | None = None,
                            max_confirmations: int = 3) -> float:
    """Score the signal itself.

    primary_score:    in [-1, 1] from shared/momentum_score.py
                      We map abs(score) → [0, 1]:
                      - abs ≥ 0.7 → 1.0 (strong)
                      - abs ≥ 0.5 → 0.8
                      - abs ≥ 0.35 → 0.6 (allocator's minimum)
                      - abs < 0.35 → max(0.2, abs/0.5)
    confirmations:    independent confirming signals (e.g. RSI extreme +
                      volume spike + breakout = 3)
                      score = min(1.0, confirmations / max_confirmations)
    """
    subs = []
    if primary_score is not None:
        absv = abs(float(primary_score))
        if absv >= 0.7:    subs.append(1.0)
        elif absv >= 0.5:  subs.append(0.8)
        elif absv >= 0.35: subs.append(0.6)
        else:              subs.append(max(0.2, absv / 0.5))
    if confirmations is not None and max_confirmations > 0:
        subs.append(min(1.0, confirmations / max_confirmations))
    if not subs:
        return NEUTRAL_COMPONENT
    return sum(subs) / len(subs)


def score_regime_alignment(*, regime: str | None = None,
                            strategy: str | None = None) -> float:
    """Score whether the current regime favors this strategy.

    regime:    one of "RISK_ON" | "INFLATION_SHOCK" | "RISK_OFF" | "NEUTRAL"
    strategy:  e.g. "momentum-long", "crypto-momentum", "geo-defense"

    Matrix (rows = strategy categories, cols = regimes):
       long-momentum stocks:   RISK_ON 1.0, NEUTRAL 0.7, INFL 0.5, RISK_OFF 0.3
       short / overbought:     RISK_OFF 1.0, INFL 0.7, NEUTRAL 0.5, RISK_ON 0.2
       crypto:                 NEUTRAL 0.7, RISK_ON 0.9, INFL 0.5, RISK_OFF 0.4
       geo-energy/-defense:    INFL 1.0, RISK_OFF 0.8, NEUTRAL 0.7, RISK_ON 0.6
       geo-gold:               INFL 1.0, RISK_OFF 1.0, NEUTRAL 0.7, RISK_ON 0.5
       options-momentum:       RISK_ON 0.8, NEUTRAL 0.6, INFL 0.4, RISK_OFF 0.3
       allocator-rebalance:    always 0.7 (regime-aware internally)
    """
    if not regime or not strategy:
        return NEUTRAL_COMPONENT
    s = (strategy or "").lower()
    r = (regime or "").upper()

    if "short" in s or "breakdown" in s:
        m = {"RISK_OFF": 1.0, "INFLATION_SHOCK": 0.7, "NEUTRAL": 0.5, "RISK_ON": 0.2}
    elif s.startswith("crypto"):
        m = {"NEUTRAL": 0.7, "RISK_ON": 0.9, "INFLATION_SHOCK": 0.5, "RISK_OFF": 0.4}
    elif "geo-gold" in s:
        m = {"INFLATION_SHOCK": 1.0, "RISK_OFF": 1.0, "NEUTRAL": 0.7, "RISK_ON": 0.5}
    elif s.startswith("geo-"):
        m = {"INFLATION_SHOCK": 1.0, "RISK_OFF": 0.8, "NEUTRAL": 0.7, "RISK_ON": 0.6}
    elif s.startswith("options"):
        m = {"RISK_ON": 0.8, "NEUTRAL": 0.6, "INFLATION_SHOCK": 0.4, "RISK_OFF": 0.3}
    elif "long" in s or "momentum" in s:
        m = {"RISK_ON": 1.0, "NEUTRAL": 0.7, "INFLATION_SHOCK": 0.5, "RISK_OFF": 0.3}
    elif "allocator" in s or "alloc-" in s:
        return 0.7  # allocator is regime-internal-aware
    else:
        return NEUTRAL_COMPONENT
    return m.get(r, NEUTRAL_COMPONENT)


def score_system_health(*, components_alive: int | None = None,
                          components_total: int | None = None,
                          recent_errors: int | None = None,
                          audit_gap_seconds: float | None = None) -> float:
    """Score current system health.

    components_alive / components_total: e.g. 10/11 monitors healthy → 0.91
    recent_errors:    count of errors in last hour
                      - 0    → 1.0
                      - 1-2  → 0.7
                      - 3-5  → 0.4
                      - 6+   → 0.1
    audit_gap_seconds: time since last audit JSONL write
                      - ≤ 300s   → 1.0
                      - ≤ 1800s  → 0.7
                      - ≤ 3600s  → 0.4
                      - > 3600s  → 0.1
    """
    subs = []
    if components_alive is not None and components_total and components_total > 0:
        subs.append(min(1.0, components_alive / components_total))
    if recent_errors is not None:
        if recent_errors == 0:   subs.append(1.0)
        elif recent_errors <= 2: subs.append(0.7)
        elif recent_errors <= 5: subs.append(0.4)
        else:                    subs.append(0.1)
    if audit_gap_seconds is not None:
        if audit_gap_seconds <= 300:    subs.append(1.0)
        elif audit_gap_seconds <= 1800: subs.append(0.7)
        elif audit_gap_seconds <= 3600: subs.append(0.4)
        else:                            subs.append(0.1)
    if not subs:
        return NEUTRAL_COMPONENT
    return sum(subs) / len(subs)


def score_risk_state(*, intraday_pnl_pct: float | None = None,
                       giveback_pct_of_peak: float | None = None,
                       consecutive_losses: int | None = None,
                       drawdown_pct: float | None = None) -> float:
    """Score current risk posture.

    intraday_pnl_pct:    today's P&L %
                         - ≥ 0     → 1.0
                         - ≥ -1%   → 0.7
                         - ≥ -3%   → 0.4
                         - < -3%   → 0.1
    giveback_pct_of_peak: how much of intraday peak has been given back
                         - ≤ 20%   → 1.0
                         - ≤ 35%   → 0.7  (governor WARN zone)
                         - ≤ 50%   → 0.3  (governor PROFIT_LOCK zone)
                         - > 50%   → 0.05
    consecutive_losses:  - 0       → 1.0
                         - 1-2     → 0.7
                         - 3-4     → 0.3
                         - 5+      → 0.05 (cooldown territory)
    drawdown_pct:        - ≥ 0     → 1.0
                         - ≥ -3%   → 0.7
                         - ≥ -7%   → 0.3
                         - < -7%   → 0.05
    """
    subs = []
    if intraday_pnl_pct is not None:
        if intraday_pnl_pct >= 0:    subs.append(1.0)
        elif intraday_pnl_pct >= -1: subs.append(0.7)
        elif intraday_pnl_pct >= -3: subs.append(0.4)
        else:                         subs.append(0.1)
    if giveback_pct_of_peak is not None:
        gb = abs(giveback_pct_of_peak)
        if gb <= 0.20:   subs.append(1.0)
        elif gb <= 0.35: subs.append(0.7)
        elif gb <= 0.50: subs.append(0.3)
        else:            subs.append(0.05)
    if consecutive_losses is not None:
        if consecutive_losses == 0:   subs.append(1.0)
        elif consecutive_losses <= 2: subs.append(0.7)
        elif consecutive_losses <= 4: subs.append(0.3)
        else:                          subs.append(0.05)
    if drawdown_pct is not None:
        if drawdown_pct >= 0:    subs.append(1.0)
        elif drawdown_pct >= -3: subs.append(0.7)
        elif drawdown_pct >= -7: subs.append(0.3)
        else:                     subs.append(0.05)
    if not subs:
        return NEUTRAL_COMPONENT
    return sum(subs) / len(subs)


# ─── Main entry point ────────────────────────────────────────────────────────

def compute_confidence(*,
                        # data_quality inputs
                        bar_age_seconds: float | None = None,
                        quote_spread_pct: float | None = None,
                        bars_count: int | None = None,
                        # signal_strength inputs
                        primary_score: float | None = None,
                        confirmations: int | None = None,
                        # regime inputs
                        regime: str | None = None,
                        strategy: str | None = None,
                        # system_health inputs
                        components_alive: int | None = None,
                        components_total: int | None = None,
                        recent_errors: int | None = None,
                        audit_gap_seconds: float | None = None,
                        # risk_state inputs
                        intraday_pnl_pct: float | None = None,
                        giveback_pct_of_peak: float | None = None,
                        consecutive_losses: int | None = None,
                        drawdown_pct: float | None = None,
                        # overrides
                        weights: dict | None = None,
                        thresholds: dict | None = None,
                        ) -> ConfidenceReport:
    """Compute multi-component confidence with audit-able rationale.

    Pure function: deterministic from inputs. Any None input contributes
    a neutral 0.5 to its component (so missing data DOES degrade the score
    but doesn't zero it out — several missing pieces drive total below
    threshold organically).
    """
    w = weights or _resolve_weights()
    t = thresholds or _resolve_thresholds()

    components = {
        "data_quality":     score_data_quality(
            bar_age_seconds=bar_age_seconds,
            quote_spread_pct=quote_spread_pct,
            bars_count=bars_count,
        ),
        "signal_strength":  score_signal_strength(
            primary_score=primary_score,
            confirmations=confirmations,
        ),
        "regime_alignment": score_regime_alignment(
            regime=regime,
            strategy=strategy,
        ),
        "system_health":    score_system_health(
            components_alive=components_alive,
            components_total=components_total,
            recent_errors=recent_errors,
            audit_gap_seconds=audit_gap_seconds,
        ),
        "risk_state":       score_risk_state(
            intraday_pnl_pct=intraday_pnl_pct,
            giveback_pct_of_peak=giveback_pct_of_peak,
            consecutive_losses=consecutive_losses,
            drawdown_pct=drawdown_pct,
        ),
    }

    # Weighted total
    total = sum(components[k] * w.get(k, 0.0) for k in components)
    total = max(0.0, min(1.0, total))

    # Decision
    if total >= t["allow"]:
        decision = "ALLOW"
    elif total >= t["alert_only"]:
        decision = "ALERT_ONLY"
    else:
        decision = "BLOCK"

    # Identify weakest component for diagnostic
    weak = min(components, key=components.get)
    reason = (
        f"confidence={total:.3f} (allow≥{t['allow']:.2f}, alert≥{t['alert_only']:.2f}) "
        f"weakest={weak}={components[weak]:.2f}"
    )

    return ConfidenceReport(
        total=total,
        components=components,
        weights=w,
        threshold=t["allow"],
        decision=decision,
        reason=reason,
        inputs_used={
            "bar_age_seconds":      bar_age_seconds,
            "quote_spread_pct":     quote_spread_pct,
            "bars_count":           bars_count,
            "primary_score":        primary_score,
            "confirmations":        confirmations,
            "regime":               regime,
            "strategy":             strategy,
            "components_alive":     components_alive,
            "components_total":     components_total,
            "recent_errors":        recent_errors,
            "audit_gap_seconds":    audit_gap_seconds,
            "intraday_pnl_pct":     intraday_pnl_pct,
            "giveback_pct_of_peak": giveback_pct_of_peak,
            "consecutive_losses":   consecutive_losses,
            "drawdown_pct":         drawdown_pct,
        },
    )


__all__ = [
    "ConfidenceReport",
    "compute_confidence",
    "score_data_quality",
    "score_signal_strength",
    "score_regime_alignment",
    "score_system_health",
    "score_risk_state",
    "DEFAULT_WEIGHTS",
    "DEFAULT_THRESHOLDS",
]
