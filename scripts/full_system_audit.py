#!/usr/bin/env python3
"""Full system forensic audit — 2026-06-16 through today.

Read-only aggregator that walks all local artefacts and produces two
paired outputs:

  - reports/full_system_audit_<today>.json  (machine-readable)
  - reports/full_system_audit_<today>.md    (human-readable)

Scope (per operator request):
  * git log since 2026-06-16
  * .github/workflows/*.yml
  * briefs/*.md, docs/*LATEST*, docs/*STATUS*, docs/*REVIEW*
  * journal/autonomy/*.jsonl
  * learning-loop/allocations/*.{json,execution.json,log}
  * learning-loop/opportunity_ledger/*.jsonl
  * learning-loop/shadow_evidence/**
  * learning-loop/llm_advisory/**
  * learning-loop/runtime_state.json
  * safe_mode + broker_repair state
  * incident reports + repair markers
  * strategy, risk, confidence, reconciliation, monitor artefacts

Read-only Alpaca verification is OPTIONAL — runs only if the local env
carries ALPACA_API_KEY + ALPACA_SECRET_KEY. The script uses the paper
endpoint exclusively (invariant asserted) and issues only GET requests.
It never prints credentials.

HARD SAFETY:
  - no POST/PATCH/PUT/DELETE broker calls
  - no file mutation outside reports/
  - no secret values in output
  - refuses to run if a live endpoint is somehow configured
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
SCOPE_START_DATE = "2026-06-16"
PAPER_ENDPOINT = "https://paper-api.alpaca.markets"


# ── helpers ────────────────────────────────────────────────────────────────

def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _list_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return rows


def _date_from_filename(name: str) -> str:
    # e.g. "2026-06-17.execution.json" → "2026-06-17"
    base = name.rsplit(".execution", 1)[0].rsplit(".json", 1)[0]
    base = base.rsplit(".jsonl", 1)[0]
    return base


def _in_scope(iso_or_name: str) -> bool:
    """True if the timestamp/name is on or after SCOPE_START_DATE."""
    try:
        first10 = iso_or_name[:10]
        return first10 >= SCOPE_START_DATE
    except Exception:
        return False


def _redact(s: str) -> str:
    """Redact any accidental long-hex tokens (belt & suspenders)."""
    if not isinstance(s, str):
        return str(s)
    if len(s) >= 32 and s.replace("_", "").replace("-", "").isalnum():
        return s[:6] + "…REDACTED…" + s[-4:]
    return s


# ── audit sections ────────────────────────────────────────────────────────

def audit_git(scope: dict) -> dict:
    """git commits since SCOPE_START_DATE."""
    try:
        r = subprocess.run(
            ["git", "log", f"--since={SCOPE_START_DATE}", "--format=%H|%at|%s"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=30,
        )
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        commits = []
        for l in lines:
            parts = l.split("|", 2)
            if len(parts) == 3:
                sha, ts, subj = parts
                commits.append({"sha": sha, "ts_utc": int(ts), "subject": subj})
        # count by-author + by-day
        by_day: Counter = Counter()
        for c in commits:
            d = datetime.fromtimestamp(c["ts_utc"], tz=timezone.utc).date().isoformat()
            by_day[d] += 1
        return {
            "scope_start": SCOPE_START_DATE,
            "total_commits": len(commits),
            "commits_by_day": dict(sorted(by_day.items())),
            "head": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip(),
            "origin_main": subprocess.run(
                ["git", "rev-parse", "origin/main"],
                capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip(),
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def audit_workflows(scope: dict) -> dict:
    """List .github/workflows and pull last-run summary via gh (if available)."""
    wf_dir = REPO_ROOT / ".github" / "workflows"
    files = sorted(f.name for f in wf_dir.glob("*.yml"))
    out: dict[str, Any] = {"workflow_count": len(files), "workflows": files}

    # Try gh for latest run status per workflow.
    try:
        r = subprocess.run(
            ["gh", "run", "list", "--branch", "main", "--limit", "200",
             "--json", "name,status,conclusion,event,createdAt,databaseId,headSha"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=45,
        )
        if r.returncode == 0:
            runs = json.loads(r.stdout or "[]")
            in_scope = [r for r in runs if _in_scope(r.get("createdAt", ""))]
            by_wf: dict[str, list[dict]] = defaultdict(list)
            for run in in_scope:
                by_wf[run.get("name", "?")].append(run)

            wf_health: dict[str, dict] = {}
            for wf_name, wf_runs in by_wf.items():
                conclusions = Counter(r.get("conclusion") for r in wf_runs)
                wf_health[wf_name] = {
                    "runs_in_scope": len(wf_runs),
                    "conclusions": dict(conclusions),
                    "last_run_at": max((r.get("createdAt", "") for r in wf_runs), default=""),
                    "last_conclusion": sorted(
                        wf_runs, key=lambda r: r.get("createdAt", "")
                    )[-1].get("conclusion") if wf_runs else None,
                }
            out["workflow_run_health"] = wf_health
            # Failed runs
            failed = [
                {"name": r.get("name"), "id": r.get("databaseId"),
                 "createdAt": r.get("createdAt"), "conclusion": r.get("conclusion")}
                for r in in_scope
                if r.get("conclusion") in ("failure", "cancelled", "startup_failure")
            ]
            out["failed_runs_in_scope"] = failed[:100]
            out["failed_runs_count"] = len(failed)
        else:
            out["gh_error"] = r.stderr[:200]
    except Exception as e:
        out["gh_error"] = f"{type(e).__name__}: {e}"

    return out


def audit_allocations(scope: dict) -> dict:
    """Walk learning-loop/allocations/ for plans + execution results."""
    plans = sorted(glob.glob(str(REPO_ROOT / "learning-loop" / "allocations" / "*.json")))
    plans = [p for p in plans if not p.endswith(".execution.json")]
    plans = [p for p in plans if _in_scope(_date_from_filename(Path(p).name))]

    execs = sorted(glob.glob(str(REPO_ROOT / "learning-loop" / "allocations" / "*.execution.json")))
    execs = [e for e in execs if _in_scope(_date_from_filename(Path(e).name))]

    logs = sorted(glob.glob(str(REPO_ROOT / "learning-loop" / "allocations" / "*.log")))
    logs = [l for l in logs if _in_scope(_date_from_filename(Path(l).name))]

    per_day: dict[str, dict] = {}
    total_planned_notional = 0.0
    total_placed = 0
    total_skipped = 0
    total_failed = 0
    rejection_categories: Counter = Counter()
    plan_dates = set()

    for p in plans:
        date = _date_from_filename(Path(p).name)
        plan_dates.add(date)
        d = _read_json(Path(p), default={}) or {}
        rebalance = d.get("rebalance_orders", []) or []
        planned = sum(
            abs(float(r.get("target_value", 0) or 0))
            for r in rebalance
            if r.get("action") in ("BUY", "REDUCE", "EXIT")
        )
        total_planned_notional += planned
        per_day.setdefault(date, {})["plan"] = {
            "generated_at": d.get("generated_at"),
            "regime": d.get("market_regime"),
            "allowed_buckets": d.get("allowed_buckets"),
            "n_rebalance_orders": len(rebalance),
            "planned_notional_abs": planned,
            "auto_execute": d.get("config", {}).get("auto_execute"),
            "target_invested_ratio": d.get("config", {}).get("target_invested_ratio"),
            "account_equity": d.get("account_equity"),
            "cash": d.get("cash"),
            "buying_power": d.get("buying_power"),
        }

    for e in execs:
        date = _date_from_filename(Path(e).name).rsplit(".execution", 1)[0]
        d = _read_json(Path(e), default={}) or {}
        results = d.get("results", []) or []
        placed = sum(1 for r in results if r.get("status") == "placed")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        failed = sum(1 for r in results if r.get("status") == "failed")
        for r in results:
            if r.get("status") == "failed":
                rejection_categories[r.get("rejection_category", "UNKNOWN")] += 1
        total_placed += placed
        total_skipped += skipped
        total_failed += failed
        per_day.setdefault(date, {})["execution"] = {
            "executed_at": d.get("executed_at"),
            "n_placed": placed,
            "n_skipped": skipped,
            "n_failed": failed,
            "failure_samples": [
                {
                    "symbol": r.get("symbol"),
                    "action": r.get("action"),
                    "rejection_category": r.get("rejection_category"),
                    "http_status": r.get("http_status"),
                    "alpaca_message": r.get("alpaca_message"),
                    "order_notional": r.get("order_notional"),
                }
                for r in results
                if r.get("status") == "failed"
            ][:5],
            "skip_reasons": Counter(
                r.get("reason", "")
                for r in results
                if r.get("status") == "skipped"
            ),
        }

    return {
        "plans_found": len(plans),
        "executions_found": len(execs),
        "logs_found": len(logs),
        "total_planned_notional_abs": total_planned_notional,
        "orders": {
            "total_placed": total_placed,
            "total_skipped": total_skipped,
            "total_failed": total_failed,
        },
        "rejection_categories": dict(rejection_categories),
        "per_day": per_day,
    }


def audit_briefs_and_docs(scope: dict) -> dict:
    """Inventory briefs/*.md + docs/*LATEST* + docs/*STATUS* + docs/*REVIEW*."""
    briefs = sorted(glob.glob(str(REPO_ROOT / "briefs" / "*.md")))
    briefs = [b for b in briefs if _in_scope(_date_from_filename(Path(b).name))]

    docs_dir = REPO_ROOT / "docs"
    latest = sorted(f.name for f in docs_dir.glob("*LATEST*"))
    status = sorted(f.name for f in docs_dir.glob("*STATUS*"))
    review = sorted(f.name for f in docs_dir.glob("*REVIEW*"))

    # For each docs/*.json, check for a top-level 'generated_at_iso' or 'ts_iso'
    # to compute freshness.
    now = datetime.now(timezone.utc)
    doc_freshness: list[dict] = []
    for f in docs_dir.glob("*.json"):
        d = _read_json(f, default={}) or {}
        ts = d.get("generated_at_iso") or d.get("evaluated_at_iso") or d.get("ts_iso")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            age_hours = (now - dt).total_seconds() / 3600.0 if dt else None
        except Exception:
            age_hours = None
        doc_freshness.append({"file": f.name, "ts_iso": ts, "age_hours": age_hours})

    stale_docs = [d for d in doc_freshness
                  if d["age_hours"] is not None and d["age_hours"] > 48]

    return {
        "briefs_count_in_scope": len(briefs),
        "latest_docs": latest,
        "status_docs": status,
        "review_docs": review,
        "doc_freshness_all": sorted(doc_freshness, key=lambda x: x.get("file", "")),
        "stale_docs_over_48h": stale_docs,
    }


def audit_autonomy_journal(scope: dict) -> dict:
    """Walk journal/autonomy/*.jsonl since SCOPE_START_DATE."""
    files = sorted(glob.glob(str(REPO_ROOT / "journal" / "autonomy" / "*.jsonl")))
    files = [f for f in files if _in_scope(_date_from_filename(Path(f).name))]

    per_day: dict[str, Counter] = {}
    all_decision_types: Counter = Counter()
    events_by_actor: Counter = Counter()
    close_position_failed = 0
    safe_mode_events = 0
    broker_repair_events = 0

    for f in files:
        date = _date_from_filename(Path(f).name)
        rows = _list_jsonl(Path(f))
        c: Counter = Counter()
        for r in rows:
            dt = r.get("decision_type", "unknown")
            all_decision_types[dt] += 1
            c[dt] += 1
            actor = r.get("actor", "unknown")
            events_by_actor[actor] += 1
            if dt == "CLOSE_POSITION" and r.get("decision") == "FAILED":
                close_position_failed += 1
            if "SAFE_MODE" in dt:
                safe_mode_events += 1
            if "REPAIR" in dt or "BROKER_REPAIR" in dt:
                broker_repair_events += 1
        per_day[date] = dict(c)

    return {
        "files_scanned": len(files),
        "total_decision_types": dict(all_decision_types.most_common(30)),
        "close_position_failed_count": close_position_failed,
        "safe_mode_events_count": safe_mode_events,
        "broker_repair_events_count": broker_repair_events,
        "events_by_actor_top20": dict(events_by_actor.most_common(20)),
        "per_day_decision_type_counts": per_day,
    }


def audit_opportunity_ledger(scope: dict) -> dict:
    """Walk learning-loop/opportunity_ledger/*.jsonl."""
    files = sorted(glob.glob(str(REPO_ROOT / "learning-loop" / "opportunity_ledger" / "*.jsonl")))
    files = [f for f in files if _in_scope(_date_from_filename(Path(f).name))]

    per_day: dict[str, int] = {}
    entry_capable_count = 0
    strategies: Counter = Counter()
    for f in files:
        date = _date_from_filename(Path(f).name)
        rows = _list_jsonl(Path(f))
        per_day[date] = len(rows)
        for r in rows:
            if r.get("entry_capable"):
                entry_capable_count += 1
            strategies[r.get("strategy", "unknown")] += 1

    return {
        "files_scanned": len(files),
        "total_rows": sum(per_day.values()),
        "entry_capable_rows": entry_capable_count,
        "strategies_top10": dict(strategies.most_common(10)),
        "per_day_row_count": per_day,
    }


def audit_shadow_evidence(scope: dict) -> dict:
    """Walk learning-loop/shadow_evidence/**."""
    root = REPO_ROOT / "learning-loop" / "shadow_evidence"
    if not root.exists():
        return {"missing": True}
    files = sorted(str(p) for p in root.rglob("*"))
    file_types: Counter = Counter()
    jsonl_row_counts = 0
    obs_records = 0

    for f in files:
        p = Path(f)
        if p.is_dir():
            continue
        ext = p.suffix
        file_types[ext] += 1
        if ext == ".jsonl":
            rows = _list_jsonl(p)
            jsonl_row_counts += len(rows)
            obs_records += sum(1 for r in rows if r.get("type") == "observation")

    latest = _read_json(root / "acceleration_latest.json", default={}) or {}
    outcomes_dir = root / "outcomes"
    outcome_files = sorted(outcomes_dir.glob("*.jsonl")) if outcomes_dir.exists() else []
    outcome_rows = sum(len(_list_jsonl(p)) for p in outcome_files)

    return {
        "root_exists": True,
        "file_count": sum(1 for f in files if Path(f).is_file()),
        "file_type_counts": dict(file_types),
        "jsonl_total_rows": jsonl_row_counts,
        "observation_row_count": obs_records,
        "acceleration_latest_top_fields": {
            k: latest.get(k) for k in ("generated_at_iso", "verdict", "status",
                                       "signals_seen", "opportunities_recorded",
                                       "shadow_fills", "shadow_outcomes")
        },
        "outcomes_files": len(outcome_files),
        "outcomes_row_count": outcome_rows,
    }


def audit_llm_advisory(scope: dict) -> dict:
    """Walk learning-loop/llm_advisory/**."""
    root = REPO_ROOT / "learning-loop" / "llm_advisory"
    if not root.exists():
        return {"missing": True}
    role_files = sorted(root.glob("*_latest.json"))
    roles: list[dict] = []
    for f in role_files:
        d = _read_json(f, default={}) or {}
        roles.append({
            "role": f.stem.replace("_latest", ""),
            "generated_at": d.get("generated_at_iso") or d.get("ts_iso"),
            "recommendation": d.get("recommendation") or d.get("verdict"),
            "authority": d.get("authority"),
            "confidence": d.get("confidence"),
        })
    provider = _read_json(root / "provider_activation_latest.json", default={}) or {}
    return {
        "role_files_found": len(role_files),
        "roles": roles,
        "provider_status": {
            "verdict": provider.get("verdict"),
            "gemini_key_present": provider.get("gemini_api_key_present"),
            "smoke_test_executed": provider.get("smoke_test_executed"),
            "dry_run": provider.get("dry_run"),
        },
    }


def audit_state_files(scope: dict) -> dict:
    """Runtime + safe_mode + broker_repair state."""
    files_of_interest = [
        "learning-loop/runtime_state.json",
        "learning-loop/safe_mode_state.json",
        "learning-loop/safe_mode_consistency_latest.json",
        "learning-loop/broker_repair_required_latest.json",
        "learning-loop/system_activation_status_latest.json",
        "learning-loop/position_reconciliation_latest.json",
        "learning-loop/operator_clearance_readiness_latest.json",
        "learning-loop/post_repair_activation_path_latest.json",
    ]
    out: dict[str, Any] = {}
    now = datetime.now(timezone.utc)
    for rel in files_of_interest:
        p = REPO_ROOT / rel
        d = _read_json(p, default=None)
        if d is None:
            out[rel] = {"missing_or_unreadable": True}
            continue
        ts = None
        for key in ("generated_at_iso", "evaluated_at_iso", "updated_at",
                    "last_transition_iso", "ts_iso"):
            if key in d:
                ts = d[key]
                break
        # cheap age
        age_hours = None
        if ts:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                age_hours = (now - dt).total_seconds() / 3600.0
            except Exception:
                pass
        # extract key top-level fields
        key_fields = {}
        for k in ("verdict", "master_decision", "master_blockers", "flags",
                  "entries", "active", "runtime_active"):
            if k in d:
                key_fields[k] = d[k]
        out[rel] = {
            "ts": ts,
            "age_hours": age_hours,
            "key_fields": key_fields,
        }
    return out


def audit_alpaca_read_only(scope: dict) -> dict:
    """OPTIONAL: GET account/positions/orders from paper Alpaca.

    Runs ONLY if ALPACA_API_KEY + ALPACA_SECRET_KEY are in env.
    Refuses if paper endpoint is not paper-api.alpaca.markets.
    NEVER prints credentials.
    """
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        return {
            "attempted": False,
            "reason": "ALPACA_API_KEY/ALPACA_SECRET_KEY not in local env — "
                      "Alpaca GET verification skipped. Truth-of-record for "
                      "broker state is CI, which has the secret.",
        }
    endpoint = os.environ.get("ALPACA_BASE_URL", PAPER_ENDPOINT).strip()
    if endpoint != PAPER_ENDPOINT:
        return {
            "attempted": False,
            "reason": (f"ALPACA_BASE_URL is {_redact(endpoint)} not paper-api. "
                       "Refusing to call — invariant violation."),
        }

    try:
        import requests  # type: ignore
    except ImportError:
        return {"attempted": False, "reason": "requests library not available"}

    h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    out: dict[str, Any] = {"attempted": True, "endpoint": PAPER_ENDPOINT}
    try:
        # /v2/account
        r = requests.get(f"{PAPER_ENDPOINT}/v2/account", headers=h, timeout=10)
        r.raise_for_status()
        acct = r.json()
        out["account"] = {
            "id": acct.get("id"),
            "account_number": acct.get("account_number"),
            "status": acct.get("status"),
            "equity": acct.get("equity"),
            "cash": acct.get("cash"),
            "buying_power": acct.get("buying_power"),
            "daytrade_count": acct.get("daytrade_count"),
            "pattern_day_trader": acct.get("pattern_day_trader"),
            "trading_blocked": acct.get("trading_blocked"),
            "account_blocked": acct.get("account_blocked"),
        }

        # /v2/positions
        r = requests.get(f"{PAPER_ENDPOINT}/v2/positions", headers=h, timeout=10)
        r.raise_for_status()
        pos = r.json()
        out["positions_count"] = len(pos)
        out["positions_snapshot"] = [
            {"symbol": p.get("symbol"), "qty": p.get("qty"),
             "market_value": p.get("market_value"),
             "unrealized_pl": p.get("unrealized_pl")}
            for p in pos
        ]

        # /v2/orders?status=all&after=SCOPE_START_DATE
        r = requests.get(
            f"{PAPER_ENDPOINT}/v2/orders",
            headers=h,
            params={"status": "all", "after": f"{SCOPE_START_DATE}T00:00:00Z",
                    "limit": 500, "direction": "asc"},
            timeout=15,
        )
        r.raise_for_status()
        orders = r.json()
        out["orders_since_scope"] = len(orders)
        out["orders_by_status"] = dict(Counter(o.get("status") for o in orders))
        # never print client_order_id if it might leak sensitive info; kept for
        # cross-check only
        out["orders_first10_sample"] = [
            {"symbol": o.get("symbol"), "side": o.get("side"),
             "qty": o.get("qty"), "notional": o.get("notional"),
             "status": o.get("status"), "submitted_at": o.get("submitted_at"),
             "filled_at": o.get("filled_at")}
            for o in orders[:10]
        ]
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:200]}"

    return out


# ── render ─────────────────────────────────────────────────────────────────

def render_markdown(report: dict) -> str:
    lines = [
        "# Full System Forensic Audit",
        "",
        f"- Scope: {SCOPE_START_DATE} → {report['as_of_iso'][:10]}",
        f"- Generated at: `{report['as_of_iso']}`",
        "- Read-only. No broker mutations. No secret values printed.",
        "",
        "## Summary",
        "",
    ]

    git = report.get("git", {})
    lines.append(f"- Git commits since {SCOPE_START_DATE}: **{git.get('total_commits','?')}**")
    lines.append(f"- HEAD `{git.get('head','?')[:12]}` vs origin/main `{git.get('origin_main','?')[:12]}`")

    wf = report.get("workflows", {})
    lines.append(f"- Workflows on disk: **{wf.get('workflow_count','?')}**")
    lines.append(f"- Failed workflow runs in scope: **{wf.get('failed_runs_count','?')}**")

    alloc = report.get("allocations", {})
    orders = alloc.get("orders", {})
    lines.append(f"- Allocation plans generated: **{alloc.get('plans_found', 0)}**")
    lines.append(f"- Execution records: **{alloc.get('executions_found', 0)}**")
    lines.append(f"- **Total orders placed: {orders.get('total_placed',0)}**")
    lines.append(f"- **Total orders skipped: {orders.get('total_skipped',0)}**")
    lines.append(f"- **Total orders failed: {orders.get('total_failed',0)}**")
    lines.append(f"- Rejection categories: `{alloc.get('rejection_categories', {})}`")

    jrnl = report.get("autonomy_journal", {})
    lines.append(f"- Autonomy journal files scanned: **{jrnl.get('files_scanned',0)}**")
    lines.append(f"- CLOSE_POSITION FAILED events: **{jrnl.get('close_position_failed_count',0)}**")
    lines.append(f"- SAFE_MODE events: **{jrnl.get('safe_mode_events_count',0)}**")
    lines.append(f"- BROKER_REPAIR events: **{jrnl.get('broker_repair_events_count',0)}**")

    opp = report.get("opportunity_ledger", {})
    lines.append(f"- Opportunity ledger files: **{opp.get('files_scanned',0)}**, rows: **{opp.get('total_rows',0)}**, entry-capable: **{opp.get('entry_capable_rows',0)}**")

    shd = report.get("shadow_evidence", {})
    lines.append(f"- Shadow evidence root: {'yes' if shd.get('root_exists') else 'MISSING'}, "
                 f"jsonl rows: **{shd.get('jsonl_total_rows',0)}**, "
                 f"observations: **{shd.get('observation_row_count',0)}**")

    llm = report.get("llm_advisory", {})
    lines.append(f"- LLM advisory role files: **{llm.get('role_files_found',0)}**")

    alp = report.get("alpaca_read_only", {})
    if alp.get("attempted"):
        acct = alp.get("account", {})
        lines.append("")
        lines.append("### Read-only Alpaca (paper)")
        lines.append(f"- account status: `{acct.get('status')}` "
                     f"trading_blocked=`{acct.get('trading_blocked')}` "
                     f"account_blocked=`{acct.get('account_blocked')}`")
        lines.append(f"- equity=`{acct.get('equity')}` cash=`{acct.get('cash')}` bp=`{acct.get('buying_power')}`")
        lines.append(f"- positions: `{alp.get('positions_count')}`")
        lines.append(f"- orders since scope: `{alp.get('orders_since_scope')}` "
                     f"by_status=`{alp.get('orders_by_status')}`")
    else:
        lines.append(f"- Alpaca GET verification NOT ATTEMPTED — {alp.get('reason','')[:120]}")

    lines.append("")
    lines.append("## Per-day allocation outcomes")
    lines.append("")
    lines.append("| Date | Plan | Notional | Placed | Skipped | Failed | Rejection categories |")
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for date, pd_info in sorted(alloc.get("per_day", {}).items()):
        plan = pd_info.get("plan", {})
        exec_ = pd_info.get("execution", {})
        rej_cats = Counter(
            f.get("rejection_category")
            for f in exec_.get("failure_samples", [])
        )
        lines.append(f"| {date} | {plan.get('n_rebalance_orders','?')} | "
                     f"{plan.get('planned_notional_abs',0):.0f} | "
                     f"{exec_.get('n_placed','—')} | "
                     f"{exec_.get('n_skipped','—')} | "
                     f"{exec_.get('n_failed','—')} | "
                     f"`{dict(rej_cats)}` |")

    lines.append("")
    lines.append("## Workflow health (in scope)")
    lines.append("")
    for wf_name, hlth in sorted(wf.get("workflow_run_health", {}).items()):
        lines.append(f"- **{wf_name}**: {hlth.get('runs_in_scope','?')} runs, "
                     f"last=`{hlth.get('last_conclusion')}`, "
                     f"conclusions=`{hlth.get('conclusions')}`")

    lines.append("")
    lines.append("## Critical discrepancies observed")
    lines.append("")
    # Auto-flagged contradictions
    disc: list[str] = []
    if orders.get("total_failed", 0) > 0 and "UNKNOWN_BROKER_REJECTION" in alloc.get("rejection_categories", {}):
        disc.append(
            f"**Execution contradiction**: {orders['total_failed']} orders failed "
            f"with `UNKNOWN_BROKER_REJECTION` (no HTTP status, no Alpaca message) — "
            f"suggests rejection happens BEFORE the HTTP call reaches Alpaca, "
            f"but dashboard reports TRADING_EXECUTION_ON=false."
        )
    if orders.get("total_placed", 0) == 0 and (
        orders.get("total_failed", 0) + orders.get("total_skipped", 0) > 0
    ):
        disc.append(
            "**Zero orders placed since scope start** — "
            "either the mode is functionally OFF or every attempt has been rejected."
        )
    state_ = report.get("state", {})
    brs = state_.get("learning-loop/broker_repair_required_latest.json", {})
    if brs.get("key_fields", {}).get("entries"):
        entries_data = brs.get("key_fields", {}).get("entries")
        if entries_data and isinstance(entries_data, dict):
            disc.append(f"**broker_repair_required has entries: {list(entries_data.keys())}** — deterministic gate blocking.")
    if disc:
        for d in disc:
            lines.append(f"- {d}")
    else:
        lines.append("- (none auto-detected — see per-day + workflow sections)")

    lines.append("")
    lines.append("---")
    lines.append("This report is read-only. It does not mutate state, place orders, or print secrets.")
    return "\n".join(lines)


# ── main ───────────────────────────────────────────────────────────────────

def build_report() -> dict:
    scope: dict = {"start_date": SCOPE_START_DATE}
    report = {
        "as_of_iso": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "git": audit_git(scope),
        "workflows": audit_workflows(scope),
        "allocations": audit_allocations(scope),
        "briefs_and_docs": audit_briefs_and_docs(scope),
        "autonomy_journal": audit_autonomy_journal(scope),
        "opportunity_ledger": audit_opportunity_ledger(scope),
        "shadow_evidence": audit_shadow_evidence(scope),
        "llm_advisory": audit_llm_advisory(scope),
        "state": audit_state_files(scope),
        "alpaca_read_only": audit_alpaca_read_only(scope),
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=str(REPO_ROOT / "reports"))
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    report = build_report()
    today = datetime.now(timezone.utc).date().isoformat()

    json_path = out_dir / f"full_system_audit_{today}.json"
    md_path = out_dir / f"full_system_audit_{today}.md"

    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"Wrote: {json_path}")

    if not args.json_only:
        md_path.write_text(render_markdown(report), encoding="utf-8")
        print(f"Wrote: {md_path}")

    # brief operator summary
    print()
    print("=" * 60)
    print(f"SCOPE: {SCOPE_START_DATE} → {today}")
    print(f"Git commits in scope:    {report['git'].get('total_commits')}")
    alloc = report["allocations"]
    print(f"Alloc plans:             {alloc['plans_found']}")
    print(f"Alloc executions:        {alloc['executions_found']}")
    print(f"Orders placed:           {alloc['orders']['total_placed']}")
    print(f"Orders skipped:          {alloc['orders']['total_skipped']}")
    print(f"Orders failed:           {alloc['orders']['total_failed']}")
    print(f"Rejection categories:    {alloc['rejection_categories']}")
    wf = report["workflows"]
    print(f"Failed workflow runs:    {wf.get('failed_runs_count')}")
    alp = report["alpaca_read_only"]
    print(f"Alpaca GET attempted:    {alp.get('attempted')}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
