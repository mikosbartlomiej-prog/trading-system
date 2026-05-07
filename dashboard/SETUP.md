# Live Portfolio Dashboard — Setup Guide

A single Cloudflare Worker that serves both the HTML page and the
read-only Alpaca snapshot API. **Zero build step.** ~5 minutes to deploy.

## What you get

- **Dark-mode dashboard** at one URL; auto-refresh every 30 s
- **Account cards:** equity, daily P&L (with %), cash, buying power
- **Open positions table:** symbol, asset class (stock/option/crypto),
  side, qty, entry, current, P&L $, P&L %, % of equity
  (concentration warning when ticker > 35% of equity)
- **Recent orders table:** last 15 orders with status pills
- **No MCP dependency** — works in any browser, doesn't go through
  Cowork/claude.ai

## Deploy in 5 steps (~5 min)

### 1. Create the Worker

[https://dash.cloudflare.com](https://dash.cloudflare.com) → **Workers & Pages** → **Create application** → **Create Worker**

- **Name:** `dashboard-proxy` (anything you like)
- **Edit Code** → delete the default template → paste the entire content
  of `dashboard/worker.js` from this repo
- **Save and Deploy**

### 2. Add the Alpaca secrets

Worker → **Settings** → **Variables and Secrets** → **+ Add variable**

| Variable | Value | Type |
|---|---|---|
| `ALPACA_API_KEY` | (same as your GitHub secret) | **Encrypt** |
| `ALPACA_SECRET_KEY` | (same as your GitHub secret) | **Encrypt** |

Click **Save and Deploy**.

### 3. Open the URL

Cloudflare gives you a URL like `https://dashboard-proxy.<account>.workers.dev`. Open in browser. You should see the dashboard populate within 1-2 seconds.

### 4. (optional) Bookmark + add to home screen

The page works on phone/tablet too — refresh button is in the top bar.

### 5. (optional) Lock it down with a token

If you don't want anyone who guesses the workers.dev URL to read your
positions, add a third env var:

| Variable | Value | Type |
|---|---|---|
| `DASHBOARD_AUTH_TOKEN` | any random string (e.g. `openssl rand -hex 16`) | **Encrypt** |

Then access the dashboard via `https://dashboard-proxy.../?t=<token>`.

(Token-gating not yet implemented in v1 of `worker.js` — current version
relies on URL obscurity. Roadmap item if you want it.)

---

## What the page calls

| Path | Purpose |
|---|---|
| `GET /` | Returns the dashboard HTML |
| `GET /api/snapshot` | Returns JSON: `{account, positions, orders, timestamp, errors}` |

The `/api/snapshot` handler combines three Alpaca paper-API calls in
parallel (`Promise.all`):

- `GET /v2/account`
- `GET /v2/positions`
- `GET /v2/orders?status=all&limit=15&direction=desc`

The HTML page calls `/api/snapshot` on load and every 30 seconds. The
Alpaca keys never leave the Worker — the browser only ever sees the
flattened/enriched JSON snapshot.

---

## Concentration colouring (v2.0 risk-on aware)

| % of equity | Display |
|---|---|
| < 25 % | normal (white) |
| 25 – 35 % | amber (warning, getting close to 40 % per-ticker cap) |
| > 35 % | amber (still under 40 % cap but worth attention) |

Per-ticker hard cap is 40% (matches `shared/risk_guards.py::POSITION_PCT_CAP` and `docs/STRATEGY.md` §2.2).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Failed to load: HTTP 500` | Worker raised exception | Check Cloudflare → Worker → Logs (real-time tail) |
| `Failed to load: HTTP 401` from /api/snapshot | Wrong Alpaca creds | Re-check env vars; they must match GitHub secrets |
| Dashboard shows but tables empty | No positions yet OR Alpaca returned empty arrays | Open `/api/snapshot` directly in browser to inspect raw JSON |
| `Alpaca /v2/positions: HTTP 403` | Likely live keys instead of paper | Make sure you're using paper keys (PA…) — same as GitHub secrets |
| Dashboard slow / stale | Browser tab in background | Refresh button forces immediate fetch |

---

## Updating the dashboard later

When `dashboard/worker.js` changes in the repo:

1. Cloudflare → Workers → `dashboard-proxy` → **Edit Code**
2. Replace contents with new file from repo
3. **Save and Deploy**

(Or use `wrangler` CLI to deploy from local — but for a single Worker
the dashboard UI is faster.)
