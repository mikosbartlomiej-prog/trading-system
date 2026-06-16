# LLM Provider Activation Check (v3.31)

_Generated:_ `2026-06-16T13:11:22.091314+00:00`

## Verdict

- **Verdict:** `DETERMINISTIC_FALLBACK_UNTIL_SECRET_SET`
- **Dry-run:** `True`
- **Smoke-test requested:** `False`
- **Smoke-test executed:** `False`
- **GEMINI_API_KEY present:** `False` (value NEVER printed)

**Reason:** GEMINI_API_KEY not present in env; LLM advisory mesh remains in deterministic fallback. Deterministic gates remain final.

## Operator instructions (missing/failed key)

1. GitHub repo: Settings -> Secrets and variables -> Actions -> New repository secret
2. Name: GEMINI_API_KEY
3. Value: <obtain from https://aistudio.google.com/apikey>
4. After saving, the daily llm-advisory-mesh.yml workflow will use the secret automatically

---

### Standing markers
- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER`
- `LLM_ADVISORY_ONLY`
- `NO_LLM_STATE_MUTATION`

> This reporter is read-only. It never calls the broker, never places orders, never flips any flag, never auto-clears safe_mode, and never prints the secret value.
