# cron-trigger — Cloudflare Worker

External cron driver for GitHub Actions workflows. Bypasses GH Actions
schedule cron-skip cascade (observed 5-12% delivery rate vs 99% expected
on 2026-05-29 in production).

## Why

GitHub Actions schedule cron triggers are best-effort — under load, GH
silently drops 80-95% of scheduled triggers. This makes hot monitors
(crypto, defense, twitter) effectively useless for real-time signal
detection.

**Real numbers from 2026-05-29 (production):**
- crypto-monitor: 8 schedule runs/24h vs 288 expected = **2.8%**
- defense-monitor: 8/288 = **2.8%**
- watchdog: 8/96 = **8%** (itself dropped — can't save anything)

Cloudflare Workers cron triggers (free tier, 99.99% SLA) fire reliably.
This worker translates Cloudflare cron → `POST /repos/{x}/actions/workflows/{y}/dispatches`
via GitHub API.

## Setup (one-time, ~10 min)

### Step 1: Cloudflare account

You already have a Cloudflare account (per CLAUDE.md: 13 workers running
including `reddit-fetch-proxy`, `crypto-proxy`, etc). Same account.

### Step 2: Create the worker

**Option A — via dashboard (recommended):**

1. Login: https://dash.cloudflare.com
2. Workers & Pages → Create application → Create Worker
3. Name: `cron-trigger`
4. Paste contents of `worker.js` into the editor
5. Save and Deploy

**Option B — via wrangler CLI:**

```bash
cd cloudflare-workers/cron-trigger
npm install -g wrangler   # if not installed
wrangler login
wrangler deploy
```

### Step 3: Configure environment variables

In Cloudflare dashboard → Workers → cron-trigger → Settings → Variables:

| Variable | Value | Notes |
|---|---|---|
| `GITHUB_PAT` | (existing WORKFLOW_PAT) | Encrypt as secret. Same Classic PAT used by `sync-workflows.yml` (90-day rotation cycle, next: 2026-08-11) |
| `GITHUB_REPO` | `mikosbartlomiej-prog/trading-system` | Plain text variable |
| `ALERT_WEBHOOK_URL` | (optional) | Slack/Discord/etc webhook for failure alerts |

**To get WORKFLOW_PAT value:**
- GitHub → Settings → Secrets → Actions → can't view secret directly
- Option: generate NEW PAT at github.com/settings/tokens (Classic, scopes:
  `repo`, `workflow`). Use new PAT here AND update WORKFLOW_PAT in GH
  secrets to match.
- OR keep existing PAT — it's only readable by GitHub Actions runners,
  not by you. Just generate fresh one for Cloudflare.

### Step 4: Configure cron triggers

In Cloudflare dashboard → Workers → cron-trigger → Settings → Triggers:

Add 3 cron triggers:
- `*/5 * * * *`     — every 5 min (hot monitors)
- `*/15 * * * *`    — every 15 min (medium-freq)
- `45 13 * * 1-5`   — weekday 13:45 UTC (morning-allocator backup)

Cloudflare free tier allows max 3 cron triggers per worker — sufficient.

### Step 5: Verify

Visit `https://cron-trigger.<your-subdomain>.workers.dev/health`

Should return JSON with worker config + market hours status.

Test manual trigger:
```
GET https://cron-trigger.<your-subdomain>.workers.dev/trigger?workflow=crypto-monitor.yml
```

Should return `{ "workflow": "crypto-monitor.yml", "ok": true, "status": 204 }`
and trigger a new run visible in `gh run list`.

### Step 6: Monitor

After deploy, check within 10 min:
```bash
gh run list --workflow=crypto-monitor.yml --limit 10
```

Should see ~2 runs from `schedule` (GH cron) + ~2 runs from
`workflow_dispatch` (Cloudflare-driven) = 4× more activity than before.

After 1 hour, count should hit ~12 (1 every 5 min) — close to expected
cadence.

## How it works

```
Cloudflare Cron (99.99% SLA)
    ↓ every 5 min
Worker scheduled() handler
    ↓ POST /actions/workflows/{name}/dispatches
GitHub API (Authorization: Bearer PAT)
    ↓ creates workflow_dispatch run
GitHub Actions runner picks up
    ↓
Monitor runs (crypto, defense, twitter, ...)
```

The existing GH schedule cron in workflow YAMLs **stays in place** as
fallback. When both fire, GH concurrency `cancel-in-progress: true`
prevents duplicates. Worst case: brief duplicate run cancelled.

## Cost

Cloudflare Workers Free tier:
- 100,000 requests/day
- 10ms CPU per request

Our usage:
- 288 `*/5` triggers × ~6 workflows = 1,728 GH API calls/day
- 96 `*/15` triggers × ~4 workflows = 384 GH API calls/day
- 5 `45 13` × 1 workflow = 5 GH API calls/day
- Total: **~2,117 requests/day** (2.1% of free quota)

GitHub Actions: workflow_dispatch is not rate-limited like schedule cron
on public repos. Each trigger is its own API call.

## Decommission / fallback

If Cloudflare Worker fails (very unlikely — 99.99% SLA), GH schedule
cron remains as fallback path. Workflows will fire less often but won't
stop entirely.

To temporarily disable cron-trigger:
- Cloudflare dashboard → Workers → cron-trigger → Triggers → Delete crons
- Worker stays deployed; just won't fire automatically. Manual `/trigger`
  endpoint still works.

## Maintenance

- PAT rotation every 90 days (matches `WORKFLOW_PAT` rotation cycle)
- Add new workflows: edit `worker.js` arrays + redeploy
- Remove workflows: edit `worker.js` + redeploy (workflow YAMLs unchanged)
