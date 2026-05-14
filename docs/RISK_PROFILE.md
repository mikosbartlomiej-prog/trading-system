# Risk profiles

`RISK_PROFILE` is an env var read by `shared/runtime_config.py`. It
controls the per-trade and portfolio-level caps enforced by
`shared/portfolio_risk.py`.

Three profiles ship; **default is `BALANCED_PAPER`**.

| Setting | SAFE_FREE | BALANCED_PAPER (default) | AGGRESSIVE_PAPER |
|---|---:|---:|---:|
| max_single_trade_pct | 5% | 10% | 20% |
| max_symbol_exposure_pct | 12% | 20% | 40% |
| max_correlated_bucket_pct | 25% | 35% | 60% |
| max_gross_exposure_pct | 100% | 125% | 200% |
| max_net_long_exposure_pct | 90% | 100% | 150% |
| max_short_exposure_pct | 15% | 40% | 80% |
| max_crypto_exposure_pct | 10% | 20% | 25% |
| max_options_premium_at_risk_pct | 1% | 3% | 5% |
| min_cash_reserve_pct | 20% | 10% | 0% |
| max_daily_drawdown_pct | -5% | -8% | -12% |
| options_enabled_default | false | false | true |
| margin_enabled | false | true | true |

## When to use each

- **SAFE_FREE** — operator's first week on the system, or after a
  losing month. Tight caps, full cash reserve, no margin, no options.
  System will hand-place at most a handful of small trades per day.
- **BALANCED_PAPER** — the recommended default. Mirrors typical retail
  paper-account usage: ~10 active positions, moderate gross exposure,
  small options allocation. Conservative on the upside, opinionated
  on diversification (35% correlated-bucket cap).
- **AGGRESSIVE_PAPER** — current production mode (v3.5). 98-100% of
  capital is deployed at all times (`target_invested_ratio: 1.00`,
  `cash_reserve_pct_equity: 0.00`); the safety net is the deterministic
  IntradayProfitGovernor (`docs/INTRADAY_PROTECTION.md`) rather than
  idle cash. Single-trade cap 20%, gross 200%, options always-on by
  default (`options_enabled_default=true`). When the governor enters
  PROFIT_LOCK / DEFEND_DAY / RED_DAY_AFTER_GREEN, the **effective**
  max_gross_exposure shrinks to 1.00 / 0.50 / 0.25× equity even though
  the profile's nominal ceiling is 2.00. Full deployment resumes only
  on the next session plan from `daily-learning` — never intraday
  redeploy after a risk event.

## Correlated buckets (all profiles)

Position exposure is summed across **all** buckets a ticker sits in —
e.g. NVDA at $10k contributes $10k each to `ai_semis` and
`nasdaq_beta`. The per-bucket cap fires when ANY bucket exceeds the
profile's limit, even if the per-symbol cap is fine.

Buckets shipped in `shared/portfolio_risk.py::CORRELATED_BUCKETS`:

- `ai_semis` — NVDA, AMD, AVGO, ARM, SMCI, SOXL, SOXS, SMH
- `nasdaq_beta` — QQQ, TQQQ, SQQQ, AAPL, MSFT, META, AMZN, GOOGL,
  TSLA, NVDA, AVGO
- `crypto_beta` — BTC/USD, ETH/USD, COIN, MSTR, MARA, RIOT, SOL/USD,
  AVAX/USD, LINK/USD, DOT/USD
- `defense` — LMT, RTX, NOC, GD, BA, HII, KTOS, PLTR, AXON, LDOS,
  SAIC, CACI, AVAV, ITA, XAR, DFEN, BAESY, EADSY
- `broad_market` — SPY, QQQ, DIA, IWM, VOO, VTI, SPXL, SPXS, UPRO,
  SPXU, TNA, TZA
- `energy` — XLE, XOM, CVX, USO, OXY
- `leveraged_3x` — TQQQ, SQQQ, SPXL, SPXS, UPRO, SPXU, SOXL, SOXS,
  FAS, FAZ, TNA, TZA

To add a new bucket: edit `CORRELATED_BUCKETS` and add a unit test.
The portfolio_risk gate auto-picks it up.

## How to switch profile

Set the env var on the workflow YAML or your local shell:

```yaml
env:
  RISK_PROFILE: SAFE_FREE
```

Switch is hot — no rebuild needed. Misconfigured values fall back to
`BALANCED_PAPER` to avoid accidental aggression.

## Bounded self-modification

`config/autonomy_bounds.json` defines what the autonomous layer may
move automatically:

- `size_multiplier`: bounded [0.30, 2.00], step up ≤ 20%/day,
  step down ≤ 50%/day. Increase requires `trades_7d ≥ 20`. Decrease
  for safety can happen with smaller samples.
- `strategy_enabled`: auto-pause always allowed. Auto-resume requires
  cooldown + N consecutive OK health checks + risk-condition resolved.
- `options`: auto-disable always allowed. Auto-enable requires
  `OPTIONS_ENABLED=true`, liquidity OK, paper-only confirmed.
- `exposure_caps`: autonomy may TIGHTEN (lower the cap) but not LOOSEN
  beyond the profile's limit. Loosening is HIGH_RISK and never
  auto-merged.

LLM cannot raise risk bounds, cannot enable live, cannot bypass
sample-size rules. The validator + state schema enforce this.

## Fail-open contract

If Alpaca is unreachable when the gate runs (e.g. account fetch fails),
`portfolio_risk.evaluate_portfolio_risk()` returns `APPROVE` with a
warning. The system trades-through the outage. This is consistent
with `shared/risk_guards.py` — we never silently HALT all trading
because an API was flaky.
