# Pre-market data (FB-002) — v3.16.0 (2026-06-04)

## What this is

`shared/pre_market_data.py` is the free-tier fetcher that finally gives
`shared/pre_open_behavior.analyze_pre_open` real input bars. The v3.15.0
interface accepted caller-supplied bars and shipped synthetic tests, but
no production data source. v3.16 wires Yahoo Finance's chart endpoint as
primary, with a Nasdaq extended-trading summary as fallback.

## Why ship it

Trader feedback (audit-board 2026-06-02, FB-002) noted that pre-market
behavior often predicts opening behavior — gap up on heavy volume vs gap
up on no volume tells a different story. Without real pre-market data the
v3.15.0 `analyze_pre_open` always returned `INSUFFICIENT_DATA`, so the
confidence builder never got a +0.05 boost from pre-open analysis.

The operator (decision walkthrough 2026-06-04, question #3) opted IN for
the gray-zone Yahoo path knowing the trade-offs:

- Pros: free, low latency, broad coverage of US equities, includes
  pre-market when `includePrePost=true`.
- Cons: undocumented endpoint; Yahoo can change the response shape or
  rate-limit without notice; technically outside their published API.

The Nasdaq extended-trading endpoint is also undocumented but published
on their consumer-facing site and tends to be stable for individual
symbol look-ups. It only returns a summary snapshot, not bars — so it's a
last-mile fallback when Yahoo fails.

## How it integrates

```text
caller monitor
    │
    └─► shared/pre_market_data.get_pre_market_context(symbol)
            │
            ├── fetch_pre_market_bars(symbol)             # Yahoo (primary)
            │       └─ list[bar_dict] (bars["o","h","l","c","v","t"])
            │
            ├── fetch_pre_market_summary(symbol)          # Nasdaq (fallback)
            │       └─ dict | None
            │
            └── shared/market_data.get_daily_bars(...)    # prev-session OHLC
                    └─ Alpaca IEX free
        │
        ▼
    {"pre_market_bars": [...], "prev_session_close": float|None, ...}
        │
        ▼
    shared/pre_open_behavior.analyze_pre_open(
        pre_market_bars=ctx["pre_market_bars"],
        prev_session_close=ctx["prev_session_close"],
        prev_session_high=ctx["prev_session_high"],
        prev_session_low=ctx["prev_session_low"],
    )
        │
        ▼
    PreOpenAnalysis  (consumed by shared/confidence_builder)
```

The wiring inside `confidence_builder` is the responsibility of the next
backlog item (FB-002 step 2). This module is the data layer only.

## Yahoo gray-zone ToS

The operator explicitly accepted (2026-06-04 question #3) that Yahoo's
`v8/finance/chart` is undocumented. Mitigations baked into this module:

- Custom `User-Agent: trading-system-paper/3.16 ...` so traffic is
  identifiable and rate-limit-able by Yahoo if needed.
- 10s HTTP timeout — no long-running connections.
- 300s in-process cache per (symbol, endpoint) — caps request rate from
  any single monitor process.
- Fail-soft on every error path: HTTP 429, timeout, malformed JSON,
  missing keys → empty list / None / `source=unavailable` + warning.

If Yahoo blocks us, the system degrades gracefully — `PreOpenAnalysis`
returns `INSUFFICIENT_DATA`, confidence does not get the +0.05 boost,
and trading continues with reduced information (exactly as v3.15.0
behaved). No trades go through naked.

## Rate-limit assumptions

- Yahoo: undocumented but empirically tolerant of single-symbol look-ups
  at ≤1/min/symbol. We cache 5 minutes so even an aggressive caller
  loop only hits Yahoo once per 5 min per symbol.
- Nasdaq: same caching applies.
- All HTTP calls share the 10s timeout — no thread is blocked longer.

## Failure modes (all silent / fail-soft)

| Failure                                   | What happens                                                     |
|-------------------------------------------|------------------------------------------------------------------|
| Empty / `None` / blank symbol             | Empty list / None / `source=unavailable` + `empty_symbol` warn   |
| Yahoo HTTP 429                            | Empty list; Nasdaq fallback tried for `get_pre_market_context`   |
| Yahoo HTTP 5xx / timeout / DNS / SSL      | Same                                                              |
| Yahoo JSON malformed                      | Same                                                              |
| Yahoo OK but no `chart.result`            | Same                                                              |
| Yahoo OK but no pre-market window         | Empty list; bars filtered to pre window only                     |
| Nasdaq HTTP failure or unknown shape      | `summary=None`; context `source=unavailable`                     |
| `shared.market_data.get_daily_bars` fails | `prev_session_*` stay None; warn `daily_bars_fail`               |
| Special chars in symbol (e.g. `BRK.B`)    | URL-encoded via `urllib.parse.quote_plus`                        |

## Re-decision triggers

- Yahoo `v8/finance/chart` HTTP 429 sustained for ≥24h → switch primary
  to Nasdaq and accept that we only get summary snapshots (no per-minute
  bars). Trade-off: PreOpenAnalysis loses VWAP + direction_changes.
- Yahoo response shape changes (tests break in CI) → patch parser, do
  not deploy until tests are green.
- A free pre-market feed appears (Polygon free tier with PM, IEX cloud
  free tier, broker API) → add as Tier-0 source above Yahoo.
- Operator decides to pay for SIP feed → drop this module entirely and
  route Alpaca SIP bars directly into `analyze_pre_open`.

## Tests

`tests/test_pre_market_data_v3160.py` covers ≥12 cases with all network
mocked:

- Yahoo success → bars returned with the exact shape that
  `analyze_pre_open` expects (`o`, `h`, `l`, `c`, `v`, `t`).
- Yahoo 429 → empty bars; Nasdaq fallback called.
- Yahoo timeout / connection error → empty bars.
- Yahoo malformed JSON → empty bars.
- Nasdaq success → summary dict.
- Both fail → context has empty bars + None prev close + warnings.
- Cache hit within TTL.
- Cache expiry after TTL.
- Empty / None symbol → empty / None / context-with-warnings.
- Special chars in symbol → URL-encoded path verified.
- Bar timestamps are UTC ISO strings.
- `analyze_pre_open` consumes built bars correctly (integration).

Run locally:

```bash
python3 -m unittest tests.test_pre_market_data_v3160 -v
```

## What this module does NOT do

- It does not call live HTTP in tests. All tests monkey-patch
  `requests.get`.
- It does not bypass risk officer. The data layer is upstream of the
  risk engine; nothing here can approve a trade.
- It does not write to disk. No state. No audit emission. The caller
  (confidence_builder wiring, separate backlog item) is responsible
  for surfacing the source/warnings in the decision audit JSONL.
- It does not import paid SDKs. Only `requests` (already a dep) and
  stdlib.
