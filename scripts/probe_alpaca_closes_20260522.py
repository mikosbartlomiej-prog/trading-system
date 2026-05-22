"""
Diagnostic probe (2026-05-22) — investigate what closed today's 7 positions.

Read-only — queries Alpaca paper account for:
  1. All orders filled/canceled in last 24h (filter to today UTC)
  2. Account activities (FILL/PARTIAL_FILL/CFEE/DIV/etc) for last 24h
  3. Current open orders
  4. Position history if accessible

NO write operations. Outputs structured log to stdout for workflow capture.
"""
from __future__ import annotations
import os, json, sys
from datetime import datetime, timezone, timedelta
import requests

KEY = os.environ.get("ALPACA_API_KEY") or ""
SEC = os.environ.get("ALPACA_SECRET_KEY") or ""
BASE = "https://paper-api.alpaca.markets"
HDRS = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SEC}

if not KEY or not SEC:
    print("ERROR: ALPACA_API_KEY / ALPACA_SECRET_KEY not set in env")
    sys.exit(1)


def line(c="="): print(c * 70)


def section(title):
    line()
    print(f"  {title}")
    line()


def fmt_dt(s):
    if not s: return ""
    return s[:19].replace("T", " ")


# ─── 1. Account snapshot ──────────────────────────────────────────────────
section("1. ACCOUNT (now)")
r = requests.get(f"{BASE}/v2/account", headers=HDRS, timeout=20)
if r.status_code == 200:
    a = r.json()
    print(f"  equity:          ${float(a['equity']):>12,.2f}")
    print(f"  last_equity:     ${float(a['last_equity']):>12,.2f}")
    print(f"  cash:            ${float(a['cash']):>12,.2f}")
    print(f"  long_market_value: ${float(a['long_market_value']):>10,.2f}")
    print(f"  daytrade_count:  {a['daytrade_count']}")
    print(f"  buying_power:    ${float(a['buying_power']):>12,.2f}")
else:
    print(f"  ERROR: HTTP {r.status_code}")

# ─── 2. Open positions ────────────────────────────────────────────────────
section("2. OPEN POSITIONS (now)")
r = requests.get(f"{BASE}/v2/positions", headers=HDRS, timeout=20)
if r.status_code == 200:
    positions = r.json()
    print(f"  count: {len(positions)}")
    for p in positions:
        print(f"    {p['symbol']:<6} {p['side']:<5} qty={p['qty']:>8}  "
              f"mv=${float(p['market_value']):>9,.0f}  "
              f"avg_entry=${float(p['avg_entry_price']):>7,.2f}  "
              f"pl=${float(p['unrealized_pl']):>+8,.2f} "
              f"({float(p['unrealized_plpc'])*100:+.2f}%)")
else:
    print(f"  ERROR: HTTP {r.status_code}")

# ─── 3. Open orders ───────────────────────────────────────────────────────
section("3. OPEN ORDERS (now)")
r = requests.get(f"{BASE}/v2/orders", headers=HDRS,
                  params={"status": "open", "limit": 50, "nested": "true"},
                  timeout=20)
if r.status_code == 200:
    orders = r.json()
    print(f"  count: {len(orders)}")
    for o in orders:
        cls = o.get("order_class", "simple")
        children = len(o.get("legs") or []) if cls == "bracket" else 0
        print(f"    {o.get('symbol','?'):<6}  {o.get('side','?'):<4} "
              f"{o.get('type','?'):<6} qty={o.get('qty','?'):<6} "
              f"limit=${o.get('limit_price') or 'n/a'} "
              f"stop=${o.get('stop_price') or 'n/a'}  "
              f"class={cls} legs={children}  "
              f"submitted={fmt_dt(o.get('submitted_at',''))}")
        for leg in (o.get("legs") or []):
            print(f"      └─ leg {leg.get('side'):<4} {leg.get('type'):<6} "
                  f"qty={leg.get('qty')} limit=${leg.get('limit_price') or '-'} "
                  f"stop=${leg.get('stop_price') or '-'} status={leg.get('status')}")
else:
    print(f"  ERROR: HTTP {r.status_code}")

