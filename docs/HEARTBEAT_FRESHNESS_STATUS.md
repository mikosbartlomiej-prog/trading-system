# Heartbeat Freshness Status

- Generated at: `2026-08-01T07:02:34.798614+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 121 | 2026-08-01T07:00:34.132003+00:00 |
| `defense-monitor` | FRESH | 119 | 2026-08-01T07:00:36.187585+00:00 |
| `twitter-monitor` | FRESH | 108 | 2026-08-01T07:00:46.578874+00:00 |
| `reddit-monitor` | FRESH | 29075 | 2026-07-31T22:58:00.201417+00:00 |
| `geo-monitor` | FRESH | 993 | 2026-08-01T06:46:01.926397+00:00 |
| `politician-monitor` | FRESH | 1904 | 2026-08-01T06:30:51.075993+00:00 |
| `options-monitor` | FRESH | 35141 | 2026-07-31T21:16:53.993982+00:00 |
| `options-exit-monitor` | FRESH | 126 | 2026-08-01T07:00:29.141291+00:00 |
| `price-monitor` | FRESH | 34975 | 2026-07-31T21:19:39.343023+00:00 |
| `exit-monitor` | FRESH | 426 | 2026-08-01T06:55:29.237858+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

