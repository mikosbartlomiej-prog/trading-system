"""v3.15.0 (2026-06-04) — LiquiditySweepGuard.

Closes audit-board feedback FB-012 (liquidity sweep / trap defense).

WHY
---
Trader feedback: protect against liquidity sweeps, fake breakouts, and
sudden liquidity withdrawals. The system currently has zero defense against
"long wick on breakout then sharp reversal" patterns — exactly what wrecks
intraday entries on otherwise-good momentum setups.

CONTRACT
--------
Pure, deterministic, fail-soft. Reads `InstrumentProfile` + recent bars.
Outputs a verdict consumed by:
  - confidence_builder (lowers confidence component)
  - risk_officer (optional BLOCK at high sweep risk)
  - audit log (every decision JSONL)

VERDICTS
--------
- ALLOW          — no sweep risk detected
- ELEVATED_RISK  — sweep-like conditions present; downgrade confidence
- BLOCK          — strong sweep evidence; refuse trade

NEVER:
  - generates a trade
  - raises aggressiveness
  - overrides risk engine BLOCK
  - increases position size

Safety
------
Fail-soft → empty inputs → ALLOW (legacy compat, no breakage).
Deterministic: same inputs → same verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Sequence

# ─── Verdict ──────────────────────────────────────────────────────────────────

ALLOW          = "ALLOW"
ELEVATED_RISK  = "ELEVATED_RISK"
BLOCK          = "BLOCK"
VALID_VERDICTS = (ALLOW, ELEVATED_RISK, BLOCK)


# ─── Tunable thresholds (documented; conservative) ────────────────────────────

# A bar is a "long-wick reversal" candidate if its top wick exceeds
# this multiple of body size AND the close gives back > X% of high.
LONG_WICK_BODY_MULT      = 2.0
WICK_REVERSAL_GIVEBACK   = 0.50   # 50% retrace from high

# Volume-spike-no-follow-through: today's volume > VOL_SPIKE_MULT × 20d avg
# AND today's close < high - VOL_SPIKE_GIVEBACK × range
VOL_SPIKE_MULT           = 2.0
VOL_SPIKE_GIVEBACK       = 0.50

# Fast reversal after breakout: today made a new 20-bar high but closed below
# yesterday's close
FAST_REVERSAL_LOOKBACK   = 20

# Spread/slippage proxy threshold (bps). When > this, mark low liquidity.
HIGH_SPREAD_BPS          = 50.0   # 0.50% — conservative

# Per-symbol historical wick stats from InstrumentProfile.long_wick_ratio
HISTORICAL_TRAP_RATIO    = 0.25   # > 25% bars historically long-wick → "trap-prone"

# Verdict scoring: more signals stacked → harsher verdict
ELEVATED_THRESHOLD       = 2      # ≥ 2 signals → ELEVATED_RISK
BLOCK_THRESHOLD          = 3      # ≥ 3 signals → BLOCK


@dataclass(frozen=True)
class SweepCheckResult:
    """Output of liquidity sweep evaluation."""
    verdict:                  str
    signal_count:             int
    triggered_signals:        tuple
    long_wick_reversal:       bool
    volume_spike_no_follow:   bool
    fast_reversal_post_break: bool
    historical_trap_prone:    bool
    low_liquidity_warning:    bool
    rationale:                str

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Pure detectors ───────────────────────────────────────────────────────────

def _check_long_wick_reversal(opens, highs, lows, closes) -> bool:
    """Last bar shows long upper-wick reversal (fake breakout up)
       OR long lower-wick reversal (fake breakdown).

    Signal: upper_wick > 2 × body AND close < high - 50% of range
    Mirror for long lower wick.
    """
    if len(closes) < 2:
        return False
    o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
    body = abs(c - o) or 1e-9
    bar_range = h - l
    if bar_range <= 0:
        return False
    body_low, body_high = min(o, c), max(o, c)
    up_wick = h - body_high
    lo_wick = body_low - l
    giveback_from_high = (h - c) / bar_range if bar_range > 0 else 0
    giveback_from_low  = (c - l) / bar_range if bar_range > 0 else 0
    upper_trap = (up_wick > LONG_WICK_BODY_MULT * body) and \
                 (giveback_from_high > WICK_REVERSAL_GIVEBACK)
    lower_trap = (lo_wick > LONG_WICK_BODY_MULT * body) and \
                 (giveback_from_low  > WICK_REVERSAL_GIVEBACK)
    return upper_trap or lower_trap


def _check_volume_spike_no_follow(volumes, highs, lows, closes) -> bool:
    """Today's volume > 2× 20-day avg AND close gives back > 50% of high.

    Indicates absorbed-buying / liquidation cascade rather than real
    momentum.
    """
    if len(closes) < 21:
        return False
    last_vol = volumes[-1]
    if last_vol <= 0:
        return False
    avg = sum(v for v in volumes[-21:-1] if v > 0) / max(
        sum(1 for v in volumes[-21:-1] if v > 0), 1)
    if avg <= 0:
        return False
    if last_vol < VOL_SPIKE_MULT * avg:
        return False
    h, l, c = highs[-1], lows[-1], closes[-1]
    bar_range = h - l
    if bar_range <= 0:
        return False
    giveback = (h - c) / bar_range
    return giveback > VOL_SPIKE_GIVEBACK


def _check_fast_reversal_post_breakout(highs, closes) -> bool:
    """Today made a 20-bar high but closed below yesterday's close.

    Classic "stop hunt" pattern.
    """
    if len(closes) < FAST_REVERSAL_LOOKBACK + 1:
        return False
    prior_high = max(highs[-(FAST_REVERSAL_LOOKBACK + 1):-1])
    return (highs[-1] > prior_high) and (closes[-1] < closes[-2])


def _check_historical_trap_prone(profile) -> bool:
    """From InstrumentProfile.wicks.long_wick_ratio."""
    if not profile or not profile.wicks:
        return False
    return profile.wicks.long_wick_ratio > HISTORICAL_TRAP_RATIO


def _check_low_liquidity(quote_spread_bps: float | None) -> bool:
    """When spread proxy is large, refuse risky setups."""
    if quote_spread_bps is None:
        return False
    return quote_spread_bps > HIGH_SPREAD_BPS


# ─── Public API ───────────────────────────────────────────────────────────────

def evaluate_sweep_risk(*,
                          opens: Sequence[float] | None = None,
                          highs: Sequence[float] | None = None,
                          lows: Sequence[float] | None = None,
                          closes: Sequence[float] | None = None,
                          volumes: Sequence[float] | None = None,
                          quote_spread_bps: float | None = None,
                          profile=None,
                          ) -> SweepCheckResult:
    """Score liquidity-sweep risk for a candidate setup.

    Fail-soft: missing data → ALLOW (caller already has confidence floor +
    risk_officer downstream).

    Returns SweepCheckResult — caller's responsibility to:
      * If BLOCK: refuse trade upfront.
      * If ELEVATED_RISK: degrade confidence component.
      * If ALLOW: proceed normally.
    """
    opens   = list(opens   or [])
    highs   = list(highs   or [])
    lows    = list(lows    or [])
    closes  = list(closes  or [])
    volumes = list(volumes or [])

    has_bars = len(closes) >= 2 and len(closes) == len(opens) == len(highs) == len(lows)
    has_vol = len(volumes) == len(closes)

    long_wick     = _check_long_wick_reversal(opens, highs, lows, closes) if has_bars else False
    vol_spike     = _check_volume_spike_no_follow(volumes, highs, lows, closes) if (has_bars and has_vol) else False
    fast_reversal = _check_fast_reversal_post_breakout(highs, closes) if has_bars else False
    trap_prone    = _check_historical_trap_prone(profile)
    low_liquidity = _check_low_liquidity(quote_spread_bps)

    triggered = []
    if long_wick:     triggered.append("long_wick_reversal")
    if vol_spike:     triggered.append("volume_spike_no_follow_through")
    if fast_reversal: triggered.append("fast_reversal_post_breakout")
    if trap_prone:    triggered.append("historical_trap_prone")
    if low_liquidity: triggered.append("low_liquidity")

    count = len(triggered)
    if count >= BLOCK_THRESHOLD:
        verdict = BLOCK
    elif count >= ELEVATED_THRESHOLD:
        verdict = ELEVATED_RISK
    else:
        verdict = ALLOW

    rationale = (
        f"sweep_signals={count}/{len(triggered) if triggered else 0}; "
        f"triggered={','.join(triggered) if triggered else 'none'}"
    )

    return SweepCheckResult(
        verdict=verdict,
        signal_count=count,
        triggered_signals=tuple(triggered),
        long_wick_reversal=long_wick,
        volume_spike_no_follow=vol_spike,
        fast_reversal_post_break=fast_reversal,
        historical_trap_prone=trap_prone,
        low_liquidity_warning=low_liquidity,
        rationale=rationale,
    )


def confidence_penalty(result: SweepCheckResult) -> float:
    """Translate verdict → confidence penalty in [0..0.30].

    Conservative: even ELEVATED gives a meaningful penalty so the score
    component degrades when sweep risk is present. BLOCK is handled
    upstream (trade refused before confidence calc).
    """
    if result.verdict == BLOCK:
        return 0.30
    if result.verdict == ELEVATED_RISK:
        return 0.15
    if result.signal_count == 1:
        return 0.05
    return 0.0


__all__ = [
    "ALLOW", "ELEVATED_RISK", "BLOCK", "VALID_VERDICTS",
    "SweepCheckResult", "evaluate_sweep_risk", "confidence_penalty",
    "LONG_WICK_BODY_MULT", "VOL_SPIKE_MULT", "HIGH_SPREAD_BPS",
    "HISTORICAL_TRAP_RATIO", "ELEVATED_THRESHOLD", "BLOCK_THRESHOLD",
]
