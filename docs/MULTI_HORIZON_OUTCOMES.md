# Multi-Horizon Outcome Tracking — v3.21 ETAP 3

## Why

The audit board flagged STRAT-003 (strategy validation deficit). A single
end-of-trade P&L number hides whether the edge lives in the first five
minutes, dies after lunch, or only shows up overnight. Multi-horizon
outcomes compute deterministic hypothetical results at six fixed
horizons so the strategy layer can see the *shape* of the return, not
just its tail.

## Hard invariants

- Records are stamped with `evidence_source="MULTI_HORIZON"` (a plain
  string constant). They are **never** counted as paper trades and
  **never** modify `paper_n`. Strategy ranking and the evidence lower
  bounds module continue to treat them as triage-only.
- Each horizon is computed independently. A failure in one horizon
  emits `outcome="UNKNOWN"` for that horizon only — the other horizons
  still compute.
- The module is observe-only: no broker calls, no LLM, no paid APIs,
  no state mutations, and no flip of `EDGE_GATE_ENABLED`. Risk gates
  in upstream code paths are not affected by this module.
- Determinism is enforced by deterministic slippage (5 bps) and
  half-spread (1 bps) constants — same inputs always yield the same
  outcome record.

## Public API

```python
from shared.multi_horizon_outcomes import (
    HORIZONS,
    compute_outcome_for_signal,
    compute_outcomes_for_signal,
    compute_outcomes_for_ledger,
    write_outcomes_jsonl,
)
```

- `HORIZONS` — `("5min", "15min", "30min", "60min", "end_of_day",
  "next_session_open")`.
- `compute_outcome_for_signal(signal, horizon, *, bars_fetcher=None,
  slippage_bps=5.0, half_spread_bps=1.0)` returns one `HorizonOutcome`.
- `compute_outcomes_for_signal(signal, horizons=HORIZONS, **kwargs)`
  returns `{horizon: HorizonOutcome}`.
- `compute_outcomes_for_ledger(date_iso=None, ledger_dir=None,
  horizons=HORIZONS, **kwargs)` runs over the opportunity ledger and
  writes one record per signal.
- `write_outcomes_jsonl(records, *, out_dir=None, date_iso=None)`
  appends to `learning-loop/multi_horizon_outcomes/<date>.jsonl`.

## Outcome shape

```python
@dataclass
class HorizonOutcome:
    signal_id: str
    symbol: str
    side: str
    horizon: str
    horizon_minutes: int | None
    entry_ts: str
    entry_price: float
    horizon_price: float | None
    hypothetical_return_pct: float
    net_return_after_costs_pct: float
    mfe_pct: float
    mae_pct: float
    direction_correctness: bool | None
    drawdown_before_profit_pct: float
    time_to_mfe_minutes: float | None
    time_to_mae_minutes: float | None
    outcome: str            # "PROFITABLE" | "LOSING" | "FLAT" | "UNKNOWN"
    status: str = "OK"      # "OK" | "MISSING_BARS" | "BAD_INPUT" | ...
    evidence_source: str = "MULTI_HORIZON"
    notes: str = ""
```

## CLI

```
python3 scripts/multi_horizon_outcome_report.py --date 2026-06-04
python3 scripts/multi_horizon_outcome_report.py --date today --dry-run
```

The report writes a markdown summary plus a JSONL file under
`reports/multi_horizon_outcomes/<date>.{md,jsonl}`. The operator
reviews the markdown before any downstream gate is touched.

## What the module does not do

- It does not enable trading.
- It does not modify risk thresholds or `EDGE_GATE_ENABLED`.
- It does not call the broker. The only network call possible is the
  injectable `bars_fetcher` which defaults to the existing
  `shared.market_data.get_daily_bars` helper.
- It does not promise profits or recommend live trading.

## Reviewers

This module is governed by the Multi-Agent Audit Board: the markdown
report is the artefact reviewed; the JSONL is the deterministic record.
Threshold or weight changes are non-auto-apply by design.
