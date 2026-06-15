# Shadow candidate queue (v3.27.0)

**Generated:** `2026-06-15T15:14:11.647395+00:00`
**git_head:** `1b2a7b9825753d2e05fc7f218fafdc168709dce2`
**Total rows:** 36
**Active risk blockers:** none

Every row stays at `WAITING_FOR_REAL_MARKET_TRIGGER` until a real-time event satisfies the trigger. This queue NEVER auto-promotes, NEVER places orders, NEVER creates a shadow fill, NEVER inflates shadow-eligibility counters.

## Rows by source

| Source | Count |
|---|---|
| `REAL` | 3 |
| `REPLAY` | 20 |
| `VARIANT` | 13 |

## Rows by strategy

| Strategy | Count |
|---|---|
| `crypto-momentum` | 10 |
| `crypto-oversold-bounce` | 5 |
| `momentum-long` | 10 |
| `momentum-long-loose` | 5 |
| `overbought-short` | 6 |

## Candidate rows

| Strategy | Variant | Symbol | Asset | Source | Reason | Trigger | Confidence | Risk Pre | Mode | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| `crypto-momentum` | `—` | `ALL_OBSERVED_SYMBOLS` | `us_equity` | `REAL` | near-miss aggregate sample=3789 p95_abs_distance=8.6 ratio=0.1433 | predator-bracket 24h move in [3%, 15%] AND RSI band met AND volume > avg multipl | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-oversold-bounce` | `—` | `ALL_OBSERVED_SYMBOLS` | `us_equity` | `REAL` | near-miss aggregate sample=141 p95_abs_distance=3.333333 ratio=0.1111 | RSI(14) <= 30 on H1 close AND 3-bar stabilization AND volume >= 25% of avg | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `overbought-short` | `—` | `ALL_OBSERVED_SYMBOLS` | `us_equity` | `REAL` | near-miss aggregate sample=144 p95_abs_distance=10.564758 ratio=0.1467 | RSI(14) > 72 AND 2-of-3 weakening conditions met | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long` | `—` | `AAPL` | `us_equity` | `REPLAY` | replay candidates: 3; replay near-misses: 8 | close crosses above 20-day high AND volume > 1.5x 20-day avg AND RSI(14) in [50, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long-loose` | `—` | `AAPL` | `us_equity` | `REPLAY` | replay candidates: 4; replay near-misses: 8 | close crosses above 20-day high AND volume > 1.2x 20-day avg AND RSI(14) in [45, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `overbought-short` | `—` | `AAPL` | `us_equity` | `REPLAY` | replay candidates: 2; replay near-misses: 3 | RSI(14) > 72 AND 2-of-3 weakening conditions met | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long` | `—` | `AMZN` | `us_equity` | `REPLAY` | replay candidates: 1; replay near-misses: 8 | close crosses above 20-day high AND volume > 1.5x 20-day avg AND RSI(14) in [50, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long-loose` | `—` | `AMZN` | `us_equity` | `REPLAY` | replay candidates: 1; replay near-misses: 10 | close crosses above 20-day high AND volume > 1.2x 20-day avg AND RSI(14) in [45, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `overbought-short` | `—` | `AMZN` | `us_equity` | `REPLAY` | replay candidates: 5 | RSI(14) > 72 AND 2-of-3 weakening conditions met | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long` | `—` | `META` | `us_equity` | `REPLAY` | replay near-misses: 7 | close crosses above 20-day high AND volume > 1.5x 20-day avg AND RSI(14) in [50, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long-loose` | `—` | `META` | `us_equity` | `REPLAY` | replay candidates: 1; replay near-misses: 12 | close crosses above 20-day high AND volume > 1.2x 20-day avg AND RSI(14) in [45, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `overbought-short` | `—` | `META` | `us_equity` | `REPLAY` | replay candidates: 5 | RSI(14) > 72 AND 2-of-3 weakening conditions met | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long` | `—` | `MSFT` | `us_equity` | `REPLAY` | replay near-misses: 5 | close crosses above 20-day high AND volume > 1.5x 20-day avg AND RSI(14) in [50, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long-loose` | `—` | `MSFT` | `us_equity` | `REPLAY` | replay near-misses: 11 | close crosses above 20-day high AND volume > 1.2x 20-day avg AND RSI(14) in [45, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `overbought-short` | `—` | `MSFT` | `us_equity` | `REPLAY` | replay candidates: 2 | RSI(14) > 72 AND 2-of-3 weakening conditions met | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long` | `—` | `NVDA` | `us_equity` | `REPLAY` | replay near-misses: 12 | close crosses above 20-day high AND volume > 1.5x 20-day avg AND RSI(14) in [50, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long-loose` | `—` | `NVDA` | `us_equity` | `REPLAY` | replay near-misses: 16 | close crosses above 20-day high AND volume > 1.2x 20-day avg AND RSI(14) in [45, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `overbought-short` | `—` | `NVDA` | `us_equity` | `REPLAY` | replay candidates: 5; replay near-misses: 4 | RSI(14) > 72 AND 2-of-3 weakening conditions met | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-oversold-bounce` | `—` | `ETH/USD` | `crypto` | `REPLAY` | replay near-misses: 6 | RSI(14) <= 30 on H1 close AND 3-bar stabilization AND volume >= 25% of avg | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-momentum` | `—` | `LTC/USD` | `crypto` | `REPLAY` | replay near-misses: 4 | predator-bracket 24h move in [3%, 15%] AND RSI band met AND volume > avg multipl | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-oversold-bounce` | `—` | `AVAX/USD` | `crypto` | `REPLAY` | replay near-misses: 6 | RSI(14) <= 30 on H1 close AND 3-bar stabilization AND volume >= 25% of avg | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-momentum` | `—` | `BCH/USD` | `crypto` | `REPLAY` | replay near-misses: 4 | predator-bracket 24h move in [3%, 15%] AND RSI band met AND volume > avg multipl | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-momentum` | `—` | `AAVE/USD` | `crypto` | `REPLAY` | replay near-misses: 4 | predator-bracket 24h move in [3%, 15%] AND RSI band met AND volume > avg multipl | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-momentum` | `crypto-momentum--rsi_threshold_55` | `BTC/USD` | `crypto` | `VARIANT` | quarantined variant 'crypto-momentum--rsi_threshold_55': threshold reality TOO_STRICT for some 7d windows; relax by 5 po | predator-bracket 24h move in [3%, 15%] AND RSI band met AND volume > avg multipl | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-momentum` | `crypto-momentum--rsi_threshold_55` | `ETH/USD` | `crypto` | `VARIANT` | quarantined variant 'crypto-momentum--rsi_threshold_55': threshold reality TOO_STRICT for some 7d windows; relax by 5 po | predator-bracket 24h move in [3%, 15%] AND RSI band met AND volume > avg multipl | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-momentum` | `crypto-momentum--rsi_threshold_55` | `SOL/USD` | `crypto` | `VARIANT` | quarantined variant 'crypto-momentum--rsi_threshold_55': threshold reality TOO_STRICT for some 7d windows; relax by 5 po | predator-bracket 24h move in [3%, 15%] AND RSI band met AND volume > avg multipl | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-momentum` | `crypto-momentum--24h_bracket_relaxed_2pct` | `BTC/USD` | `crypto` | `VARIANT` | quarantined variant 'crypto-momentum--24h_bracket_relaxed_2pct': predator bracket [3%, 15%] blocks oversold-bounce setup | predator-bracket 24h move in [3%, 15%] AND RSI band met AND volume > avg multipl | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-momentum` | `crypto-momentum--24h_bracket_relaxed_2pct` | `ETH/USD` | `crypto` | `VARIANT` | quarantined variant 'crypto-momentum--24h_bracket_relaxed_2pct': predator bracket [3%, 15%] blocks oversold-bounce setup | predator-bracket 24h move in [3%, 15%] AND RSI band met AND volume > avg multipl | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-momentum` | `crypto-momentum--24h_bracket_relaxed_2pct` | `SOL/USD` | `crypto` | `VARIANT` | quarantined variant 'crypto-momentum--24h_bracket_relaxed_2pct': predator bracket [3%, 15%] blocks oversold-bounce setup | predator-bracket 24h move in [3%, 15%] AND RSI band met AND volume > avg multipl | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-oversold-bounce` | `crypto-oversold-bounce--rsi_threshold_33` | `BTC/USD` | `crypto` | `VARIANT` | quarantined variant 'crypto-oversold-bounce--rsi_threshold_33': near-miss cluster observed around RSI 31-33; current 30  | RSI(14) <= 30 on H1 close AND 3-bar stabilization AND volume >= 25% of avg | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `crypto-oversold-bounce` | `crypto-oversold-bounce--rsi_threshold_33` | `ETH/USD` | `crypto` | `VARIANT` | quarantined variant 'crypto-oversold-bounce--rsi_threshold_33': near-miss cluster observed around RSI 31-33; current 30  | RSI(14) <= 30 on H1 close AND 3-bar stabilization AND volume >= 25% of avg | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long` | `momentum-long--breakout_threshold_1_5pct` | `AAPL` | `us_equity` | `VARIANT` | quarantined variant 'momentum-long--breakout_threshold_1_5pct': 0 production fires lifetime for momentum-long; replay ca | close crosses above 20-day high AND volume > 1.5x 20-day avg AND RSI(14) in [50, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long` | `momentum-long--breakout_threshold_1_5pct` | `MSFT` | `us_equity` | `VARIANT` | quarantined variant 'momentum-long--breakout_threshold_1_5pct': 0 production fires lifetime for momentum-long; replay ca | close crosses above 20-day high AND volume > 1.5x 20-day avg AND RSI(14) in [50, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long` | `momentum-long--breakout_threshold_1_5pct` | `NVDA` | `us_equity` | `VARIANT` | quarantined variant 'momentum-long--breakout_threshold_1_5pct': 0 production fires lifetime for momentum-long; replay ca | close crosses above 20-day high AND volume > 1.5x 20-day avg AND RSI(14) in [50, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long` | `momentum-long--breakout_threshold_1_5pct` | `AMZN` | `us_equity` | `VARIANT` | quarantined variant 'momentum-long--breakout_threshold_1_5pct': 0 production fires lifetime for momentum-long; replay ca | close crosses above 20-day high AND volume > 1.5x 20-day avg AND RSI(14) in [50, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |
| `momentum-long` | `momentum-long--breakout_threshold_1_5pct` | `META` | `us_equity` | `VARIANT` | quarantined variant 'momentum-long--breakout_threshold_1_5pct': 0 production fires lifetime for momentum-long; replay ca | close crosses above 20-day high AND volume > 1.5x 20-day avg AND RSI(14) in [50, | 0.50 - 0.75 (builder default) | none | `SHADOW_ONLY` | `WAITING_FOR_REAL_MARKET_TRIGGER` |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `SHADOW_CANDIDATE_NEVER_AUTO_PROMOTED`
- `SHADOW_CANDIDATE_NEVER_PLACES_ORDERS`
- `SHADOW_CANDIDATE_NEVER_CREATES_SHADOW_FILL`
- `QUEUE_NEVER_INFLATES_SHADOW_ELIGIBILITY`
- `QUEUE_NEVER_TOUCHES_STATE_JSON`
- `SEEDER_DOES_NOT_FETCH_NETWORK`
