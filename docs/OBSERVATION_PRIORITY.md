# Adaptive Observation Priority — v3.21 ETAP 8

## Why

The experiment scheduler (v3.20 ETAP 7) treats every (strategy, symbol,
regime) triple as equally interesting once the operator has opted in.
Over time some triples become well-sampled while others are critically
under-covered for the regime we are about to enter. Adaptive priority
ranks triples deterministically so the scheduler can focus its
observation budget on the data it actually needs.

## Hard invariants

- The module is **recommendation-only**. It never enables trading,
  never raises position limits, never bypasses risk gates, and never
  flips `EDGE_GATE_ENABLED`.
- It is consumed by the experiment scheduler — which is itself
  observe-only.
- No broker calls, no paid APIs, no LLM. Pure stdlib + the opportunity
  ledger and confidence calibration helpers already in the repo.
- Determinism: same inputs → same priority. No randomness, no
  time-of-day jitter.
- `DO_NOT_OBSERVE` only fires when `shared.evidence_lower_bounds`
  classifies the strategy as `EVIDENCE_REJECT` — this module does
  **not** introduce a new gate.

## Inputs

Each call to `compute_priority` accepts the following keyword arguments;
every one is optional and defaults to a neutral component score of 0.5:

| Argument | Component | Notes |
|---|---|---|
| `paper_n` | `missing_evidence` | Gap to `TARGET_PAPER_N = 50`. |
| `opportunities_per_day` | `signal_density` | Capped at 5 / day. |
| `historical_promise` | `historical_promise` | Already in `[0, 1]`. |
| `confidence_calibration` | `confidence_calibration_gap` | From `shared.confidence_calibration`. |
| `regime_coverage` | `regime_undercoverage` | `{regime: coverage_ratio}`. |
| `quote` | `symbol_liquidity` + `spread_quality` | `{bid, ask}`. |
| `unknown_rejection_rate` | `rejection_uncertainty` | Counterfactual `UNKNOWN` share. |
| `false_rejection_rate` | `counterfactual_opportunity` | From `aggregate_by_gate`. |
| `strategy_ranking_score` / `rank_position` / `total_ranked` | `strategy_ranking` | Pre-computed by `rank_strategies`. |
| `lower_bound_status` | `lower_bound_status` | From `classify_strategy_evidence`. |

## Output

```python
@dataclass
class PriorityScore:
    strategy: str
    symbol: str
    regime: str
    priority_score: float
    status: str        # PRIORITY_OBSERVE | NORMAL_OBSERVE | LOW_PRIORITY
                       # | DO_NOT_OBSERVE | NEEDS_DATA
    components: dict
    notes: str = ""
```

## Status ladder

- `PRIORITY_OBSERVE` — high priority, the scheduler should bump this
  triple.
- `NORMAL_OBSERVE` — default rotation.
- `LOW_PRIORITY` — observe rarely.
- `DO_NOT_OBSERVE` — `lower_bound_status == "EVIDENCE_REJECT"`.
- `NEEDS_DATA` — fresh triple with no paper data; never starve it.

## CLI

```
python3 scripts/observation_priority_report.py \
    --input triples.json --date today
```

The input file is a JSON list of dicts shaped like the keyword
arguments of `compute_priority`. The script writes both a markdown
summary and a JSONL trace under `reports/observation_priority/<date>.{md,jsonl}`.

## Reviewers

The scheduler is governed by the Multi-Agent Audit Board. Weight or
threshold changes are non-auto-apply by design.
