# Strategy Discovery Sandbox v2 (v3.21.0)

**Module:** `shared/strategy_discovery_sandbox.py`
**Report script:** `scripts/strategy_discovery_report.py`
**Tests:** `tests/test_strategy_discovery_sandbox_v3210.py`
**Status:** PAPER ONLY — non-auto-apply by design.

## Purpose

Closes the gap between Evidence Lower Bounds (v3.20 ETAP 4) and the
Variant Quarantine (v3.20 ETAP 6): when a strategy is sparse, has a
high opportunity rejection ratio, has no variants on file, or is
EVIDENCE_IMPROVING, the Discovery Sandbox proposes concrete variants
and registers them in the quarantine zone for later replay-based
evaluation.

## Invariants

```
DISCOVERY_NEVER_ENABLES_RUNTIME = True
DISCOVERY_NEVER_PLACES_TRADES   = True
DISCOVERY_NEVER_REMOVES_GATES   = True
```

The module:

- has no broker imports;
- never edits `state.json` / strategy registries;
- never flips `EDGE_GATE_ENABLED`;
- only writes via `shared/strategy_variant_quarantine.register_variant`,
  whose closed override schema (`threshold`, `regime_filter`,
  `confidence_cap`, `universe_filter`, `exit_rule`, `cooldown`) cannot
  express a risk-gate weakening.

Promotion of any quarantined variant is gated on **Multi-Agent Audit
Board review**. The sandbox itself does not promote anything.

## Status triggers

A strategy is forwarded to discovery when it lands in one of:

| Trigger                          | Condition                                                                                  |
| -------------------------------- | ------------------------------------------------------------------------------------------ |
| `TOO_SPARSE`                     | `n_trades < 20`                                                                            |
| `HIGH_REJECTION_BUT_PROMISING`   | opportunity rejection ratio ≥ 0.60 AND evidence status not `EVIDENCE_REJECT`               |
| `NEEDS_VARIANT_DISCOVERY`        | `n_trades ≥ 20`, no variants on file, evidence status not `EVIDENCE_ROBUST_CANDIDATE`      |
| `EVIDENCE_IMPROVING`             | evidence status is `EVIDENCE_IMPROVING`                                                    |

Strategies in `EVIDENCE_REJECT` are skipped (the remedy is via
Strategy Quality Gate, not discovery). Healthy `EVIDENCE_ROBUST_CANDIDATE`
strategies that already have variants are skipped.

## Variant kinds

Each candidate strategy gets up to seven proposals across the closed
set of kinds:

- `wider_threshold`
- `narrower_threshold`
- `different_confidence_cap`
- `different_regime_filter`
- `different_time_window`
- `different_universe_subset`
- `additional_liquidity_filter`
- `additional_confirmation_requirement`

Each proposal carries: `change_rationale`, `expected_effect`,
`risk_note`, `params` (whitelisted overrides only), `test_plan`,
`rollback_note`, `promotion_criteria`, and `rejection_criteria`.

## Operational flow

```
identify_candidates(ranking, ledger, evidence, existing_variants)
        ↓
generate_proposals(candidate)         ← deterministic, pure
        ↓
register_proposals_with_quarantine(...)  ← writes to quarantine ONLY
        ↓
Multi-Agent Audit Board review        ← non-auto-apply gate
        ↓
[manual] promote to runtime if approved
```

`run_discovery(...)` is the high-level entry point that wires these
phases together. `scripts/strategy_discovery_report.py` is the
operator-facing CLI report; default behavior is identify-only,
`--register` writes proposals to the quarantine, `--no-write` prints
the report to stdout.

## Free-tier compliance

Pure stdlib. No network. No paid APIs. No LLM calls.

## Test coverage (6 tests)

1. Sandbox creates variant only via `register_variant`.
2. Variant id never appears in `backtest.strategy_registry` (when import
   is available).
3. Every proposal has a non-empty `change_rationale`.
4. Every proposal has at least one entry in `rejection_criteria`.
5. The candidate's `current_params` dict is not mutated by generation.
6. No proposal includes a forbidden risk-gate key; all used keys are in
   the quarantine module's closed whitelist.

Plus an `identify_candidates` + `run_discovery` summary smoke-test.
