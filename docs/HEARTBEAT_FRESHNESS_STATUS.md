# Heartbeat Freshness Status

- Generated at: `2026-10-08T11:32:56.135082+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=9, STALE=0, MISSING=2, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 81 | 2026-10-08T11:31:35.370880+00:00 |
| `defense-monitor` | FRESH | 401 | 2026-10-08T11:26:15.376633+00:00 |
| `twitter-monitor` | FRESH | 391 | 2026-10-08T11:26:25.399304+00:00 |
| `reddit-monitor` | FRESH | 35969 | 2026-10-08T01:33:27.525967+00:00 |
| `geo-monitor` | FRESH | 78 | 2026-10-08T11:31:38.452692+00:00 |
| `politician-monitor` | FRESH | 10789 | 2026-10-08T08:33:06.998995+00:00 |
| `options-monitor` | FRESH | 43057 | 2026-10-07T23:35:19.543950+00:00 |
| `options-exit-monitor` | FRESH | 81 | 2026-10-08T11:31:34.771709+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 406 | 2026-10-08T11:26:09.976200+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

