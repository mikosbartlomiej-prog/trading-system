# Heartbeat Freshness Status

- Generated at: `2026-09-19T08:54:21.402291+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 231 | 2026-09-19T08:50:30.197304+00:00 |
| `defense-monitor` | FRESH | 232 | 2026-09-19T08:50:29.828760+00:00 |
| `twitter-monitor` | FRESH | 213 | 2026-09-19T08:50:48.726499+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 2331 | 2026-09-19T08:15:30.767672+00:00 |
| `politician-monitor` | FRESH | 865 | 2026-09-19T08:39:56.484390+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 233 | 2026-09-19T08:50:28.033978+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 519 | 2026-09-19T08:45:41.954857+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

