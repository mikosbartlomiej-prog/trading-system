# Monitor Emission Status

- Generated: `2026-06-15T10:10:55.528856+00:00`
- HEAD: `4bd7ed2403e09608047d5f442da72e500a5885f6`
- Window: last `7` days
- Version: `v3.23.0`

- Summary: ACTIVE=1, WIRED_BUT_NOT_FIRING=7, DORMANT=0, NOT_APPLICABLE=2, TOTAL=10
- Ledger rows scanned: 16592; unattributed (no strategy->monitor map): 0

## Per-monitor table

| Monitor | Wired | Ledger rows (window) | Last ledger ts | Verdict |
|---|---|---|---|---|
| `price-monitor` | Y | 0 | — | **WIRED_BUT_NOT_FIRING** |
| `options-monitor` | Y | 0 | — | **WIRED_BUT_NOT_FIRING** |
| `crypto-monitor` | Y | 16592 | 2026-06-15T09:51:09.088985+00:00 | **ACTIVE** |
| `defense-monitor` | Y | 0 | — | **WIRED_BUT_NOT_FIRING** |
| `twitter-monitor` | Y | 0 | — | **WIRED_BUT_NOT_FIRING** |
| `reddit-monitor` | Y | 0 | — | **WIRED_BUT_NOT_FIRING** |
| `geo-monitor` | Y | 0 | — | **WIRED_BUT_NOT_FIRING** |
| `politician-monitor` | Y | 0 | — | **WIRED_BUT_NOT_FIRING** |
| `exit-monitor` | Y | 0 | — | **NOT_APPLICABLE** |
| `options-exit-monitor` | Y | 0 | — | **NOT_APPLICABLE** |

## Strategy -> monitor attribution map

| Strategy | Monitor |
|---|---|
| `crypto-breakdown` | `crypto-monitor` |
| `crypto-momentum` | `crypto-monitor` |
| `crypto-oversold-bounce` | `crypto-monitor` |
| `defense-news` | `defense-monitor` |
| `exit-monitor` | `exit-monitor` |
| `geo-news` | `geo-monitor` |
| `leveraged-etf` | `price-monitor` |
| `momentum-long` | `price-monitor` |
| `options-exit` | `options-exit-monitor` |
| `options-momentum` | `options-monitor` |
| `politician-djt` | `politician-monitor` |
| `politician-tracker` | `politician-monitor` |
| `reddit-sentiment` | `reddit-monitor` |

## Standing markers

- EDGE_GATE_ENABLED = false
- ALLOW_BROKER_PAPER = false
- LIVE_TRADING_UNSUPPORTED
- NO_ORDER_PLACEMENT

_This report is observability-only. It never places orders, never imports `alpaca_orders`, never mutates runtime state._
