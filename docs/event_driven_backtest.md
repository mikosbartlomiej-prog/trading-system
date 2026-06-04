# Event-driven backtest harness (Phase 1 MVP)

**Version:** v3.16.0 (2026-06-04)
**Status:** MVP_IN_PROGRESS — results advisory only

This is the operator+engineer reference for the event-driven backtest path
shipped in v3.16.0 for the `geo-defense`, `geo-energy`, and `geo-gold`
strategies. It explains WHY the readiness is `MVP_IN_PROGRESS` (not
`HAS_SIGNAL`), the data sources used, the architecture, how to run, and
the decision matrix for promoting the readiness label.

## Why MVP_IN_PROGRESS — statistical power requirement

The system already has a backtest readiness contract (see
`backtest/strategy_registry.py`). Three labels existed before v3.16.0:

  - `HAS_SIGNAL`     — pure signal function exists, walk-forward replay works.
  - `INTERFACE`      — registered but no backtest function yet.
  - `EVENT_DRIVEN`   — requires event-stream replay, NOT bar replay.
  - `NOT_APPLICABLE` — admin / no actual trading signal.

Geo-* strategies were `EVENT_DRIVEN` — that flagged the need for replay
infrastructure but did NOT mean it existed. v3.16.0 ships that
infrastructure (`backtest/event_data.py` + `backtest/event_replay.py` +
`backtest/event_strategies.py`), but the audit-board STRAT-003 contract
requires `n >= 50` backtest trades AND `n >= 20` live trades BEFORE the
`EDGE_GATE_ENABLED` flag can flip and the strategy joins the production
edge ranking.

To honor that gate WITHOUT pretending the harness equals statistical
proof, we introduce a fourth label:

  - `MVP_IN_PROGRESS` — the harness exists, can produce a ledger, but n
    is below the threshold; results are ADVISORY ONLY.

`is_backtest_ready()` returns `False` for `MVP_IN_PROGRESS`. The
`coverage_report()` summary lists it under `tradeable_uncovered`.

## Data source — GDELT 2.0 (free)

We use the GDELT 2.0 Event Database — a publicly accessible event stream
with 15-minute CSV exports going back to 2015.

  - Public bucket: `http://data.gdeltproject.org/gdeltv2/`
  - Schema documentation:
    `http://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf`
  - License: CC-BY (free for research and commercial use)
  - No auth, no rate-limit-by-key (we self-impose 1 req/sec).

### Caveats

  - GDELT v2 CSV does NOT carry headline text per row (only `SOURCEURL`).
    For Phase 1 we attach a SYNTHETIC headline via the test path and rely
    on `event_code` (CAMEO) + `goldstein` score to gate the strategy.
    Phase 2 will cross-reference NewsAPI archives or the GDELT GKG table
    for headlines.
  - CAMEO codes are noisy. Default whitelist:
    `DEFAULT_DEFENSE_PREFIXES = ("19", "20", "18", "17", "13")`.
    Tune via `event_code_prefixes=` parameter.
  - GDELT publishes machine-coded events with some false-positive rate.
    Treat the n < 50 phase as RESEARCH ONLY.
  - The free bucket may be slow under load. The harness has a 30s timeout
    and fails soft (returns `[]`) when downloads fail.

### Cache

  - `backtest/cache/events/<YYYY-MM-DD>.jsonl` per day.
  - Subsequent runs reuse the cache unless `--no-cache` is passed.
  - Tests use `synthesize_event()` — no network ever.

## Architecture

```
┌──────────────────┐                ┌──────────────────────────┐
│  GDELT 2.0       │  fetch_events_ │ backtest/event_data.py   │
│  CSV.zip exports │ ─────for_range │ • parse_gdelt_csv_zip    │
│  (HTTP, free)    │                │ • rate-limit guard       │
└──────────────────┘                │ • JSONL cache            │
                                    └─────────┬────────────────┘
                                              │
                                              ▼
┌──────────────────┐                ┌──────────────────────────┐
│ shared/          │  classify_     │ backtest/event_replay.py │
│ geo_classifier.py│  event_to_     │ • per-event signal fan-  │
│ • KEYWORDS_*     │ ─signals──────►│   out                    │
│ • GeoSignal data │                │ • next-bar-open entry    │
│ • PURE FUNCTION  │                │ • bracket SL/TP simulate │
│ • no I/O         │                │ • trade ledger output    │
└──────────────────┘                └─────────┬────────────────┘
        ▲                                     │
        │ same classifier                     ▼
        │                          ┌──────────────────────────┐
┌───────┴──────────┐               │ backtest/event_          │
│ geo-monitor/     │               │ strategies.py            │
│ monitor.py       │               │ • geo_defense_event_     │
│ • LIVE path:     │               │ • geo_energy_event_      │
│   delegates to   │               │ • geo_gold_event_        │
│   shared         │               │ • EVENT_STRATEGIES map   │
│   classifier     │               └─────────┬────────────────┘
└──────────────────┘                         │
                                              ▼
                                    ┌──────────────────────────┐
                                    │ backtest/run.py CLI      │
                                    │ • dispatch on strategy   │
                                    │   name                   │
                                    │ • writes results JSON    │
                                    └──────────────────────────┘
```

### Classifier as a PURE function

`shared/geo_classifier.py` exports a deterministic function with NO I/O:

```python
def classify_event_to_signals(
    headline: str,
    summary: str = "",
    source_type: str = "",
    *,
    detected_at_iso: str = "",
    event_scoring_result: dict | None = None,
    priority: str | None = None,
    score: int | None = None,
) -> list[GeoSignal]:
    ...
```

