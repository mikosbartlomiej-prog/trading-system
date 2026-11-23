# Heartbeat Freshness Status

- Generated at: `2026-11-23T15:11:12.714867+00:00`
- US market session: **OPEN** (open)
- Stale threshold in effect: `7200s`
- Exit code: `3`

- Summary: FRESH=8, STALE=2, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 307 | 2026-11-23T15:06:06.194540+00:00 |
| `defense-monitor` | FRESH | 906 | 2026-11-23T14:56:06.740734+00:00 |
| `twitter-monitor` | FRESH | 294 | 2026-11-23T15:06:18.532304+00:00 |
| `reddit-monitor` | STALE | 46625 | 2026-11-23T02:14:08.089683+00:00 |
| `geo-monitor` | FRESH | 609 | 2026-11-23T15:01:03.690429+00:00 |
| `politician-monitor` | STALE | 8688 | 2026-11-23T12:46:24.871455+00:00 |
| `options-monitor` | FRESH | 330 | 2026-11-23T15:05:42.982699+00:00 |
| `options-exit-monitor` | FRESH | 332 | 2026-11-23T15:05:41.149589+00:00 |
| `price-monitor` | FRESH | 321 | 2026-11-23T15:05:51.874817+00:00 |
| `exit-monitor` | FRESH | 314 | 2026-11-23T15:05:58.523574+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

