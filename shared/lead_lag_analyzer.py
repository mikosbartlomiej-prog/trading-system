"""v3.15.0 (2026-06-04) — LeadLagAnalyzer.

Closes audit-board feedback FB-003 (index/sector lead-lag influence).

WHY
---
Trader feedback: when an index moves, it usually pulls the stock with it,
sometimes with a delay. The system has no index-correlation or lead-lag
analysis. Adding it gives:
  - confidence boost when stock is index-aligned with sane correlation
  - confidence penalty when stock diverges from a strongly-moving index
  - "delayed follower" detection (stock lags index → entry opportunity)

CONTRACT
--------
Pure computation on daily bars. Reads symbol bars + index bars
(typically SPY/QQQ) from `market_data.get_daily_bars`. Outputs
`LeadLagResult` dataclass consumed by confidence_builder.

NEVER generates trades. NEVER raises caller errors. Conservative output:
unclear correlation → "no_edge" verdict that does NOT raise confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence

# ─── Verdict labels ───────────────────────────────────────────────────────────

INDEX_ALIGNED        = "INDEX_ALIGNED"
INDEX_DIVERGENT      = "INDEX_DIVERGENT"
DELAYED_FOLLOWER     = "DELAYED_FOLLOWER"
LEAD_INDEX           = "LEAD_INDEX"
NO_EDGE              = "NO_EDGE"
INSUFFICIENT_DATA    = "INSUFFICIENT_DATA"

VALID_VERDICTS = (INDEX_ALIGNED, INDEX_DIVERGENT, DELAYED_FOLLOWER,
                   LEAD_INDEX, NO_EDGE, INSUFFICIENT_DATA)


# ─── Tunables ────────────────────────────────────────────────────────────────

MIN_BARS_FOR_CORR        = 20
LOOKBACK                 = 30
LAG_RANGE                = 3       # test lags 1..3 days for delayed follower
STRONG_CORR_THRESHOLD    = 0.50
DIVERGENCE_THRESHOLD     = -0.30
LAG_PREFERENCE_THRESHOLD = 0.10    # lag corr must beat lag-0 by this margin


@dataclass(frozen=True)
class LeadLagResult:
    verdict:                str
    contemporaneous_corr:   float        # symbol returns vs index returns, same day
    best_lag:               int          # +1..LAG_RANGE = symbol lags index by N days
    best_lag_corr:          float
    sample_size:            int
    last_index_return_pct:  float | None
    last_symbol_return_pct: float | None
    same_day_alignment:     str          # "same_dir", "opposite_dir", "flat"
    rationale:              str

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Pure helpers ─────────────────────────────────────────────────────────────

def _pct_changes(closes: Sequence[float]) -> list[float]:
    if len(closes) < 2:
        return []
    return [(closes[i] - closes[i-1]) / closes[i-1]
             for i in range(1, len(closes)) if closes[i-1] != 0]


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _pearson(xs, ys):
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom_x = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    denom_y = (sum((y - my) ** 2 for y in ys)) ** 0.5
    denom = denom_x * denom_y
    if denom == 0:
        return 0.0
    return num / denom


def _lagged_corr(symbol_rets, index_rets, lag):
    """Correlation when symbol_rets[t] is paired with index_rets[t-lag].

    lag > 0  → symbol follows index by `lag` days (delayed follower hypothesis).
    lag < 0  → symbol leads index.
    """
    if lag == 0:
        return _pearson(symbol_rets, index_rets)
    if lag > 0:
        if lag >= len(symbol_rets):
            return 0.0
        return _pearson(symbol_rets[lag:], index_rets[:-lag])
    # lag < 0
    k = -lag
    if k >= len(symbol_rets):
        return 0.0
    return _pearson(symbol_rets[:-k], index_rets[k:])


# ─── Public API ───────────────────────────────────────────────────────────────

def analyze_lead_lag(*,
                       symbol_closes: Sequence[float],
                       index_closes:  Sequence[float],
                       ) -> LeadLagResult:
    """Compute lead-lag correlation between symbol and index.

    Inputs are daily closes (chronological). Lengths can differ — we align
    to the shorter sequence (trailing).
    """
    if (symbol_closes is None or index_closes is None
            or len(symbol_closes) < MIN_BARS_FOR_CORR
            or len(index_closes)  < MIN_BARS_FOR_CORR):
        return LeadLagResult(
            verdict=INSUFFICIENT_DATA, contemporaneous_corr=0.0,
            best_lag=0, best_lag_corr=0.0, sample_size=0,
            last_index_return_pct=None, last_symbol_return_pct=None,
            same_day_alignment="unknown",
            rationale="insufficient_bars",
        )

    n = min(len(symbol_closes), len(index_closes), LOOKBACK + 1)
    s_window = list(symbol_closes)[-n:]
    i_window = list(index_closes)[-n:]
    s_rets = _pct_changes(s_window)
    i_rets = _pct_changes(i_window)

    if len(s_rets) != len(i_rets) or len(s_rets) < MIN_BARS_FOR_CORR - 1:
        return LeadLagResult(
            verdict=INSUFFICIENT_DATA, contemporaneous_corr=0.0,
            best_lag=0, best_lag_corr=0.0, sample_size=len(s_rets),
            last_index_return_pct=None, last_symbol_return_pct=None,
            same_day_alignment="unknown",
            rationale="aligned_return_series_too_short",
        )

    contemp = _pearson(s_rets, i_rets)

    # Search for best lag in -LAG_RANGE..+LAG_RANGE (excluding 0)
    best_lag, best_lag_corr = 0, contemp
    for lag in range(-LAG_RANGE, LAG_RANGE + 1):
        if lag == 0:
            continue
        c = _lagged_corr(s_rets, i_rets, lag)
        if abs(c) > abs(best_lag_corr):
            best_lag = lag
            best_lag_corr = c

    last_index_ret = i_rets[-1] if i_rets else None
    last_symbol_ret = s_rets[-1] if s_rets else None

    same_dir_threshold = 0.001
    if last_index_ret is None or last_symbol_ret is None:
        alignment = "unknown"
    elif abs(last_index_ret) < same_dir_threshold and abs(last_symbol_ret) < same_dir_threshold:
        alignment = "flat"
    elif last_index_ret * last_symbol_ret > 0:
        alignment = "same_dir"
    else:
        alignment = "opposite_dir"

    # Verdict
    if contemp >= STRONG_CORR_THRESHOLD:
        verdict = INDEX_ALIGNED
        rationale = (f"contemporaneous_corr={contemp:.2f} >= {STRONG_CORR_THRESHOLD}; "
                      f"alignment={alignment}")
    elif contemp <= DIVERGENCE_THRESHOLD:
        verdict = INDEX_DIVERGENT
        rationale = (f"contemporaneous_corr={contemp:.2f} <= {DIVERGENCE_THRESHOLD} "
                      f"(strongly negative correlation); alignment={alignment}")
    elif (best_lag > 0
            and best_lag_corr > STRONG_CORR_THRESHOLD
            and best_lag_corr > contemp + LAG_PREFERENCE_THRESHOLD):
        verdict = DELAYED_FOLLOWER
        rationale = (f"delayed_follower: lag={best_lag}d corr={best_lag_corr:.2f} > "
                      f"contemp={contemp:.2f}+margin {LAG_PREFERENCE_THRESHOLD}")
    elif (best_lag < 0
            and best_lag_corr > STRONG_CORR_THRESHOLD
            and best_lag_corr > contemp + LAG_PREFERENCE_THRESHOLD):
        verdict = LEAD_INDEX
        rationale = (f"leads_index: lag={best_lag}d corr={best_lag_corr:.2f}")
    else:
        verdict = NO_EDGE
        rationale = (f"contemp_corr={contemp:.2f}; best_lag={best_lag} corr={best_lag_corr:.2f}; "
                      f"no_clear_edge")

    return LeadLagResult(
        verdict=verdict,
        contemporaneous_corr=contemp,
        best_lag=best_lag,
        best_lag_corr=best_lag_corr,
        sample_size=len(s_rets),
        last_index_return_pct=last_index_ret,
        last_symbol_return_pct=last_symbol_ret,
        same_day_alignment=alignment,
        rationale=rationale,
    )


def confidence_adjustment(result: LeadLagResult) -> float:
    """Translate verdict into a CONFIDENCE ADJUSTMENT in [-0.10..+0.05].

    Conservative — never adds more than +0.05; can subtract up to 0.10.
    The point is to gently reward alignment, gently penalise divergence.
    """
    v = result.verdict
    if v == INDEX_ALIGNED and result.same_day_alignment == "same_dir":
        return +0.05
    if v == DELAYED_FOLLOWER:
        return +0.03
    if v == LEAD_INDEX:
        return +0.02
    if v == INDEX_DIVERGENT:
        return -0.10
    if v == NO_EDGE and result.same_day_alignment == "opposite_dir":
        return -0.03
    return 0.0


__all__ = [
    "INDEX_ALIGNED", "INDEX_DIVERGENT", "DELAYED_FOLLOWER",
    "LEAD_INDEX", "NO_EDGE", "INSUFFICIENT_DATA",
    "VALID_VERDICTS",
    "MIN_BARS_FOR_CORR", "LOOKBACK", "LAG_RANGE",
    "STRONG_CORR_THRESHOLD", "DIVERGENCE_THRESHOLD",
    "LeadLagResult", "analyze_lead_lag", "confidence_adjustment",
]
