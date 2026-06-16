# LLM Provider Health Audit (v3.29)

_Generated:_ `2026-06-16T09:21:05.605936+00:00`

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

## Proposed fixes (operator action — DO NOT auto-apply)

- [PROPOSED-FIX] LLM provider may be DEGRADED/UNKNOWN because GEMINI_API_KEY env not configured in workflow context — operator should add the secret in GitHub repo settings (Settings → Secrets and variables → Actions → New repository secret). Do NOT auto-apply.

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
