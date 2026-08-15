# Heartbeat Freshness Status

- Generated at: `2026-08-15T04:57:17.408990+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 56 | 2026-08-15T04:56:21.266231+00:00 |
| `defense-monitor` | FRESH | 56 | 2026-08-15T04:56:21.582441+00:00 |
| `twitter-monitor` | FRESH | 51 | 2026-08-15T04:56:26.726646+00:00 |
| `reddit-monitor` | FRESH | 23833 | 2026-08-14T22:20:04.357962+00:00 |
| `geo-monitor` | FRESH | 660 | 2026-08-15T04:46:17.065585+00:00 |
| `politician-monitor` | FRESH | 1446 | 2026-08-15T04:33:11.442341+00:00 |
| `options-monitor` | FRESH | 27502 | 2026-08-14T21:18:55.603767+00:00 |
| `options-exit-monitor` | FRESH | 63 | 2026-08-15T04:56:14.741972+00:00 |
| `price-monitor` | FRESH | 28712 | 2026-08-14T20:58:45.599133+00:00 |
| `exit-monitor` | FRESH | 65 | 2026-08-15T04:56:12.159732+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

