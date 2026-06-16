# Geo Monitor Health Audit (v3.29)

_Generated:_ `2026-06-16T09:21:05.571498+00:00`

**Verdict:** `OK`
**Reason:** `heartbeat fresh and pipeline healthy`
**Is market hours:** `False`

## 80-day-down claim

- Verdict: `CLAIM_UNSUPPORTED`
- Reason: `heartbeat age is 1638s which is FAR less than 80 days; the 80-day-down claim is debunked by direct evidence`

## Heartbeat

- last_seen_iso: `2026-06-15T11:01:18.996852+00:00`
- age_seconds: `1637.895597`
- status: `FRESH`

## Opportunity ledger

- geo rows last 7d: `0`

## monitor_runtime_diag tokens (7d)

- `RAN`: `0`
- `EMIT_SUCCESS`: `0`
- `EMIT_FAILED`: `0`
- available: `True`

## state.json::strategies geo-* entries

- `geo-defense`: enabled=True, paused_until=None, trades_lifetime=0, placed_lifetime=None
- `geo-energy`: enabled=True, paused_until=None, trades_lifetime=None, placed_lifetime=None
- `geo-gold`: enabled=True, paused_until=None, trades_lifetime=0, placed_lifetime=None
- `geo-xom`: enabled=True, paused_until=None, trades_lifetime=0, placed_lifetime=None

## Standing markers
- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER`

---

_This audit never submits, cancels, or closes any order, never enables broker paper, never enables live trading, never mutates strategy thresholds, never auto-clears safe_mode. Output is read-only._
