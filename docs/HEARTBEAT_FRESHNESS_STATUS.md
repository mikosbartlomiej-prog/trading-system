# Heartbeat Freshness Status

- Generated at: `2026-06-17T09:18:37.973827+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 186 | 2026-06-17T09:15:31.750629+00:00 |
| `defense-monitor` | FRESH | 182 | 2026-06-17T09:15:36.347894+00:00 |
| `twitter-monitor` | FRESH | 162 | 2026-06-17T09:15:56.425569+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 1993 | 2026-06-17T08:45:25.186359+00:00 |
| `politician-monitor` | FRESH | 6450 | 2026-06-17T07:31:08.430405+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 195 | 2026-06-17T09:15:23.286687+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 194 | 2026-06-17T09:15:24.371212+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

