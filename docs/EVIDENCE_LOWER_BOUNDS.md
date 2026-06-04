# Evidence Lower Bounds — paper-only edge evidence

**Version:** v3.20.0 (2026-06-04)
**Module:** `shared/evidence_lower_bounds.py`
**Report script:** `scripts/evidence_lower_bounds_report.py`
**Status:** sandbox-only; never auto-flips `EDGE_GATE_ENABLED`; never
calls the broker; never calls a paid API.

## Why

The 2026-06-02 audit board reaffirmed `NOT_SAFE_FOR_LIVE_TRADING`. One
of the headline reasons (STRAT-003) is that the system did not
distinguish *point-estimate* metrics from *statistical lower bounds*.
A strategy with `WR_mean = 0.55` over `n = 18` trades has a Wilson 95%
lower bound of about 0.34 — well below chance after costs. Approving
edge on such a sample would be operator self-deception.

This module computes the lower-bound view of every metric used in
`strategy_quality_gate.classify_strategy(...)`. It does **not** modify
the gate. Future wiring is the responsibility of a separate ETAP gated
on operator review of the audit-board outcome.

## Lower-bound metrics computed

For each strategy with at least one closed paper trade:

| Metric | Definition |
| --- | --- |
| `win_rate_lower_cb` | Wilson 95% lower bound: `(p + z²/(2n) − z·sqrt((p(1−p) + z²/(4n))/n)) / (1 + z²/n)` with `z = 1.96`. |
| `profit_factor_lower_bound` | 5th percentile of 1000 bootstrap resamples (with replacement). |
| `expectancy_lower_bound` | 5th percentile of bootstrap expectancy. |
| `drawdown_upper_bound` | 95th percentile of bootstrap max drawdown. |
| `bootstrap_outcome_stability` | `stdev(bootstrap_total_pnl) / max(|mean|, 1)` — descriptive only. |
| `worst_20_trade_window` | Worst rolling sum over any contiguous 20-trade window. |
| `probability_of_negative_expectancy` | Bootstrap-estimated `P(sum(net_pnl) ≤ 0)`. |
| `sample_size_sufficiency` | `n ≥ 50` boolean. |

The bootstrap is deterministic: `seed = 42 + stable_hash(strategy_name)`
where `stable_hash` is the first 8 bytes of SHA-256. The exact same
ledger and exact same strategy name always produce the exact same
numbers across processes and runs.

## Status ladder

`classify_strategy_evidence(ledger, strategy)` returns one of:

| Status | Trigger |
| --- | --- |
| `EVIDENCE_TOO_WEAK` | `n < 50` OR Wilson WR lower bound `< 0.40`. |
| `EVIDENCE_IMPROVING` | `20 ≤ n < 50` AND mean WR `≥ 0.50` AND Wilson LB `≥ 0.40`. |
| `EVIDENCE_ROBUST_CANDIDATE` | `n ≥ 50` AND PF lower bound `≥ 1.3` AND expectancy LB `> 0`. |
| `EVIDENCE_DEGRADING` | `n ≥ 40` AND last 20 trades mean `<` first 20 trades mean. |
| `EVIDENCE_REJECT` | PF mean `≥ 1.3` AND PF lower bound `< 1.0` (mean inflated by tail wins). |

`EVIDENCE_ROBUST_CANDIDATE` is the **highest** rung this module can
report. It is **not** approval to trade live — it is an input signal
that the operator may consider as one of many factors when reviewing
whether the system has gathered enough evidence for the next experiment.

## Paper-only

The report script reads exclusively from the PAPER ledger via
`paper_experiment.load_paper_ledger(...)`. Backtest and replay records
are intentionally excluded — they are triage only.

## Free-tier operation

* No paid API calls.
* Pure Python — uses `math`, `random`, `statistics` from stdlib only.
* Deterministic and idempotent — safe to schedule.

## Usage

```bash
python3 scripts/evidence_lower_bounds_report.py
python3 scripts/evidence_lower_bounds_report.py --window-days 90
python3 scripts/evidence_lower_bounds_report.py --bootstrap-n 500 --json
```

Output: `docs/EVIDENCE_LOWER_BOUNDS_LATEST.md` (plus sibling `.json`
when `--json` is passed).

## What this does NOT do

* It does not place trades.
* It does not raise position sizes / leverage / risk limits.
* It does not lower risk engine thresholds.
* It does not disable safe-mode / kill-switch.
* It does not bypass the audit log.
* It does not auto-flip `EDGE_GATE_ENABLED`.
* It does not recommend live trading.
* It does not mix paper evidence with backtest or replay evidence.
* It does not introduce a `LIVE_APPROVED` status.
