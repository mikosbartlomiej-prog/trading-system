# Signal Opportunity Ledger (v3.20.0 — ETAP 2)

**Status:** PASSIVE — append-only ledger; never trades.
**Owner:** `shared/signal_opportunity_ledger.py`.
**Ledger:** `learning-loop/opportunity_ledger/<date>.jsonl`.
**Audit event:** `V320_OPPORTUNITY_RECORDED` (per recorded opportunity).

---

## Why this exists

Before v3.20.0, signals that were `BLOCK`ed or `DEFER`red by the gate
stack (confidence / risk / universe / regime / spread / quality)
disappeared into stderr. The learning loop had to *guess* why a
strategy generated few trades. Two audit-board P1 items
(`CONF-003`, `DATA-002`) called this out explicitly.

The Opportunity Ledger fixes it: every signal — accepted, downsized,
deferred, blocked — gets exactly one daily JSONL line. With this in
place, the learning loop can answer questions like:

- "How many momentum-long signals were dropped by `confidence` in the
  last 30 days?"
- "Of the rejected geo-defense signals, how many would have passed if
  the universe filter were relaxed to BUCKET_PREFERRED?"
- "Did spread/slippage gate cost us trades during BTC's RSI 22 dip?"

without touching the broker or risking real cash.

## Schema

```jsonc
{
  "signal_id":             "...",
  "strategy":              "momentum-long",
  "symbol":                "AAPL",
  "timestamp":             "2026-06-04T13:30:01.123456+00:00",
  "raw_signal":            { "...": "input dict (truncated by caller if needed)" },
  "confidence_score":      0.71,
  "confidence_components": { "data_quality": 0.9, "signal_strength": 0.6, "...": "..." },
  "risk_decision":         "APPROVE" | "REJECT" | "DEFER" | "...",
  "gate_decisions": [
    { "gate": "confidence",      "decision": "PASS",        "reason": "", "score": 0.71, "extra": {} },
    { "gate": "risk",            "decision": "PASS",        "reason": "", "score": null, "extra": {} },
    { "gate": "universe",        "decision": "PASS",        "reason": "", "score": null, "extra": {} },
    { "gate": "regime",          "decision": "PASS",        "reason": "", "score": null, "extra": {} },
    { "gate": "spread_slippage", "decision": "PASS",        "reason": "", "score": null, "extra": {} },
    { "gate": "quality",         "decision": "ALERT_ONLY",  "reason": "low_volume", "score": null, "extra": {} }
  ],
  "rejection_reasons":     ["quality: low_volume"],
  "market_regime":         "NEUTRAL",
  "universe_status":       "WHITELISTED",
  "paper_action":          "BUY",
  "shadow_action":         "SHADOW_SIM_FILLED",
  "audit_link":            "shadow:2026-06-04.jsonl#AAPL",
  "schema_version":        "v3.20.0",
  "unknown_gates":         []   // only present if any unrecognised gate name appeared
}
```

## Recognised gate types

The spec freezes six gate types:

- `confidence`       — score from `shared/confidence`
- `risk`             — verdict from `shared/risk_officer`
- `universe`         — whitelist / bucket allow rule
- `regime`           — `shared/regime` state vs strategy preferences
- `spread_slippage`  — `shared/confidence.score_slippage_risk` style
- `quality`          — earnings ± 1d, near-DTE, volume floors, etc.

Unknown gate names are NOT silently dropped — they are recorded
verbatim AND surfaced in `unknown_gates` so audits can flag them.

## Constraints (HARD)

- **Never places trades.** A static test in
  `tests/test_signal_opportunity_ledger_v3200.py` asserts that
  recording an opportunity never imports `alpaca_orders`.
- **Offline-safe.** A separate test patches `socket.socket.connect` to
  raise; the recorder must still succeed. No network calls.
- **Determinism.** Records are written sorted-keys JSON with
  microsecond-precision timestamps so consecutive records do not
  collide and replay diffs are stable.
- **Free operation.** Local filesystem only. Same audit helper as the
  rest of the system (`shared/audit.write_audit_event`).
- **Audit per record.** Emits `V320_OPPORTUNITY_RECORDED` to the
  trading audit JSONL (`journal/autonomy/YYYY-MM-DD.jsonl`).
- **No LLM in the call path.** This is pure record-keeping.
- **No risk-limit / size-limit changes.** This ledger has no power to
  raise sizes, leverage, or EDGE_GATE flags.

## Usage

Typical monitor call site:

```python
from shared.signal_opportunity_ledger import record_opportunity

record_opportunity(
    signal_id   = sig["id"],
    strategy    = sig["strategy"],
    symbol      = sig["symbol"],
    raw_signal  = sig,
    confidence_score      = report.total,
    confidence_components = report.components,
    risk_decision         = risk_result["decision"],
    gate_decisions = [
        {"gate": "confidence",      "decision": conf_gate.decision, "reason": conf_gate.reason, "score": report.total},
        {"gate": "risk",            "decision": risk_result["decision"], "reason": risk_result["rationale"]},
        {"gate": "universe",        "decision": uni_decision},
        {"gate": "regime",          "decision": regime_decision},
        {"gate": "spread_slippage", "decision": spread_decision, "reason": spread_reason},
        {"gate": "quality",         "decision": quality_decision},
    ],
    market_regime   = current_regime,
    universe_status = uni_status,
    paper_action    = "BUY" if accepted else "NONE",
    shadow_action   = shadow_result.execution_source if shadow_result else "NONE",
    audit_link      = shadow_result.audit_reference if shadow_result else None,
)
```

The function returns the persisted record so the caller can attach it
to email / Slack / logs.

## Reading

```python
from shared.signal_opportunity_ledger import read_today
for opp in read_today():
    if opp["risk_decision"] != "APPROVE":
        print(opp["symbol"], opp["rejection_reasons"])
```

## Test coverage

`tests/test_signal_opportunity_ledger_v3200.py` covers:

- one record per call (three calls → three lines in one daily file),
- accepted signal carries the `audit_link`,
- rejected signal collects the gate reason,
- unknown gate names are recorded AND surfaced,
- recording never imports broker code,
- recording works with `socket.connect` blocked,
- the schema shape contains all required fields.

Run locally:

```bash
python3 -m unittest tests.test_signal_opportunity_ledger_v3200
```
