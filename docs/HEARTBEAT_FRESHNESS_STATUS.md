# Heartbeat Freshness Status

- Generated at: `2026-10-03T10:00:01.628753+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 229 | 2026-10-03T09:56:12.246945+00:00 |
| `defense-monitor` | FRESH | 227 | 2026-10-03T09:56:14.812096+00:00 |
| `twitter-monitor` | FRESH | 209 | 2026-10-03T09:56:32.541875+00:00 |
| `reddit-monitor` | FRESH | 32663 | 2026-10-03T00:55:38.543011+00:00 |
| `geo-monitor` | FRESH | 8922 | 2026-10-03T07:31:20.120238+00:00 |
| `politician-monitor` | FRESH | 8887 | 2026-10-03T07:31:54.772987+00:00 |
| `options-monitor` | FRESH | 42271 | 2026-10-02T22:15:30.998068+00:00 |
| `options-exit-monitor` | FRESH | 229 | 2026-10-03T09:56:13.004288+00:00 |
| `price-monitor` | FRESH | 42119 | 2026-10-02T22:18:02.449643+00:00 |
| `exit-monitor` | FRESH | 231 | 2026-10-03T09:56:10.213468+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

