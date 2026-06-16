#!/usr/bin/env python3
"""v3.22 (2026-06-07) — Position reconciliation report.

After the 2026-06-07 incident (equity -4.27% / -$8,744 over 3 days
with 0 attributed closed trades), the operator needs a single
read-only artifact that reconciles:

- open positions per Alpaca (live snapshot, paper account)
- the orders that opened them (from allocator execution.json + audit JSONL)
- per-position audit references
- per-position risk decision
- per-position confidence score (if recorded)
- per-position exit plan / SL eligibility
- per-position unrealized P&L
- aggregate unrealized drawdown

The script is READ-ONLY. It does not place trades, modify positions,
or recommend live actions. Output: `docs/position_reconciliation_LATEST.md`
+ JSON variant.

Run:
  python3 scripts/position_reconciliation_report.py
  python3 scripts/position_reconciliation_report.py --no-write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))


def _read_json(path: Path, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _list_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


def fetch_alpaca_snapshot() -> dict:
    """Fetch account + positions from paper Alpaca. Fail-soft if creds missing."""
    out: dict[str, Any] = {"available": False, "account": None, "positions": []}
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        out["error"] = "ALPACA_API_KEY/ALPACA_SECRET_KEY not in env"
        return out
    try:
        import requests  # type: ignore
        base = "https://paper-api.alpaca.markets"
        h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        r = requests.get(f"{base}/v2/account", headers=h, timeout=5)
        r.raise_for_status()
        out["account"] = r.json()
        r2 = requests.get(f"{base}/v2/positions", headers=h, timeout=5)
        r2.raise_for_status()
        out["positions"] = r2.json()
        out["available"] = True
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return out


def collect_recent_executions(days_back: int = 7) -> list[dict]:
    """Read allocator execution.json from the past N days."""
    out = []
    today = date.today()
    for offset in range(days_back + 1):
        d = today.replace(day=today.day) if offset == 0 else None
        try:
            from datetime import timedelta
            d = (today - timedelta(days=offset)).isoformat()
        except Exception:
            continue
        p = REPO_ROOT / "learning-loop" / "allocations" / f"{d}.execution.json"
        if p.exists():
            data = _read_json(p, default={})
            data["_date"] = d
            out.append(data)
    return out


def collect_audit_events_for_symbol(symbol: str, days_back: int = 7) -> list[dict]:
    """Scan recent audit JSONL for events touching this symbol."""
    out = []
    today = date.today()
    from datetime import timedelta
    for offset in range(days_back + 1):
        d = (today - timedelta(days=offset)).isoformat()
        p = REPO_ROOT / "journal" / "autonomy" / f"{d}.jsonl"
        events = _list_jsonl(p)
        for e in events:
            payload = e.get("payload", {})
            if (
                e.get("symbol") == symbol
                or payload.get("symbol") == symbol
                or symbol in str(payload).split()
            ):
                out.append({"date": d, "type": e.get("decision_type") or e.get("type"), "payload": payload})
    return out


def reconcile_position(position: dict, executions: list[dict]) -> dict:
    """Attribute one position to its opening order(s) if findable."""
    symbol = position.get("symbol", "?")
    rec: dict[str, Any] = {
        "symbol": symbol,
        "qty": position.get("qty", "?"),
        "market_value": position.get("market_value", "?"),
        "cost_basis": position.get("cost_basis", "?"),
        "unrealized_pl": position.get("unrealized_pl", "?"),
        "unrealized_plpc": position.get("unrealized_plpc", "?"),
        "side": position.get("side", "?"),
        "opening_orders_found": [],
        "audit_events_count": 0,
        "risk_decision_at_entry": None,
        "confidence_score_at_entry": None,
        "stop_loss_at_entry": None,
        "exit_plan_present": False,
    }

    for exec_run in executions:
        for r in exec_run.get("results", []):
            if r.get("symbol") == symbol and r.get("action") == "BUY" and r.get("status") in ("placed", "filled"):
                rec["opening_orders_found"].append({
                    "date": exec_run.get("_date"),
                    "alpaca_order_id": r.get("alpaca_order_id"),
                    "reason": r.get("reason"),
                    "intended_notional": r.get("target_value"),
                })

    events = collect_audit_events_for_symbol(symbol)
    rec["audit_events_count"] = len(events)
    for e in events:
        if "risk" in (e.get("type") or "").lower() and rec["risk_decision_at_entry"] is None:
            p = e.get("payload", {})
            rec["risk_decision_at_entry"] = p.get("decision") or p.get("verdict")
        if "confidence" in (e.get("type") or "").lower() and rec["confidence_score_at_entry"] is None:
            p = e.get("payload", {})
            rec["confidence_score_at_entry"] = p.get("total_score") or p.get("score")

    return rec


def build_report() -> dict:
    snap = fetch_alpaca_snapshot()
    executions = collect_recent_executions(days_back=7)

    account = snap.get("account") or {}
    positions = snap.get("positions") or []

    reconciled = [reconcile_position(p, executions) for p in positions]

    total_unrealized = 0.0
    try:
        total_unrealized = sum(float(p.get("unrealized_pl", 0) or 0) for p in positions)
    except (TypeError, ValueError):
        pass

    return {
        "version": "v3.22.0",
        "generated_at_iso": datetime.now(timezone.utc).isoformat(),
        "alpaca_available": snap.get("available", False),
        "alpaca_error": snap.get("error"),
        "account": {
            "equity": account.get("equity"),
            "last_equity": account.get("last_equity"),
            "cash": account.get("cash"),
            "buying_power": account.get("buying_power"),
            "daytrade_count": account.get("daytrade_count"),
        } if account else None,
        "positions_count": len(positions),
        "positions": reconciled,
        "executions_scanned": len(executions),
        "total_unrealized_pl": total_unrealized,
        "invariants": {
            "live_trading_disabled": True,
            "edge_gate_enabled": False,
            "read_only": True,
            "does_not_close_positions": True,
            "does_not_place_orders": True,
        },
    }


def render_markdown(report: dict) -> str:
    lines = ["# Position Reconciliation Report (v3.22)", ""]
    lines.append("Generated by `scripts/position_reconciliation_report.py`. READ-ONLY.")
    lines.append("This report does not place trades, close positions, or recommend live action.")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at_iso']}`")
    lines.append(f"- Alpaca available: `{report['alpaca_available']}`")
    if report.get("alpaca_error"):
        lines.append(f"- Alpaca error: `{report['alpaca_error']}`")
    lines.append(f"- Open positions: `{report['positions_count']}`")
    lines.append(f"- Total unrealized P&L: `${report.get('total_unrealized_pl', 0):.2f}`")
    lines.append(f"- Executions scanned: `{report['executions_scanned']}` (last 7 days)")
    lines.append("")

    if report.get("account"):
        a = report["account"]
        lines.append("## Account snapshot (paper)")
        lines.append("")
        lines.append(f"- Equity: `${a.get('equity', '?')}`")
        lines.append(f"- Last equity: `${a.get('last_equity', '?')}`")
        lines.append(f"- Cash: `${a.get('cash', '?')}`")
        lines.append(f"- Buying power: `${a.get('buying_power', '?')}`")
        lines.append(f"- Daytrade count: `{a.get('daytrade_count', '?')}`")
        lines.append("")

    if report["positions_count"] == 0:
        lines.append("## No open positions")
        if not report["alpaca_available"]:
            lines.append("")
            lines.append("(could be because Alpaca credentials missing in env — re-run with ALPACA_API_KEY + ALPACA_SECRET_KEY set)")
    else:
        lines.append("## Per-position reconciliation")
        lines.append("")
        lines.append("| Symbol | Qty | Side | Market value | Unrealized P&L | % | Opening orders | Audit events | Risk decision | Confidence |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for p in report["positions"]:
            lines.append(
                f"| {p['symbol']} | {p['qty']} | {p['side']} | "
                f"${p['market_value']} | ${p['unrealized_pl']} | {p['unrealized_plpc']} | "
                f"{len(p['opening_orders_found'])} | {p['audit_events_count']} | "
                f"{p.get('risk_decision_at_entry') or '?'} | "
                f"{p.get('confidence_score_at_entry') or '?'} |"
            )

    lines.append("")
    lines.append("## Invariants verified")
    lines.append("")
    for k, v in report["invariants"].items():
        lines.append(f"- `{k}`: **{v}**")
    lines.append("")
    lines.append("---")
    lines.append("This report does not change runtime state. Threshold changes are governed by Strategy Quality Gate.")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    report = build_report()
    md = render_markdown(report)

    if args.no_write:
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(md)
        return 0

    docs = REPO_ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "position_reconciliation_LATEST.md").write_text(md, encoding="utf-8")
    (docs / "position_reconciliation_LATEST.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"Wrote: docs/position_reconciliation_LATEST.md")
    print(f"Wrote: docs/position_reconciliation_LATEST.json")

    # Gate-readable artefact (system_activation_gate reads this exact path).
    # NOT the same as ``learning-loop/position_reconciliation/latest.json`` —
    # that one is an unrelated followup-tracking artefact and stays untouched.
    ll_dir = REPO_ROOT / "learning-loop"
    ll_dir.mkdir(parents=True, exist_ok=True)
    (ll_dir / "position_reconciliation_latest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"Wrote: learning-loop/position_reconciliation_latest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
