# Strategy Ranking (v3.19.0, ETAP 5)

**Module:** `shared/strategy_ranking.py`
**Reports:** `docs/strategy_ranking_LATEST.md` + `.json`
**Status:** Advisory only · Paper trading only · Never auto-trades

---

## Purpose

`strategy_ranking` orders strategies worst → best on a composite,
deterministic score based on paper trading evidence. It exists so the
operator can quickly see which strategies are currently strongest and
which need attention.

It does **not** increase real risk. Ranking is purely about better
selection of what to observe and propose for review.

---

## Hard contract

| Rule | Enforcement |
|---|---|
| Paper trading only | Reads paper metrics. Never live broker. |
| Cannot raise risk | Score has no effect on position size, leverage, exposure. |
| Cannot auto-trade | Output is reports only. |
| Never enables EDGE_GATE | Strategy ranking ≠ promotion. |
| Defensive | Bad metrics LOWER rank. They never raise it. |
| Deterministic | Same input → same ranking + scores. |
| Audit emit | Each rank decision emits a JSONL line. |

---

## Component weights (sum normalized)

| Component | Weight | Direction |
|---|---:|---|
| `n_closed` (sample size, capped at 100) | 0.05 | more = better |
| `profit_factor` | 0.18 | higher = better |
| `expectancy` | 0.12 | positive = better |
| `win_rate` | 0.10 | higher = better |
| `max_drawdown` | 0.10 | lower = better |
| `slippage_adjusted_pf` | 0.08 | higher = better |
| `fee_adjusted_expectancy` | 0.07 | higher = better |
| `confidence_calibration` | 0.10 | higher = better |
| `regime_stability` | 0.10 | more regimes = better |
| `instrument_concentration` | 0.05 | lower share = better |
| `recent_degradation_penalty` | 0.05 | no degradation = better |

**Hard gates (score pinned to 0.0, automatic last rank):**

- `risk_violations > 0`
- `audit_incomplete == True`

The hard gates ensure that a strategy with operational defects can
never rise above a healthy one purely on raw P&L.

---

## Status mapping

```
EDGE_REVIEW_CANDIDATE  : score >= 0.78
TOP_OBSERVE            : score >= 0.65
CONTINUE_OBSERVE       : score >= 0.45
REDUCE_PRIORITY        : score <= 0.25
DISABLE_CANDIDATE      : score <= 0.10 (or risk_violations / audit_incomplete)
NEEDS_MORE_DATA        : n_closed < 10
```

Status order in code:

```
NEEDS_MORE_DATA   (data thin)
DISABLE_CANDIDATE (hard violations or score ~0)
REDUCE_PRIORITY
CONTINUE_OBSERVE
TOP_OBSERVE
EDGE_REVIEW_CANDIDATE
```

`EDGE_REVIEW_CANDIDATE` is **NOT** an auto-promotion. The strategy
quality gate (`shared/strategy_quality_gate.py`) plus a manual operator
flip are still required before `EDGE_GATE_ENABLED` can be set true.

---

## Example

```python
from shared.strategy_ranking import rank_strategies, write_ranking_reports
from shared.paper_experiment import compute_strategy_metrics

metrics = {
    name: compute_strategy_metrics(name, window_days=180)
    for name in ["momentum-long", "geo-defense", "crypto-momentum"]
}

ranked = rank_strategies(paper_metrics_per_strategy=metrics)
write_ranking_reports(ranked)
```

The ordering is `score DESC, strategy ASC` — deterministic ties.

---

## What it does NOT do

- It does **not** mutate `learning-loop/state.json`.
- It does **not** flip `EDGE_GATE_ENABLED`.
- It does **not** change position sizes, risk caps, or kill-switch
  state.
- It does **not** make any trading decision.
- It does **not** use LLM.
- It does **not** compare backtest with paper as equivalent evidence.
