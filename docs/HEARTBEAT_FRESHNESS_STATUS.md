# Heartbeat Freshness Status

- Generated at: `2026-11-26T14:13:46.409503+00:00`
- US market session: **CLOSED** (holiday)
- Stale threshold in effect: `86400s`
- Exit code: `2`

- Summary: FRESH=9, STALE=1, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 465 | 2026-11-26T14:06:01.718981+00:00 |
| `defense-monitor` | FRESH | 156 | 2026-11-26T14:11:10.000091+00:00 |
| `twitter-monitor` | FRESH | 146 | 2026-11-26T14:11:20.165537+00:00 |
| `reddit-monitor` | STALE | 141359 | 2026-11-24T22:57:47.743867+00:00 |
| `geo-monitor` | FRESH | 2564 | 2026-11-26T13:31:02.238948+00:00 |
| `politician-monitor` | FRESH | 1609 | 2026-11-26T13:46:57.700346+00:00 |
| `options-monitor` | FRESH | 160 | 2026-11-26T14:11:06.479984+00:00 |
| `options-exit-monitor` | FRESH | 168 | 2026-11-26T14:10:58.784846+00:00 |
| `price-monitor` | FRESH | 163 | 2026-11-26T14:11:03.129357+00:00 |
| `exit-monitor` | FRESH | 453 | 2026-11-26T14:06:12.927943+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

