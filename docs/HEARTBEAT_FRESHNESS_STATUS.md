# Heartbeat Freshness Status

- Generated at: `2026-11-02T12:47:00.562625+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 342 | 2026-11-02T12:41:18.763898+00:00 |
| `defense-monitor` | FRESH | 331 | 2026-11-02T12:41:29.993202+00:00 |
| `twitter-monitor` | FRESH | 309 | 2026-11-02T12:41:51.729388+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 3632 | 2026-11-02T11:46:28.803136+00:00 |
| `politician-monitor` | FRESH | 1767 | 2026-11-02T12:17:33.678579+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 335 | 2026-11-02T12:41:25.872744+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 344 | 2026-11-02T12:41:16.710282+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

