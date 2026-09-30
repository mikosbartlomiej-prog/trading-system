# Heartbeat Freshness Status

- Generated at: `2026-09-30T10:39:52.193535+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=6, STALE=0, MISSING=5, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 209 | 2026-09-30T10:36:22.860067+00:00 |
| `defense-monitor` | FRESH | 1411 | 2026-09-30T10:16:21.688156+00:00 |
| `twitter-monitor` | FRESH | 197 | 2026-09-30T10:36:35.272720+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | MISSING | n/a | — |
| `politician-monitor` | FRESH | 448 | 2026-09-30T10:32:24.359643+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 204 | 2026-09-30T10:36:28.604660+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 207 | 2026-09-30T10:36:24.987408+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

