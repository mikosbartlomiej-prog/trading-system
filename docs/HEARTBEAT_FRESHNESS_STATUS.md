# Heartbeat Freshness Status

- Generated at: `2026-11-05T12:39:51.624642+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 211 | 2026-11-05T12:36:21.039217+00:00 |
| `defense-monitor` | FRESH | 523 | 2026-11-05T12:31:08.889171+00:00 |
| `twitter-monitor` | FRESH | 209 | 2026-11-05T12:36:23.058130+00:00 |
| `reddit-monitor` | FRESH | 38418 | 2026-11-05T01:59:33.183331+00:00 |
| `geo-monitor` | FRESH | 525 | 2026-11-05T12:31:06.994301+00:00 |
| `politician-monitor` | FRESH | 2253 | 2026-11-05T12:02:18.781597+00:00 |
| `options-monitor` | FRESH | 42225 | 2026-11-05T00:56:06.525242+00:00 |
| `options-exit-monitor` | FRESH | 217 | 2026-11-05T12:36:14.475475+00:00 |
| `price-monitor` | FRESH | 58899 | 2026-11-04T20:18:12.163353+00:00 |
| `exit-monitor` | FRESH | 223 | 2026-11-05T12:36:08.683595+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

