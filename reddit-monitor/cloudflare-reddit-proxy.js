// Cloudflare Worker: reddit-fetch-proxy
//
// Fetches Reddit public JSON endpoints from Cloudflare's edge IP and
// returns response untouched. Used by reddit-monitor/monitor.py to
// bypass Reddit's 403 block on cloud-provider data-center IPs (Azure,
// AWS, GCP — i.e. GitHub Actions runners).
//
// Reddit does NOT (typically) block Cloudflare's egress IPs — Cloudflare
// is widely whitelisted because it routes much of the web. This Worker
// is a thin pass-through: client sends a Reddit-style path, Worker
// fetches `https://www.reddit.com<path>` server-side and returns the
// JSON.
//
// Security: only paths starting with /r/ or /user/ are allowed (i.e.
// public Reddit content). No POST. No auth. No way to abuse this proxy
// for general HTTP relay.
//
// Caching: Cloudflare caches each unique path for 60s. With our cron at
// once per hour, cache won't help most calls — but if we ever bump
// frequency, this saves Reddit's load.

export default {
  async fetch(request, env) {
    if (request.method !== "GET") {
      return new Response("Method not allowed", { status: 405 });
    }

    const url = new URL(request.url);
    const path = url.pathname + url.search;

    // Whitelist: only allow /r/<sub>/... or /user/<name>/... paths
    if (!path.startsWith("/r/") && !path.startsWith("/user/")) {
      return new Response(
        JSON.stringify({ error: "Path not allowed", path }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    const target = `https://www.reddit.com${path}`;

    let upstream;
    try {
      upstream = await fetch(target, {
        headers: {
          // Reddit prefers UA in `<platform>:<app>:<version> (by /u/<name>)` format.
          "User-Agent": "trading-system-research/1.0 (by /u/anonymous)",
          "Accept":     "application/json",
        },
        cf: {
          // Cache identical requests for 60s on Cloudflare edge.
          cacheTtl:        60,
          cacheEverything: true,
        },
      });
    } catch (e) {
      return new Response(
        JSON.stringify({ error: "Upstream fetch failed", detail: String(e) }),
        { status: 502, headers: { "Content-Type": "application/json" } }
      );
    }

    const body = await upstream.text();
    return new Response(body, {
      status: upstream.status,
      headers: {
        "Content-Type": "application/json",
        "X-Proxy":      "reddit-fetch-proxy",
        "X-Upstream-Status": String(upstream.status),
      },
    });
  },
};
