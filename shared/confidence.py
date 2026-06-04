"""v3.18.0 (2026-06-04) — Deterministic multi-component confidence score.

v3.12.0: introduced 5 components (data_quality, signal_strength,
regime_alignment, system_health, risk_state) + ALLOW/ALERT/BLOCK tiers.

v3.18.0 ETAP 6+7 (this revision) — extensions that make HIGH confidence
RARE but VALUABLE. New defensive components + a multiplicative penalty
layer that cannot raise the score, only constrain it.

NEW COMPONENTS (additive, do NOT rename/remove existing)
- liquidity_quality        — spread + volume vs universe baseline
- paper_sample_size_score  — Kelly-friendly sample size gate (n_closed_paper)
- recent_strategy_health   — rolling 20-trade WR; <30% penalised
- (anomaly_penalty + event_risk_penalty act as MULTIPLIERS — see below)

NEW SCORING FUNCTIONS (each [0.0, 1.0], NEUTRAL_COMPONENT on missing input)
- score_liquidity_quality(quote_spread_pct, daily_volume_usd, universe_spread_baseline)
- score_slippage_risk(estimated_slippage_bps, expected_edge_bps)
- score_strategy_edge_evidence(n_closed_paper, profit_factor)
- score_paper_sample_size(n_closed_paper)
- score_recent_strategy_health(recent_20_wr)
- score_anomaly_penalty(price_move_atr, volume_ratio)
- score_event_risk_penalty(days_to_earnings, days_to_fomc)

WEIGHTS (8 weighted components; sum=1.0)
- data_quality:            0.15
- signal_strength:         0.20
- regime_alignment:        0.15
- system_health:           0.08
- risk_state:              0.15
- liquidity_quality:       0.08
- paper_sample_size_score: 0.10
- recent_strategy_health:  0.05
- (anomaly_penalty + event_risk_penalty are MULTIPLIERS, not summed)

Total formula:
  total = sum(component[k] * weight[k] for k in weighted_components)
          * anomaly_penalty * event_risk_penalty

This asymmetry is intentional. A single severe anomaly (e.g. 4×ATR move
+ 5× normal volume) can cut total by 80% even if other components score
well. event_risk_penalty=0 during earnings ±1d / FOMC ±1d enforces the
"no trades around binary events" iron rule deterministically.

CONTRACT
--------
`compute_confidence(...)` returns a `ConfidenceReport` with:
  * total       — float in [0.0, 1.0]
  * components  — dict[str, float] each in [0.0, 1.0]
  * weights     — dict[str, float]
  * threshold   — float (the gate value used)
  * decision    — "ALLOW" | "ALERT_ONLY" | "BLOCK"
  * reason      — human-readable summary

THIS DOES NOT REPLACE THE RISK ENGINE.
- risk_officer can still BLOCK a high-confidence trade (e.g. PDT lock).
- confidence can BLOCK a trade the risk_officer would have ALLOWED.
- BOTH must agree for a trade to fire.

THRESHOLDS (per decision tier)
- ALLOW:        ≥ 0.65
- ALERT_ONLY:   ≥ 0.50
- BLOCK:        < 0.50

Operator can tune via config/aggressive_profile.json::confidence section.

BACKWARD COMPATIBILITY
----------------------
Callers that omit the new inputs see the same behavior as v3.12.0 — the
new weighted components fall back to NEUTRAL_COMPONENT (0.5) and the two
multipliers default to 1.0 (no penalty). DEFAULT_WEIGHTS still re-normalize
to 1.0, so tests asserting "sum(weights)==1.0" pass unchanged.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── Defaults ────────────────────────────────────────────────────────────────

# v3.18.0 — weighted components.
# These eight components are summed (with weights normalized to 1.0 in
# _resolve_weights). Raw values below sum to 0.96; _resolve_weights
# divides every weight by their sum, so the operative weighted sum is 1.0.
DEFAULT_WEIGHTS = {
    "data_quality":            0.15,
    "signal_strength":         0.20,
    "regime_alignment":        0.15,
    "system_health":           0.08,
    "risk_state":              0.15,
    "liquidity_quality":       0.08,
    "paper_sample_size_score": 0.10,
    "recent_strategy_health":  0.05,
}

# These components are NEVER summed; they multiply the weighted total.
# Each defaults to 1.0 when its input is missing (no penalty).
# anomaly_penalty: scales (0..1] based on |move|×ATR + volume ratio.
# event_risk_penalty: scales (0..1] based on days_to_earnings / FOMC.
MULTIPLIER_COMPONENTS = ("anomaly_penalty", "event_risk_penalty")

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


# ─── v3.18.0 component scorers ───────────────────────────────────────────────

def score_liquidity_quality(*,
                              quote_spread_pct: float | None = None,
                              daily_volume_usd: float | None = None,
                              universe_spread_baseline: float | None = None) -> float:
    """Score liquidity quality vs the symbol's universe baseline.

    quote_spread_pct:           (ask-bid)/mid × 100  (smaller is better)
    daily_volume_usd:           rolling daily $ volume (higher is better)
    universe_spread_baseline:   reference baseline spread % for this symbol's
                                bucket (e.g. 0.05 for mega-cap, 0.30 for alts).
                                If None → only absolute thresholds.

    All-or-nothing: any None inputs contribute NEUTRAL_COMPONENT to the
    sub-score average (so absent data doesn't slam the score).

    Sub-scores
      relative_spread:  spread / baseline   ratio ≤1.0 → 1.0; ≤1.5 → 0.7;
                                            ≤2.5 → 0.4; >2.5 → 0.1
      absolute_volume:  ≥ $50M     → 1.0
                        ≥ $10M     → 0.7
                        ≥ $1M      → 0.4
                        < $1M      → 0.1
    """
    subs: list[float] = []
    if quote_spread_pct is not None and universe_spread_baseline is not None:
        try:
            base = float(universe_spread_baseline)
            spread = float(quote_spread_pct)
            if base <= 0:
                # divide-by-zero guard — treat as fully passing
                subs.append(1.0)
            else:
                ratio = spread / base
                if ratio <= 1.0:    subs.append(1.0)
                elif ratio <= 1.5:  subs.append(0.7)
                elif ratio <= 2.5:  subs.append(0.4)
                else:               subs.append(0.1)
        except Exception:
            pass
    elif quote_spread_pct is not None:
        # No baseline — fall back to absolute thresholds (mega-cap-friendly).
        try:
            spread = float(quote_spread_pct)
            if spread <= 0.05:   subs.append(1.0)
            elif spread <= 0.20: subs.append(0.7)
            elif spread <= 0.50: subs.append(0.4)
            else:                subs.append(0.1)
        except Exception:
            pass

    if daily_volume_usd is not None:
        try:
            vol = float(daily_volume_usd)
            if vol >= 50_000_000:   subs.append(1.0)
            elif vol >= 10_000_000: subs.append(0.7)
            elif vol >= 1_000_000:  subs.append(0.4)
            else:                   subs.append(0.1)
        except Exception:
            pass

    if not subs:
        return NEUTRAL_COMPONENT
    return sum(subs) / len(subs)


def score_slippage_risk(*,
                          estimated_slippage_bps: float | None = None,
                          expected_edge_bps: float | None = None) -> float:
    """Score estimated slippage cost vs expected edge.

    Both arguments in basis points (1 bps = 0.01%).
    Ratio = slippage / edge:
      ratio ≤ 0.10  → 1.0 (slippage takes <10% of edge)
      ratio ≤ 0.25  → 0.7
      ratio ≤ 0.50  → 0.4
      ratio ≤ 0.75  → 0.2
      ratio >  0.75 → 0.05 (slippage eats most of edge → effectively no edge)

    If edge ≤ 0 (no positive expected edge), returns 0.0 — never reward
    a setup where projected slippage exceeds projected gain.
    """
    if estimated_slippage_bps is None or expected_edge_bps is None:
        return NEUTRAL_COMPONENT
    try:
        slip = max(0.0, float(estimated_slippage_bps))
        edge = float(expected_edge_bps)
    except Exception:
        return NEUTRAL_COMPONENT
    if edge <= 0:
        return 0.0
    ratio = slip / edge
    if ratio <= 0.10:   return 1.0
    elif ratio <= 0.25: return 0.7
    elif ratio <= 0.50: return 0.4
    elif ratio <= 0.75: return 0.2
    else:               return 0.05


def score_strategy_edge_evidence(*,
                                   n_closed_paper: int | None = None,
                                   profit_factor: float | None = None) -> float:
    """Score how much CLOSED paper-trade evidence exists for this strategy's edge.

    n_closed_paper: count of closed paper trades attributed to this strategy.
                    More data = stronger conclusion.
    profit_factor:  sum(wins) / abs(sum(losses)). PF≥1 = profitable in paper.

    Returns the AVERAGE of two sub-scores so missing PF still degrades but
    doesn't zero out.

    Sub-score: n_closed_paper
      ≥ 50  → 1.0
      ≥ 30  → 0.7
      ≥ 10  → 0.5
      < 10  → 0.2

    Sub-score: profit_factor
      ≥ 2.0   → 1.0
      ≥ 1.3   → 0.7  (Edge gate threshold)
      ≥ 1.0   → 0.4
      < 1.0   → 0.1  (losing strategy in paper)
    """
    subs: list[float] = []
    if n_closed_paper is not None:
        try:
            n = int(n_closed_paper)
            if n >= 50:   subs.append(1.0)
            elif n >= 30: subs.append(0.7)
            elif n >= 10: subs.append(0.5)
            else:         subs.append(0.2)
        except Exception:
            pass
    if profit_factor is not None:
        try:
            pf = float(profit_factor)
            if pf >= 2.0:   subs.append(1.0)
            elif pf >= 1.3: subs.append(0.7)
            elif pf >= 1.0: subs.append(0.4)
            else:           subs.append(0.1)
        except Exception:
            pass
    if not subs:
        return NEUTRAL_COMPONENT
    return sum(subs) / len(subs)


def score_paper_sample_size(*, n_closed_paper: int | None = None) -> float:
    """Standalone gate: confidence cannot exceed sample-size justification.

    Mapping from task contract:
      n < 10  → 0.0  (no statistical claim possible)
      n < 30  → 0.3
      n < 50  → 0.7
      n ≥ 50  → 1.0

    This is the SINGLE most important defensive component for new strategies.
    Even with perfect everything else, n=10 caps total at threshold via the
    weighted formula (see TestPaperSampleSizeGatesAllow).
    """
    if n_closed_paper is None:
        return NEUTRAL_COMPONENT
    try:
        n = int(n_closed_paper)
    except Exception:
        return NEUTRAL_COMPONENT
    if n < 10:    return 0.0
    elif n < 30:  return 0.3
    elif n < 50:  return 0.7
    else:         return 1.0


def score_recent_strategy_health(*, recent_20_wr: float | None = None) -> float:
    """Score the strategy's last-20-trade win rate.

    recent_20_wr expected in [0.0, 1.0] (fraction). A WR below 30% is a
    strong signal that the strategy is broken (or regime-misaligned).

      ≥ 0.55  → 1.0
      ≥ 0.45  → 0.8
      ≥ 0.35  → 0.5
      ≥ 0.30  → 0.3
      < 0.30  → 0.05  (cool-down territory)
    """
    if recent_20_wr is None:
        return NEUTRAL_COMPONENT
    try:
        wr = float(recent_20_wr)
    except Exception:
        return NEUTRAL_COMPONENT
    if wr >= 0.55:   return 1.0
    elif wr >= 0.45: return 0.8
    elif wr >= 0.35: return 0.5
    elif wr >= 0.30: return 0.3
    else:            return 0.05


def score_anomaly_penalty(*,
                            price_move_atr: float | None = None,
                            volume_ratio: float | None = None) -> float:
    """Multiplicative penalty for abnormal market state.

    price_move_atr:  today's |move| / ATR. > 2 = unusual; > 3 = violent.
    volume_ratio:    today's vol / 20-day avg. > 3 = unusual; > 5 = abnormal.

    Returns scalar in (0, 1.0]. Default missing inputs → 1.0 (no penalty).

      max(move, vol_score) anomaly:
        ≤ 1.5   → 1.0   (normal)
        ≤ 2.5   → 0.85
        ≤ 3.5   → 0.6
        ≤ 5.0   → 0.4
        > 5.0   → 0.2   (extreme; setup likely already exhausted or trapped)
    """
    if price_move_atr is None and volume_ratio is None:
        return 1.0  # MULTIPLIER default: no penalty when uninformed
    try:
        move = abs(float(price_move_atr)) if price_move_atr is not None else 0.0
    except Exception:
        move = 0.0
    try:
        vol  = float(volume_ratio) if volume_ratio is not None else 0.0
    except Exception:
        vol  = 0.0
    score = max(move, vol)
    if score <= 1.5:   return 1.0
    elif score <= 2.5: return 0.85
    elif score <= 3.5: return 0.6
    elif score <= 5.0: return 0.4
    else:              return 0.2


def score_event_risk_penalty(*,
                               days_to_earnings: float | None = None,
                               days_to_fomc: float | None = None) -> float:
    """Multiplicative penalty for proximity to binary events.

    Returns scalar in [0.0, 1.0]. Default missing → 1.0.

    Earnings blackout (±1 trading day):
      |days_to_earnings| < 1  → 0.0  (BLOCK — iron rule)
      |days_to_earnings| < 3  → 0.6
      |days_to_earnings| < 5  → 0.85
      else                    → 1.0

    FOMC blackout (±1 day for SPY/QQQ/macro exposure):
      |days_to_fomc|     < 1  → 0.2  (extreme caution)
      |days_to_fomc|     < 2  → 0.7
      else                    → 1.0

    Combined penalty = min(earnings_penalty, fomc_penalty)
    """
    earn_pen = 1.0
    fomc_pen = 1.0
    if days_to_earnings is not None:
        try:
            d = abs(float(days_to_earnings))
            if d < 1:   earn_pen = 0.0
            elif d < 3: earn_pen = 0.6
            elif d < 5: earn_pen = 0.85
            else:       earn_pen = 1.0
        except Exception:
            pass
    if days_to_fomc is not None:
        try:
            d = abs(float(days_to_fomc))
            if d < 1:   fomc_pen = 0.2
            elif d < 2: fomc_pen = 0.7
            else:       fomc_pen = 1.0
        except Exception:
            pass
    if days_to_earnings is None and days_to_fomc is None:
        return 1.0
    return min(earn_pen, fomc_pen)


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
                        # v3.18.0 — liquidity_quality inputs
                        daily_volume_usd: float | None = None,
                        universe_spread_baseline_bps: float | None = None,
                        # v3.18.0 — slippage_risk inputs
                        estimated_slippage_bps: float | None = None,
                        expected_edge_bps: float | None = None,
                        # v3.18.0 — paper-experiment inputs
                        strategy_n_closed_paper: int | None = None,
                        strategy_profit_factor: float | None = None,
                        recent_20_wr: float | None = None,
                        # v3.18.0 — multiplier (anomaly + event) inputs
                        price_move_atr: float | None = None,
                        volume_ratio: float | None = None,
                        days_to_earnings: float | None = None,
                        days_to_fomc: float | None = None,
                        # overrides
                        weights: dict | None = None,
                        thresholds: dict | None = None,
                        # Forward-compat: accept (and ignore) extra metadata
                        # such as `_v3150_meta` that callers may pass via
                        # **builder_output. This preserves the contract that
                        # `compute_confidence(**build_confidence_inputs(...))`
                        # always works.
                        **_extras,
                        ) -> ConfidenceReport:
    """Compute multi-component confidence with audit-able rationale.

    Pure function: deterministic from inputs. Any None input contributes
    a neutral 0.5 to its component (so missing data DOES degrade the score
    but doesn't zero it out — several missing pieces drive total below
    threshold organically).

    v3.18.0 — additional defensive components and two multiplicative
    penalty terms (anomaly_penalty + event_risk_penalty). Multipliers
    default to 1.0 (no penalty) when their inputs are absent — so
    legacy callers without the new args get the same numeric behavior
    as v3.12.0 modulo the renormalized weights.
    """
    w = weights or _resolve_weights()
    t = thresholds or _resolve_thresholds()

    # ── Weighted components (summed) ────────────────────────────────────────
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
        "liquidity_quality": score_liquidity_quality(
            quote_spread_pct=quote_spread_pct,
            daily_volume_usd=daily_volume_usd,
            universe_spread_baseline=universe_spread_baseline_bps,
        ),
        "paper_sample_size_score": score_paper_sample_size(
            n_closed_paper=strategy_n_closed_paper,
        ),
        "recent_strategy_health": score_recent_strategy_health(
            recent_20_wr=recent_20_wr,
        ),
    }

    # ── Additional informational scores (NOT weighted) ──────────────────────
    # These are stored in components dict for audit visibility but their
    # weight in DEFAULT_WEIGHTS is 0 (they don't directly contribute to the
    # weighted sum). edge_evidence is correlated with paper_sample_size_score
    # so we keep them visible for the operator.
    edge_evidence = score_strategy_edge_evidence(
        n_closed_paper=strategy_n_closed_paper,
        profit_factor=strategy_profit_factor,
    )
    slippage = score_slippage_risk(
        estimated_slippage_bps=estimated_slippage_bps,
        expected_edge_bps=expected_edge_bps,
    )
    components["edge_evidence"] = edge_evidence
    components["slippage_risk"] = slippage

    # ── Multiplier components (NOT summed; scale total) ─────────────────────
    anomaly_pen = score_anomaly_penalty(
        price_move_atr=price_move_atr,
        volume_ratio=volume_ratio,
    )
    event_pen = score_event_risk_penalty(
        days_to_earnings=days_to_earnings,
        days_to_fomc=days_to_fomc,
    )
    components["anomaly_penalty"]     = anomaly_pen
    components["event_risk_penalty"]  = event_pen

    # ── Weighted sum (only over keys present in resolved weights) ───────────
    # _resolve_weights normalizes weights to sum=1.0 across its keys.
    weighted_sum = sum(components[k] * w.get(k, 0.0) for k in w)

    # Slippage acts as an extra soft multiplier: bad slippage discounts the
    # weighted sum further. If slippage data is missing we skip this layer.
    if estimated_slippage_bps is not None and expected_edge_bps is not None:
        # Linear map: slippage_subscore [0..1] → discount factor [0.7..1.0]
        # so the worst case (0.05) still leaves 70% of the score intact.
        slippage_factor = 0.7 + 0.3 * max(0.0, min(1.0, slippage))
    else:
        slippage_factor = 1.0

    # ── Hard gate: paper_sample_size_score also acts as a soft CAP. ─────────
    # Rationale: a strategy with <10 closed paper trades has not earned the
    # right to fire at confidence > sample_size_score. This enforces the
    # iron rule "evidence first, conviction second". When sample size is
    # known (input present), it provides a ceiling on total.
    #
    # Mapping:
    #   n_closed ≥ 50  → cap 1.00 (no cap)
    #   n_closed ≥ 30  → cap 0.85
    #   n_closed ≥ 10  → cap 0.60  (just below ALLOW threshold 0.65)
    #   n_closed <  10 → cap 0.35  (forces ALERT_ONLY at best)
    #   n_closed None  → no cap   (unknown evidence — score on other components)
    if strategy_n_closed_paper is not None:
        try:
            n = int(strategy_n_closed_paper)
            if n >= 50:   sample_cap = 1.0
            elif n >= 30: sample_cap = 0.85
            elif n >= 10: sample_cap = 0.60
            else:         sample_cap = 0.35
        except Exception:
            sample_cap = 1.0
    else:
        sample_cap = 1.0

    total = weighted_sum * anomaly_pen * event_pen * slippage_factor
    total = max(0.0, min(1.0, total))
    # Apply sample-size ceiling AFTER multipliers (penalties still apply).
    total = min(total, sample_cap)

    # Decision
    if total >= t["allow"]:
        decision = "ALLOW"
    elif total >= t["alert_only"]:
        decision = "ALERT_ONLY"
    else:
        decision = "BLOCK"

    # Identify weakest WEIGHTED component for diagnostic
    weighted_only = {k: components[k] for k in w if k in components}
    if weighted_only:
        weak = min(weighted_only, key=weighted_only.get)
        reason = (
            f"confidence={total:.3f} (allow≥{t['allow']:.2f}, alert≥{t['alert_only']:.2f}) "
            f"weakest={weak}={components[weak]:.2f} "
            f"anomaly={anomaly_pen:.2f} event={event_pen:.2f}"
        )
    else:
        reason = f"confidence={total:.3f} (no weighted components)"

    return ConfidenceReport(
        total=total,
        components=components,
        weights=w,
        threshold=t["allow"],
        decision=decision,
        reason=reason,
        inputs_used={
            "bar_age_seconds":             bar_age_seconds,
            "quote_spread_pct":            quote_spread_pct,
            "bars_count":                  bars_count,
            "primary_score":               primary_score,
            "confirmations":               confirmations,
            "regime":                      regime,
            "strategy":                    strategy,
            "components_alive":            components_alive,
            "components_total":            components_total,
            "recent_errors":               recent_errors,
            "audit_gap_seconds":           audit_gap_seconds,
            "intraday_pnl_pct":            intraday_pnl_pct,
            "giveback_pct_of_peak":        giveback_pct_of_peak,
            "consecutive_losses":          consecutive_losses,
            "drawdown_pct":                drawdown_pct,
            # v3.18.0
            "daily_volume_usd":            daily_volume_usd,
            "universe_spread_baseline_bps": universe_spread_baseline_bps,
            "estimated_slippage_bps":      estimated_slippage_bps,
            "expected_edge_bps":           expected_edge_bps,
            "strategy_n_closed_paper":     strategy_n_closed_paper,
            "strategy_profit_factor":      strategy_profit_factor,
            "recent_20_wr":                recent_20_wr,
            "price_move_atr":              price_move_atr,
            "volume_ratio":                volume_ratio,
            "days_to_earnings":            days_to_earnings,
            "days_to_fomc":                days_to_fomc,
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
    # v3.18.0 additions
    "score_liquidity_quality",
    "score_slippage_risk",
    "score_strategy_edge_evidence",
    "score_paper_sample_size",
    "score_recent_strategy_health",
    "score_anomaly_penalty",
    "score_event_risk_penalty",
    "DEFAULT_WEIGHTS",
    "DEFAULT_THRESHOLDS",
    "MULTIPLIER_COMPONENTS",
    "NEUTRAL_COMPONENT",
]
