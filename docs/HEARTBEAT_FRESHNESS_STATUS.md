# Heartbeat Freshness Status

- Generated at: `2026-07-02T07:50:39.177983+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 280 | 2026-07-02T07:45:59.677289+00:00 |
| `defense-monitor` | FRESH | 141 | 2026-07-02T07:48:18.335270+00:00 |
| `twitter-monitor` | FRESH | 248 | 2026-07-02T07:46:31.559708+00:00 |
| `reddit-monitor` | FRESH | 31021 | 2026-07-01T23:13:38.393872+00:00 |
| `geo-monitor` | FRESH | 282 | 2026-07-02T07:45:57.431163+00:00 |
| `politician-monitor` | FRESH | 957 | 2026-07-02T07:34:42.310230+00:00 |
| `options-monitor` | FRESH | 39067 | 2026-07-01T20:59:31.940456+00:00 |
| `options-exit-monitor` | FRESH | 286 | 2026-07-02T07:45:53.266748+00:00 |
| `price-monitor` | FRESH | 39050 | 2026-07-01T20:59:49.256001+00:00 |
| `exit-monitor` | FRESH | 287 | 2026-07-02T07:45:52.191285+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

