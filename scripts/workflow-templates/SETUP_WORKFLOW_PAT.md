# Workflow PAT Setup — one-time, ~5 minutes

## Why

GitHub policy: workflows cannot modify files in `.github/workflows/`
using the auto-injected `GITHUB_TOKEN`. The OAuth token in my Claude
Code session also lacks the `workflow` scope (Anthropic restricts
agent OAuth to minimize blast radius).

**IMPORTANT (correction 2026-05-13):** Fine-grained PATs do **NOT**
have a `workflow` scope. GitHub only allows the `workflow` scope on
**Classic PATs**. Fine-grained "Actions: Read/write" controls run
management (start/cancel/rerun), NOT workflow file editing.

So this setup uses a **Classic PAT** with two scopes: `repo` + `workflow`.
Tradeoff: classic tokens have account-wide access (not repo-scoped),
but with short expiration (90 days) and explicit naming this is
acceptable for a paper-trading repo.

## Setup (one-time)

### Step 1 — Revoke previous fine-grained PAT (if generated)

If you already generated a fine-grained PAT named "trading-system workflow sync":
1. Open https://github.com/settings/personal-access-tokens
2. Find the token, click **Revoke**
3. Confirm

(The fine-grained token won't work — must be Classic.)

### Step 2 — Generate Classic PAT (3 min)

1. Open https://github.com/settings/tokens/new
2. **Note (name):** `trading-system workflow sync`
3. **Expiration:** 90 days (max recommended for classic)
4. **Select scopes:**
   - ☑ **`repo`** (entire group — Full control of private repositories)
   - ☑ **`workflow`** (Update GitHub Action workflows)
   - Leave everything else UNCHECKED
5. Click **Generate token** (green button at bottom)
6. **COPY THE TOKEN NOW** — format: `ghp_...`. GitHub shows it once.

### Step 3 — Update repo secret (30s)

1. Open https://github.com/mikosbartlomiej-prog/trading-system/settings/secrets/actions
2. Find `WORKFLOW_PAT` → click **Update** (if it exists)
   - Or click **New repository secret** if first time
3. **Name:** `WORKFLOW_PAT` (exact, case-sensitive)
4. **Secret:** paste the new classic token from Step 2
5. **Add secret** / **Update secret**

### Step 4 — Re-trigger sync workflow (30s)

1. Open https://github.com/mikosbartlomiej-prog/trading-system/actions/workflows/sync-workflows.yml
2. **Run workflow** → branch `main` → Run
3. ~30s later: commit `workflow-sync: propagate templates ... [automerge]`
   should now succeed (no more "without workflow scope" error).

## After setup — workflow

From now on:
- I edit `scripts/workflow-templates/<name>.yml`
- Push event triggers `sync-workflows.yml`
- Template copied to `.github/workflows/<name>.yml` using classic PAT
- Commits `[automerge]` → auto-merge.yml propagates to main
- New cron schedule active within ~1-2 min

No more manual paste from operator.

## Rotation reminder

Classic PAT expires in 90 days max. Calendar reminder:
**2026-08-11 — Rotate WORKFLOW_PAT (classic, repo+workflow scopes)**.

Steps to rotate:
1. Generate new classic PAT (same name + scopes, fresh expiration)
2. Update `WORKFLOW_PAT` secret with new token
3. Revoke old PAT in https://github.com/settings/tokens

## Security tradeoffs (classic vs fine-grained)

**Classic PAT (what we use):**
- Pros: Has `workflow` scope (required)
- Cons: Account-wide access to all repos; revoke if leaked
- Mitigation: 90-day expiration, named explicitly, audit via Settings → Tokens

**Fine-grained PAT (does NOT work for this):**
- Repo-scoped, more granular permissions
- BUT cannot edit workflow files — closest permission is run management

**GitHub App alternative (more complex, defer):**
- Could install custom app with workflow:write permission scoped to single repo
- Setup: ~30 min, requires app registration
- Worth doing if Classic PAT proves insufficient

## Revocation

Token has been leaked or compromised? Revoke instantly:
https://github.com/settings/tokens → click revoke on the token

After revoke, sync-workflows.yml will fail loudly with HTTP 401 until
you provision a new PAT and update the secret.
