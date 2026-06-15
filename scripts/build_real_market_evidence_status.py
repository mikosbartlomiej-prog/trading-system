#!/usr/bin/env python3
"""v3.23.0 (2026-06-15) — Real-market evidence status reporter.

Operator-readable breakdown of where real-market evidence stands:
how many opportunities the ledger saw today, by monitor, strategy,
symbol, and confidence bucket; the distribution of gate decisions;
shadow-eligible row counts; and the diagnostic-token data-failure
signature pulled from ``workflow_health_latest.json``.

Outputs:

- ``learning-loop/shadow_evidence/real_market_evidence_status_latest.json``
- ``docs/REAL_MARKET_EVIDENCE_STATUS.md``

HARD SAFETY RULES (cannot be opted out of)
------------------------------------------
- NEVER submits orders.
- NEVER imports ``alpaca_orders``.
- NEVER calls broker / network endpoints.
- NEVER mutates state.json or runtime_state.json.
- NEVER counts observation records as opportunities.
- Every output carries the v3.23 standing markers footer.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Standing markers reproduced verbatim in every emitted artifact.
STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "learning-loop" / "shadow_evidence"
LEDGER_DIR = REPO_ROOT / "learning-loop" / "opportunity_ledger"
OBS_DIR = EVIDENCE_DIR / "observations"

LATEST_JSON_PATH = EVIDENCE_DIR / "real_market_evidence_status_latest.json"
LATEST_MD_PATH = REPO_ROOT / "docs" / "REAL_MARKET_EVIDENCE_STATUS.md"

# Strategy -> monitor source map. When a strategy doesn't appear here
# it falls through to "unknown".
STRATEGY_TO_MONITOR = {
    "crypto-momentum":        "crypto-monitor",
    "crypto-oversold-bounce": "crypto-monitor",
    "crypto-breakdown":       "crypto-monitor",
    "momentum-long":          "price-monitor",
    "momentum-long-loose":    "price-monitor",
    "overbought-short":       "price-monitor",
    "geo-defense":            "geo-monitor",
    "geo-energy":             "geo-monitor",
    "geo-gold":               "geo-monitor",
    "geo-xom":                "geo-monitor",
    "options-momentum":       "options-monitor",
    "alloc-exit":             "allocator",
    "alloc-reduce":           "allocator",
    "allocator-rebalance":    "allocator",
}

# Confidence buckets.
CONF_BUCKETS = ("0.0-0.5", "0.5-0.65", "0.65-0.80", "0.80+", "null")


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True, check=True, text=True, timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _confidence_bucket(score: Any) -> str:
    if score is None:
        return "null"
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "null"
    if s < 0.5:
        return "0.0-0.5"
    if s < 0.65:
        return "0.5-0.65"
    if s < 0.80:
        return "0.65-0.80"
    return "0.80+"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return out
    return out


def _load_ledger_rows(ledger_dir: Path, as_of: datetime,
                       days: int) -> list[dict]:
    """Load ledger rows for as_of and the preceding ``days - 1`` days."""
    rows: list[dict] = []
    for delta in range(days):
        # delta=0 -> today
        d = (as_of.date()
             if delta == 0
             else as_of.date() - __import__("datetime")
                  .timedelta(days=delta))
        # Use timedelta cleanly:
        from datetime import timedelta
        d = (as_of - timedelta(days=delta)).date()
        path = ledger_dir / f"{d.isoformat()}.jsonl"
        rows.extend(_load_jsonl(path))
    return rows


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _count_observations_today(obs_dir: Path, as_of: datetime) -> int:
    """Count v3.30 observation records for today. Observations DO NOT
    count toward the readiness gate — we report the number purely so
    the operator sees data is reaching the system."""
    if not obs_dir.exists():
        return 0
    today_path = obs_dir / f"{as_of.date().isoformat()}.jsonl"
    return len(_load_jsonl(today_path))


def _resolve_monitor(strategy: str) -> str:
    return STRATEGY_TO_MONITOR.get(strategy or "", "unknown")


def _is_shadow_eligible(row: dict) -> bool:
    """A row is shadow-eligible if risk_decision is APPROVE or
    DETECTED and confidence_score >= 0.50.

    When confidence_score is None we treat it as ineligible (see
    confidence-reality-check report for why).
    """
    rd = (row.get("risk_decision") or "").upper()
    if rd not in ("APPROVE", "DETECTED"):
        return False
    score = row.get("confidence_score")
    if score is None:
        return False
    try:
        return float(score) >= 0.50
    except (TypeError, ValueError):
        return False


def _diagnose_blocker(
    *,
    opp_today: int,
    diag_counts: dict[str, int],
    counters: dict,
    last_workflow_run_conclusion: str | None,
    last_collector_status: str | None,
    secrets_status: str | None,
) -> str:
    """Return a single phrase describing the current blocker."""
    if last_workflow_run_conclusion == "failure":
        return "WORKFLOW_FAILED_LAST_RUN"
    if last_workflow_run_conclusion is None and not diag_counts:
        return "WORKFLOW_NOT_FIRING"
    if (secrets_status or "").upper() == "SECRETS_MISSING_OR_UNAVAILABLE":
        return "AUTH_MISSING"
    auth_failed = (
        diag_counts.get("AUTH_FAILED", 0)
        + diag_counts.get("AUTH_MISSING", 0)
        + diag_counts.get("MARKET_DATA_AUTH_FAILED", 0))
    provider_err = (
        diag_counts.get("PROVIDER_ERROR", 0)
        + diag_counts.get("MARKET_DATA_PROVIDER_ERROR", 0))
    real_no_sig = (
        diag_counts.get("REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL", 0)
        + diag_counts.get(
            "INSUFFICIENT_BARS_FOR_SIGNAL", 0))
    if auth_failed > 0 and provider_err + real_no_sig == 0:
        return "AUTH_FAILED"
    if provider_err > 0 and real_no_sig == 0:
        return "PROVIDER_ERROR"
    if (last_collector_status
            == "SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA"
            and real_no_sig == 0):
        return "NO_REAL_MARKET_DATA"
    if real_no_sig > 0 and opp_today == 0:
        return "ALL_NO_SIGNAL_OR_INSUFFICIENT_BARS"
    if opp_today == 0:
        return "NO_REAL_MARKET_DATA"
    return "NONE_OPPORTUNITIES_FLOWING"


def _days_to_n50_estimate(rolling_avg: float, target: int) -> str:
    if rolling_avg <= 0:
        return "UNKNOWN"
    remaining = max(0, target - 0)
    if remaining == 0:
        return "ALREADY_REACHED"
    days = remaining / rolling_avg
    return f"{days:.1f}"


def build_status(
    *,
    as_of: datetime,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Pure builder: returns the status dict without writing files."""
    if repo_root is None:
        repo_root = REPO_ROOT
    ledger_dir = repo_root / "learning-loop" / "opportunity_ledger"
    obs_dir = repo_root / "learning-loop" / "shadow_evidence" / "observations"
    evidence_dir = repo_root / "learning-loop" / "shadow_evidence"

    # Today + 3-day rolling.
    today_rows = _load_jsonl(ledger_dir / f"{as_of.date().isoformat()}.jsonl")
    rolling_rows = _load_ledger_rows(ledger_dir, as_of, days=3)

    counters = _load_json(evidence_dir / "evidence_counters_latest.json")
    health = _load_json(evidence_dir / "workflow_health_latest.json")
    diag_counts: dict[str, int] = (
        health.get("diagnostic_token_counts") or {})

    by_monitor: dict[str, int] = collections.Counter()
    by_strategy: dict[str, int] = collections.Counter()
    by_symbol: dict[str, int] = collections.Counter()
    conf_dist: dict[str, int] = {b: 0 for b in CONF_BUCKETS}
    gate_dist: dict[str, int] = collections.Counter()
    shadow_eligible = 0

    for row in today_rows:
        strat = row.get("strategy") or "unknown"
        by_strategy[strat] += 1
        by_monitor[_resolve_monitor(strat)] += 1
        by_symbol[row.get("symbol") or "?"] += 1
        conf_dist[_confidence_bucket(row.get("confidence_score"))] += 1
        rd = (row.get("risk_decision") or "UNKNOWN").upper()
        gate_dist[rd] += 1
        if _is_shadow_eligible(row):
            shadow_eligible += 1

    # Rolling average across the 3-day window (today + 2 prior days).
    rolling_days = 3
    rolling_total = (
        counters.get("real_market_opportunities_count", 0))
    rolling_avg = rolling_total / max(1, rolling_days)

    observations_today = _count_observations_today(obs_dir, as_of)

    blocker = _diagnose_blocker(
        opp_today=len(today_rows),
        diag_counts=diag_counts,
        counters=counters,
        last_workflow_run_conclusion=(
            health.get("last_workflow_run_conclusion")),
        last_collector_status=health.get("last_collector_status"),
        secrets_status=health.get("secrets_status"),
    )

    target_n50 = counters.get("thresholds", {}).get(
        "real_market_opportunities", 50)
    real_count = counters.get("real_market_opportunities_count", 0)
    remaining = max(0, target_n50 - real_count)
    if rolling_avg <= 0 or real_count >= target_n50:
        days_estimate = (
            "ALREADY_REACHED" if real_count >= target_n50 else "UNKNOWN")
    else:
        days_estimate = f"{remaining / rolling_avg:.1f}"

    out: dict[str, Any] = {
        "version":                       "v3.23.0",
        "generated_at_iso":              datetime.now(
                                            timezone.utc).isoformat(),
        "as_of":                         as_of.isoformat(),
        "git_head":                      _git_head(),
        "opportunities_today":           len(today_rows),
        "opportunities_today_by_monitor": dict(by_monitor),
        "opportunities_today_by_strategy": dict(by_strategy),
        "opportunities_today_by_symbol_top10": dict(by_symbol.most_common(10)),
        "confidence_distribution":       dict(conf_dist),
        "gate_decision_distribution":    dict(gate_dist),
        "shadow_eligible_count_today":   shadow_eligible,
        "observations_today":            observations_today,
        "real_market_opportunities_count_lifetime": real_count,
        "real_market_opportunities_target":         target_n50,
        "data_failure_counts":           dict(diag_counts),
        "rolling_window_days":           rolling_days,
        "rolling_avg_real_market_opps_per_day": rolling_avg,
        "days_to_n50_estimate":          days_estimate,
        "current_blocker":               blocker,
        "last_workflow_run_id":          health.get("last_workflow_run_id"),
        "last_workflow_run_conclusion":  health.get(
                                            "last_workflow_run_conclusion"),
        "last_collector_status":         health.get("last_collector_status"),
        "secrets_status":                health.get("secrets_status"),
        "safety": {
            "edge_gate_enabled":          False,
            "allow_broker_paper":         False,
            "live_trading_supported":     False,
            "observations_count_as_opportunities": False,
        },
        "standing_markers":              list(STANDING_MARKERS),
    }
    return out


