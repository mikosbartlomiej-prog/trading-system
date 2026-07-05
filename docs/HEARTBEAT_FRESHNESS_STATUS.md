# Heartbeat Freshness Status

- Generated at: `2026-07-05T07:43:43.632854+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `2`

- Summary: FRESH=7, STALE=1, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 186 | 2026-07-05T07:40:37.720194+00:00 |
| `defense-monitor` | FRESH | 786 | 2026-07-05T07:30:37.635891+00:00 |
| `twitter-monitor` | FRESH | 176 | 2026-07-05T07:40:47.164936+00:00 |
| `reddit-monitor` | STALE | 117736 | 2026-07-03T23:01:27.851599+00:00 |
| `geo-monitor` | FRESH | 1682 | 2026-07-05T07:15:41.968448+00:00 |
| `politician-monitor` | FRESH | 901 | 2026-07-05T07:28:43.030282+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 190 | 2026-07-05T07:40:34.056542+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 189 | 2026-07-05T07:40:34.802824+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

