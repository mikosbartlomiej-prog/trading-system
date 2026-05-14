#!/usr/bin/env python3
"""
Trading-health check — "can the system safely trade and close positions
right now?"

Different from the older scripts/monitor_health.py which reports on
GitHub-Actions run statuses. This script focuses on TRADING IMPACT:

  - Alpaca auth + account + positions + orders fetch
  - state.json validity + age + schema
  - Open orders vs positions consistency
  - Positions without exit plan
  - Stale open orders
  - Duplicate exit orders
  - LLM status (informational — not blocking)
  - Options safety status (OPTIONS_ENABLED, count, premium-at-risk)

Severity ladder:
  OK        — green; system is healthy
  WARN      — yellow; minor inconsistency, doesn't block trading
  DEGRADED  — orange; partial outage; new entries should be cautious
  BLOCKED   — red; do NOT trade — fix issues first

Exit codes:
  0 if max severity ≤ WARN
  2 if DEGRADED
  3 if BLOCKED

Outputs:
  - JSON to stdout (default) or `--out-json` path
  - Markdown to stderr (default) or `--out-md` path
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


# Allow `from runtime_config import ...` from this script directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

ALPACA_BASE_URL = "https://paper-api.alpaca.markets"

OK, WARN, DEGRADED, BLOCKED = "OK", "WARN", "DEGRADED", "BLOCKED"
SEVERITY_RANK = {OK: 0, WARN: 1, DEGRADED: 2, BLOCKED: 3}


def headers() -> dict[str, str]:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


def _alpaca_get(endpoint: str, params: dict | None = None, timeout: int = 10) -> Any:
    try:
        r = requests.get(f"{ALPACA_BASE_URL}{endpoint}",
                         headers=headers(), params=params or {}, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        return {"_status": r.status_code, "_text": r.text[:200]}
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


def _is_option(sym: str) -> bool:
    return len(sym) > 7 and any(ch.isdigit() for ch in sym)


def _check_alpaca_auth() -> dict:
    if not headers()["APCA-API-KEY-ID"]:
        return {"name": "alpaca_auth", "severity": BLOCKED,
                "detail": "ALPACA_API_KEY missing"}
    acct = _alpaca_get("/v2/account")
    if isinstance(acct, dict) and (acct.get("_error") or acct.get("_status")):
        return {"name": "alpaca_auth", "severity": BLOCKED,
                "detail": f"account fetch failed: {acct}"}
    if not isinstance(acct, dict) or "equity" not in acct:
        return {"name": "alpaca_auth", "severity": BLOCKED,
                "detail": "account fetch returned unexpected shape"}
    return {"name": "alpaca_auth", "severity": OK,
            "detail": f"equity={acct.get('equity')}, status={acct.get('status')}",
            "account": acct}


def _check_positions_fetch() -> dict:
    p = _alpaca_get("/v2/positions")
    if isinstance(p, dict) and (p.get("_error") or p.get("_status")):
        return {"name": "positions_fetch", "severity": DEGRADED,
                "detail": f"positions fetch failed: {p}"}
    return {"name": "positions_fetch", "severity": OK,
            "detail": f"open positions: {len(p or [])}",
            "positions": p or []}


def _check_orders_fetch() -> dict:
    o = _alpaca_get("/v2/orders", params={"status": "open"})
    if isinstance(o, dict) and (o.get("_error") or o.get("_status")):
        return {"name": "orders_fetch", "severity": DEGRADED,
                "detail": f"orders fetch failed: {o}"}
    return {"name": "orders_fetch", "severity": OK,
            "detail": f"open orders: {len(o or [])}",
            "orders": o or []}


def _check_state_file() -> dict:
    """state.json schema-validates + age."""
    path = REPO_ROOT / "learning-loop" / "state.json"
    if not path.exists():
        return {"name": "state_file", "severity": WARN,
                "detail": f"state.json missing at {path}"}
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return {"name": "state_file", "severity": DEGRADED,
                "detail": f"state.json malformed: {e}"}
    try:
        from state_schema import validate_state
        sanitized, errors = validate_state(raw)
    except Exception as e:
        return {"name": "state_file", "severity": WARN,
                "detail": f"state_schema unavailable: {e}",
                "raw_keys": list(raw.keys()) if isinstance(raw, dict) else []}

    age = None
    raw_at = (raw.get("last_validated_at") if isinstance(raw, dict) else None) or ""
    try:
        if raw_at:
            ts = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    except (ValueError, TypeError):
        pass

    if errors and any("not a dict" in e for e in errors):
        return {"name": "state_file", "severity": DEGRADED,
                "detail": "state malformed", "errors": errors}
    sev = OK
    if errors:
        sev = WARN
    if age is not None and age > 48:
        sev = DEGRADED if sev == OK else sev
    return {"name": "state_file", "severity": sev,
            "detail": f"errors={len(errors)} age_hours={age}",
            "errors": errors, "age_hours": age}


def _check_positions_have_exit(positions: list[dict], orders: list[dict]) -> dict:
    """Each open position should have at least one open SELL order (TP or SL)."""
    missing: list[str] = []
    sells_by_sym: dict[str, int] = {}
    for o in orders or []:
        sym = (o.get("symbol") or "").upper()
        side = (o.get("side") or "").lower()
        if not sym or side not in ("sell", "sell_short"):
            continue
        sells_by_sym[sym] = sells_by_sym.get(sym, 0) + 1
    for p in positions or []:
        sym = (p.get("symbol") or "").upper()
        if not sym:
            continue
        # Long positions are protected by SELL; shorts by BUY-to-cover.
        # For simplicity flag any position with zero opposite-side orders.
        side = (p.get("side") or "").lower()
        if side == "short":
            # short positions need BUY orders
            buys = sum(1 for o in (orders or [])
                       if (o.get("symbol") or "").upper() == sym
                       and (o.get("side") or "").lower() == "buy")
            if buys == 0:
                missing.append(sym)
        else:
            if sells_by_sym.get(sym, 0) == 0:
                missing.append(sym)
    if not missing:
        return {"name": "positions_have_exit", "severity": OK,
                "detail": f"all {len(positions or [])} positions have exit orders"}
    return {"name": "positions_have_exit", "severity": WARN,
            "detail": f"{len(missing)} positions without exit orders",
            "missing": missing}


def _check_stale_orders(orders: list[dict], max_age_hours: float = 24.0) -> dict:
    """Open orders sitting unfilled past max_age_hours."""
    stale: list[dict[str, Any]] = []
    for o in orders or []:
        sub = o.get("submitted_at") or o.get("created_at") or ""
        try:
            ts = datetime.fromisoformat(sub.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
            if age_h > max_age_hours:
                stale.append({"id": o.get("id"), "symbol": o.get("symbol"),
                              "side": o.get("side"), "age_hours": round(age_h, 1)})
        except (ValueError, TypeError):
            continue
    if not stale:
        return {"name": "stale_orders", "severity": OK,
                "detail": "no stale open orders"}
    return {"name": "stale_orders", "severity": WARN,
            "detail": f"{len(stale)} orders > {max_age_hours}h old",
            "stale": stale[:10]}


def _check_duplicate_exits(orders: list[dict]) -> dict:
    """Multiple SELL/BUY orders for the same symbol = potential bug."""
    by_sym_side: dict[tuple[str, str], int] = {}
    for o in orders or []:
        sym = (o.get("symbol") or "").upper()
        side = (o.get("side") or "").lower()
        if not sym or not side:
            continue
        by_sym_side[(sym, side)] = by_sym_side.get((sym, side), 0) + 1
    dups = [(s, side, n) for (s, side), n in by_sym_side.items() if n > 1]
    if not dups:
        return {"name": "duplicate_exits", "severity": OK,
                "detail": "no duplicate exit orders"}
    return {"name": "duplicate_exits", "severity": WARN,
            "detail": f"{len(dups)} (symbol,side) pairs with multiple open orders",
            "duplicates": dups}


def _check_options_safety(positions: list[dict]) -> dict:
    """OPTIONS_ENABLED flag + count + premium-at-risk."""
    from runtime_config import options_enabled, profile_limits, risk_profile
    profile = risk_profile()
    limits = profile_limits(profile)
    options = [p for p in (positions or []) if _is_option((p.get("symbol") or ""))]
    count = len(options)
    enabled = options_enabled()
    premium_usd = 0.0
    for p in options:
        try:
            premium_usd += abs(float(p.get("market_value") or 0))
        except (TypeError, ValueError):
            continue
    sev = OK
    detail_parts = [
        f"OPTIONS_ENABLED={enabled}",
        f"profile={profile}",
        f"open_options={count}",
        f"premium_at_risk=${premium_usd:.2f}",
    ]
    if not enabled and count > 0:
        sev = WARN
        detail_parts.append("note: ENABLED=false but {count} option(s) still open — exit-only mode")
    return {"name": "options_safety", "severity": sev,
            "detail": "; ".join(detail_parts),
            "open_count": count, "premium_at_risk_usd": premium_usd,
            "enabled": enabled, "profile": profile,
            "limits_premium_pct": limits.get("max_options_premium_at_risk_pct")}


def _check_llm_status() -> dict:
    """LLM status is informational only — never blocks execution (spec §I.13)."""
    try:
        from runtime_config import llm_enabled, llm_reports_enabled
        enabled = llm_enabled()
        reports = llm_reports_enabled()
    except Exception as e:
        return {"name": "llm_status", "severity": OK,
                "detail": f"runtime_config unavailable ({e}) — LLM treated as off"}
    return {"name": "llm_status", "severity": OK,
            "detail": f"LLM_ENABLED={enabled}, LLM_REPORTS_ENABLED={reports}; "
                      "informational — execution never depends on LLM",
            "enabled": enabled, "reports_enabled": reports}


def run_all_checks() -> dict:
    checks: list[dict] = []

    auth = _check_alpaca_auth()
    checks.append(auth)
    if auth["severity"] == BLOCKED:
        # Nothing else makes sense if Alpaca is down.
        return {
            "max_severity": BLOCKED,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
        }

    positions_check = _check_positions_fetch()
    orders_check = _check_orders_fetch()
    checks.append(positions_check)
    checks.append(orders_check)

    positions = positions_check.get("positions", []) if positions_check["severity"] == OK else []
    orders = orders_check.get("orders", []) if orders_check["severity"] == OK else []

    checks.append(_check_state_file())
    checks.append(_check_positions_have_exit(positions, orders))
    checks.append(_check_stale_orders(orders))
    checks.append(_check_duplicate_exits(orders))
    checks.append(_check_options_safety(positions))
    checks.append(_check_llm_status())

    max_sev = max(checks, key=lambda c: SEVERITY_RANK.get(c.get("severity", OK), 0))["severity"]
    return {
        "max_severity": max_sev,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }


def render_markdown(result: dict) -> str:
    lines = [
        f"# Trading Health Report",
        f"",
        f"- generated_at: `{result['generated_at']}`",
        f"- max_severity: **{result['max_severity']}**",
        f"",
        f"| Check | Severity | Detail |",
        f"|-------|----------|--------|",
    ]
    for c in result["checks"]:
        sev = c.get("severity", "?")
        detail = (c.get("detail") or "").replace("|", "\\|")
        lines.append(f"| {c.get('name', '?')} | {sev} | {detail} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-json", help="Write JSON to this path")
    parser.add_argument("--out-md",   help="Write Markdown to this path")
    args = parser.parse_args()

    result = run_all_checks()

    out_json = json.dumps(result, indent=2, default=str)
    out_md = render_markdown(result)

    if args.out_json:
        Path(args.out_json).write_text(out_json)
    else:
        print(out_json)

    if args.out_md:
        Path(args.out_md).write_text(out_md)
    else:
        print(out_md, file=sys.stderr)

    return {
        OK: 0, WARN: 0, DEGRADED: 2, BLOCKED: 3,
    }.get(result["max_severity"], 0)


if __name__ == "__main__":
    sys.exit(main())
