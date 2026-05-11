// Live Portfolio Dashboard — self-contained Cloudflare Worker.
//
// One Worker does both jobs:
//   GET /              -> serves the dashboard HTML (vanilla JS, no build)
//   GET /api/snapshot  -> JSON snapshot of /v2/account + /v2/positions + /v2/orders
//
// Auth: this Worker holds the Alpaca paper keys server-side, so the HTML
// page does NOT see them. The page just calls /api/snapshot.
//
// Required Worker env vars (set in Cloudflare dashboard -> Settings -> Variables):
//   ALPACA_API_KEY     — same value as the GitHub secret
//   ALPACA_SECRET_KEY  — same value as the GitHub secret
//
// Optional:
//   DASHBOARD_AUTH_TOKEN — if set, the page asks for this token before
//                          loading data. Lightweight protection so anyone
//                          who guesses the workers.dev URL can't read your
//                          positions. Leave unset on day one if you want
//                          a frictionless open-in-browser experience.

const ALPACA_BASE = "https://paper-api.alpaca.markets";
const GH_API_BASE = "https://api.github.com";
const GH_REPO     = "mikosbartlomiej-prog/trading-system";

async function alpaca(env, path) {
  const r = await fetch(`${ALPACA_BASE}${path}`, {
    headers: {
      "APCA-API-KEY-ID":     env.ALPACA_API_KEY,
      "APCA-API-SECRET-KEY": env.ALPACA_SECRET_KEY,
    },
  });
  if (!r.ok) {
    return { _error: `Alpaca ${path}: HTTP ${r.status}`, _body: await r.text() };
  }
  return r.json();
}

// Fetch a file from the trading-system repo (private). Requires
// GITHUB_TOKEN env var with `contents:read` scope on the repo.
// Returns parsed JSON for .json files, raw text for everything else.
// On 404 / missing token / network failure returns null (caller renders
// "unavailable" gracefully). Cache-busts via Authorization header.
async function githubReadFile(env, path) {
  if (!env.GITHUB_TOKEN) return null;
  try {
    const r = await fetch(
      `${GH_API_BASE}/repos/${GH_REPO}/contents/${path}`,
      {
        headers: {
          "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
          "Accept":        "application/vnd.github.v3+json",
          "User-Agent":    "trading-system-dashboard",
        },
      }
    );
    if (!r.ok) return null;
    const data = await r.json();
    if (!data.content) return null;
    // GitHub returns base64 (with line breaks). atob → binary string of
    // bytes 0-255. For UTF-8 source (polskie znaki, `·`, em-dashes etc.)
    // we MUST run TextDecoder so multibyte sequences are decoded
    // correctly — otherwise we get mojibake (`Â·` instead of `·`).
    const binary = atob(data.content.replace(/\n/g, ""));
    const bytes  = Uint8Array.from(binary, c => c.charCodeAt(0));
    const raw    = new TextDecoder("utf-8").decode(bytes);
    if (path.endsWith(".json")) {
      try { return JSON.parse(raw); } catch { return null; }
    }
    return raw;
  } catch (e) {
    return null;
  }
}

async function buildLearningLoopSnapshot(env) {
  // Best-effort fetch — if GITHUB_TOKEN missing or any call fails,
  // return null so dashboard shows "unavailable" tile.
  const [state, rationale] = await Promise.all([
    githubReadFile(env, "learning-loop/state.json"),
    githubReadFile(env, "learning-loop/rationale.md"),
  ]);
  if (!state) return null;

  const strategies = state.strategies || {};
  const tickers    = state.tickers    || {};
  const overrides  = [];
  const disabled_strategies = [];
  const paused_tickers      = [];

  for (const [name, cfg] of Object.entries(strategies)) {
    if (cfg.enabled === false) {
      disabled_strategies.push({ name, paused_until: cfg.paused_until || null });
    }
    const mult = cfg.size_multiplier;
    if (mult !== undefined && mult !== null && Math.abs(mult - 1.0) > 0.001) {
      overrides.push({
        name,
        size_multiplier: mult,
        side_bias:       cfg.side_bias || null,
      });
    }
  }
  for (const [name, cfg] of Object.entries(tickers)) {
    if (cfg.enabled === false) {
      paused_tickers.push({ name, evidence: cfg.evidence || null });
    }
  }

  // Last 8 rationale lines (rationale.md grows append-only)
  let rationale_tail = [];
  if (rationale && typeof rationale === "string") {
    const lines = rationale.split("\n")
                            .filter(L => L.trim().startsWith("- "))
                            .map(L => L.replace(/^- /, "").trim());
    rationale_tail = lines.slice(-8);
  }

  return {
    days_tracked:        state.days_tracked || 0,
    last_updated:        state.last_updated || null,
    options_side_bias:   (state.global_overrides || {}).options_side_bias || null,
    cumulative:          state.cumulative || {},
    overrides,
    disabled_strategies,
    paused_tickers,
    rationale_tail,
  };
}

