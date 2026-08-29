# Heartbeat Freshness Status

- Generated at: `2026-08-29T11:18:14.438035+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 141 | 2026-08-29T11:15:53.595021+00:00 |
| `defense-monitor` | FRESH | 744 | 2026-08-29T11:05:50.868080+00:00 |
| `twitter-monitor` | FRESH | 131 | 2026-08-29T11:16:03.565104+00:00 |
| `reddit-monitor` | FRESH | 28109 | 2026-08-29T03:29:45.402258+00:00 |
| `geo-monitor` | FRESH | 140 | 2026-08-29T11:15:54.399651+00:00 |
| `politician-monitor` | FRESH | 1413 | 2026-08-29T10:54:41.877606+00:00 |
| `options-monitor` | FRESH | 44722 | 2026-08-28T22:52:52.560878+00:00 |
| `options-exit-monitor` | FRESH | 447 | 2026-08-29T11:10:47.934555+00:00 |
| `price-monitor` | FRESH | 44644 | 2026-08-28T22:54:10.351311+00:00 |
| `exit-monitor` | FRESH | 144 | 2026-08-29T11:15:50.806098+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

