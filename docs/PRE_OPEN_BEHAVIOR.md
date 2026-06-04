# Pre-Open Behavior — v3.18.0 (2026-06-04)

**Status:** Activated. `scripts/pre_open_session_planner.py` runs daily
30 min before US market open.

## What the planner does

The pre-open session planner is a one-shot script that runs ~30 min
before US market open (13:00 UTC, weekdays). For each symbol in the
current watchlist:

1. Fetches pre-market context via
   `shared/pre_market_data.get_pre_market_context(symbol)`. This taps
   the **Yahoo + Nasdaq cascade** (free, gray-zone, no API key).
2. Analyzes the pre-market bars via
   `shared/pre_open_behavior.analyze_pre_open(...)`. Classifies into one
   of: GAP_UP_STRONG / GAP_UP_WEAK / GAP_DOWN_STRONG / GAP_DOWN_WEAK /
   FLAT / HIGH_REL_VOLUME / LOW_VOLUME_FAKE_MOVE / INSUFFICIENT_DATA.
3. Persists per-symbol plan into
   `learning-loop/runtime_state.json::pre_open_plan` via
   `shared/pre_open_plan.store_plan(...)`.

Monitors read the plan during the session via
`shared.pre_open_plan.get_plan_for_symbol(symbol)` and add the per-symbol
penalty / minor booster into `confidence_inputs`. The confidence builder
then combines it with the existing v3.15 / v3.17 adjustments.

## Free data source

Trader feedback question #3 (operator decision walkthrough 2026-06-04)
opted in for the gray-zone path:

- **Tier 1 (primary)**: Yahoo `query1.finance.yahoo.com/v8/finance/chart`
  — undocumented but stable. Includes pre/post sessions.
- **Tier 2 (fallback)**: Nasdaq
  `api.nasdaq.com/api/quote/{symbol}/extended-trading` — also
  undocumented, simpler summary shape.
- **Tier 3 (last resort)**: previous-day OHLC from Alpaca IEX daily bars
  (always free for paper). When pre-market itself is unavailable, the
  planner emits the `no_data` warning and zero confidence adjustment.

IEX (Alpaca free feed) does **not** include pre-market bars; that
requires the paid SIP feed (currently rejected for cost reasons).

## Plan output schema

Per-symbol entry shape (stored in `runtime_state.json::pre_open_plan.per_symbol`):

```json
{
  "symbol":                "AAPL",
  "label":                 "GAP_UP_STRONG_PRE_OPEN",
  "gap_pct":               0.0287,
  "warnings":              ["pre_market_gap_strong"],
  "confidence_adjustment": 0.05,
  "source":                "yahoo",
  "rationale":             "gap=+0.029 vwap=178.41 rel_vol=2.1 → ...",
  "generated_at":          "2026-06-04T13:00:08Z"
}
```

Top-level wrapper:

```json
{
  "plan_date":       "2026-06-04",
  "generated_at":    "2026-06-04T13:00:09Z",
  "per_symbol":      { "AAPL": {...}, "MSFT": {...} },
  "warnings":        [],
  "symbols_planned": 28
}
```

## How monitors consume the plan

Monitors that build `confidence_inputs` for a symbol can fetch the
pre-open entry and route it through the confidence builder via the
`pre_open_analysis` parameter (already supported in v3.15.0):

```python
from shared.pre_open_plan import get_plan_for_symbol
entry = get_plan_for_symbol(symbol)
if entry:
    # Build a lightweight PreOpenAnalysis-shaped object or pass dict-as-attr
    signal["confidence_inputs"]["pre_open_warnings"]    = entry["warnings"]
    signal["confidence_inputs"]["pre_open_adjustment"]  = entry["confidence_adjustment"]
    signal["confidence_inputs"]["pre_open_label"]       = entry["label"]
```

The confidence builder applies the adjustment within its capped envelope
(net ± 0.10) so even a strong pre-market signal cannot dominate the
five-component score.

## Why this NEVER places trades

By design and by audit:

- `pre_open_session_planner.py` calls **only** `pre_market_data`,
  `pre_open_behavior`, and `pre_open_plan`. None of these touch
  `alpaca_orders`, `allocator`, or any execution path.
- `pre_open_plan.store_plan(...)` writes to `runtime_state.json` only;
  it never schedules orders.
- The `MAX_POSITIVE_ADJUSTMENT = +0.05` constant in
  `shared/pre_open_plan.py` is enforced as a hard clamp regardless of
  what the upstream analyzer returned — defense in depth.

## Limitations

- **No pre-market on free IEX.** Yahoo + Nasdaq fill the gap but both
  are gray-zone (undocumented, can rate-limit / change response shape).
