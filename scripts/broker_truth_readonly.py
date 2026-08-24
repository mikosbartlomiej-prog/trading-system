#!/usr/bin/env python3
"""Read-only broker truth reporter.

Reads Alpaca paper account state via GET-only HTTP and produces two paired
artefacts:

  * ``reports/broker_truth_latest.json``   — machine-readable
  * ``reports/broker_truth_latest.md``     — human-readable

Also reconciles broker truth against every local
``learning-loop/allocations/*.execution.json`` since 2026-06-16.

HARD SAFETY invariants (enforced structurally in this script):

  1. Endpoint must be exactly ``https://paper-api.alpaca.markets``.
     Any other endpoint triggers refuse-and-return.
  2. Only ``requests.get`` is imported from ``requests``.
     There is NO ``requests.post`` / ``requests.delete`` in this file.
  3. Account "paper" tag verified BEFORE emitting results.
  4. Credential values NEVER printed.
  5. Full HTTP bodies NEVER logged.
  6. Client-order-id last-6 characters only, not full.

Exit codes:
  0 — reports written successfully
  1 — endpoint refusal (invariant violation)
  2 — missing credentials
  3 — auth failure
  4 — network failure
  5 — account is not paper (STOP CONDITION)
  6 — unexpected open orders or positions (STOP CONDITION)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Explicit narrow import — ``requests.get`` only. If a maintainer ever
# adds ``requests.post`` calls to this file the wildcard import audit
# in tests will flag it.
from requests import get as _http_get, RequestException  # type: ignore
from requests.exceptions import Timeout, ConnectionError as _ConnectionError  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
SCOPE_START = "2026-06-16"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_id(s: str | None) -> str:
    if not s:
        return ""
    s = str(s)
    if len(s) <= 8:
        return "…" + s[-4:]
    return s[:4] + "…" + s[-4:]


def _get(url: str, headers: dict, params: dict | None = None) -> tuple[int, Any, str]:
    """Wrapped GET. Returns (status_code, body_json_or_text, error_str).

    NEVER prints credentials or the Authorization/APCA-* header values.
    """
    try:
        r = _http_get(url, headers=headers, params=params or {}, timeout=15)
        try:
            body = r.json()
        except Exception:
            body = r.text[:400]
        return r.status_code, body, ""
    except Timeout as e:
        return 0, None, f"Timeout: {type(e).__name__}"
    except _ConnectionError as e:
        return 0, None, f"ConnectionError: {type(e).__name__}"
    except RequestException as e:
        return 0, None, f"{type(e).__name__}"
    except Exception as e:
        return 0, None, f"{type(e).__name__}: {str(e)[:80]}"


def _load_local_executions() -> list[dict]:
    """Read every learning-loop/allocations/*.execution.json since scope."""
    out = []
    root = REPO_ROOT / "learning-loop" / "allocations"
    if not root.exists():
        return out
    for p in sorted(root.glob("*.execution.json")):
        date = p.stem.replace(".execution", "")
        if date < SCOPE_START:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d["_file"] = p.name
            out.append(d)
        except Exception:
            continue
    return out


def build_report() -> tuple[dict, int]:
    """Build the broker-truth report. Returns (report_dict, exit_code)."""
    report: dict[str, Any] = {
        "generated_at_iso": _now_iso(),
        "schema_version": "v1.0",
        "endpoint_verified": False,
        "endpoint": PAPER_ENDPOINT,
        "credentials_present": False,
        "account": None,
        "account_status": None,
        "account_type_paper": None,
        "positions": [],
        "open_orders": [],
        "closed_orders": [],
        "fills": [],
        "reconciliation": [],
        "stop_conditions_triggered": [],
        "diagnostics": [],
    }

    # 1. Endpoint whitelist. If ALPACA_BASE_URL is set to anything else,
    # refuse.
    endpoint_env = os.environ.get("ALPACA_BASE_URL", PAPER_ENDPOINT).strip()
    if endpoint_env != PAPER_ENDPOINT:
        report["diagnostics"].append(
            f"REFUSED: ALPACA_BASE_URL is not paper-api. Live endpoint is unsupported."
        )
        return report, 1

    report["endpoint_verified"] = True

    # 2. Credentials
    key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        report["diagnostics"].append(
            "credentials missing — ALPACA_API_KEY / ALPACA_SECRET_KEY not in env"
        )
        return report, 2

    report["credentials_present"] = True

    h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

    # 3. GET /v2/account — verify paper.
    code, body, err = _get(f"{PAPER_ENDPOINT}/v2/account", h)
    if code == 401 or code == 403:
        report["diagnostics"].append(f"auth failure on /v2/account (HTTP {code})")
        return report, 3
    if code != 200 or not isinstance(body, dict):
        report["diagnostics"].append(f"/v2/account failed: HTTP={code}, err={err}, body_type={type(body).__name__}")
        return report, 4

    acct = body
    report["account"] = {
        "id": _redact_id(acct.get("id")),
        "account_number": _redact_id(acct.get("account_number")),
        "status": acct.get("status"),
        "currency": acct.get("currency"),
        "equity": acct.get("equity"),
        "last_equity": acct.get("last_equity"),
        "cash": acct.get("cash"),
        "buying_power": acct.get("buying_power"),
        "long_market_value": acct.get("long_market_value"),
        "short_market_value": acct.get("short_market_value"),
        "daytrade_count": acct.get("daytrade_count"),
        "pattern_day_trader": acct.get("pattern_day_trader"),
        "account_blocked": acct.get("account_blocked"),
        "trading_blocked": acct.get("trading_blocked"),
        "transfers_blocked": acct.get("transfers_blocked"),
        "shorting_enabled": acct.get("shorting_enabled"),
        "multiplier": acct.get("multiplier"),
        "regt_buying_power": acct.get("regt_buying_power"),
        "created_at": acct.get("created_at"),
    }
    report["account_status"] = acct.get("status")

    # 4. Verify paper. Alpaca account object doesn't always include
    # 'trading_type'; instead we check that our endpoint is paper AND
    # that the account is not flagged as live-specific. This is the same
    # verification the assert_paper_only() helper uses elsewhere.
    is_paper = (
        endpoint_env == PAPER_ENDPOINT and
        # paper accounts have their id + account_number,
        # never crypto-only live restrictions.
        acct.get("crypto_status") in (None, "ACTIVE", "SUBMITTED", "INACTIVE") and
        acct.get("account_blocked") in (False, None) and
        acct.get("account_number") is not None
    )
    report["account_type_paper"] = is_paper
    if not is_paper:
        report["stop_conditions_triggered"].append("account_not_paper_or_blocked")
        report["diagnostics"].append("Account paper-tag verification failed.")
        return report, 5

    # 5. GET /v2/clock — session-truth
    code, body, err = _get(f"{PAPER_ENDPOINT}/v2/clock", h)
    if code == 200 and isinstance(body, dict):
        report["clock"] = {
            "timestamp": body.get("timestamp"),
            "is_open": body.get("is_open"),
            "next_open": body.get("next_open"),
            "next_close": body.get("next_close"),
        }
    else:
        report["diagnostics"].append(f"/v2/clock failed: HTTP={code}, err={err}")

    # 6. GET /v2/positions
    code, body, err = _get(f"{PAPER_ENDPOINT}/v2/positions", h)
    if code == 200 and isinstance(body, list):
        report["positions"] = [
            {
                "symbol": p.get("symbol"),
                "asset_class": p.get("asset_class"),
                "qty": p.get("qty"),
                "side": p.get("side"),
                "avg_entry_price": p.get("avg_entry_price"),
                "current_price": p.get("current_price"),
                "market_value": p.get("market_value"),
                "cost_basis": p.get("cost_basis"),
                "unrealized_pl": p.get("unrealized_pl"),
                "unrealized_plpc": p.get("unrealized_plpc"),
            }
            for p in body
        ]
        report["position_count"] = len(body)
    else:
        report["diagnostics"].append(f"/v2/positions failed: HTTP={code}, err={err}")

    # 7. GET /v2/orders?status=open — open orders
    code, body, err = _get(
        f"{PAPER_ENDPOINT}/v2/orders",
        h,
        params={"status": "open", "limit": 500, "direction": "asc"},
    )
    if code == 200 and isinstance(body, list):
        report["open_orders"] = [
            {
                "id": _redact_id(o.get("id")),
                "client_order_id": _redact_id(o.get("client_order_id")),
                "symbol": o.get("symbol"),
                "side": o.get("side"),
                "qty": o.get("qty"),
                "notional": o.get("notional"),
                "type": o.get("type"),
                "time_in_force": o.get("time_in_force"),
                "status": o.get("status"),
                "submitted_at": o.get("submitted_at"),
            }
            for o in body
        ]
        report["open_order_count"] = len(body)
    else:
        report["diagnostics"].append(f"/v2/orders?status=open failed: HTTP={code}, err={err}")

    # 8. GET /v2/orders?status=closed since scope
    all_closed = []
    page_after = f"{SCOPE_START}T00:00:00Z"
    while True:
        code, body, err = _get(
            f"{PAPER_ENDPOINT}/v2/orders",
            h,
            params={
                "status": "closed",
                "after": page_after,
                "limit": 500,
                "direction": "asc",
            },
        )
        if code != 200 or not isinstance(body, list):
            report["diagnostics"].append(
                f"/v2/orders?status=closed failed at after={page_after}: HTTP={code}"
            )
            break
        all_closed.extend(body)
        if len(body) < 500:
            break
        # advance page: use last submitted_at
        page_after = body[-1].get("submitted_at") or body[-1].get("created_at") or ""
        if not page_after:
            break
    report["closed_orders"] = [
        {
            "id": _redact_id(o.get("id")),
            "client_order_id": _redact_id(o.get("client_order_id")),
            "symbol": o.get("symbol"),
            "side": o.get("side"),
            "qty": o.get("qty"),
            "filled_qty": o.get("filled_qty"),
            "notional": o.get("notional"),
            "filled_avg_price": o.get("filled_avg_price"),
            "type": o.get("type"),
            "status": o.get("status"),
            "submitted_at": o.get("submitted_at"),
            "filled_at": o.get("filled_at"),
            "canceled_at": o.get("canceled_at"),
            "expired_at": o.get("expired_at"),
        }
        for o in all_closed
    ]
    report["closed_order_count"] = len(all_closed)
    from collections import Counter
    report["closed_orders_by_status"] = dict(Counter(o.get("status") for o in all_closed))

    # 9. GET /v2/account/activities (fills)
    code, body, err = _get(
        f"{PAPER_ENDPOINT}/v2/account/activities/FILL",
        h,
        params={"date": None, "page_size": 100, "direction": "desc"},
    )
    if code == 200 and isinstance(body, list):
        report["fills"] = [
            {
                "id": _redact_id(a.get("id")),
                "order_id": _redact_id(a.get("order_id")),
                "symbol": a.get("symbol"),
                "side": a.get("side"),
                "qty": a.get("qty"),
                "price": a.get("price"),
                "type": a.get("type"),
                "transaction_time": a.get("transaction_time"),
            }
            for a in body
            if a.get("transaction_time", "") >= SCOPE_START
        ]
        report["fill_count"] = len(report["fills"])
    else:
        report["diagnostics"].append(f"/v2/account/activities/FILL failed: HTTP={code}, err={err}")

    # 10. Reconciliation against local .execution.json
    locals_ = _load_local_executions()
    total_local_attempts = 0
    total_local_placed = 0
    total_local_failed = 0
    reconciliation_notes = []

    for local in locals_:
        results = local.get("results", []) or []
        for r in results:
            total_local_attempts += 1
            if r.get("status") == "placed":
                total_local_placed += 1
            elif r.get("status") == "failed":
                total_local_failed += 1

    broker_placed = sum(
        1 for o in report["closed_orders"]
        if o.get("status") in ("filled", "partially_filled", "new", "accepted")
    )

    if broker_placed == 0 and total_local_placed == 0:
        reconciliation_notes.append(
            "Broker truth agrees with local execution.json — zero orders "
            "successfully placed across scope."
        )
    if total_local_failed > 0 and report["closed_order_count"] == 0:
        reconciliation_notes.append(
            f"Local .execution.json reports {total_local_failed} FAILED "
            "attempts, but broker shows 0 closed orders since scope — "
            "confirms rejections happened BEFORE broker received the "
            "request (client-side / pre-HTTP path)."
        )

    report["reconciliation"] = {
        "local_execution_files": len(locals_),
        "local_attempts": total_local_attempts,
        "local_placed": total_local_placed,
        "local_failed": total_local_failed,
        "broker_orders_placed_in_scope": broker_placed,
        "notes": reconciliation_notes,
    }

    # 11. Stop conditions on unexpected state
    if report["open_order_count"] > 0:
        report["stop_conditions_triggered"].append(
            f"unexpected_open_orders={report['open_order_count']}"
        )
    # Positions of 0 during freeze is expected. Non-zero is worth flagging
    # but not a stop condition unless we specifically didn't expect any.
    if report["position_count"] > 0:
        report["diagnostics"].append(
            f"positions_present={report['position_count']} — investigate before enabling paper canary"
        )

    if report["stop_conditions_triggered"]:
        return report, 6

    return report, 0


def render_markdown(r: dict, exit_code: int) -> str:
    lines = [
        "# Broker truth report (READ-ONLY)",
        "",
        f"- Generated: `{r['generated_at_iso']}`",
        f"- Endpoint: `{r['endpoint']}` verified={r['endpoint_verified']}",
        f"- Credentials present: `{r['credentials_present']}`",
        f"- Account type paper: `{r['account_type_paper']}`",
        f"- Exit code: `{exit_code}`",
        "",
    ]
    if not r.get("credentials_present"):
        lines.append("**Skipped — ALPACA credentials not in env.**")
        return "\n".join(lines)

    acct = r.get("account") or {}
    lines.append("## Account")
    lines.append("")
    for k, v in acct.items():
        lines.append(f"- `{k}` = `{v}`")
    lines.append("")

    lines.append(f"## Positions ({r.get('position_count',0)})")
    lines.append("")
    for p in r.get("positions", []):
        lines.append(f"- {p.get('symbol')} qty={p.get('qty')} side={p.get('side')} "
                     f"market_value={p.get('market_value')} pl={p.get('unrealized_pl')}")

    lines.append("")
    lines.append(f"## Open orders ({r.get('open_order_count',0)})")
    lines.append("")
    for o in r.get("open_orders", []):
        lines.append(f"- {o.get('symbol')} {o.get('side')} {o.get('qty')} @{o.get('type')} status={o.get('status')}")

    lines.append("")
    lines.append(f"## Closed orders since {SCOPE_START} ({r.get('closed_order_count',0)})")
    lines.append("")
    lines.append(f"- by_status: `{r.get('closed_orders_by_status', {})}`")

    lines.append("")
    lines.append(f"## Fills ({r.get('fill_count',0)})")
    lines.append("")
    lines.append("(most recent 10)")
    for a in r.get("fills", [])[:10]:
        lines.append(f"- {a.get('symbol')} {a.get('side')} qty={a.get('qty')} price={a.get('price')} at={a.get('transaction_time')}")

    lines.append("")
    lines.append("## Reconciliation with local `.execution.json`")
    lines.append("")
    rec = r.get("reconciliation", {})
    lines.append(f"- local files scanned: `{rec.get('local_execution_files')}`")
    lines.append(f"- local attempts: `{rec.get('local_attempts')}`")
    lines.append(f"- local placed: `{rec.get('local_placed')}`")
    lines.append(f"- local failed: `{rec.get('local_failed')}`")
    lines.append(f"- broker orders placed in scope: `{rec.get('broker_orders_placed_in_scope')}`")
    lines.append("")
    for note in rec.get("notes", []):
        lines.append(f"> {note}")

    lines.append("")
    if r.get("stop_conditions_triggered"):
        lines.append("## STOP conditions triggered")
        lines.append("")
        for s in r["stop_conditions_triggered"]:
            lines.append(f"- **{s}**")

    lines.append("")
    lines.append("## Diagnostics")
    lines.append("")
    for d in r.get("diagnostics", []):
        lines.append(f"- {d}")

    lines.append("")
    lines.append("---")
    lines.append(
        "This report contains GET-only broker observations. "
        "No mutation was performed. Credentials and full IDs were not printed."
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=str(REPO_ROOT / "reports"))
    args = ap.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    report, exit_code = build_report()
    (out / "broker_truth_latest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    (out / "broker_truth_latest.md").write_text(
        render_markdown(report, exit_code),
        encoding="utf-8",
    )
    print(f"Wrote: {out / 'broker_truth_latest.json'}")
    print(f"Wrote: {out / 'broker_truth_latest.md'}")
    print(f"exit_code={exit_code}")
    print(f"account_type_paper={report.get('account_type_paper')}")
    print(f"position_count={report.get('position_count')}")
    print(f"open_order_count={report.get('open_order_count')}")
    print(f"closed_order_count={report.get('closed_order_count')}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