async function buildSnapshot(env) {
  const [account, positions, orders, learning_loop] = await Promise.all([
    alpaca(env, "/v2/account"),
    alpaca(env, "/v2/positions"),
    alpaca(env, "/v2/orders?status=all&limit=15&direction=desc"),
    buildLearningLoopSnapshot(env),
  ]);

  const equity      = parseFloat(account.equity || "0");
  const lastEquity  = parseFloat(account.last_equity || equity);
  const dailyPL     = equity - lastEquity;
  const dailyPLPct  = lastEquity > 0 ? (dailyPL / lastEquity) * 100 : 0;

  const enriched = (Array.isArray(positions) ? positions : []).map(p => {
    const qty       = parseFloat(p.qty || "0");
    const entry     = parseFloat(p.avg_entry_price || "0");
    const current   = parseFloat(p.current_price || "0");
    const mv        = parseFloat(p.market_value || "0");
    const upl       = parseFloat(p.unrealized_pl || "0");
    const uplPct    = parseFloat(p.unrealized_plpc || "0") * 100;
    return {
      symbol:    p.symbol,
      asset:     p.asset_class,    // "us_equity" | "us_option" | "crypto"
      side:      p.side,
      qty,
      entry,
      current,
      market_value: mv,
      pl_usd:    upl,
      pl_pct:    uplPct,
      pct_of_equity: equity > 0 ? (Math.abs(mv) / equity) * 100 : 0,
    };
  });

  enriched.sort((a, b) => Math.abs(b.market_value) - Math.abs(a.market_value));

  const recentOrders = (Array.isArray(orders) ? orders : []).map(o => ({
    symbol:        o.symbol,
    side:          o.side,
    qty:           o.qty,
    type:          o.type,
    limit_price:   o.limit_price,
    status:        o.status,
    submitted_at:  o.submitted_at,
    filled_at:     o.filled_at,
    asset_class:   o.asset_class,
  })).slice(0, 15);

  return {
    timestamp: new Date().toISOString(),
    account: {
      equity,
      last_equity:    lastEquity,
      cash:           parseFloat(account.cash || "0"),
      buying_power:   parseFloat(account.buying_power || "0"),
      daily_pl:       dailyPL,
      daily_pl_pct:   dailyPLPct,
      account_id:     account.account_number || "",
    },
    positions: enriched,
    orders:    recentOrders,
    learning_loop,                     // may be null if GITHUB_TOKEN missing
    errors: [account, positions, orders]
              .filter(o => o && o._error)
              .map(o => o._error),
  };
}

const HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Trading System — Live Dashboard</title>
<style>
  :root {
    --bg:      #0d1117;
    --panel:   #161b22;
    --border:  #30363d;
    --text:    #e6edf3;
    --muted:   #8b949e;
    --green:   #3fb950;
    --red:     #f85149;
    --amber:   #d29922;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
               font: 14px/1.4 -apple-system, BlinkMacSystemFont, "SF Pro", Segoe UI, system-ui, sans-serif; }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 16px; }
  h1 { font-size: 18px; margin: 0 0 4px; font-weight: 600; }
  .meta { color: var(--muted); font-size: 12px; margin-bottom: 12px; }
  .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin-bottom: 16px; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
  .card .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
  .card .value { font-size: 22px; font-weight: 600; margin-top: 4px; font-variant-numeric: tabular-nums; }
  .card .sub   { color: var(--muted); font-size: 12px; margin-top: 4px; }
  .green { color: var(--green); }
  .red   { color: var(--red);   }
  .amber { color: var(--amber); }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td { padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: left; font-size: 13px; }
  th { color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; margin-bottom: 12px; }
  .panel h2 { font-size: 13px; margin: 0 0 10px; color: var(--muted); font-weight: 600;
              text-transform: uppercase; letter-spacing: 0.5px; }
  .pill { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px;
          background: #1f2937; color: var(--muted); }
  .pill.us_option { background: #4c1d95; color: #ddd6fe; }
  .pill.crypto    { background: #134e4a; color: #99f6e4; }
  .pill.long      { background: #14532d; color: #86efac; }
  .pill.short     { background: #7f1d1d; color: #fca5a5; }
  .pill.filled    { background: #14532d; color: #86efac; }
  .pill.canceled  { background: #1f2937; color: var(--muted); }
  .pill.rejected  { background: #7f1d1d; color: #fca5a5; }
  .pill.new       { background: #1e3a8a; color: #bfdbfe; }
  .pill.open      { background: #1e3a8a; color: #bfdbfe; }
  .empty { color: var(--muted); padding: 20px 0; text-align: center; font-size: 13px; }
  .err   { background: #3a1414; border: 1px solid var(--red); color: #fda4a4;
           padding: 8px 10px; border-radius: 6px; margin-bottom: 10px; font-size: 12px; }
  .footer { color: var(--muted); font-size: 11px; text-align: center; margin-top: 16px; }
  button { background: var(--panel); border: 1px solid var(--border); color: var(--text);
           padding: 6px 10px; border-radius: 6px; cursor: pointer; font: inherit; }
  button:hover { background: #1f2937; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Trading System — Live Portfolio</h1>
  <div class="meta">
    <span id="ts">loading…</span>
    &nbsp;·&nbsp; refreshes every 30 s &nbsp;·&nbsp;
    <button onclick="loadOnce()">refresh now</button>
  </div>

  <div id="errors"></div>

  <div class="grid" id="account-grid"></div>

  <div class="panel">
    <h2>Open positions <span id="pos-count" style="color: var(--muted)"></span></h2>
    <table id="positions-table">
      <thead>
        <tr>
          <th>Symbol</th>
          <th>Asset</th>
          <th>Side</th>
          <th class="num">Qty</th>
          <th class="num">Entry</th>
          <th class="num">Current</th>
          <th class="num">P&amp;L $</th>
          <th class="num">P&amp;L %</th>
          <th class="num">% Equity</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
    <div class="empty" id="positions-empty" style="display:none">No open positions</div>
  </div>

  <div class="panel">
    <h2>Recent orders</h2>
    <table id="orders-table">
      <thead>
        <tr>
          <th>Time</th>
          <th>Symbol</th>
          <th>Side</th>
          <th class="num">Qty</th>
          <th>Type</th>
          <th class="num">Limit</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
    <div class="empty" id="orders-empty" style="display:none">No recent orders</div>
  </div>

  <div class="panel" id="learning-panel">
    <h2>Learning loop <span id="ll-meta" style="color: var(--muted); text-transform: none; font-weight: normal"></span></h2>
    <div id="ll-unavailable" class="empty" style="display:none">
      learning-loop snapshot unavailable
      (set <code>GITHUB_TOKEN</code> Worker env var with contents:read scope)
    </div>
    <div id="ll-content" style="display:none">
      <div style="display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); margin-bottom: 12px">
        <div>
          <div style="color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px">Active overrides</div>
          <table id="ll-overrides"><tbody></tbody></table>
          <div class="empty" id="ll-overrides-empty" style="display:none; padding: 8px 0; text-align: left">all multipliers = 1.0</div>
        </div>
        <div>
          <div style="color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px">Disabled / paused</div>
          <div id="ll-disabled"></div>
        </div>
      </div>
      <div>
        <div style="color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px">Recent rationale (last 8)</div>
        <ul id="ll-rationale" style="margin: 0; padding-left: 18px; color: var(--text); font-size: 12px; line-height: 1.5"></ul>
      </div>
    </div>
  </div>

  <div class="footer">
    Alpaca paper account · read-only · <span id="account-id"></span>
  </div>
</div>

<script>
const fmtUSD = v => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtPct = v => (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
const fmtNum = v => v.toLocaleString("en-US", { maximumFractionDigits: 4 });
const fmtTime = iso => {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toISOString().slice(11, 19) + "Z";
};

async function loadOnce() {
  try {
    const r = await fetch("/api/snapshot", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    render(d);
  } catch (e) {
    document.getElementById("errors").innerHTML =
      '<div class="err">Failed to load: ' + e.message + "</div>";
  }
}

function render(d) {
  document.getElementById("ts").textContent = "Last update: " + fmtTime(d.timestamp);
  document.getElementById("account-id").textContent = d.account.account_id || "—";

  const errBox = document.getElementById("errors");
  errBox.innerHTML = (d.errors || []).map(e => '<div class="err">' + e + "</div>").join("");

  // Account cards
  const a = d.account;
  const plClass = a.daily_pl >= 0 ? "green" : "red";
  const cashPct = a.equity > 0 ? (a.cash / a.equity) * 100 : 0;
  document.getElementById("account-grid").innerHTML = [
    '<div class="card"><div class="label">Equity</div>'
      + '<div class="value">' + fmtUSD(a.equity) + "</div>"
      + '<div class="sub">last: ' + fmtUSD(a.last_equity) + "</div></div>",
    '<div class="card"><div class="label">Daily P&amp;L</div>'
      + '<div class="value ' + plClass + '">' + (a.daily_pl >= 0 ? "+" : "") + fmtUSD(a.daily_pl) + "</div>"
      + '<div class="sub ' + plClass + '">' + fmtPct(a.daily_pl_pct) + "</div></div>",
    '<div class="card"><div class="label">Cash</div>'
      + '<div class="value">' + fmtUSD(a.cash) + "</div>"
      + '<div class="sub">' + cashPct.toFixed(1) + "% of equity</div></div>",
    '<div class="card"><div class="label">Buying Power</div>'
      + '<div class="value">' + fmtUSD(a.buying_power) + "</div>"
      + '<div class="sub">Reg-T intraday</div></div>',
  ].join("");

  // Positions
  const tbody = document.querySelector("#positions-table tbody");
  if (!d.positions || d.positions.length === 0) {
    tbody.innerHTML = "";
    document.getElementById("positions-empty").style.display = "";
    document.getElementById("pos-count").textContent = "(0)";
  } else {
    document.getElementById("positions-empty").style.display = "none";
    document.getElementById("pos-count").textContent = "(" + d.positions.length + ")";
    tbody.innerHTML = d.positions.map(p => {
      const cls = p.pl_usd >= 0 ? "green" : "red";
      const assetPill = '<span class="pill ' + (p.asset || "") + '">' + (p.asset || "") + "</span>";
      const sidePill  = '<span class="pill ' + (p.side || "") + '">' + (p.side || "") + "</span>";
      const concAmber = p.pct_of_equity > 35 ? " amber" : (p.pct_of_equity > 25 ? " amber" : "");
      return "<tr>"
        + "<td><strong>" + p.symbol + "</strong></td>"
        + "<td>" + assetPill + "</td>"
        + "<td>" + sidePill + "</td>"
        + '<td class="num">' + fmtNum(p.qty) + "</td>"
        + '<td class="num">' + (p.entry ? "$" + p.entry.toFixed(2) : "—") + "</td>"
        + '<td class="num">' + (p.current ? "$" + p.current.toFixed(2) : "—") + "</td>"
        + '<td class="num ' + cls + '">' + (p.pl_usd >= 0 ? "+" : "") + fmtUSD(p.pl_usd) + "</td>"
        + '<td class="num ' + cls + '">' + fmtPct(p.pl_pct) + "</td>"
        + '<td class="num' + concAmber + '">' + p.pct_of_equity.toFixed(1) + "%</td>"
        + "</tr>";
    }).join("");
  }

  // Orders
  const obody = document.querySelector("#orders-table tbody");
  if (!d.orders || d.orders.length === 0) {
    obody.innerHTML = "";
    document.getElementById("orders-empty").style.display = "";
  } else {
    document.getElementById("orders-empty").style.display = "none";
    obody.innerHTML = d.orders.map(o => {
      const ts = o.filled_at || o.submitted_at;
      const statusPill = '<span class="pill ' + o.status + '">' + o.status + "</span>";
      const sidePill   = '<span class="pill ' + o.side + '">' + o.side + "</span>";
      return "<tr>"
        + "<td>" + fmtTime(ts) + "</td>"
        + "<td><strong>" + o.symbol + "</strong></td>"
        + "<td>" + sidePill + "</td>"
        + '<td class="num">' + (o.qty || "—") + "</td>"
        + "<td>" + (o.type || "—") + "</td>"
        + '<td class="num">' + (o.limit_price ? "$" + parseFloat(o.limit_price).toFixed(2) : "—") + "</td>"
        + "<td>" + statusPill + "</td>"
        + "</tr>";
    }).join("");
  }

  // Learning loop
  renderLearningLoop(d.learning_loop);
}

function renderLearningLoop(ll) {
  const meta = document.getElementById("ll-meta");
  const unavail = document.getElementById("ll-unavailable");
  const content = document.getElementById("ll-content");

  if (!ll) {
    meta.textContent = "";
    unavail.style.display = "";
    content.style.display = "none";
    return;
  }
  unavail.style.display = "none";
  content.style.display = "";

  // Meta line
  const updTs = ll.last_updated ? fmtTime(ll.last_updated) : "—";
  const cumPL = ll.cumulative && ll.cumulative.total_pnl_usd != null
    ? fmtUSD(ll.cumulative.total_pnl_usd) : "—";
  const trades = ll.cumulative && ll.cumulative.total_trades != null
    ? ll.cumulative.total_trades : 0;
  const bias = ll.options_side_bias || "neutral";
  meta.textContent = "· " + ll.days_tracked + "d tracked · "
                   + trades + " cumulative trades · cum P&L " + cumPL
                   + " · options bias " + bias + " · adapter ran " + updTs;

  // Overrides table
  const obody = document.querySelector("#ll-overrides tbody");
  const oEmpty = document.getElementById("ll-overrides-empty");
  if (!ll.overrides || ll.overrides.length === 0) {
    obody.innerHTML = "";
    oEmpty.style.display = "";
  } else {
    oEmpty.style.display = "none";
    obody.innerHTML = ll.overrides.map(o => {
      const mult = parseFloat(o.size_multiplier);
      const cls = mult > 1.0 ? "green" : (mult < 1.0 ? "amber" : "");
      const bias = o.side_bias ? ' <span class="pill">' + o.side_bias + "</span>" : "";
      return "<tr>"
        + "<td><strong>" + o.name + "</strong>" + bias + "</td>"
        + '<td class="num ' + cls + '">' + mult.toFixed(2) + "×</td>"
        + "</tr>";
    }).join("");
  }

  // Disabled / paused
  const dbox = document.getElementById("ll-disabled");
  const items = [];
  (ll.disabled_strategies || []).forEach(s => {
    items.push('<div style="margin-bottom:4px"><span class="pill" style="background:#7f1d1d;color:#fca5a5">strategy</span> <strong>' + s.name + "</strong></div>");
  });
  (ll.paused_tickers || []).forEach(t => {
    items.push('<div style="margin-bottom:4px"><span class="pill" style="background:#451a03;color:#fed7aa">ticker</span> <strong>' + t.name + "</strong></div>");
  });
  dbox.innerHTML = items.length
    ? items.join("")
    : '<div class="empty" style="padding:8px 0;text-align:left">none</div>';

  // Rationale tail
  const rul = document.getElementById("ll-rationale");
  if (!ll.rationale_tail || ll.rationale_tail.length === 0) {
    rul.innerHTML = '<li class="empty" style="list-style:none;margin-left:-18px">no recent rationale</li>';
  } else {
    rul.innerHTML = ll.rationale_tail.map(line => {
      // escape minimal HTML
      const safe = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      return "<li>" + safe + "</li>";
    }).join("");
  }
}

loadOnce();
setInterval(loadOnce, 30000);
</script>
</body>
</html>
`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/snapshot") {
      try {
        const data = await buildSnapshot(env);
        return new Response(JSON.stringify(data), {
          headers: {
            "content-type":  "application/json; charset=utf-8",
            "cache-control": "no-store",
          },
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: String(e) }), {
          status: 500,
          headers: { "content-type": "application/json" },
        });
      }
    }

    // /  -> dashboard HTML
    if (url.pathname === "/" || url.pathname === "") {
      return new Response(HTML, {
        headers: {
          "content-type":  "text/html; charset=utf-8",
          "cache-control": "no-store",
        },
      });
    }

    return new Response("Not found", { status: 404 });
  },
};
