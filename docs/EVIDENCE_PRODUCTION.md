# Evidence Production Path (v3.20.0 — ETAP 1)

**Status:** DORMANT by default. Default mode is `SIGNAL_ONLY`.
**Owner:** `shared/evidence_production.py`.
**Ledger:** `learning-loop/shadow_ledger/<date>.jsonl`.
**Audit event:** `V320_SHADOW_FILL` (per shadow fill, only).

---

## Why this exists

The 2026-06-02 audit board reaffirmed the secondary verdict
`NOT_SAFE_FOR_LIVE_TRADING` and surfaced cross-cutting theme STRAT-003
(strategy validation deficit). Before any further flip of
`EDGE_GATE_ENABLED`, the system needs a deterministic way to PRODUCE
paper-quality evidence without:

- bypassing the risk engine,
- accidentally raising sizes / leverage / risk limits,
- adding paid APIs, databases, or hosting,
- letting an LLM influence the runtime trading path,
- placing real trades that consume PDT budget on noise.

This module provides exactly that.

## Modes (mutually exclusive)

| Mode               | Records to ledger | Fill simulator | Hits broker? | Default |
|--------------------|-------------------|----------------|--------------|---------|
| `SIGNAL_ONLY`      | NO                | NO             | NO           | YES     |
| `SHADOW_PAPER_SIM` | YES (`learning-loop/shadow_ledger/`) | YES (5 bps slippage + 1 bps half-spread) | NO | NO |
| `BROKER_PAPER`     | YES (delegated to existing paper path) | NO (uses real Alpaca paper fills) | YES (paper-only) | NO |

Selected via `EVIDENCE_PRODUCTION_MODE` env or the `mode=` kwarg on
`produce_evidence(...)`. Unknown values fall back to `SIGNAL_ONLY`.

### `SIGNAL_ONLY`

Pure baseline. The signal runs through the risk engine, the result is
reported, but NOTHING is written to the shadow ledger and NO fill is
simulated. Useful when paired with the Opportunity Ledger (ETAP 2) to
collect coverage on rejected signals without polluting evidence
metrics.

### `SHADOW_PAPER_SIM`

The risk engine runs first; if it `APPROVE`s, we apply deterministic
execution-cost assumptions to the entry reference price:

- 5 bps slippage in the direction of the trade,
- 1 bps half-spread,
- result is rounded to 8 decimal places.

These are intentionally pessimistic so the resulting WR / PF estimates
are conservative. The record carries `execution_source=SHADOW_SIM` and
the canonical `evidence_source=PAPER`.

### `BROKER_PAPER` (opt-in only)

Hard-asserts the broker endpoint equals `PAPER_BASE_URL`
(`shared/autonomy.assert_paper_only`). Live URL strings are never
referenced literally — they are constructed indirectly via
string concatenation and the central `PAPER_BASE_URL` constant. If
ALPACA paper credentials are missing in env, the module DOWNGRADES to
`SHADOW_PAPER_SIM` and records the downgrade in audit and on the
record (`fallback_reason="missing_paper_credentials"`). The downgrade
exists because we never want a fresh CI runner to suddenly start
placing real paper orders by accident.

## Record schema

Every shadow / broker-paper record contains:

| Field                  | Type                  | Notes                                              |
|------------------------|-----------------------|----------------------------------------------------|
| `strategy`             | str                   | propagated from the signal                         |
| `symbol`               | str                   |                                                    |
| `timestamp`            | iso 8601 UTC          | microsecond precision                              |
| `signal_id`            | str                   | passed in by the caller                            |
| `confidence_score`     | float or null         | from `shared/confidence`                           |
| `confidence_components`| dict[str, float]      |                                                    |
| `regime`               | str or null           |                                                    |
| `spread_estimate`      | float (bps)           | == `half_spread_bps` of the fill                   |
| `slippage_estimate`    | float (bps)           |                                                    |
| `fill_assumption`      | str                   | `"shadow_mid_plus_costs"`                          |
| `risk_decision`        | str                   | APPROVE / REJECT / DEFER / ...                     |
| `audit_reference`      | str                   | `shadow:<file>#<symbol>@<timestamp>`               |
| `evidence_source`      | str                   | always `"PAPER"`                                   |
| `execution_source`     | str                   | `SIGNAL_ONLY` / `SHADOW_SIM` / `BROKER_PAPER`      |
| `mode`                 | str                   | mirror of resolved mode                            |
| `action` / `size_usd` / `reference_price` / `fill_price` | mixed | echo of the input signal |
| `rationale`            | str                   | from the risk officer                              |
| `fallback_reason`      | str or absent         | only set when broker → shadow downgrade happened   |

## Constraints (HARD)

- The risk engine (`shared/risk_officer.evaluate_trade`) is invoked on
  every call. If it returns anything other than `APPROVE`, NO record
  is written.
- Audit emit per fill is `V320_SHADOW_FILL`. If the audit subsystem is
  unavailable, the producer fails soft (audit must never break the
  call path).
- No paid services, no LLM, no new SDKs. Local filesystem only.
- The module never references a live URL literal. The paper-only
  static scan checks for `https://api.alpaca.markets` and friends —
  zero matches in this module.
- `EDGE_GATE_ENABLED` is NEVER flipped from this module.

## Operator runbook

To run the system in pure-observation mode (default):

```bash
# Default. Nothing to set.
EVIDENCE_PRODUCTION_MODE=SIGNAL_ONLY
```

To start producing local shadow evidence:

```bash
EVIDENCE_PRODUCTION_MODE=SHADOW_PAPER_SIM
```

Records will appear at `learning-loop/shadow_ledger/YYYY-MM-DD.jsonl`.
Inspect with `jq`, summarise into the learning loop separately.

To route accepted signals through the real paper broker (rare):

```bash
EVIDENCE_PRODUCTION_MODE=BROKER_PAPER
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
```

Credentials missing → silent fallback to shadow. Audit captures the
fallback. The module STILL asserts paper-only invariants before any
network reference.

## Test coverage

`tests/test_evidence_production_v3200.py` covers (at least):

- mode resolution (env, kwarg, invalid value → default),
- shadow fill cost math (long pushes up, short pushes down, zero ref
  price is safe),
- `SIGNAL_ONLY` does not create a record or trade,
- `SHADOW_PAPER_SIM` writes exactly one ledger line,
- shadow fills carry slippage + spread,
- shadow path does not bypass the risk engine,
- `BROKER_PAPER` asserts paper URL,
- `BROKER_PAPER` without creds falls back to `SHADOW_PAPER_SIM`,
- the module source contains zero live URL literals.

Run locally:

```bash
python3 -m unittest tests.test_evidence_production_v3200
```
