# Strategy Coverage Status (v3.23.0)

**Generated:** `2026-06-15T10:07:56.537892+00:00`
**As of:** `2026-06-15T10:07:56.414850+00:00`
**Git HEAD:** `4b15542f95fad53584a283fdc8f8b168426a94cd`
**Strategies total:** `14` (registry: `7`, state.json: `12`)

## Status distribution

| Status | Count |
|---|---|
| `ACTIVE` | 2 |
| `DEAD` | 1 |
| `OBSERVE_ONLY` | 2 |
| `ZOMBIE` | 9 |

## Per-strategy detail

| Strategy | Monitor | Status | Registry | In state | Observe-only | Paid data | Signals 7d | No-signal 7d | Rejections 7d | Shadow-eligible 7d |
|---|---|---|---|---|---|---|---|---|---|---|
| `alloc-exit` | `allocator` | `ZOMBIE` | `False` | `True` | `False` | `False` | `0` | `0` | `0` | `0` |
| `alloc-reduce` | `allocator` | `ZOMBIE` | `False` | `True` | `False` | `False` | `0` | `0` | `0` | `0` |
| `allocator-rebalance` | `allocator` | `ZOMBIE` | `False` | `True` | `False` | `False` | `0` | `0` | `0` | `0` |
| `crypto-breakdown` | `crypto-monitor` | `ZOMBIE` | `False` | `True` | `False` | `False` | `0` | `0` | `86` | `0` |
| `crypto-momentum` | `crypto-monitor` | `ACTIVE` | `True` | `True` | `False` | `False` | `62` | `5424` | `10395` | `0` |
| `crypto-oversold-bounce` | `crypto-monitor` | `ACTIVE` | `True` | `True` | `False` | `False` | `35` | `0` | `35` | `0` |
| `geo-defense` | `geo-monitor` | `OBSERVE_ONLY` | `True` | `True` | `True` | `False` | `0` | `0` | `0` | `0` |
| `geo-energy` | `geo-monitor` | `ZOMBIE` | `False` | `True` | `False` | `False` | `0` | `0` | `0` | `0` |
| `geo-gold` | `geo-monitor` | `ZOMBIE` | `False` | `True` | `False` | `False` | `0` | `0` | `0` | `0` |
| `geo-xom` | `geo-monitor` | `ZOMBIE` | `False` | `True` | `False` | `False` | `0` | `0` | `0` | `0` |
| `momentum-long` | `price-monitor` | `ZOMBIE` | `True` | `False` | `False` | `False` | `0` | `0` | `0` | `0` |
| `momentum-long-loose` | `price-monitor` | `ZOMBIE` | `True` | `False` | `False` | `False` | `0` | `0` | `0` | `0` |
| `options-momentum` | `options-monitor` | `OBSERVE_ONLY` | `True` | `True` | `True` | `True` | `0` | `0` | `0` | `0` |
| `overbought-short` | `price-monitor` | `DEAD` | `True` | `True` | `False` | `False` | `0` | `0` | `0` | `0` |

## Status enum

- `ACTIVE` — at least one DETECTED/APPROVE signal in 7d
- `DORMANT` — only NO_SIGNAL / REJECT in 7d, no DETECTED
- `OBSERVE_ONLY` — registry marks observe_only=True (geo-defense, options-momentum)
- `DEAD` — disabled + zero ledger activity in 7d
- `ZOMBIE` — present in only one of (registry / state.json); inconsistent

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
