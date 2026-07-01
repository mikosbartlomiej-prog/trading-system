# Heartbeat Freshness Status

- Generated at: `2026-07-01T08:35:47.274767+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 319 | 2026-07-01T08:30:27.952570+00:00 |
| `defense-monitor` | FRESH | 316 | 2026-07-01T08:30:31.097334+00:00 |
| `twitter-monitor` | FRESH | 295 | 2026-07-01T08:30:52.003141+00:00 |
| `reddit-monitor` | FRESH | 36830 | 2026-06-30T22:21:57.140950+00:00 |
| `geo-monitor` | FRESH | 319 | 2026-07-01T08:30:28.153727+00:00 |
| `politician-monitor` | FRESH | 4793 | 2026-07-01T07:15:53.923203+00:00 |
| `options-monitor` | FRESH | 41284 | 2026-06-30T21:07:43.494071+00:00 |
| `options-exit-monitor` | FRESH | 622 | 2026-07-01T08:25:25.356626+00:00 |
| `price-monitor` | FRESH | 41163 | 2026-06-30T21:09:43.781607+00:00 |
| `exit-monitor` | FRESH | 621 | 2026-07-01T08:25:25.895804+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

