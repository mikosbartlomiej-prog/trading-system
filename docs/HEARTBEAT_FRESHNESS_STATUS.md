# Heartbeat Freshness Status

- Generated at: `2026-06-25T08:00:13.697944+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 282 | 2026-06-25T07:55:31.286179+00:00 |
| `defense-monitor` | FRESH | 284 | 2026-06-25T07:55:29.309570+00:00 |
| `twitter-monitor` | FRESH | 258 | 2026-06-25T07:55:55.219745+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 1778 | 2026-06-25T07:30:35.441937+00:00 |
| `politician-monitor` | FRESH | 802 | 2026-06-25T07:46:51.563965+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 288 | 2026-06-25T07:55:25.497033+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 279 | 2026-06-25T07:55:34.593170+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

