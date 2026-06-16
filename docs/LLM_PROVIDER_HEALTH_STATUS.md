# LLM Provider Health Audit (v3.30)

_Generated:_ `2026-06-16T12:17:17.042885+00:00`

## Providers

### `anthropic`
- env: `ANTHROPIC_API_KEY` present=`False` length=`0` (value NEVER printed)
- verdict: `UNKNOWN`
- reason: `ANTHROPIC_API_KEY env not set; cannot determine provider liveness from a read-only audit`

### `gemini`
- env: `GEMINI_API_KEY` present=`False` length=`0` (value NEVER printed)
- verdict: `UNKNOWN`
- reason: `GEMINI_API_KEY env not set; cannot determine provider liveness from a read-only audit`

### `openai`
- env: `OPENAI_API_KEY` present=`False` length=`0` (value NEVER printed)
- verdict: `UNKNOWN`
- reason: `OPENAI_API_KEY env not set; cannot determine provider liveness from a read-only audit`

## 80-day-down operator claim

- Verdict: `CLAIM_UNSUPPORTED`
- Reason: `history lacks usable timestamps; the 80-day-down claim is unsupported by direct evidence`

## Activation snapshot

- present: `True`
- quality_review present: `True`

## Quality history (last 200 rows)

- rows: `6`
- n_success: `0`
- n_failure: `0`
- n_unknown: `6`
- earliest_iso: `None`
- latest_iso: `None`

## Budget

- calls_today: `None`
- daily_call_budget: `None`
- remaining: `None`
- spent_today_usd: `None`
- max_cost_usd_per_day: `None`

## v3.30 quality counts (per-agent latest rows)

- total rows scanned: `15`
- acceptable: `0`
- low_quality: `0`
- empty: `1`
- low_quality_ratio: `0.0`
- flagged: `False` (threshold > 0.5)

## v3.30 smoke test

- status: `SKIPPED_NO_KEY`
- reason: `GEMINI_API_KEY not set in current shell`

## Proposed fixes (operator action — DO NOT auto-apply)

- [PROPOSED-FIX] LLM provider may be DEGRADED/UNKNOWN because GEMINI_API_KEY env not configured in workflow context — operator should set GEMINI_API_KEY in GitHub repo secrets at Settings → Secrets and variables → Actions → New repository secret. Do NOT auto-apply.

## Standing markers
- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER`
- `LLM_ADVISORY_ONLY`
- `LLM_NEVER_IN_ORDER_PATH`

---

_This audit never enables broker paper, never enables live trading, never enables `EDGE_GATE_ENABLED`, never prints any secret value (all output passes through redact_secrets), never auto-applies fixes, never modifies the LLM budget, never submits / cancels / closes any order. LLM output is advisory-only and MUST NOT participate in the broker / order / risk path._
