# v3.20 ETAP 3 — Counterfactual Outcome Engine

## Why

Every trading day the system rejects (or stamps `observe_only`) a long
list of candidate signals via the opportunity ledger. Until now we had
no way to look back and ask: *"If we had actually taken those trades,
would they have made money?"* Without that feedback, every gate in the
pipeline operates blind — we cannot tell which rejections were
protecting us from loss and which were burning real edge.

This module fills that gap. It reads
`learning-loop/opportunity_ledger/<date>.jsonl`, waits the
deterministic horizon (24 h / 48 h), and computes for each signal:

- `hypothetical_pnl_after_costs` — round-trip P&L the trade would have
  produced, with slippage / commission baked in.
- `MFE` / `MAE` — maximum favourable / adverse excursion during the
  hold window, direction-aware.
- `was_rejection_correct` — `True` if the trade would have lost or been
  flat, `False` if it would have profited, `None` when bar data is
  unavailable.
- `missed_opportunity_cost` — magnitude of the profit we did not take
  (only positive when the rejection was wrong).

## Critical contracts

- **Counterfactuals are NEVER paper trades.** Each record carries
  `evidence_source = "COUNTERFACTUAL"` (a plain string constant in
  `shared/counterfactual_outcomes.py`; we deliberately did NOT extend
  `shared.evidence_source.EvidenceSource` to avoid a merge collision
  with the other v3.20 etaps).
- **No real orders are placed.** No paid APIs are called. Bar data goes
  through the existing free `shared/market_data.get_daily_bars` adapter.
- **Missing data → `UNKNOWN`.** We never invent prices when bars are
  missing — those signals are excluded from the false-rejection rate.
- **Audit emit on every computation** via `write_audit_event(..., kind="trading")`
  with decision tag `V320_COUNTERFACTUAL_COMPUTED`.

## CLI

```bash
# Human-readable summary for today.
python3 scripts/counterfactual_report.py --date today

# Machine-readable JSON for a specific date.
python3 scripts/counterfactual_report.py --date 2026-06-03 --json

# Skip audit emission (useful in tests).
python3 scripts/counterfactual_report.py --date today --no-audit
```

## Aggregation by gate

`aggregate_by_gate(...)` collapses per-signal results into per-gate
counts:

- `n_rejections` — total ALLOW=False outcomes touched.
- `n_false_rejections` — rejections that would have profited.
- `n_correct_rejections` — rejections that would have lost or been flat.
- `n_bad_acceptances` — accepted trades that lost.
- `false_rejection_rate` = `n_false_rejections / n_rejections`.
- `bad_acceptance_rate` = `n_bad_acceptances /
  (n_rejections + n_bad_acceptances)`.

Downstream calibration logic (ETAP 9, `shared/gate_calibration.py`)
re-labels false rejections on the `risk` gate as
`safety_correct_rejection` to enforce the asymmetric safety rule.

## Free-tier compliance

- Pure stdlib + the existing free Alpaca bar fetcher.
- No new dependencies, no paid APIs, offline-only tests.
- Bar fetches are fail-soft: on any exception the record is marked
  `UNKNOWN` rather than crashing the pipeline.
