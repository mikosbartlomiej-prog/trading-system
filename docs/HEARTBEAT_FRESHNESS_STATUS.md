# Heartbeat Freshness Status

- Generated at: `2026-11-20T13:27:27.981568+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 214 | 2026-11-20T13:23:53.821965+00:00 |
| `defense-monitor` | FRESH | 377 | 2026-11-20T13:21:11.157030+00:00 |
| `twitter-monitor` | FRESH | 356 | 2026-11-20T13:21:32.465962+00:00 |
| `reddit-monitor` | FRESH | 38224 | 2026-11-20T02:50:24.059786+00:00 |
| `geo-monitor` | FRESH | 668 | 2026-11-20T13:16:19.704185+00:00 |
| `politician-monitor` | FRESH | 3119 | 2026-11-20T12:35:29.364631+00:00 |
| `options-monitor` | FRESH | 680 | 2026-11-20T13:16:07.954693+00:00 |
| `options-exit-monitor` | FRESH | 381 | 2026-11-20T13:21:06.936200+00:00 |
| `price-monitor` | FRESH | 663 | 2026-11-20T13:16:25.468088+00:00 |
| `exit-monitor` | FRESH | 374 | 2026-11-20T13:21:14.114794+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

