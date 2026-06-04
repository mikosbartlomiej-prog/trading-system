# Strategy Disable / Degrade Rules (v3.19.0, ETAP 8)

**Module:** `shared/strategy_disable_rules.py`
**Status:** Advisory only · No runtime mutation · No LLM

---

## Purpose

`evaluate_disable_rules` runs a set of conservative, deterministic
rules over a strategy's paper-trading metrics and recent operational
signals. Each rule that fires votes for a severity. The final
recommendation is the **most severe** triggered.

The function emits a recommendation only. No state is changed.
No strategy is auto-disabled at runtime.

---

## Recommendation enum (closed, severity order ascending)

```
KEEP                       # nothing fired
OBSERVE                    # soft signal; watch closely
DEGRADE                    # downgrade to OBSERVE_ONLY priority
DISABLE_CANDIDATE          # strong evidence; operator should review
MANUAL_REVIEW_REQUIRED     # operational anomaly; operator gate
```

`MANUAL_REVIEW_REQUIRED` beats `DISABLE_CANDIDATE` beats `DEGRADE`.

---

## Hard contract

| Rule | Enforcement |
|---|---|
| Paper trading only | Reads metrics + breakdowns. No live broker. |
| No runtime mutation | Output is advisory; operator action required. |
| Conservative | Multiple weak signals must combine before reaching DISABLE_CANDIDATE. |
| Deterministic | Same input → same output. |
| Audit emit | Each recommendation emits a JSONL line. |
| Fail-soft | Never raises. Internal errors → MANUAL_REVIEW_REQUIRED. |

---

## Rules

Each rule below is independent. Multiple may trigger; the
combined severity wins.

| ID | Trigger | Severity |
|---|---|---|
| `low_win_rate` | `n_closed >= 20` and `WR < 30%` | DEGRADE |
| `low_profit_factor` | `n_closed >= 30` and `PF < 0.80` | DISABLE_CANDIDATE |
| `negative_expectancy_after_fees` | `expectancy_after_fees < 0` | DEGRADE |
| `max_drawdown` | `max_drawdown_pct > 30%` | DEGRADE |
| `risk_violations` | `recent_violations > 0` | MANUAL_REVIEW_REQUIRED |
| `calibration_quality` | `calibration_quality == "uncalibrated"` | DEGRADE |
| `instrument_concentration` | top-symbol share > 80% of trades | MANUAL_REVIEW_REQUIRED |
| `high_slippage` | `avg_slippage_bps > 50` | DEGRADE |
| `rejected_signals` | `rejected_signals_pct > 40%` | DEGRADE |
| `recent_degradation` | last 20 WR < 30% (when `n >= 20`) | DEGRADE |

---

## Signature

```python
def evaluate_disable_rules(
    strategy: str,
    metrics: dict,
    recent_violations: int = 0,
    calibration_quality: str = "unknown",
    instrument_breakdown: dict | None = None,
    *,
    emit_audit: bool = True,
) -> dict:
    """
    Returns:
      {
        "strategy":         <name>,
        "recommendation":   KEEP | OBSERVE | DEGRADE |
                            DISABLE_CANDIDATE | MANUAL_REVIEW_REQUIRED,
        "triggered_rules":  list[str],
        "rationale":        str,
      }
    """
```

The function **never raises**. Even if an internal rule raises, the
function falls back to `MANUAL_REVIEW_REQUIRED` so the operator is
asked to investigate.

---

## Audit

Each recommendation emits a JSONL line via `shared/audit.py` with
`actor="strategy-disable-rules"` and `reason` referencing the
triggered rule(s). This makes after-the-fact reconstruction trivial.

---

## What it does NOT do

- Does **not** mutate `learning-loop/state.json`.
- Does **not** disable strategies at runtime.
- Does **not** flip `EDGE_GATE_ENABLED`.
- Does **not** change risk caps, position sizes, kill-switch.
- Does **not** use LLM.
- Does **not** mix backtest evidence with paper evidence.
