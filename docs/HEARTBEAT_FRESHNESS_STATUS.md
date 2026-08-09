# Heartbeat Freshness Status

- Generated at: `2026-08-09T05:29:17.605530+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 209 | 2026-08-09T05:25:48.894829+00:00 |
| `defense-monitor` | FRESH | 510 | 2026-08-09T05:20:47.893174+00:00 |
| `twitter-monitor` | FRESH | 175 | 2026-08-09T05:26:22.629875+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 3926 | 2026-08-09T04:23:51.254609+00:00 |
| `politician-monitor` | FRESH | 1339 | 2026-08-09T05:06:58.857050+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 212 | 2026-08-09T05:25:45.712709+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 210 | 2026-08-09T05:25:47.563396+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

