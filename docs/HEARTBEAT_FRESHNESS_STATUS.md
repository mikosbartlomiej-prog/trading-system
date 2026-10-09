# Heartbeat Freshness Status

- Generated at: `2026-10-09T11:28:13.445405+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 122 | 2026-10-09T11:26:11.889312+00:00 |
| `defense-monitor` | FRESH | 119 | 2026-10-09T11:26:14.766905+00:00 |
| `twitter-monitor` | FRESH | 110 | 2026-10-09T11:26:23.112891+00:00 |
| `reddit-monitor` | FRESH | 35008 | 2026-10-09T01:44:45.467708+00:00 |
| `geo-monitor` | FRESH | 719 | 2026-10-09T11:16:14.088862+00:00 |
| `politician-monitor` | FRESH | 11450 | 2026-10-09T08:17:23.913750+00:00 |
| `options-monitor` | FRESH | 42252 | 2026-10-08T23:44:01.910337+00:00 |
| `options-exit-monitor` | FRESH | 123 | 2026-10-09T11:26:10.073086+00:00 |
| `price-monitor` | FRESH | 42225 | 2026-10-08T23:44:28.320292+00:00 |
| `exit-monitor` | FRESH | 420 | 2026-10-09T11:21:13.396549+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

