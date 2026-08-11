# Heartbeat Freshness Status

- Generated at: `2026-08-11T05:35:34.812684+00:00`
- US market session: **CLOSED** (closed)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 288 | 2026-08-11T05:30:46.781054+00:00 |
| `defense-monitor` | FRESH | 576 | 2026-08-11T05:25:58.805599+00:00 |
| `twitter-monitor` | FRESH | 263 | 2026-08-11T05:31:11.654387+00:00 |
| `reddit-monitor` | FRESH | 25240 | 2026-08-10T22:34:54.479003+00:00 |
| `geo-monitor` | FRESH | 354 | 2026-08-11T05:29:40.576306+00:00 |
| `politician-monitor` | FRESH | 6536 | 2026-08-11T03:46:38.883902+00:00 |
| `options-monitor` | FRESH | 31125 | 2026-08-10T20:56:49.352779+00:00 |
| `options-exit-monitor` | FRESH | 289 | 2026-08-11T05:30:46.008392+00:00 |
| `price-monitor` | FRESH | 31080 | 2026-08-10T20:57:34.693327+00:00 |
| `exit-monitor` | FRESH | 288 | 2026-08-11T05:30:46.506373+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