Properties:
  - Same inputs → same outputs (pure).
  - Any exception caught → returns `[]` (fail-soft).
  - Never raises.
  - Module-level constants document keyword maps + ticker buckets.

The live monitor (`geo-monitor/monitor.py`) was refactored to delegate to
this classifier instead of carrying its own inline keyword/ticker logic.
The parity test (`test_event_backtest_v3160.TestLiveMonitorParity`)
asserts identical bucket/strategy output on 5 representative headlines.

### Replay loop — no-lookahead invariant

`backtest/event_replay.replay_events()`:

  1. For each event, call `classifier_fn(headline, summary, source_type, ...)`.
  2. For each emitted `GeoSignal`, fetch bars (with cache) for the primary
     ticker.
  3. Find `next bar index > event_day` — entry uses NEXT bar's `open`
     (no same-day fill).
  4. Walk forward up to `max_hold_days`, checking high/low against
     `entry * (1 + sl_pct)` and `entry * (1 + tp_pct)`.
  5. On SL/TP hit OR max-hold, record a trade row.

Trade rows match the shape produced by `backtest/replay.py` so
`compute_rich_metrics()` and `run.py` report logic are reusable.

## How to run

### CLI

```bash
# Geo-defense MVP run, October 2024 window, advisory only:
ALPACA_API_KEY=... ALPACA_SECRET_KEY=... \
python3 -m backtest.run \
    --strategy geo-defense \
    --start 2024-10-01 --days 30
```

Available event strategies:
  - `geo-defense`  — RTX, LMT (CAMEO defense events)
  - `geo-energy`   — XOM, CVX (energy supply shocks)
  - `geo-gold`     — GLD (safe-haven flight)
  - `geo-all`      — all three (matches live monitor's broad pattern)

Bar strategies (`momentum-long`, etc.) still work via the same CLI; the
dispatcher routes by strategy name.

### Expected output

```
Event backtest: strategy=geo-defense window=2024-10-01..2024-10-31 tickers=[]
  (MVP: results ADVISORY ONLY; statistical power threshold n>=50 not enforced)
  events_loaded: <N>
  trades: <T>  wr: <X>%  pnl: $<P>  avg/trade: <Y>%
  debug: {n_events_processed, rejected_events, rejected_signals, unique_symbols}
  ledger written: backtest/results/geo-defense-event-YYYYMMDD-HHMM.json
```

The JSON ledger contains every trade row plus the `summary` block. Use
`compute_rich_metrics()` in `backtest/realism.py` for profit factor and
max drawdown.

## Operator decision matrix — when to flip MVP_IN_PROGRESS → HAS_SIGNAL

DO NOT flip unless ALL of the following hold (audit-board STRAT-003):

  1. Backtest n >= 50 (geo-defense) — accumulate ≥50 SL/TP trades across
     historical windows that span at least one full geopolitical macro
     regime (e.g. include both quiet and elevated periods).
  2. Backtest win rate ≥ 50%.
  3. Profit factor ≥ 1.3.
  4. Max drawdown < 20%.
  5. Live n >= 20 — geo-monitor must have placed ≥20 actual trades in
     production with the SAME classifier.
  6. Live win rate matches backtest within ±15 percentage points.

When ALL six conditions hold, update the registry entry:

```python
"geo-defense": StrategyRegistration(
    name="geo-defense",
    readiness=HAS_SIGNAL,   # flipped from MVP_IN_PROGRESS
    ...
),
```

Then run `strategy_coherence_agent` + `system_consistency_agent` to
verify no regressions. Only then can `EDGE_GATE_ENABLED` consider this
strategy when deciding to enable/disable in production.

## NEVER

  - Flip readiness BEFORE the n thresholds are met.
  - Use the MVP_IN_PROGRESS ledger to size live positions.
  - Promise edge from advisory output.
  - Make the classifier non-pure (no I/O, no state, no network).
  - Break the no-lookahead invariant.

## Tests

`tests/test_event_backtest_v3160.py` — 22 cases:

  - Classifier deterministic per bucket (defense/energy/gold).
  - Noise event returns `[]`.
  - Empty / None inputs handled fail-soft.
  - Cap helper enforces `MAX_TRADES_PER_RUN`.
  - Live-monitor parity on 5 representative headlines.
  - GDELT rate-limit guard sleeps minimum interval.
  - Replay uses next-bar open (no lookahead).
  - Strategy registry exposes `MVP_IN_PROGRESS`.
  - `is_backtest_ready('geo-defense')` returns `False`.
  - CSV parser rejects malformed rows.
  - `synthesize_event()` round-trips.

Run:

```bash
python3 -m unittest tests.test_event_backtest_v3160 -v
```

## Next iteration (out of scope for v3.16.0 MVP)

  - Phase 2: backfill headline text from GDELT GKG table or NewsAPI
    archive — current Phase 1 events have empty `headline` from GDELT v2
    CSV alone, which limits the classifier on real GDELT output.
  - Phase 2: add `event_credibility * goldstein` weighting so violent
    high-goldstein events get HIGH priority sizing automatically.
  - Phase 2: per-event walk-forward folds + Monte-Carlo confidence interval
    on n<50 windows.
  - Phase 3: cross-strategy correlation check (geo-defense vs geo-energy
    fire concurrently — concentration cap interaction).
  - Phase 3: integrate `event_scoring.score_and_decide` into the harness
    so backtest ledger carries the same stance labels live signals do.
