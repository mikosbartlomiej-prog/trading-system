# SignalEvent — v3.22.0 canonical signal carrier

**Version:** v3.22.0 (2026-06-15)
**Module:** `shared/signal_event.py`
**Status:** advisory data carrier — NEVER places trades.

---

## Why this exists

Before v3.22 every monitor (price, crypto, options, defense, geo,
twitter, reddit, politician) invented its own ad-hoc dict and shoved
it into the opportunity ledger directly. The shapes drifted; the
learning loop could not reason over the rows; and there was no
single point at which we could insert hard-safety invariants.

`SignalEvent` is the **single canonical signal carrier**. Every
monitor builds one of these, every emitter consumes one of these,
the ledger persists one of these. Drift becomes impossible.

---

## Contract

`SignalEvent` is a **frozen dataclass** (immutable once constructed)
defined in `shared/signal_event.py`. The contract:

| Field | Type | Required | Notes |
|---|---|---|---|
| `signal_id` | `str` | yes | Deterministic ID. Use `build_signal_id(...)` for stability across replays. |
| `strategy_id` | `str` | yes | The strategy that fired the signal (e.g. `momentum-long`). |
| `symbol` | `str` | yes | Ticker / OCC option symbol / crypto pair. |
| `asset_class` | `str` | yes (string) | e.g. `us_equity`, `crypto`, `us_option`. May be empty for observe events. |
| `side` | `str` | yes | One of `long`, `short`, `flat`, `n/a`. |
| `action` | `str` | yes | One of `BUY`, `SELL`, `SELL_SHORT`, `HOLD`, `NO_SIGNAL`, `REJECT`, `HALTED`, `DETECTED`, `BLOCKED`. |
| `timestamp_iso` | `str` | yes | ISO 8601 UTC, microsecond precision recommended. |
| `source_monitor` | `str` | yes | Name of the emitting monitor (e.g. `price-monitor`). |
| `pipeline` | `str` | yes | One of `monitor`, `shadow`, `paper`, `replay`, `backtest`. **`live` is intentionally NOT allowed** — live trading is unsupported. |
| `evidence_source` | `str` / `EvidenceSource` | yes | One of `BACKTEST`, `REPLAY`, `PAPER`. |
| `entry_capable` | `bool` | yes | `True` ↔ the event represents a potential entry. `False` ↔ observe-only telemetry (HALTED, BLOCKED, DETECTED, etc.). |
| `raw_signal` | `dict` | no | The monitor's own payload (score, RSI, volume ratio, etc.). |
| `market_regime` | `dict` | no | Snapshot of regime detector output for downstream replay. |
| `confidence_inputs` | `dict` | **required if `entry_capable=True`** | Kwargs forwarded to `shared.confidence.compute_confidence`. |
| `risk_inputs` | `dict` | **required if `entry_capable=True`** | Inputs the risk officer needs (size, SL, etc.). |
| `universe_status` | `dict` | no | Universe-gate snapshot. |
| `pre_open_flags` | `dict` | no | Earnings, blackout, news flags. |
| `metadata` | `dict` | no | Free-form. The emitter pulls `metadata.audit_link` through to the ledger row. |

`validate(event)` is a pure function returning a list of error
strings. Empty list = valid. Callers (the emitter) decide whether
to proceed.

---

## Pipeline enum

```
monitor    — live monitor cron run (no broker contact)
shadow     — synthetic shadow opportunity generator
paper      — would-be paper trade if ALLOW_BROKER_PAPER were true (still gated)
replay     — historical replay for backtest / calibration
backtest   — backtest harness
```

`live` is intentionally absent. Live trading is unsupported in this
repo and the codebase is hard-pinned to that contract.

---

## Evidence source mapping

| `evidence_source` | Meaning |
|---|---|
| `BACKTEST` | Computed from historical bars in a backtest run. |
| `REPLAY` | Replay of a recorded session for calibration. |
| `PAPER` | Real-market observation against the paper broker (NO order placed in v3.22). |

`evidence_source` is the single most important field for the
learning loop: it tells the LLM whether a signal carries any
real-market evidence weight or whether it is a synthetic
counterfactual. v3.22 does not yet produce real evidence from the
production path — the spine is wired, but `ALLOW_BROKER_PAPER`
stays `false` so no actual paper order is placed.

---

## Hard safety

- `signal_event.py` NEVER imports `alpaca_orders` (or any broker
  module).
- It NEVER places trades; it is a pure dataclass file.
- It is loadable under any sandbox / no-network test harness.

---

## How to build one

```python
from shared.signal_event import SignalEvent, build_signal_id, validate

sid = build_signal_id(
    strategy_id="momentum-long",
    symbol="AAPL",
    timestamp_iso="2026-06-15T13:30:00Z",
    source_monitor="price-monitor",
)
event = SignalEvent(
    signal_id=sid,
    strategy_id="momentum-long",
    symbol="AAPL",
    asset_class="us_equity",
    side="long",
    action="BUY",
    timestamp_iso="2026-06-15T13:30:00Z",
    source_monitor="price-monitor",
    pipeline="monitor",
    evidence_source="PAPER",
    entry_capable=True,
    raw_signal={"primary_score": 0.72},
    confidence_inputs={"primary_score": 0.72},
    risk_inputs={"size_usd": 10_000, "stop_loss_pct": 0.05},
    metadata={"audit_link": "audit-abc"},
)
errors = validate(event)
assert errors == []
```

Then hand the event to `shared.signal_emitter.emit_signal_opportunity(event)`.

---

## What this is NOT

- It is NOT a trade order.
- It is NOT an instruction to the broker.
- It is NOT a guarantee that a trade was placed.
- It is NOT proof of edge — the system has not yet proven edge.

System is **not live-ready**. Confidence score without data is not
proof of edge. `EDGE_GATE_ENABLED` remains `false`.
`ALLOW_BROKER_PAPER` remains `false`. **Live trading forbidden.**
System remains free to operate.
