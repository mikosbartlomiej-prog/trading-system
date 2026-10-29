# Heartbeat Freshness Status

- Generated at: `2026-10-29T11:02:17.021218+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 386 | 2026-10-29T10:55:51.355967+00:00 |
| `defense-monitor` | FRESH | 675 | 2026-10-29T10:51:02.127460+00:00 |
| `twitter-monitor` | FRESH | 377 | 2026-10-29T10:55:59.809683+00:00 |
| `reddit-monitor` | FRESH | 34162 | 2026-10-29T01:32:55.500475+00:00 |
| `geo-monitor` | FRESH | 982 | 2026-10-29T10:45:54.970117+00:00 |
| `politician-monitor` | FRESH | 10275 | 2026-10-29T08:11:02.315977+00:00 |
| `options-monitor` | FRESH | 43857 | 2026-10-28T22:51:20.032529+00:00 |
| `options-exit-monitor` | FRESH | 392 | 2026-10-29T10:55:44.908968+00:00 |
| `price-monitor` | FRESH | 43811 | 2026-10-28T22:52:05.848169+00:00 |
| `exit-monitor` | FRESH | 388 | 2026-10-29T10:55:48.602993+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

