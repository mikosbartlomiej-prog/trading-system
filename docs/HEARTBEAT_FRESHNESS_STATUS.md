# Heartbeat Freshness Status

- Generated at: `2026-08-08T05:20:47.679681+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 287 | 2026-08-08T05:16:00.629799+00:00 |
| `defense-monitor` | FRESH | 586 | 2026-08-08T05:11:02.158096+00:00 |
| `twitter-monitor` | FRESH | 268 | 2026-08-08T05:16:19.829945+00:00 |
| `reddit-monitor` | FRESH | 24496 | 2026-08-07T22:32:31.466098+00:00 |
| `geo-monitor` | FRESH | 284 | 2026-08-08T05:16:03.495144+00:00 |
| `politician-monitor` | FRESH | 1315 | 2026-08-08T04:58:52.199559+00:00 |
| `options-monitor` | FRESH | 28747 | 2026-08-07T21:21:40.310746+00:00 |
| `options-exit-monitor` | FRESH | 591 | 2026-08-08T05:10:57.138579+00:00 |
| `price-monitor` | FRESH | 28618 | 2026-08-07T21:23:49.481279+00:00 |
| `exit-monitor` | FRESH | 190 | 2026-08-08T05:17:37.320936+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

