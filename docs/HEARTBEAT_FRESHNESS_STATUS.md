# Heartbeat Freshness Status

- Generated at: `2026-09-12T08:45:33.961508+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 299 | 2026-09-12T08:40:34.670459+00:00 |
| `defense-monitor` | FRESH | 597 | 2026-09-12T08:35:36.829226+00:00 |
| `twitter-monitor` | FRESH | 280 | 2026-09-12T08:40:53.710826+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 1797 | 2026-09-12T08:15:36.761582+00:00 |
| `politician-monitor` | FRESH | 1025 | 2026-09-12T08:28:28.808390+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 302 | 2026-09-12T08:40:32.385206+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 304 | 2026-09-12T08:40:29.988296+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

