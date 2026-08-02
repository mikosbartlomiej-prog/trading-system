# Heartbeat Freshness Status

- Generated at: `2026-08-02T07:07:33.784134+00:00`
- US market session: **CLOSED** (weekend)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=7, STALE=0, MISSING=4, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 117 | 2026-08-02T07:05:36.530781+00:00 |
| `defense-monitor` | FRESH | 121 | 2026-08-02T07:05:33.077780+00:00 |
| `twitter-monitor` | FRESH | 417 | 2026-08-02T07:00:36.794903+00:00 |
| `reddit-monitor` | MISSING | n/a | — |
| `geo-monitor` | FRESH | 427 | 2026-08-02T07:00:26.886833+00:00 |
| `politician-monitor` | FRESH | 1966 | 2026-08-02T06:34:48.225711+00:00 |
| `options-monitor` | MISSING | n/a | — |
| `options-exit-monitor` | FRESH | 121 | 2026-08-02T07:05:32.674955+00:00 |
| `price-monitor` | MISSING | n/a | — |
| `exit-monitor` | FRESH | 429 | 2026-08-02T07:00:24.844571+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