# ─── 4. Recent filled/canceled orders (last 30h) ──────────────────────────
section("4. ORDERS LAST 30h (filled / canceled / expired)")
cutoff = (datetime.now(timezone.utc) - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
r = requests.get(f"{BASE}/v2/orders", headers=HDRS,
                  params={"status": "all", "limit": 100, "after": cutoff,
                          "direction": "desc", "nested": "false"},
                  timeout=20)
if r.status_code == 200:
    orders = r.json()
    print(f"  count: {len(orders)} (since {cutoff})")
    print()
    print(f"  {'time':<19} {'sym':<6} {'side':<4} {'type':<6} {'status':<10} "
          f"qty       fill_qty  avg_fill  client_order_id")
    print("  " + "-" * 100)
    for o in orders:
        st = o.get("status", "?")
        # Show only fills + cancels + expires (skip new/replaced)
        if st not in ("filled", "canceled", "expired", "partially_filled", "rejected"):
            continue
        t_str = fmt_dt(o.get("filled_at") or o.get("canceled_at")
                        or o.get("expired_at") or o.get("updated_at",""))
        print(f"  {t_str:<19} {o.get('symbol','?'):<6} "
              f"{o.get('side','?'):<4} {o.get('type','?'):<6} {st:<10} "
              f"{o.get('qty','?'):<6}  "
              f"{o.get('filled_qty','?'):<8}  "
              f"${o.get('filled_avg_price') or '-':<8}  "
              f"{(o.get('client_order_id') or '')[:35]}")
else:
    print(f"  ERROR: HTTP {r.status_code}")

# ─── 5. Account activities (FILL events) ──────────────────────────────────
section("5. ACCOUNT ACTIVITIES (FILL / CFEE / DIV last 30h)")
r = requests.get(f"{BASE}/v2/account/activities", headers=HDRS,
                  params={"activity_types": "FILL,CFEE,DIV",
                          "page_size": 100, "direction": "desc"},
                  timeout=20)
if r.status_code == 200:
    activities = r.json()
    cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=30)
    print(f"  total (all time): {len(activities)}, showing last 30h:")
    for act in activities:
        t = act.get("transaction_time", "")
        try:
            t_dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            if t_dt < cutoff_dt:
                continue
        except ValueError:
            pass
        side = act.get("side", "")
        sym = act.get("symbol", "")
        qty = act.get("qty", "")
        price = act.get("price", "")
        kind = act.get("activity_type", "")
        print(f"    {fmt_dt(t):<19} {kind:<5} {sym:<6} {side:<5} "
              f"qty={qty:<6} price=${price:<7} "
              f"order_id={(act.get('order_id') or '')[:12]} "
              f"type={act.get('type','')}")
else:
    print(f"  ERROR: HTTP {r.status_code}")

# ─── 6. Portfolio history (24h equity curve) ──────────────────────────────
section("6. PORTFOLIO HISTORY (24h, 15min bars)")
r = requests.get(f"{BASE}/v2/account/portfolio/history", headers=HDRS,
                  params={"period": "1D", "timeframe": "15Min",
                          "extended_hours": "true"},
                  timeout=20)
if r.status_code == 200:
    ph = r.json()
    ts = ph.get("timestamp", [])
    eq = ph.get("equity", [])
    pl = ph.get("profit_loss", [])
    pct = ph.get("profit_loss_pct", [])
    print(f"  base_value: ${float(ph.get('base_value', 0)):,.2f}")
    print(f"  bars: {len(ts)}")
    print()
    print(f"  {'time':<19} equity      pnl       pnl_pct")
    print("  " + "-" * 60)
    for i, t in enumerate(ts):
        dt = datetime.fromtimestamp(t, tz=timezone.utc)
        e = eq[i] if i < len(eq) else None
        p = pl[i] if i < len(pl) else None
        c = pct[i] if i < len(pct) else None
        if e is None: continue
        print(f"  {dt.strftime('%Y-%m-%d %H:%M:%S'):<19} ${e:>9,.2f}  "
              f"${p:>+8,.2f}  {c*100:>+6.2f}%")
else:
    print(f"  ERROR: HTTP {r.status_code}")

line()
print("  PROBE COMPLETE")
line()
