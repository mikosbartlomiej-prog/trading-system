# Heartbeat Freshness Status

- Generated at: `2026-07-03T07:45:49.796353+00:00`
- US market session: **CLOSED** (holiday)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 296 | 2026-07-03T07:40:53.538860+00:00 |
| `defense-monitor` | FRESH | 293 | 2026-07-03T07:40:56.802025+00:00 |
| `twitter-monitor` | FRESH | 270 | 2026-07-03T07:41:19.626578+00:00 |
| `reddit-monitor` | FRESH | 31302 | 2026-07-02T23:04:08.074455+00:00 |
| `geo-monitor` | FRESH | 1793 | 2026-07-03T07:15:56.569824+00:00 |
| `politician-monitor` | FRESH | 1399 | 2026-07-03T07:22:30.963031+00:00 |
| `options-monitor` | FRESH | 36890 | 2026-07-02T21:30:59.907521+00:00 |
| `options-exit-monitor` | FRESH | 297 | 2026-07-03T07:40:52.717829+00:00 |
| `price-monitor` | FRESH | 36840 | 2026-07-02T21:31:49.980535+00:00 |
| `exit-monitor` | FRESH | 293 | 2026-07-03T07:40:56.455501+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

