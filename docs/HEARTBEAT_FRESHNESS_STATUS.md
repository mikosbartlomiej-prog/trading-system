# Heartbeat Freshness Status

- Generated at: `2026-10-30T10:59:48.161749+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 221 | 2026-10-30T10:56:06.829032+00:00 |
| `defense-monitor` | FRESH | 226 | 2026-10-30T10:56:01.760416+00:00 |
| `twitter-monitor` | FRESH | 213 | 2026-10-30T10:56:14.895967+00:00 |
| `reddit-monitor` | FRESH | 57973 | 2026-10-29T18:53:34.926709+00:00 |
| `geo-monitor` | FRESH | 832 | 2026-10-30T10:45:56.077382+00:00 |
| `politician-monitor` | FRESH | 10652 | 2026-10-30T08:02:16.598936+00:00 |
| `options-monitor` | FRESH | 43119 | 2026-10-29T23:01:08.814773+00:00 |
| `options-exit-monitor` | FRESH | 234 | 2026-10-30T10:55:53.803390+00:00 |
| `price-monitor` | FRESH | 43113 | 2026-10-29T23:01:14.942311+00:00 |
| `exit-monitor` | FRESH | 233 | 2026-10-30T10:55:55.146401+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

