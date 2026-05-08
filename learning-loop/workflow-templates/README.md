# Workflow templates — paste-ready

The OAuth proxy used by Claude Code can't push files under `.github/workflows/`
without `workflow` scope, so these YAMLs live here as paste-ready templates.

**Latest version (poll-based architecture, v2.3.2 + Lane 2 auto-PR, v2.3.3):**
the workflows now (a) pull any commits the routine pushed during the analyzer
step, (b) push to the current branch instead of hardcoded `main`, so
feature-branch testing works, and (c) for daily-learning specifically, expose
`GH_TOKEN` + `pull-requests: write` permission so the analyzer can open Lane 2
auto-PRs via `gh pr create` when the LLM proposes a new adapter heuristic.

Deploy via GitHub UI:

## 1. Update existing `daily-learning.yml`

Open https://github.com/mikosbartlomiej-prog/trading-system/blob/main/.github/workflows/daily-learning.yml
→ pencil-edit → replace contents with `daily-learning.yml` from this folder
→ commit to `main`.

What changed vs current `.github/workflows/daily-learning.yml`:
- Adds `CLOUDFLARE_LEARNING_WORKER_URL` + `USE_LLM_LEARNING=true` env vars to
  the analyzer step (so the LLM augmentation layer can call the Worker).
- Adds `git add learning-loop/heuristic_proposals.md 2>/dev/null || true` so
  the LLM-suggested heuristic queue is committed alongside state/rationale.

## 2. Create new `weekly-retro.yml`

Open https://github.com/mikosbartlomiej-prog/trading-system/tree/main/.github/workflows
→ Add file → Create new file → name `weekly-retro.yml` → paste contents from
this folder → commit to `main`.

Triggers: Sundays 22:00 UTC (`0 22 * * 0`) + manual `workflow_dispatch`.
Sends `payload.type = "weekly_retrospective"` to the same learning-loop routine
on claude.ai (type-dispatched).

## 3. Update routine on claude.ai

Open the existing `learning-loop` routine (rename to **Learning Loop Strategist**)
→ replace system prompt with the entire `═══` block from
`learning-loop/routine-prompts.md`. Routine will then handle BOTH daily and
weekly cycles via `payload.type`.

No changes needed to the existing Cloudflare Worker (`learning-loop-proxy`) —
the Worker is content-agnostic; it just forwards JSON to the routine endpoint.