def render_md(status: dict[str, Any]) -> str:
    rows_by_monitor = "\n".join(
        f"| `{k}` | {v} |"
        for k, v in sorted(status["opportunities_today_by_monitor"].items()))
    if not rows_by_monitor:
        rows_by_monitor = "| (none) | 0 |"
    rows_by_strategy = "\n".join(
        f"| `{k}` | {v} |"
        for k, v in sorted(status["opportunities_today_by_strategy"].items()))
    if not rows_by_strategy:
        rows_by_strategy = "| (none) | 0 |"
    rows_by_symbol = "\n".join(
        f"| `{k}` | {v} |"
        for k, v in status["opportunities_today_by_symbol_top10"].items())
    if not rows_by_symbol:
        rows_by_symbol = "| (none) | 0 |"
    rows_conf = "\n".join(
        f"| `{k}` | {v} |"
        for k, v in status["confidence_distribution"].items())
    rows_gate = "\n".join(
        f"| `{k}` | {v} |"
        for k, v in sorted(status["gate_decision_distribution"].items()))
    if not rows_gate:
        rows_gate = "| (none) | 0 |"
    rows_diag = "\n".join(
        f"| `{k}` | {v} |"
        for k, v in sorted(status["data_failure_counts"].items()))
    if not rows_diag:
        rows_diag = "| (none) | 0 |"
    standing = "\n".join(f"- `{m}`" for m in status["standing_markers"])

    return f"""# Real-Market Evidence Status (v3.23.0)

**Generated:** `{status["generated_at_iso"]}`
**As of:** `{status["as_of"]}`
**Git HEAD:** `{status["git_head"]}`
**Current blocker:** **`{status["current_blocker"]}`**

## Opportunities today

| Metric | Value |
|---|---|
| Total ledger rows today | `{status["opportunities_today"]}` |
| Shadow-eligible today (risk_decision in (APPROVE,DETECTED) & confidence >= 0.50) | `{status["shadow_eligible_count_today"]}` |
| Observation records today (DO NOT count toward unlock) | `{status["observations_today"]}` |

## By monitor

| Monitor | Count |
|---|---|
{rows_by_monitor}

## By strategy

| Strategy | Count |
|---|---|
{rows_by_strategy}

## By symbol (top 10)

| Symbol | Count |
|---|---|
{rows_by_symbol}

## Confidence-score distribution

| Bucket | Count |
|---|---|
{rows_conf}

## Gate-decision distribution

| Decision | Count |
|---|---|
{rows_gate}

## Data-failure signature (latest workflow_health diagnostic_token_counts)

| Token | Count |
|---|---|
{rows_diag}

## Progress toward N=50 unlock

| Metric | Value |
|---|---|
| `real_market_opportunities_count` (lifetime) | `{status["real_market_opportunities_count_lifetime"]}` |
| Target | `{status["real_market_opportunities_target"]}` |
| Rolling window (days) | `{status["rolling_window_days"]}` |
| Rolling avg opportunities/day | `{status["rolling_avg_real_market_opps_per_day"]:.3f}` |
| Estimated days to N=50 | `{status["days_to_n50_estimate"]}` |

## Workflow context

| Field | Value |
|---|---|
| Last workflow run id | `{status["last_workflow_run_id"] or 'unknown'}` |
| Last workflow run conclusion | `{status["last_workflow_run_conclusion"] or 'unknown'}` |
| Last collector status | `{status["last_collector_status"] or 'unknown'}` |
| Secrets status | `{status["secrets_status"] or 'unknown'}` |

## Safety invariants

- `edge_gate_enabled`: `false`
- `allow_broker_paper`: `false`
- `live_trading_supported`: `false`
- `observations_count_as_opportunities`: `false`

## Standing markers

{standing}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the v3.23 real-market evidence status report.")
    parser.add_argument("--as-of", default=None,
                          help="ISO-8601 timestamp; default: now (UTC).")
    parser.add_argument("--json", action="store_true",
                          help="Print the JSON body to stdout.")
    parser.add_argument("--no-write", action="store_true",
                          help="Do not write the JSON/MD output files.")
    args = parser.parse_args(argv)

    if args.as_of:
        try:
            as_of = datetime.fromisoformat(
                args.as_of.replace("Z", "+00:00"))
        except ValueError:
            print(f"Invalid --as-of: {args.as_of}", file=sys.stderr)
            return 2
    else:
        as_of = datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    status = build_status(as_of=as_of)
    md = render_md(status)

    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))

    if not args.no_write:
        LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_JSON_PATH.write_text(
            json.dumps(status, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_MD_PATH.write_text(md, encoding="utf-8")
        print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
        print(f"Wrote {LATEST_MD_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
