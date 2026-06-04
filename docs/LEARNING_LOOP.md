# Post-Session Learning Loop (v3.19.0, ETAP 2)

**Module:** `shared/post_session_learning.py`
**CLI:** `scripts/post_session_learning_report.py`
**Status:** Advisory only · Paper trading only · Free local operation

---

## Purpose

The post-session learning loop reads what actually HAPPENED in a session
and emits a structured, deterministic report:

- per-strategy / per-symbol / per-regime / per-confidence-bucket /
  per-time-window aggregate metrics,
- a list of detected findings (false positives, single-regime
  dependence, recent degradation, over-trading, backtest-vs-paper
  divergence),
- a per-strategy advisory recommendation chosen from a closed enum.

It is the **observation layer** in the learning loop — not the
intervention layer.

---

## Hard contract

The module obeys the iron rules of the system:

| Rule | Enforcement |
|---|---|
| Paper trading only | Reads `learning-loop/paper_experiments/<date>.jsonl`. No live broker calls. |
| No LLM in trading path | Pure Python, deterministic computations. |
| Read-only | Never writes `learning-loop/state.json`. Never flips `EDGE_GATE_ENABLED`. |
| Never auto-disables | Every recommendation is advisory; operator action required. |
| Backtest ≠ paper | Optional `backtest_metrics_by_strategy` is used ONLY for divergence detection — it is never substituted for paper evidence. |
| Fail-soft | Missing inputs → empty buckets + warning. Malformed lines → skipped. Never raises. |
| Audit trail | Each recommendation emits a JSONL line via `shared/audit.py`. |
| Free | $0/month. Local files only. |

---

## Recommendation enum (closed)

```
KEEP_OBSERVING             # healthy; keep collecting
NEEDS_MORE_DATA            # n_closed < 10 — wait
DEGRADE_TO_OBSERVE_ONLY    # weak signal; downgrade priority
CANDIDATE_FOR_DISABLE      # strong negative signal; operator should review
CANDIDATE_FOR_EDGE_REVIEW  # promising; multi-regime evidence; human review
```

Severity order (most severe wins):
`CANDIDATE_FOR_DISABLE > DEGRADE_TO_OBSERVE_ONLY >
CANDIDATE_FOR_EDGE_REVIEW > NEEDS_MORE_DATA > KEEP_OBSERVING`.

`CANDIDATE_FOR_EDGE_REVIEW` is **NOT** an automatic promotion. It only
flags that the strategy is worth a human review for possible
EDGE_GATE consideration — the operator still must run backtests and
satisfy `shared/strategy_quality_gate.py` criteria.

---

## Output shape

```python
{
    "date":               "2026-06-04",
    "window_days":        1,
    "n_trades_in_window": 42,
    "n_audit_events":     128,
    "strategies":         {strategy: PerStrategyMetrics},
    "symbols":            {symbol:   PerSymbolMetrics},
    "regimes":            {regime:   PerRegimeMetrics},
    "confidence_buckets": {bucket:   PerBucketMetrics},
    "time_windows":       {window:   PerWindowMetrics},
    "findings":           [{type, severity, strategy,
                            description, recommendation, ...}, ...],
    "recommendations":    {strategy: status, ...},
    "warnings":           [str, ...],
    "paper_only":         True,
    "generated_at":       "...",
}
```

`PerStrategyMetrics` includes a `per_regime` block so the consumer can
inspect regime breakdowns without an extra call.

---

## Triggers / cadence

Two natural cadences (operator may run more often as needed):

1. **End of session** (~20:30 UTC) — after the trading session closes.
2. **Daily** (~04:30 UTC) — alongside daily-learning so the
   recommendations are visible to the human review in the morning.

The CLI is idempotent: running it twice writes the same content
(modulo `generated_at`) because the underlying computations are
deterministic on the input ledger.

---

## CLI usage

```bash
python -m scripts.post_session_learning_report
python -m scripts.post_session_learning_report --date 2026-06-04
python -m scripts.post_session_learning_report --window-days 7
python -m scripts.post_session_learning_report --no-emit-audit
```

Writes:
- `docs/post_session_LATEST.md`  (human-readable)
- `docs/post_session_LATEST.json` (machine-readable)

---

## What it does NOT do

- It does **not** mutate `learning-loop/state.json`.
- It does **not** flip `EDGE_GATE_ENABLED`.
- It does **not** raise risk limits, position sizes, leverage.
- It does **not** disable / pause cooldown, kill-switch, safe-mode, or
  any gate.
- It does **not** call the broker.
- It does **not** call any LLM.
- It does **not** count backtest / replay evidence as paper edge
  approval.

---

## Related modules

- `shared/paper_experiment.py` — the canonical paper ledger writer.
- `shared/strategy_quality_gate.py` — the hard-gate classifier
  (`OBSERVE_ONLY` / `PAPER_*` / `EDGE_*` / `REJECTED`).
- `shared/strategy_ranking.py` — composite ordering of strategies
  (ETAP 5).
- `shared/strategy_disable_rules.py` — conservative disable / degrade
  recommendations (ETAP 8).
