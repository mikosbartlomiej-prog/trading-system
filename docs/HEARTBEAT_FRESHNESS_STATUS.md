# Heartbeat Freshness Status

- Generated at: `2026-11-18T13:19:52.719142+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=9, STALE=0, MISSING=2, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 205 | 2026-11-18T13:16:27.650500+00:00 |
| `defense-monitor` | FRESH | 216 | 2026-11-18T13:16:17.144426+00:00 |
| `twitter-monitor` | FRESH | 514 | 2026-11-18T13:11:18.975536+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 200 | 2026-11-18T13:16:32.916759+00:00 |
| `politician-monitor` | FRESH | 2060 | 2026-11-18T12:45:32.525361+00:00 |
| `options-monitor` | FRESH | 229 | 2026-11-18T13:16:03.468495+00:00 |
| `options-exit-monitor` | FRESH | 212 | 2026-11-18T13:16:21.116641+00:00 |
| `price-monitor` | FRESH | 1125 | 2026-11-18T13:01:07.912672+00:00 |
| `exit-monitor` | FRESH | 229 | 2026-11-18T13:16:03.436685+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

