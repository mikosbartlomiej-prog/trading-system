# Edge Evidence Contract — v3.19.0

**Created:** 2026-06-04 (ETAP 3 of v3.19.0)
**Closes:** audit-board STRAT-003 follow-up (evidence-source mixing risk)
**Source-of-truth:** `shared/evidence_source.py`, `shared/paper_experiment.py`

---

## Why this exists

The 2026-06-02 audit-board recorded `NOT_SAFE_FOR_LIVE_TRADING` and
`APPROVE_PAPER_TRADING_WITH_WARNINGS`. The follow-up question raised
in the closing brief was:

> *How does the system distinguish between a strategy that "looks good in
> backtest" and a strategy that has actually earned through paper
> trading? If both write to the same ledger, EDGE_GATE_ENABLED could
> flip on synthetic data.*

This document is the authoritative answer. Three classes of evidence
exist; only one of them can approve edge.

---

## Three evidence sources

| Source     | Where it comes from                     | Allowed use                | Approves edge? |
|------------|-----------------------------------------|----------------------------|----------------|
| `BACKTEST` | `backtest/run.py` historical replay     | Strategy candidate triage  | **No**         |
| `REPLAY`   | Event-driven scenario replay            | Triage + stress test       | **No**         |
| `PAPER`    | Live paper trading at Alpaca paper API  | Triage + edge approval     | **Yes**        |

The enum lives in `shared/evidence_source.py::EvidenceSource`.

```python
from shared.evidence_source import EvidenceSource, is_paper_only

is_paper_only(EvidenceSource.PAPER)      # True
is_paper_only(EvidenceSource.BACKTEST)   # False
is_paper_only(EvidenceSource.REPLAY)     # False
```

---

## Why backtest cannot approve edge

A backtest is a deterministic replay over a fixed historical slice.
The system that *generated* the strategy also *evaluates* it on the
same window — there is no genuine out-of-sample evidence. Backtests
are highly susceptible to:

- **Look-ahead bias**: implicit use of future information through
  indicator windows or signal lookups.
- **Selection bias**: strategy variants surviving the experimenter's
  filter typically look better than they really are.
- **Regime survivorship**: a window with a strong trend or quiet vol
  will not generalise to a regime change.
- **Overfit parameters**: thresholds tuned to maximise PF on past
  data have no reason to hold in the future.

Backtests are useful for *triage* — they help us spot strategies that
clearly do **not** work and need to be cut before paper trading. They
are not, and will never be, sufficient evidence to flip
`EDGE_GATE_ENABLED`.

## Why replay cannot approve edge

A replay reproduces a specific event-driven scenario (e.g. an FOMC
announcement, a geopolitical headline, an earnings cycle). It is
useful for:

- **Stress testing** the risk engine and exit ladder.
- **Regime simulation** — does the strategy survive a known crash?

But the same selection / look-ahead / survivorship traps apply, plus
a smaller sample size. Replay results enrich the triage view; they do
not produce edge.

## Why paper is the only edge-approval source

Paper trading at the Alpaca paper API runs against live market data
in real time. Each trade is exposed to actual spread, slippage,
queueing, partial fills, and intraday volatility. The trades arrive
unpredictably; the system has not pre-selected them.

The trade is closed and recorded only after it has actually filled
both legs. Each record is stamped with the realised fees, spread, and
slippage. Aggregating ~50+ such trades is the **minimum honest
empirical evidence** the system can produce locally without paying
for any external data feed.

---

## Approval thresholds (paper only)

All thresholds are deterministic and live in
`shared/strategy_quality_gate.py`. They are not auto-tuned. They
cannot be relaxed by a strategy proposing its own.

| Criterion                  | Threshold | Source                       |
|----------------------------|-----------|------------------------------|
| n_closed (paper)           | ≥ 50      | `MIN_TRADES_FOR_PAPER`       |
| Win rate                   | ≥ 50 %    | `MIN_WR_FOR_EDGE`            |
| Profit factor              | ≥ 1.30    | `MIN_PF_FOR_EDGE`            |
| Net P&L after fees+slip    | > 0       | `_aggregate`                 |
| Max drawdown               | < 25 %    | `MAX_DD_FOR_EDGE`            |
| Positive regimes           | ≥ 2       | `MIN_REGIMES_FOR_EDGE`       |

Even when ALL criteria are met for a single strategy, `EDGE_GATE_ENABLED`
remains false until:

1. At least 2 strategies are `EDGE_APPROVED_FOR_EXPERIMENT`,
2. No strategies are `REJECTED`,
3. All audit-board P0/P1 findings are cleared,
4. An operator explicitly sets the env var.

There is **no LIVE_APPROVED status**. There never will be.

---

## Divergence flags (overfitting detection)

`scripts/evidence_triage_report.py` writes
`docs/evidence_divergence_LATEST.md`. The report compares paper WR to
backtest WR and replay WR per strategy. When the absolute delta
exceeds the threshold (default **30 percentage points**) the row is
flagged `overfitting_warning`.

A large divergence means one of:

- The backtest is overfit (typical case) — historical WR looks great
  but the strategy fails to repeat it under live data.
- The paper sample is too small or unlucky — the report annotates the
  paper `n_closed`.
- The replay scenario is too narrow — small `replay_n` weakens the
  comparison.

Divergence flags **do not** auto-disable anything; they only surface
the warning. An operator reviews the report.

---

## Free local operation

Every artefact is local Markdown + JSONL:

```
learning-loop/paper_experiments/   # PAPER ledger
learning-loop/backtest_results/    # BACKTEST ledger
learning-loop/replay_results/      # REPLAY ledger

docs/backtest_triage_LATEST.md     # generated by evidence_triage_report.py
docs/replay_triage_LATEST.md
docs/evidence_divergence_LATEST.md
```

No paid API is called. No external monitoring or analytics service
is involved. `python3 scripts/evidence_triage_report.py` regenerates
all three reports.

---

## Operational rules

1. **Backtest pipeline** MUST set `source=EvidenceSource.BACKTEST` when
   calling `record_paper_trade(...)`. Failure to do so means the record
   lands in the wrong ledger and is excluded from triage reports.
2. **Replay pipeline** MUST set `source=EvidenceSource.REPLAY`.
3. **Paper monitor** uses the default (`source=EvidenceSource.PAPER`).
4. `compute_strategy_metrics(...)` defaults to
   `source_filter=EvidenceSource.PAPER`. The Strategy Quality Gate
   reads from this default; no override path is exposed in production.
5. Backtest and replay records that somehow land in the paper ledger
   directory are still excluded by the source-tag filter — defence in
   depth.

---

## Change history

| Version | Date       | What                                                                 |
|---------|------------|----------------------------------------------------------------------|
| 3.19.0  | 2026-06-04 | ETAP 3 — Evidence Source Separation. Initial contract.               |
