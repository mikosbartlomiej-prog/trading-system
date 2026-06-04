"""v3.15.0 (2026-06-04) — Pre-open behavior interface (FB-002).

WHY
---
Trader feedback: pre-market behavior often predicts opening behavior.
However the Alpaca FREE IEX feed does NOT provide pre-market data (extended
hours requires paid SIP feed). We ship an INTERFACE + synthetic data tests
so the contract is defined and can be wired the moment a free pre-market
source is added.

LIMITATIONS (documented)
------------------------
- IEX feed (free): regular session only (09:30-16:00 ET / 13:30-20:00 UTC).
- SIP feed (paid): includes pre/post sessions. NOT used here.
- This module's `analyze_pre_open()` accepts caller-provided bars; the
  caller decides where the data came from. With Alpaca free tier, the
  bars list will be empty during pre-market → result.insufficient_data = True
  → caller treats as missing info (confidence-conservative).

CONTRACT
--------
Pure, deterministic, fail-soft. Input: list of pre-market bars (each dict
with o/h/l/c/v + iso timestamp) + previous day close. Output:
`PreOpenAnalysis` consumed by confidence_builder.

CLASSIFICATIONS
---------------
- GAP_UP_STRONG_PRE_OPEN
- GAP_UP_WEAK_PRE_OPEN
- GAP_DOWN_STRONG_PRE_OPEN
- GAP_DOWN_WEAK_PRE_OPEN
- FLAT_PRE_OPEN
- HIGH_REL_VOLUME
- LOW_VOLUME_FAKE_MOVE
- INSUFFICIENT_DATA

The current implementation classifies based on what data is available.
With paid SIP, classes like "index-aligned move", "delayed follower" would
be filled in by combining with LeadLagAnalyzer.

SAFETY
------
- Pure function: no clock, no I/O, no orders.
- Fail-soft: missing data → INSUFFICIENT_DATA → no confidence boost.
- Conservative: result NEVER raises confidence by more than 0.05.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence

# ─── Classification labels ────────────────────────────────────────────────────

GAP_UP_STRONG_PRE_OPEN   = "GAP_UP_STRONG_PRE_OPEN"
GAP_UP_WEAK_PRE_OPEN     = "GAP_UP_WEAK_PRE_OPEN"
GAP_DOWN_STRONG_PRE_OPEN = "GAP_DOWN_STRONG_PRE_OPEN"
GAP_DOWN_WEAK_PRE_OPEN   = "GAP_DOWN_WEAK_PRE_OPEN"
FLAT_PRE_OPEN            = "FLAT_PRE_OPEN"
HIGH_REL_VOLUME          = "HIGH_REL_VOLUME"
LOW_VOLUME_FAKE_MOVE     = "LOW_VOLUME_FAKE_MOVE"
INSUFFICIENT_DATA        = "INSUFFICIENT_DATA"

VALID_LABELS = (
    GAP_UP_STRONG_PRE_OPEN, GAP_UP_WEAK_PRE_OPEN,
    GAP_DOWN_STRONG_PRE_OPEN, GAP_DOWN_WEAK_PRE_OPEN,
    FLAT_PRE_OPEN, HIGH_REL_VOLUME, LOW_VOLUME_FAKE_MOVE,
    INSUFFICIENT_DATA,
)


# ─── Thresholds ──────────────────────────────────────────────────────────────

STRONG_GAP_PCT     = 0.02     # 2%
WEAK_GAP_PCT       = 0.005    # 0.5%
HIGH_REL_VOL_MULT  = 2.0      # vs prior-day average pre-market volume (if available)
MIN_BARS           = 2


@dataclass(frozen=True)
class PreOpenAnalysis:
    label:                  str
    gap_pct:                float | None
    pre_market_volume:      float | None
    pre_market_vwap:        float | None
    distance_from_prev_close_pct: float | None
    distance_from_prev_high_pct:  float | None
    distance_from_prev_low_pct:   float | None
    bars_count:             int
    insufficient_data:      bool
    direction_changes:      int
    confidence_adjustment:  float       # never > +0.05
    rationale:              str

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Pure helpers ─────────────────────────────────────────────────────────────

def _pre_market_vwap(bars):
    """VWAP from supplied bars. None if not enough data."""
    num = den = 0.0
    for b in bars:
        try:
            typical = (float(b["h"]) + float(b["l"]) + float(b["c"])) / 3.0
            vol = float(b.get("v", 0))
        except Exception:
            continue
        num += typical * vol
        den += vol
    return (num / den) if den > 0 else None


def _direction_changes(closes):
    if len(closes) < 3:
        return 0
    changes = 0
    last_sign = 0
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        sign = 1 if diff > 0 else (-1 if diff < 0 else 0)
        if sign != 0 and last_sign != 0 and sign != last_sign:
            changes += 1
        if sign != 0:
            last_sign = sign
    return changes


# ─── Public API ───────────────────────────────────────────────────────────────

def analyze_pre_open(*,
                      pre_market_bars: Sequence[dict] | None = None,
                      prev_session_close: float | None = None,
                      prev_session_high:  float | None = None,
                      prev_session_low:   float | None = None,
                      historical_pm_volume_avg: float | None = None,
                      ) -> PreOpenAnalysis:
    """Classify pre-open behavior. Fail-soft.

    With Alpaca free IEX feed `pre_market_bars` will be empty → returns
    INSUFFICIENT_DATA. Operator can supply pre-market bars from any free
    source (e.g. their own broker session export) if available.
    """
    bars = list(pre_market_bars or [])

    if not bars or prev_session_close is None or prev_session_close <= 0 \
            or len(bars) < MIN_BARS:
        return PreOpenAnalysis(
            label=INSUFFICIENT_DATA, gap_pct=None,
            pre_market_volume=None, pre_market_vwap=None,
            distance_from_prev_close_pct=None,
            distance_from_prev_high_pct=None,
            distance_from_prev_low_pct=None,
            bars_count=len(bars),
            insufficient_data=True,
            direction_changes=0,
            confidence_adjustment=0.0,
            rationale="insufficient_pre_market_data",
        )

    try:
        first_pm_open = float(bars[0]["o"])
        last_pm_close = float(bars[-1]["c"])
        pm_volume = sum(float(b.get("v", 0)) for b in bars)
        closes = [float(b["c"]) for b in bars]
    except Exception:
        return PreOpenAnalysis(
            label=INSUFFICIENT_DATA, gap_pct=None,
            pre_market_volume=None, pre_market_vwap=None,
            distance_from_prev_close_pct=None,
            distance_from_prev_high_pct=None,
            distance_from_prev_low_pct=None,
            bars_count=len(bars),
            insufficient_data=True,
            direction_changes=0,
            confidence_adjustment=0.0,
            rationale="parse_error_in_pre_market_bars",
        )

    gap_pct = (last_pm_close - prev_session_close) / prev_session_close
    vwap = _pre_market_vwap(bars)
    distance_from_close = gap_pct
    distance_from_high = ((last_pm_close - prev_session_high) / prev_session_high
                          if prev_session_high else None)
    distance_from_low = ((last_pm_close - prev_session_low) / prev_session_low
                          if prev_session_low else None)
    direction_changes = _direction_changes(closes)

    # Volume relative to historical pre-market avg
    rel_vol = None
    if historical_pm_volume_avg and historical_pm_volume_avg > 0:
        rel_vol = pm_volume / historical_pm_volume_avg

    # Classification
    if gap_pct >= STRONG_GAP_PCT:
        if rel_vol is not None and rel_vol < 0.5:
            label = LOW_VOLUME_FAKE_MOVE
        else:
            label = GAP_UP_STRONG_PRE_OPEN
    elif gap_pct >= WEAK_GAP_PCT:
        label = GAP_UP_WEAK_PRE_OPEN
    elif gap_pct <= -STRONG_GAP_PCT:
        if rel_vol is not None and rel_vol < 0.5:
            label = LOW_VOLUME_FAKE_MOVE
        else:
            label = GAP_DOWN_STRONG_PRE_OPEN
    elif gap_pct <= -WEAK_GAP_PCT:
        label = GAP_DOWN_WEAK_PRE_OPEN
    else:
        if rel_vol is not None and rel_vol > HIGH_REL_VOL_MULT:
            label = HIGH_REL_VOLUME
        else:
            label = FLAT_PRE_OPEN

    # Conservative confidence adjustment
    if label in (GAP_UP_STRONG_PRE_OPEN, GAP_DOWN_STRONG_PRE_OPEN) and \
            rel_vol is not None and rel_vol > 1.0:
        adj = 0.05
    elif label == LOW_VOLUME_FAKE_MOVE:
        adj = -0.10
    elif label == HIGH_REL_VOLUME:
        adj = 0.02
    else:
        adj = 0.0

    rationale = (
        f"gap={gap_pct:+.3f} vwap={vwap} rel_vol={rel_vol} "
        f"direction_changes={direction_changes} → {label}"
    )

    return PreOpenAnalysis(
        label=label,
        gap_pct=gap_pct,
        pre_market_volume=pm_volume,
        pre_market_vwap=vwap,
        distance_from_prev_close_pct=distance_from_close,
        distance_from_prev_high_pct=distance_from_high,
        distance_from_prev_low_pct=distance_from_low,
        bars_count=len(bars),
        insufficient_data=False,
        direction_changes=direction_changes,
        confidence_adjustment=adj,
        rationale=rationale,
    )


__all__ = [
    "GAP_UP_STRONG_PRE_OPEN", "GAP_UP_WEAK_PRE_OPEN",
    "GAP_DOWN_STRONG_PRE_OPEN", "GAP_DOWN_WEAK_PRE_OPEN",
    "FLAT_PRE_OPEN", "HIGH_REL_VOLUME", "LOW_VOLUME_FAKE_MOVE",
    "INSUFFICIENT_DATA", "VALID_LABELS",
    "STRONG_GAP_PCT", "WEAK_GAP_PCT", "HIGH_REL_VOL_MULT",
    "PreOpenAnalysis", "analyze_pre_open",
]
