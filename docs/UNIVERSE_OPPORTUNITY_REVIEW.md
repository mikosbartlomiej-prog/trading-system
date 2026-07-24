# Universe opportunity review (v3.26.0)

**Generated:** `2026-07-24T07:08:02.179357+00:00`
**As of:** `2026-07-24T07:08:01.986858+00:00`
**Window:** last 7 days
**Universe size:** 13

## Recommendation distribution

| Recommendation | Count |
|---|---|
| `KEEP` | 5 |
| `OBSERVE_ONLY_ADD` | 0 |
| `REMOVE_LOW_QUALITY` | 8 |
| `NEEDS_DATA` | 0 |
| `REJECT_HIGH_SPREAD` | 0 |

## Per-symbol detail

| Symbol | Asset | Rec | Rows | Cands | Near | Fail | Vol | Liq | Reason |
|---|---|---|---|---|---|---|---|---|---|
| `SPY` | us_equity | **REMOVE_LOW_QUALITY** | 0 | 0 | 0 | 0 | n/a | n/a | 0 ledger rows, 0 near-misses, 0 data failures; candidate for removal review |
| `QQQ` | us_equity | **REMOVE_LOW_QUALITY** | 0 | 0 | 0 | 0 | n/a | n/a | 0 ledger rows, 0 near-misses, 0 data failures; candidate for removal review |
| `GLD` | us_equity | **REMOVE_LOW_QUALITY** | 0 | 0 | 0 | 0 | n/a | n/a | 0 ledger rows, 0 near-misses, 0 data failures; candidate for removal review |
| `AMD` | us_equity | **REMOVE_LOW_QUALITY** | 0 | 0 | 0 | 0 | n/a | n/a | 0 ledger rows, 0 near-misses, 0 data failures; candidate for removal review |
| `CRWD` | us_equity | **REMOVE_LOW_QUALITY** | 0 | 0 | 0 | 0 | n/a | n/a | 0 ledger rows, 0 near-misses, 0 data failures; candidate for removal review |
| `NOW` | us_equity | **REMOVE_LOW_QUALITY** | 0 | 0 | 0 | 0 | n/a | n/a | 0 ledger rows, 0 near-misses, 0 data failures; candidate for removal review |
| `PANW` | us_equity | **REMOVE_LOW_QUALITY** | 0 | 0 | 0 | 0 | n/a | n/a | 0 ledger rows, 0 near-misses, 0 data failures; candidate for removal review |
| `ORCL` | us_equity | **REMOVE_LOW_QUALITY** | 0 | 0 | 0 | 0 | n/a | n/a | 0 ledger rows, 0 near-misses, 0 data failures; candidate for removal review |
| `BTC/USD` | crypto | **KEEP** | 1440 | 1440 | 1967 | 0 | n/a | n/a | rows=1440, near_misses=1967, candidates=1440 |
| `ETH/USD` | crypto | **KEEP** | 1430 | 1430 | 2223 | 0 | n/a | n/a | rows=1430, near_misses=2223, candidates=1430 |
| `SOL/USD` | crypto | **KEEP** | 1430 | 1430 | 1837 | 0 | n/a | n/a | rows=1430, near_misses=1837, candidates=1430 |
| `LTC/USD` | crypto | **KEEP** | 1428 | 1428 | 2148 | 0 | n/a | n/a | rows=1428, near_misses=2148, candidates=1428 |
| `AVAX/USD` | crypto | **KEEP** | 1428 | 1428 | 2303 | 0 | n/a | n/a | rows=1428, near_misses=2303, candidates=1428 |

## Safety contract

- NEVER adds new trade-eligible symbols automatically.
- NEVER auto-removes a symbol.
- `OBSERVE_ONLY_ADD` is an advisory marker only — it does NOT modify the live universe.
- NEVER makes network calls. NEVER imports `alpaca_orders`.

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `REVIEW_NEVER_AUTO_ADDS_TRADE_ELIGIBLE_SYMBOLS`
- `REVIEW_NEVER_AUTO_REMOVES_SYMBOLS`
