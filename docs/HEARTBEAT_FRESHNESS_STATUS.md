# Heartbeat Freshness Status

- Generated at: `2026-09-29T10:51:13.935012+00:00`
- US market session: **CLOSED** (pre_market)
- Stale threshold in effect: `86400s`
- Exit code: `0`

- Summary: FRESH=10, STALE=0, MISSING=1, TOTAL=11

| Component | Status | Age (s) | Last seen |
|---|---|---|---|
| `crypto-monitor` | FRESH | 287 | 2026-09-29T10:46:27.064364+00:00 |
| `defense-monitor` | FRESH | 290 | 2026-09-29T10:46:24.158164+00:00 |
| `twitter-monitor` | FRESH | 265 | 2026-09-29T10:46:49.025142+00:00 |
| `reddit-monitor` | FRESH | 33763 | 2026-09-29T01:28:31.324359+00:00 |
| `geo-monitor` | FRESH | 292 | 2026-09-29T10:46:22.072925+00:00 |
| `politician-monitor` | FRESH | 2012 | 2026-09-29T10:17:41.937200+00:00 |
| `options-monitor` | FRESH | 37919 | 2026-09-29T00:19:15.355965+00:00 |
| `options-exit-monitor` | FRESH | 592 | 2026-09-29T10:41:22.050818+00:00 |
| `price-monitor` | FRESH | 37893 | 2026-09-29T00:19:40.527555+00:00 |
| `exit-monitor` | FRESH | 597 | 2026-09-29T10:41:16.948934+00:00 |
| `incident-pattern-detector` | MISSING | n/a | — |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._

