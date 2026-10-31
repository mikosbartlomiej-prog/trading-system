# Heartbeat Freshness Status

- Generated at: `2026-10-31T10:32:11.744350+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 360 | 2026-10-31T10:26:11.710216+00:00 |
| `defense-monitor` | FRESH | 359 | 2026-10-31T10:26:12.486961+00:00 |
| `twitter-monitor` | FRESH | 332 | 2026-10-31T10:26:39.898233+00:00 |
| `reddit-monitor` | FRESH | 32799 | 2026-10-31T01:25:32.788969+00:00 |
| `geo-monitor` | FRESH | 955 | 2026-10-31T10:16:16.544521+00:00 |
| `politician-monitor` | FRESH | 9898 | 2026-10-31T07:47:13.845428+00:00 |
| `options-monitor` | FRESH | 43152 | 2026-10-30T22:32:59.970942+00:00 |
| `options-exit-monitor` | FRESH | 348 | 2026-10-31T10:26:23.319433+00:00 |
| `price-monitor` | FRESH | 43042 | 2026-10-30T22:34:50.236490+00:00 |
| `exit-monitor` | FRESH | 362 | 2026-10-31T10:26:09.817400+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

