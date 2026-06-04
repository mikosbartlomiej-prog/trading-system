# Strategy Variant Quarantine — v3.20 ETAP 6

**Module:** `shared/strategy_variant_quarantine.py`
**CLI:** `scripts/variant_register.py`
**Tests:** `tests/test_strategy_variant_quarantine_v3200.py`
**Status:** Quarantine zone only. NEVER enables anything on the runtime
trading path.

---

## Why this exists

The audit-board verdict on 2026-06-02 remained
`APPROVE_PAPER_TRADING_WITH_WARNINGS` / `NOT_SAFE_FOR_LIVE_TRADING`.
While operators and the learning-loop keep proposing strategy tweaks
(thresholds, regime filters, cooldowns…), we needed a deterministic
storage zone for those proposals that:

- **NEVER** mutates the active strategy registry
- **NEVER** enters the paper-trading edge ledger
- **NEVER** is read by the runtime trading path

`shared/strategy_variant_quarantine.py` is that zone.

## Override whitelist

Only these keys are accepted on a quarantined variant:

| Key             | Meaning                                  |
| --------------- | ---------------------------------------- |
| `threshold`     | Entry / signal threshold                 |
| `regime_filter` | Allowed regime (`RISK_ON`, `NEUTRAL`, …) |
| `confidence_cap`| Confidence ceiling for this variant      |
| `universe_filter` | Symbol whitelist subset                |
| `exit_rule`     | Variant exit description                 |
| `cooldown`      | Cooldown seconds / bars                  |

Anything else is silently dropped and surfaced in
`dropped_param_keys` on the record. `size_multiplier`, `leverage`,
`risk_pct`, etc. are deliberately NOT in the whitelist — variants
must not be a sneak path to risk escalation.

## Closed status enum

```
QUARANTINED
REPLAY_TESTING
SHADOW_OBSERVE
REJECTED
CANDIDATE_FOR_MANUAL_REVIEW
```

There is **no `LIVE_APPROVED`** value. There is **no `PAPER_ENABLED`**
value. Even `CANDIDATE_FOR_MANUAL_REVIEW` only flags the variant for
the operator's queue — the variant is NEVER auto-promoted.

## Evidence source

`evidence_source` MUST be `REPLAY` or `BACKTEST`. `PAPER` is rejected
outright — quarantined variants live OUTSIDE the paper-trading
edge ledger so they can never contaminate edge-gate evidence.

## Variant id

```
id = sha256(parent_strategy + json(params))[:12]
```

Stable JSON keys mean the id is deterministic across runs / hosts /
operators.

## CLI

```
python3 scripts/variant_register.py \
    --parent momentum_long_strict \
    --rationale "tighten breakout threshold for chop days" \
    --evidence-source REPLAY \
    --param threshold=0.65 \
    --param cooldown=180
```

`--param` is repeatable. Values are parsed as JSON when possible
(numbers / bools / strings).

## File layout

```
learning-loop/variant_quarantine/<id>.json
```

The directory can be redirected via `VARIANT_QUARANTINE_DIR` env var
(used in tests).

## What this module does NOT do

- It does NOT call the broker.
- It does NOT raise risk limits.
- It does NOT enable strategies.
- It does NOT mix evidence sources (PAPER stays out).
- It does NOT add paid APIs / databases / hosting.
- It does NOT add LLM/agents to the runtime trading path.
- It does NOT flip `EDGE_GATE_ENABLED`.

## Audit

Every register / status change emits a JSONL line via the existing
`shared/audit.py` machinery. Audit failure is fail-soft and never
breaks the caller.
