# Heartbeat Freshness Status

- Generated at: `2026-11-14T11:41:43.036545+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 331 | 2026-11-14T11:36:12.192527+00:00 |
| `defense-monitor` | FRESH | 321 | 2026-11-14T11:36:21.663876+00:00 |
| `twitter-monitor` | FRESH | 317 | 2026-11-14T11:36:26.112576+00:00 |
| `reddit-monitor` | FRESH | 34990 | 2026-11-14T01:58:32.820940+00:00 |
| `geo-monitor` | FRESH | 1536 | 2026-11-14T11:16:06.898907+00:00 |
| `politician-monitor` | FRESH | 10641 | 2026-11-14T08:44:22.124119+00:00 |
| `options-monitor` | FRESH | 38764 | 2026-11-14T00:55:38.538554+00:00 |
| `options-exit-monitor` | FRESH | 336 | 2026-11-14T11:36:07.121289+00:00 |
| `price-monitor` | FRESH | 55247 | 2026-11-13T20:20:55.779972+00:00 |
| `exit-monitor` | FRESH | 340 | 2026-11-14T11:36:03.471793+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

