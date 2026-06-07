# Incident — 2026-06-07 Crypto-monitor Push Race Condition

**Status:** Fixed in v3.22.3.

## Timeline

- **2026-06-07 17:48 UTC** — v3.22.0 (c2ddba06) deployed with 13
  `_emit_opportunity()` sites in `crypto-monitor/monitor.py`.
- **2026-06-07 19:48 UTC** — v3.22.1 (f4564413) added halt-path emits
  (`HALTED_BY_DRAWDOWN_GUARD`, `HALTED_BY_VIX_GUARD`).
- **2026-06-07 ~21:00 UTC** — v3.22.2 (0bb51a5d) extended the workflow
  commit step to include `learning-loop/opportunity_ledger/`.
- **2026-06-07 21:15 UTC** — first production run with the extended
  commit step (workflow id `27105028911`):
  - Drawdown guard correctly halted: `-4.13% <= -3.0%`.
  - `_emit_opportunity` wrote ledger entries to disk.
  - Workflow built the commit: `[main 37c83c8] crypto-monitor: runtime_state + opportunity_ledger 2026-06-07_2115 [automerge]`.
  - **Push to origin failed** with `non-fast-forward` 3 times.
  - Workflow logged `push failed after 3 attempts — budget state not persisted` and **exited 0**, silently dropping the commit.

## Root cause

The legacy commit/push step had only 3 retries and ended with `exit 0`
on the final failure. With 8+ monitors automerging every 5 minutes,
the race window was too narrow — the 3 attempts could all lose to
faster parallel monitors.

## Fix (v3.22.3, commit pending push)

`scripts/workflow-templates/crypto-monitor.yml` "Commit routine_budget
state" step rewritten:

1. `git pull --rebase origin main` runs **before** `git add` so the
   workflow's working tree absorbs any concurrent automerge first.
2. Debug echo of `pwd`, `git status`, `ls learning-loop/opportunity_ledger/`,
   `find learning-loop`, and `git diff --cached --name-only` makes
   future race failures forensically inspectable.
3. Push retry loop expanded from 3 to **5 attempts**.
4. Between push attempts: `git pull --rebase` (still no force-push).
   If rebase fails, **`git rebase --abort` + `exit 1`** — no force-push
   fallback.
5. After all 5 attempts fail: **`exit 1`** instead of `exit 0`. The
   GitHub Actions run will be marked **failure** so the operator and
   incident-detector see it instead of it being swallowed silently.

## What this does NOT change

- crypto-monitor signal logic — unchanged
- `daily_drawdown_guard` threshold — still -3.0% (v3.0)
- risk engine limits — unchanged
- `EDGE_GATE_ENABLED` — default `false`
- `ALLOW_BROKER_PAPER` — unset
- LLM override lock — NOT auto-cleared
- live trading — blocked

## Test coverage

`tests/test_crypto_monitor_workflow_persistence_v3223.py` (13 tests)
asserts the contract:

- Template stages both runtime_state AND opportunity_ledger
- `git pull --rebase` precedes `git add`
- `git diff --cached --name-only` is emitted for forensics
- At least 5 push retries (`for attempt in 1 2 3 4 5;`)
- Final failure exits 1, not 0
- No force-push patterns present
- No `EDGE_GATE_ENABLED=true` setter
- No `ALLOW_BROKER_PAPER=true` setter
- No live URL in template
- Legacy 3-attempt loop is gone
- Active workflow at `.github/workflows/crypto-monitor.yml` mentions
  `opportunity_ledger` (will sync after this push)

## Operator verification after deploy

```bash
# After sync-workflows propagates the v3.22.3 template:
gh run list --workflow crypto-monitor.yml --limit 5
gh run view <RUN_ID> --log | grep -Ei "opportunity|ledger|HALTED|Persisted|push failed|rebasing"

# Verify ledger reaches origin:
git pull origin main
git log --oneline -- learning-loop/opportunity_ledger/
```

A successful production run will log
`Persisted crypto-monitor runtime_state + opportunity_ledger (attempt N)`
and the next `git log -- learning-loop/opportunity_ledger/` will show
the automerge commit.

A failed production run will now mark the GitHub Actions run as
**failure** (instead of silent success) — operator + incident-detector
both surface it.
