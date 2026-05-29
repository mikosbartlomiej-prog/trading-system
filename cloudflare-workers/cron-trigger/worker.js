// Cloudflare Worker: cron-trigger
//
// Triggered by Cloudflare cron (99.99% SLA, free tier). Calls GitHub API
// workflow_dispatch endpoint to trigger trading-system monitors. Bypasses
// GitHub Actions schedule cron-skip cascade (observed 5-12% delivery rate
// vs 99% expected on 2026-05-29).
//
// CONFIG (env vars set in Cloudflare dashboard):
//   GITHUB_PAT          — fine-grained PAT with workflow scope (use existing WORKFLOW_PAT)
//   GITHUB_REPO         — "mikosbartlomiej-prog/trading-system" (or override)
//   ALERT_WEBHOOK_URL   — (optional) webhook for failure alerts
//
// CRON TRIGGERS (configured in wrangler.toml):
//   "*/5 * * * *"       — every 5 min: hot 24/7 monitors
//   "*/15 * * * *"      — every 15 min: medium-freq monitors
//   "45 13 * * 1-5"     — 13:45 UTC weekday: morning-allocator backup
//
// USAGE (manual test): GET /trigger?workflow=crypto-monitor.yml
//   Triggers a single workflow on demand. Useful for debugging.

const HOT_24_7 = [
  "crypto-monitor.yml",
  "defense-monitor.yml",
  "twitter-monitor.yml",
  "exit-monitor.yml",
  "options-exit-monitor.yml",
  "incident-pattern-detector.yml",
];

const MEDIUM_FREQ = [
  "geo-monitor.yml",
  "reddit-monitor.yml",
  "monitor-health.yml",
  "entry-monitors-watchdog.yml",
];

const SESSION_ONLY = [
  "price-monitor.yml",
  "options-monitor.yml",
];

// US market hours (UTC): 13:30-20:00 weekday
function isUSMarketHours(date) {
  const dow = date.getUTCDay(); // 0=Sun..6=Sat
  if (dow === 0 || dow === 6) return false;
  const h = date.getUTCHours();
  const m = date.getUTCMinutes();
  const totalMin = h * 60 + m;
  return totalMin >= 13 * 60 + 30 && totalMin < 20 * 60;
}

async function triggerWorkflow(workflow, env) {
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${workflow}/dispatches`;
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GITHUB_PAT}`,
        "Accept":        "application/vnd.github+json",
        "User-Agent":    "cloudflare-cron-trigger/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ ref: "main" }),
    });
    return {
      workflow,
      ok: r.status === 204,
      status: r.status,
      error: r.status !== 204 ? await r.text() : null,
    };
  } catch (e) {
    return { workflow, ok: false, status: 0, error: String(e) };
  }
}

async function triggerMany(workflows, env) {
  // Fire in parallel (no waiting between)
  const results = await Promise.all(workflows.map(w => triggerWorkflow(w, env)));
  const ok = results.filter(r => r.ok).length;
  const failed = results.filter(r => !r.ok);
  return { total: results.length, ok, failed };
}

export default {
  // Scheduled trigger handler
  async scheduled(event, env, ctx) {
    const now = new Date();
    const cron = event.cron;  // "*/5 * * * *" etc

    console.log(`[cron-trigger] firing for ${cron} at ${now.toISOString()}`);

    let targets = [];
    if (cron === "*/5 * * * *") {
      // Every 5 min: hot 24/7 monitors + session-only IF market open
      targets = [...HOT_24_7];
      if (isUSMarketHours(now)) {
        targets.push(...SESSION_ONLY);
      }
    } else if (cron === "*/15 * * * *") {
      targets = [...MEDIUM_FREQ];
    } else if (cron === "45 13 * * 1-5") {
      targets = ["morning-allocator.yml"];
    } else {
      console.log(`[cron-trigger] unknown cron ${cron}, no-op`);
      return;
    }

    const result = await triggerMany(targets, env);
    console.log(`[cron-trigger] ${cron} → ${result.ok}/${result.total} succeeded`);

    if (result.failed.length > 0) {
      console.error(`[cron-trigger] failures:`, JSON.stringify(result.failed));
      if (env.ALERT_WEBHOOK_URL) {
        // Best-effort alert; don't await
        ctx.waitUntil(fetch(env.ALERT_WEBHOOK_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: `cron-trigger failures: ${result.failed.length}/${result.total}`,
            details: result.failed,
          }),
        }).catch(() => {}));
      }
    }
  },

  // HTTP handler — for manual test + status check
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return new Response(JSON.stringify({
        status: "ok",
        worker: "cron-trigger",
        hot_24_7: HOT_24_7,
        medium_freq: MEDIUM_FREQ,
        session_only: SESSION_ONLY,
        market_open_now: isUSMarketHours(new Date()),
      }, null, 2), { headers: { "Content-Type": "application/json" } });
    }

    if (url.pathname === "/trigger") {
      const workflow = url.searchParams.get("workflow");
      if (!workflow || !workflow.endsWith(".yml")) {
        return new Response(JSON.stringify({
          error: "missing or invalid ?workflow=<name>.yml",
        }), { status: 400, headers: { "Content-Type": "application/json" } });
      }
      const result = await triggerWorkflow(workflow, env);
      return new Response(JSON.stringify(result, null, 2), {
        status: result.ok ? 200 : 502,
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response(
      "Cloudflare cron-trigger worker.\n\nEndpoints:\n  GET /health  — status + config\n  GET /trigger?workflow=X.yml  — manually fire workflow\n\nCron triggers handled in scheduled() handler.",
      { headers: { "Content-Type": "text/plain" } }
    );
  },
};
