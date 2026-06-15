#!/usr/bin/env python3
"""
Portfolio rebalancer — target allocation 2026-06-15
VOO 40% | QQQ 20% | VXUS 15% | VWO 10% | GLD 10% | Cash 5%

Run via GitHub Actions workflow or manually:
  ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python3 scripts/rebalance_portfolio_20260615.py
  python3 scripts/rebalance_portfolio_20260615.py --dry-run
"""

import os, sys, json, datetime, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))

import requests

ALPACA_BASE = "https://paper-api.alpaca.markets"

TARGET = {
    "VOO":  0.40,
    "QQQ":  0.20,
    "VXUS": 0.15,
    "VWO":  0.10,
    "GLD":  0.10,
    # Cash 5% — kept as reserve, not traded
}
CASH_RESERVE_PCT = 0.05
REBALANCE_THRESHOLD = 0.03   # 3 percentage points minimum deviation
MAX_TRADE_PCT       = 0.20   # 20% equity per single trade (iron rule)
SL_PCT              = 0.07   # 7% stop-loss
TP_PCT              = 0.14   # 14% take-profit
DRY_RUN = "--dry-run" in sys.argv


def headers():
    key = os.environ.get("ALPACA_API_KEY") or os.environ.get("APCA_API_KEY_ID", "")
    sec = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY", "")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}


def get_account():
    r = requests.get(f"{ALPACA_BASE}/v2/account", headers=headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def get_positions():
    r = requests.get(f"{ALPACA_BASE}/v2/positions", headers=headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def get_latest_quote(symbol):
    r = requests.get(
        f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest",
        headers=headers(), timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    q = data.get("quote", {})
    ask = float(q.get("ap", 0))
    bid = float(q.get("bp", 0))
    mid = (ask + bid) / 2 if ask and bid else 0
    return {"ask": ask, "bid": bid, "mid": mid}


def place_order(symbol, side, notional_usd, current_price, dry_run=True):
    qty = max(int(notional_usd / current_price), 1)
    sl  = round(current_price * (1 - SL_PCT), 2)
    tp  = round(current_price * (1 + TP_PCT), 2)
    limit_price = round(current_price * 1.005, 2) if side == "buy" else round(current_price * 0.995, 2)
    order_payload = {
        "symbol":        symbol,
        "qty":           str(qty),
        "side":          side,
        "type":          "limit",
        "time_in_force": "day",
        "limit_price":   str(limit_price),
        "order_class":   "bracket",
        "stop_loss":     {"stop_price": str(sl)},
        "take_profit":   {"limit_price": str(tp)},
        "client_order_id": f"rebalance-{symbol.lower()}-{datetime.date.today().isoformat()}",
    }
    if dry_run:
        return {"dry_run": True, "payload": order_payload, "status": "would_place"}
    r = requests.post(
        f"{ALPACA_BASE}/v2/orders", headers=headers(),
        json=order_payload, timeout=15,
    )
    return r.json()


def snapshot():
    acct = get_account()
    equity = float(acct["equity"])
    cash   = float(acct["cash"])
    positions = get_positions()

    pos_map = {}
    for p in positions:
        sym = p["symbol"]
        mv  = float(p["market_value"])
        pos_map[sym] = {
            "market_value": mv,
            "pct":          mv / equity,
            "qty":          float(p["qty"]),
            "cost_basis":   float(p.get("cost_basis", 0)),
            "unrealized_pl": float(p.get("unrealized_pl", 0)),
        }

    return equity, cash, pos_map, acct


def compute_trades(equity, pos_map):
    investable = equity * (1 - CASH_RESERVE_PCT)
    trades = []
    for sym, tgt_pct in TARGET.items():
        target_val  = investable * tgt_pct
        current_val = pos_map.get(sym, {}).get("market_value", 0.0)
        deviation   = (target_val - current_val) / equity
        if abs(deviation) < REBALANCE_THRESHOLD:
            continue
        delta = target_val - current_val
        side  = "buy" if delta > 0 else "sell"
        size  = abs(delta)
        # Iron rule: single trade ≤ 20% equity
        if size > equity * MAX_TRADE_PCT:
            size = equity * MAX_TRADE_PCT
        trades.append({
            "symbol":      sym,
            "side":        side,
            "notional":    size,
            "deviation":   deviation,
            "target_pct":  tgt_pct,
            "current_pct": current_val / equity,
        })
    return trades


def main():
    print(f"=== Portfolio Rebalancer — {datetime.date.today()} (dry_run={DRY_RUN}) ===")
    print(f"Target: VOO 40% | QQQ 20% | VXUS 15% | VWO 10% | GLD 10% | Cash 5%")
    print()

    try:
        equity, cash, pos_map, acct = snapshot()
    except requests.HTTPError as e:
        print(f"ERROR: Alpaca API auth failed — {e}")
        sys.exit(1)

    print(f"Equity:  ${equity:,.2f}")
    print(f"Cash:    ${cash:,.2f} ({cash/equity*100:.1f}%)")
    print()
    print("Current positions:")
    for sym, info in sorted(pos_map.items()):
        tgt = TARGET.get(sym, 0)
        dev = info["pct"] - tgt
        print(f"  {sym:6s}  ${info['market_value']:>10,.2f}  {info['pct']*100:5.1f}%  "
              f"(target {tgt*100:.0f}%  dev {dev*100:+.1f}pp)")

    # Symbols in target but NOT held
    for sym, tgt in TARGET.items():
        if sym not in pos_map:
            print(f"  {sym:6s}  ${'0':>10}   0.0%  (target {tgt*100:.0f}%  dev {-tgt*100:+.1f}pp)")
    print()

    trades = compute_trades(equity, pos_map)
    if not trades:
        print("✅ Portfolio within thresholds — no rebalancing needed.")
        return

    print(f"Proposed trades ({len(trades)}):")
    results = []
    for t in trades:
        sym      = t["symbol"]
        side     = t["side"]
        notional = t["notional"]
        print(f"  {side.upper():4s} {sym:6s}  ${notional:>10,.2f}  "
              f"(cur {t['current_pct']*100:.1f}% → tgt {t['target_pct']*100:.0f}%  "
              f"dev {t['deviation']*100:+.1f}pp)")

        try:
            quote = get_latest_quote(sym)
            price = quote["ask"] if side == "buy" else quote["bid"]
            if price <= 0:
                print(f"    ⚠ Could not fetch price for {sym} — skipping")
                results.append({"symbol": sym, "status": "no_price"})
                continue
        except Exception as e:
            print(f"    ⚠ Quote error for {sym}: {e} — skipping")
            results.append({"symbol": sym, "status": "quote_error", "reason": str(e)})
            continue

        order_result = place_order(sym, side, notional, price, dry_run=DRY_RUN)
        print(f"    {'[DRY-RUN]' if DRY_RUN else '[ORDER]'} {sym} {side} qty≈{int(notional/price)} @ ~${price:.2f}  SL=${price*(1-SL_PCT):.2f}  TP=${price*(1+TP_PCT):.2f}")
        if not DRY_RUN:
            print(f"    Response: {json.dumps(order_result)}")
        results.append({"symbol": sym, "side": side, "status": "placed" if not DRY_RUN else "dry_run",
                        "notional": round(notional, 2), "price": price})

    print()
    print(f"Done — {len([r for r in results if r['status'] in ('placed','dry_run')])} trades {'simulated' if DRY_RUN else 'submitted'}.")
    return results


if __name__ == "__main__":
    main()