- **Yahoo rate limits.** Sustained 429s on Yahoo would degrade plan
  quality. Operator should monitor `pre_open_plan.warnings` for
  `yahoo_rate_limit` and switch primary to Nasdaq if it persists.
- **Plan is a snapshot.** The planner runs once, 30 min before open. A
  pre-market move that happens AFTER 13:00 UTC won't be reflected. The
  Intraday Trend Monitor (v3.11.3) covers post-open behavior; this
  planner only sets the opening posture.
- **No per-strategy specialization.** The planner produces one entry per
  symbol. Strategies that want strategy-specific pre-open warnings
  should read the entry and apply their own interpretation.

## Audit trail

The planner does NOT emit audit JSONL events; the plan itself is the
audit (committed to git via `runtime_state.json`). The downstream
confidence gate emits audit events when the plan-derived adjustment
causes a BLOCK / ALERT_ONLY decision in `risk_officer`.

## Re-decision triggers

Operator should re-evaluate the pre-open planner architecture when:

- **Yahoo or Nasdaq blocks our IP** (sustained 429 / 403). The free
  Polygon tier or Tiingo would be the next candidates.
- **Paid SIP feed becomes affordable** (current Alpaca quote: ~$99/mo).
  At that point IEX → SIP would unify the data path and eliminate the
  gray-zone dependency.
- **A free Polish pre-market source appears.** PL/GPW universe could
  then become viable. Currently the planner is US-only (Yahoo+Nasdaq
  cover US tickers only).

## Related files

- `shared/pre_market_data.py` — Yahoo + Nasdaq cascade fetcher.
- `shared/pre_open_behavior.py` — pure analyzer (label + adjustment).
- `shared/pre_open_plan.py` — runtime_state storage.
- `scripts/pre_open_session_planner.py` — daily orchestrator.
- `scripts/workflow-templates/pre-open-planner.yml` — cron workflow.
- `shared/confidence_builder.py::_apply_v3150_adjustments` — consumer.
- `tests/test_pre_open_plan_v3180.py` — unit tests.

---

## v2 plan extensions (v3.19.0 — 2026-06-04)

The plan schema gains session-level + per-strategy fields. v1 readers
continue to work — v2 fields are additive and optional.

### v2 schema

```json
{
  "plan_date":                      "2026-06-04",
  "generated_at":                   "2026-06-04T13:00:00Z",
  "symbols_planned":                25,
  "warnings":                       ["pre_market_data_unavailable_majority"],
  "per_symbol":                     { /* v1 per-symbol entries */ },

  // v2 extensions
  "expected_regime":                "NEUTRAL",
  "high_risk_symbols":              ["TSLA", "MSTR"],
  "do_not_trade_list":              ["NVDA"],
  "observe_only_list":              ["AAPL"],
  "strategy_warnings":              {"momentum-long": ["regime_mismatch"]},
  "confidence_caps_per_strategy":   {"options-momentum": 0.55},
  "confidence_caps_per_symbol":     {"TSLA": 0.60, "NVDA": 0.0},
  "event_risk_warnings":            ["FOMC at 18:00 UTC"],
  "liquidity_warnings":             ["GOOGL:low_volume_fake"],
  "gap_warnings":                   ["TSLA:GAP_UP_WEAK_PRE_OPEN"],
  "stale_data_warnings":            ["MSFT"],
  "daily_experiment_objectives":    ["validate fills against expectations"]
}
```

### Critical invariant: apply_pre_open_caps NEVER raises confidence

```python
from pre_open_plan import get_plan, apply_pre_open_caps
plan = get_plan()
adjusted = apply_pre_open_caps(plan,
                                strategy="momentum-long",
                                symbol="TSLA",
                                current_confidence=0.78)
# adjusted is ALWAYS <= 0.78 — this is enforced by the helper itself.
```

The helper applies, in order: per-strategy cap → per-symbol cap →
`STALE_DATA_PENALTY` (-0.05) if the symbol is on `stale_data_warnings`
→ hard zero if symbol is on `do_not_trade_list`. Each step CAN ONLY
LOWER confidence — the helper guarantees that `adjusted ≤ original`.

### CLI behaviour

`scripts/pre_open_session_planner.py` automatically derives session-level
v2 fields from per-symbol analysis:

- Strong gap (`GAP_*_STRONG_PRE_OPEN`) → `do_not_trade_list` + cap 0.0
- Weak gap → `high_risk_symbols` + cap 0.65
- Low-volume fake move → `observe_only_list` + cap 0.45
- High relative volume → `event_risk_warnings`
- Insufficient data → `stale_data_warnings`

These derivations are conservative — the operator can always edit the
stored runtime_state to override before market open if needed.
