# Heartbeat Freshness Status

- Generated at: `2026-09-08T08:59:40.040609+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 197 | 2026-09-08T08:56:22.870211+00:00 |
| `defense-monitor` | FRESH | 208 | 2026-09-08T08:56:12.031302+00:00 |
| `twitter-monitor` | FRESH | 196 | 2026-09-08T08:56:23.774206+00:00 |
| `reddit-monitor` | FRESH | 32415 | 2026-09-07T23:59:25.172760+00:00 |
| `geo-monitor` | FRESH | 1705 | 2026-09-08T08:31:15.170290+00:00 |
| `politician-monitor` | FRESH | 1068 | 2026-09-08T08:41:51.743356+00:00 |
| `options-monitor` | FRESH | 41486 | 2026-09-07T21:28:14.117744+00:00 |
| `options-exit-monitor` | FRESH | 211 | 2026-09-08T08:56:08.830935+00:00 |
| `price-monitor` | FRESH | 41449 | 2026-09-07T21:28:50.625879+00:00 |
| `exit-monitor` | FRESH | 211 | 2026-09-08T08:56:09.488886+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

