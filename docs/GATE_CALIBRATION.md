# v3.20 ETAP 9 — Gate Calibration

## Why

Every entry passes through several gates before reaching the broker:
confidence, risk officer, universe, regime, spread / slippage, signal
quality. Each gate either ALLOWs the trade or BLOCKs it. Until now we
had no per-gate visibility into whether each gate was producing edge
(protecting from losses) or destroying edge (rejecting trades that
would have made money). This module pairs realised paper trades with
counterfactual outcomes (ETAP 3) and produces a per-gate calibration
table.

## What it reports

For every known gate (`confidence`, `risk`, `universe`, `regime`,
`spread_slippage`, `quality`):

- `accepted_good_trades` — gate ALLOWed and the trade was profitable.
- `accepted_bad_trades` — gate ALLOWed and the trade lost money.
- `rejected_bad_signals` — gate BLOCKed and the counterfactual
  confirms protection (would-be trade lost or stayed flat).
- `rejected_good_signals` — gate BLOCKed but the counterfactual shows
  the trade would have profited (a miss — except for the risk gate,
  see the safety rule below).
- `false_rejection_rate` = `rejected_good / (rejected_good + rejected_bad)`.
  **Forced to 0 for the risk gate by invariant.**
- `bad_acceptance_rate` = `accepted_bad / (accepted_good + accepted_bad)`.
- `missed_opportunity_estimate` — cumulative pct from
  `rejected_good_signals`. **0 for the risk gate by invariant.**
- `protection_value` — cumulative absolute loss avoided by
  `rejected_bad_signals`.
- `net_gate_value` = `protection_value - missed_opportunity_estimate`.

## The risk-gate safety rule

The risk gate (everything routed through
`shared/risk_officer.evaluate_trade`) is special. Risk rejections
protect against tail-loss scenarios where being wrong costs much more
than missing one good trade. Therefore:

1. A risk-gate rejection whose counterfactual would have profited is
   re-labelled **`safety_correct_rejection`** (NOT
   `trading_opportunity_miss`).
2. The risk gate's `false_rejection_rate` is structurally zero.
3. The risk gate's `missed_opportunity_estimate` is structurally zero.
4. The function
   `gate_calibration.assert_risk_gate_cannot_weaken("risk", proposed_action=...)`
   raises `RiskGateInvariantViolation` for any non-`None`
   `proposed_action`. Tests enforce this; the report builder calls it
   for every risk-gate row.

This is intentional: the report can _measure_ risk-gate rejections,
but no automated process is allowed to _tune the risk gate down_ on
the basis of "you would have made money". Human review is required.

## CLI

```bash
# Human table for today's ledger + executed trades file.
python3 scripts/gate_calibration_report.py \
    --date today \
    --executed journal/executed/2026-06-03.json

# Machine JSON, no audit.
python3 scripts/gate_calibration_report.py \
    --date 2026-06-03 --horizon 48 --json --no-audit
```

## Free-tier compliance

- Pure stdlib. No new dependencies, no paid APIs.
- Uses the counterfactual engine's bar-fetch path (free Alpaca daily
  bars).
- Audit emit on every report build via
  `write_audit_event(..., kind="trading")` with decision tag
  `V320_GATE_CALIBRATION_COMPUTED`.
