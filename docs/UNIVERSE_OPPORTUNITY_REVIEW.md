# Universe opportunity review (v3.26.0)

**Generated:** `2026-07-03T07:46:29.500078+00:00`
**As of:** `2026-07-03T07:46:29.259958+00:00`
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
| `BTC/USD` | crypto | **KEEP** | 1872 | 1872 | 3019 | 0 | n/a | n/a | rows=1872, near_misses=3019, candidates=1872 |
| `ETH/USD` | crypto | **KEEP** | 1884 | 1884 | 2928 | 0 | n/a | n/a | rows=1884, near_misses=2928, candidates=1884 |
| `SOL/USD` | crypto | **KEEP** | 1859 | 1859 | 2006 | 0 | n/a | n/a | rows=1859, near_misses=2006, candidates=1859 |
| `LTC/USD` | crypto | **KEEP** | 1882 | 1882 | 2352 | 0 | n/a | n/a | rows=1882, near_misses=2352, candidates=1882 |
| `AVAX/USD` | crypto | **KEEP** | 1859 | 1859 | 2586 | 0 | n/a | n/a | rows=1859, near_misses=2586, candidates=1859 |

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
