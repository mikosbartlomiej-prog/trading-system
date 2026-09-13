# Heartbeat Freshness Status

- Generated at: `2026-09-13T09:40:39.714143+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=8, STALE=0, MISSING=3, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 596 | 2026-09-13T09:30:44.072663+00:00 |
| `defense-monitor` | FRESH | 902 | 2026-09-13T09:25:38.023391+00:00 |
| `twitter-monitor` | FRESH | 179 | 2026-09-13T09:37:40.884920+00:00 |
| `reddit-monitor` | FRESH | 35788 | 2026-09-12T23:44:11.622121+00:00 |
| `geo-monitor` | FRESH | 1505 | 2026-09-13T09:15:35.164310+00:00 |
| `politician-monitor` | FRESH | 9543 | 2026-09-13T07:01:36.579256+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 909 | 2026-09-13T09:25:30.229066+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 304 | 2026-09-13T09:35:35.214833+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

