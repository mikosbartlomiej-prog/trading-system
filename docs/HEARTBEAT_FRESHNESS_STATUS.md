# Heartbeat Freshness Status

- Generated at: `2026-07-23T07:05:46.777441+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 273 | 2026-07-23T07:01:13.771936+00:00 |
| `defense-monitor` | FRESH | 276 | 2026-07-23T07:01:11.032626+00:00 |
| `twitter-monitor` | FRESH | 251 | 2026-07-23T07:01:35.281826+00:00 |
| `reddit-monitor` | FRESH | 29105 | 2026-07-22T23:00:41.714231+00:00 |
| `geo-monitor` | FRESH | 2072 | 2026-07-23T06:31:15.047013+00:00 |
| `politician-monitor` | FRESH | 2056 | 2026-07-23T06:31:30.478207+00:00 |
| `options-monitor` | FRESH | 34467 | 2026-07-22T21:31:19.461292+00:00 |
| `options-exit-monitor` | FRESH | 279 | 2026-07-23T07:01:07.837823+00:00 |
| `price-monitor` | FRESH | 34383 | 2026-07-22T21:32:44.236893+00:00 |
| `exit-monitor` | FRESH | 279 | 2026-07-23T07:01:07.386142+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

