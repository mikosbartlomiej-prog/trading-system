# Heartbeat Freshness Status

- Generated at: `2026-06-26T08:07:30.996482+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 125 | 2026-06-26T08:05:25.778598+00:00 |
| `defense-monitor` | FRESH | 28 | 2026-06-26T08:07:02.667889+00:00 |
| `twitter-monitor` | FRESH | 109 | 2026-06-26T08:05:42.213993+00:00 |
| `reddit-monitor` | FRESH | 49770 | 2026-06-25T18:18:00.865866+00:00 |
| `geo-monitor` | FRESH | 418 | 2026-06-26T08:00:32.694975+00:00 |
| `politician-monitor` | FRESH | 665 | 2026-06-26T07:56:26.349929+00:00 |
| `options-monitor` | FRESH | 39232 | 2026-06-25T21:13:38.765646+00:00 |
| `options-exit-monitor` | FRESH | 124 | 2026-06-26T08:05:27.315193+00:00 |
| `price-monitor` | FRESH | 39209 | 2026-06-25T21:14:02.004748+00:00 |
| `exit-monitor` | FRESH | 123 | 2026-06-26T08:05:28.201391+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

