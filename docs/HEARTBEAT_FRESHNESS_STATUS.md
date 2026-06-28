# Heartbeat Freshness Status

- Generated at: `2026-06-28T08:02:51.840069+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 139 | 2026-06-28T08:00:32.428539+00:00 |
| `defense-monitor` | FRESH | 441 | 2026-06-28T07:55:30.697948+00:00 |
| `twitter-monitor` | FRESH | 135 | 2026-06-28T08:00:36.645719+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 141 | 2026-06-28T08:00:31.004905+00:00 |
| `politician-monitor` | FRESH | 2818 | 2026-06-28T07:15:53.419153+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 148 | 2026-06-28T08:00:24.110641+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 448 | 2026-06-28T07:55:23.868254+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

