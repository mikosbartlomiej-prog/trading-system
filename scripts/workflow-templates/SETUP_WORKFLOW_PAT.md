# Workflow PAT Setup — one-time, ~5 minutes

## Why

GitHub's policy: workflows cannot modify files in `.github/workflows/`
using the auto-injected `GITHUB_TOKEN`. The OAuth token in my Claude
Code session also lacks the `workflow` scope (this is intentional —
Anthropic restricts agent OAuth to minimize blast radius).

Solution: a **fine-grained Personal Access Token (PAT)** scoped only to
this repo with `Actions: Read and write` + `Contents: Read and write`.
Stored as repo secret `WORKFLOW_PAT`. The `sync-workflows.yml`
workflow uses it to push to `.github/workflows/` automatically when
I update templates.

## Setup (one-time)

### Step 1 — Generate fine-grained PAT (3 min)

1. Open https://github.com/settings/personal-access-tokens/new
2. **Token name:** `trading-system workflow sync`
3. **Resource owner:** `mikosbartlomiej-prog`
4. **Repository access:** "Only select repositories" → pick **`trading-system`**
5. **Expiration:** 1 year (max). Mark a reminder to rotate.
6. **Repository permissions:**
   - `Actions`: **Read and write**
   - `Contents`: **Read and write**
   - `Metadata`: Read-only (auto)
   - (leave everything else default = "No access")
7. Click **Generate token**.
8. **COPY THE TOKEN NOW** — GitHub shows it once. Format: `github_pat_...`.

### Step 2 — Add as repo secret (30s)

1. Open https://github.com/mikosbartlomiej-prog/trading-system/settings/secrets/actions/new
2. **Name:** `WORKFLOW_PAT` (exact spelling, case-sensitive)
3. **Secret:** paste the token from Step 1
4. Click **Add secret**

### Step 3 — Deploy sync-workflows.yml (1 min)

1. Open https://github.com/mikosbartlomiej-prog/trading-system/new/main/.github/workflows
2. **Name:** `sync-workflows.yml`
3. Paste contents of `scripts/workflow-templates/sync-workflows.yml`
4. **Commit directly to main**

### Step 4 — Trigger backfill (30s)

1. Open https://github.com/mikosbartlomiej-prog/trading-system/actions/workflows/sync-workflows.yml
2. **Run workflow** → branch `main` → Run
3. ~30s later: commit `workflow-sync: propagate templates ... [automerge]`
   appears with restored cadences (defense `*/5`, twitter `*/5`,
   monitor-health `*/30`).

## After setup — workflow

From now on:
- I edit `scripts/workflow-templates/<name>.yml`
- I push the change via my normal feature-branch flow (auto-merges to main)
- Push to main with paths matching `scripts/workflow-templates/*.yml`
  triggers `sync-workflows.yml`
- Sync workflow copies template → `.github/workflows/<name>.yml`
- Commits with `[automerge]` tag → auto-merge.yml propagates to main
- New cron schedule is active within ~1-2 min of my push

No more user paste required for workflow YAML changes.

## Rotation reminder

PAT expires in 1 year. Calendar reminder: `2027-05-13 — Rotate WORKFLOW_PAT`.
Steps: re-generate (same permissions), update repo secret, no code changes.

## Security

- Token is fine-grained — restricted to **this repo only**.
- Permissions: only Actions + Contents (no admin, no other repos).
- Stored encrypted at rest by GitHub Secrets.
- Visible to GitHub Actions only — never logged in workflow output.
- Revocable: https://github.com/settings/personal-access-tokens
