#!/usr/bin/env python3
"""v3.27.1 (2026-06-09) — automated shadow progress evaluator.

Reads:
- ``learning-loop/shadow_evidence/evidence_counters_latest.json``
- ``learning-loop/shadow_evidence/workflow_health_latest.json``
- the most recent records / outcomes JSONL files

Writes:
- ``learning-loop/shadow_evidence/workflow_health_latest.json``
  (refreshed each invocation with the latest verdict + diagnostics)
- ``docs/AUTOMATED_SHADOW_WORKFLOW_HEALTH.md`` (human view)

Produces a deterministic verdict. NEVER submits orders, NEVER imports
the broker-orders module, NEVER stores secret values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

EVIDENCE_DIR = REPO_ROOT / "learning-loop" / "shadow_evidence"
COUNTERS_PATH = EVIDENCE_DIR / "evidence_counters_latest.json"
HEALTH_PATH = EVIDENCE_DIR / "workflow_health_latest.json"
HEALTH_DOC = REPO_ROOT / "docs" / "AUTOMATED_SHADOW_WORKFLOW_HEALTH.md"

# Verdict enum.
AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET = (
    "AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET")
AUTOMATED_PIPELINE_HEALTHY_COLLECTING_REAL_MARKET_DATA = (
    "AUTOMATED_PIPELINE_HEALTHY_COLLECTING_REAL_MARKET_DATA")
AUTOMATED_PIPELINE_BLOCKED_NO_SECRETS = (
    "AUTOMATED_PIPELINE_BLOCKED_NO_SECRETS")
AUTOMATED_PIPELINE_BLOCKED_PROVIDER_ERROR = (
    "AUTOMATED_PIPELINE_BLOCKED_PROVIDER_ERROR")
AUTOMATED_PIPELINE_BLOCKED_WORKFLOW_FAILURE = (
    "AUTOMATED_PIPELINE_BLOCKED_WORKFLOW_FAILURE")
AUTOMATED_PIPELINE_BLOCKED_SCHEMA_OR_COUNTER_ERROR = (
    "AUTOMATED_PIPELINE_BLOCKED_SCHEMA_OR_COUNTER_ERROR")

ALL_VERDICTS: frozenset[str] = frozenset({
    AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET,
    AUTOMATED_PIPELINE_HEALTHY_COLLECTING_REAL_MARKET_DATA,
    AUTOMATED_PIPELINE_BLOCKED_NO_SECRETS,
    AUTOMATED_PIPELINE_BLOCKED_PROVIDER_ERROR,
    AUTOMATED_PIPELINE_BLOCKED_WORKFLOW_FAILURE,
    AUTOMATED_PIPELINE_BLOCKED_SCHEMA_OR_COUNTER_ERROR,
})

# Standing markers — these are always returned alongside the verdict.
BROKER_PAPER_CANARY_STILL_BLOCKED = "BROKER_PAPER_CANARY_STILL_BLOCKED"
LIVE_TRADING_UNSUPPORTED          = "LIVE_TRADING_UNSUPPORTED"


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def _refuse_if_broker_enabled() -> str | None:
    for name in (
        "ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
        "BROKER_EXECUTION_ENABLED",
        "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
        "LIVE_TRADING_ENABLED",
    ):
        if _env_truthy(name):
            return f"REFUSED_{name}_IS_TRUTHY"
    return None


def _load_counters() -> dict:
    if not COUNTERS_PATH.exists():
        return {}
    try:
        return json.loads(COUNTERS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_existing_health() -> dict:
    if not HEALTH_PATH.exists():
        return {}
    try:
        return json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _aggregate_diagnostic_tokens(records: list[dict],
                                   last_collector_summary: dict | None,
                                   ) -> dict[str, int]:
    """Count per-symbol tokens from the latest collector summary
    (preferred) or the per-record evidence_quality field."""
    counts: dict[str, int] = {}
    if (last_collector_summary
            and isinstance(last_collector_summary
                            .get("per_symbol_diagnostics"), list)):
        for d in last_collector_summary["per_symbol_diagnostics"]:
            tok = d.get("status_token") or "UNKNOWN"
            counts[tok] = counts.get(tok, 0) + 1
        return counts
    # Fall back to record-level evidence_quality counts.
    for r in records:
        tok = r.get("evidence_quality") or "UNKNOWN"
        counts[tok] = counts.get(tok, 0) + 1
    return counts


def evaluate_verdict(
    counters: dict,
    *,
    last_workflow_run_conclusion: str | None,
    secrets_status: str,
    diagnostic_token_counts: dict[str, int],
) -> tuple[str, list[str]]:
    """Pure verdict function. Returns (verdict, rationale)."""
    rationale: list[str] = []
    real = counters.get("real_market_opportunities_count", 0)
    completed = counters.get("completed_shadow_outcomes_count", 0)

    if last_workflow_run_conclusion == "failure":
        rationale.append(
            "most recent workflow run conclusion = failure")
        return (AUTOMATED_PIPELINE_BLOCKED_WORKFLOW_FAILURE,
                rationale)
    if secrets_status == "SECRETS_MISSING_OR_UNAVAILABLE":
        rationale.append(
            "ALPACA_API_KEY / ALPACA_SECRET_KEY missing in repo secrets")
        return AUTOMATED_PIPELINE_BLOCKED_NO_SECRETS, rationale
    provider_error_tokens = (
        diagnostic_token_counts.get("MARKET_DATA_PROVIDER_ERROR", 0)
        + diagnostic_token_counts.get("MARKET_DATA_AUTH_FAILED", 0))
    valid_data_signals = (
        diagnostic_token_counts.get(
            "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL", 0)
        + diagnostic_token_counts.get(
            "REAL_MARKET_SIGNAL_RECORDS_EMITTED", 0)
        + diagnostic_token_counts.get(
            "INSUFFICIENT_BARS_FOR_SIGNAL", 0)
        + diagnostic_token_counts.get(
            "MARKET_CLOSED_OR_NO_BARS", 0)
        + diagnostic_token_counts.get(
            "MARKET_DATA_STALE", 0))
    if (provider_error_tokens > 0
            and valid_data_signals == 0
            and last_workflow_run_conclusion in (None, "success")):
        rationale.append(
            "provider errors dominate diagnostics; no valid data "
            "tokens this cycle")
        return (AUTOMATED_PIPELINE_BLOCKED_PROVIDER_ERROR,
                rationale)
    if real > 0:
        rationale.append(
            f"real_market_opportunities_count={real} (>0)")
        if completed > 0:
            rationale.append(
                f"completed_shadow_outcomes_count={completed} (>0)")
        return (AUTOMATED_PIPELINE_HEALTHY_COLLECTING_REAL_MARKET_DATA,
                rationale)
    rationale.append(
        f"real_market_opportunities_count={real}; "
        f"workflow + data path appear healthy")
    return AUTOMATED_PIPELINE_HEALTHY_NO_REAL_DATA_YET, rationale


def render_health_md(*, verdict: str, rationale: list[str],
                       counters: dict,
                       last_workflow_run_id: str | None,
                       last_workflow_run_conclusion: str | None,
                       last_collector_status: str | None,
                       last_resolver_status: str | None,
                       diagnostic_token_counts: dict[str, int],
                       generated_at_iso: str) -> str:
    rm = counters.get("real_market_opportunities_count", 0)
    cs = counters.get("completed_shadow_outcomes_count", 0)
    diag_rows = "\n".join(
        f"| `{k}` | {v} |"
        for k, v in sorted(diagnostic_token_counts.items()))
    if not diag_rows:
        diag_rows = "| (none) | 0 |"
    rationale_md = "\n".join(f"- {r}" for r in rationale) or "- n/a"
    return f"""# Automated Shadow Workflow Health (v3.27.1)

**Generated:** `{generated_at_iso}`
**Source:** `learning-loop/shadow_evidence/workflow_health_latest.json`
**Verdict:** **`{verdict}`**
**Standing markers:** `{BROKER_PAPER_CANARY_STILL_BLOCKED}`, `{LIVE_TRADING_UNSUPPORTED}`

## Rationale

{rationale_md}

## Workflow run

| Field | Value |
|---|---|
| Last run id | `{last_workflow_run_id or 'unknown'}` |
| Last run conclusion | `{last_workflow_run_conclusion or 'unknown'}` |
| Last collector status | `{last_collector_status or 'unknown'}` |
| Last resolver status | `{last_resolver_status or 'unknown'}` |

## Canary-gate counters

| Metric | Value |
|---|---:|
| `real_market_opportunities_count` (target 50) | **{rm}** |
| `completed_shadow_outcomes_count` (target 20) | **{cs}** |
| `audit_bypass_findings_count` | {counters.get('audit_bypass_findings_count', 0)} |
| `exposure_cap_breach_count` | {counters.get('exposure_cap_breach_count', 0)} |
| `repeated_buy_violation_count` | {counters.get('repeated_buy_violation_count', 0)} |
| `unexplained_broker_state_conflicts_count` | {counters.get('unexplained_broker_state_conflicts_count', 0)} |

## Per-symbol diagnostic tokens (most recent cycle)

| Token | Symbols |
|---|---:|
{diag_rows}

## Safety invariants (from counters file)

- `broker_order_submitted_ever`: `{str((counters.get('safety_invariants') or {{}}).get('broker_order_submitted_ever', False)).lower()}`
- `live_trading_enabled`: `{str((counters.get('safety_invariants') or {{}}).get('live_trading_enabled', False)).lower()}`
- `broker_paper_enabled`: `{str((counters.get('safety_invariants') or {{}}).get('broker_paper_enabled', False)).lower()}`
- `edge_gate_enabled`: `{str((counters.get('safety_invariants') or {{}}).get('edge_gate_enabled', False)).lower()}`
- `baseline_reset`: `{str((counters.get('safety_invariants') or {{}}).get('baseline_reset', False)).lower()}`
- `drawdown_guard_lowered`: `{str((counters.get('safety_invariants') or {{}}).get('drawdown_guard_lowered', False)).lower()}`

## What this report does NOT do

- Does NOT submit orders.
- Does NOT enable broker paper.
- Does NOT enable live trading.
- Does NOT log or commit secret values.
- Does NOT modify positions.
- Does NOT lower the drawdown guard.
- Does NOT reset the equity baseline.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate automated shadow workflow progress.",
    )
    parser.add_argument("--workflow-run-id", default=None)
    parser.add_argument("--workflow-run-conclusion", default=None,
                          choices=[None, "success", "failure",
                                    "cancelled", "skipped"])
    parser.add_argument("--collector-status", default=None)
    parser.add_argument(
        "--collector-summary-path", default=None,
        help="v3.23 — path to a JSON file emitted by "
             "scripts/run_signal_shadow_evidence_collection.py that "
             "contains per_symbol_diagnostics + diagnostic_token_counts. "
             "When provided, those fields are persisted under "
             "last_collector_summary in workflow_health_latest.json so "
             "the next evaluator run can aggregate diagnostic tokens.")
    parser.add_argument("--resolver-status", default=None)
    parser.add_argument("--secrets-status",
                          default="SECRETS_STATUS_UNKNOWN",
                          choices=["SECRETS_AVAILABLE",
                                    "SECRETS_MISSING_OR_UNAVAILABLE",
                                    "SECRETS_STATUS_UNKNOWN"])
    args = parser.parse_args(argv)

    refuse = _refuse_if_broker_enabled()
    if refuse is not None:
        print(json.dumps({"status": refuse}))
        return 1

    counters = _load_counters()
    existing_health = _load_existing_health()

    # v3.23 — when the collector emits a summary file (per_symbol_
    # diagnostics + diagnostic_token_counts from the v3.22 diagnostic
    # API), load it and use it for THIS evaluator run as well as
    # persisting it for the NEXT one.
    fresh_collector_summary: dict = {}
    if args.collector_summary_path:
        try:
            fresh_collector_summary = json.loads(
                Path(args.collector_summary_path)
                .read_text(encoding="utf-8"))
            if not isinstance(fresh_collector_summary, dict):
                fresh_collector_summary = {}
        except Exception:
            fresh_collector_summary = {}

    # Prefer fresh summary; fall back to the previous run's summary
    # so we don't regress an existing populated dict to {}.
    last_collector_summary = (
        fresh_collector_summary
        or existing_health.get("last_collector_summary")
        or {})
    diag_counts = _aggregate_diagnostic_tokens(
        records=[], last_collector_summary=last_collector_summary)

    # v3.23 — if the collector summary contains a v3.22-API populated
    # ``diagnostic_token_counts`` dict, honor that (the aggregate is
    # more authoritative than re-counting per_symbol_diagnostics, e.g.
    # when symbols outside the per-symbol list contributed counts).
    fresh_diag_counts = (
        fresh_collector_summary.get("diagnostic_token_counts") or {})
    if isinstance(fresh_diag_counts, dict) and fresh_diag_counts:
        diag_counts = dict(fresh_diag_counts)

    verdict, rationale = evaluate_verdict(
        counters,
        last_workflow_run_conclusion=args.workflow_run_conclusion,
        secrets_status=args.secrets_status,
        diagnostic_token_counts=diag_counts,
    )

    generated_at_iso = datetime.now(timezone.utc).isoformat()
    health = {
        "version":                       "v3.27.1",
        "generated_at_iso":              generated_at_iso,
        "verdict":                       verdict,
        "rationale":                     rationale,
        "standing_markers": [
            BROKER_PAPER_CANARY_STILL_BLOCKED,
            LIVE_TRADING_UNSUPPORTED,
        ],
        "last_workflow_run_id":          args.workflow_run_id,
        "last_workflow_run_conclusion":  args.workflow_run_conclusion,
        "last_collector_status":         args.collector_status,
        "last_resolver_status":          args.resolver_status,
        "secrets_status":                args.secrets_status,
        "diagnostic_token_counts":       diag_counts,
        "last_collector_summary":        last_collector_summary,
        "counters_snapshot": {
            "real_market_opportunities_count":
                counters.get("real_market_opportunities_count", 0),
            "completed_shadow_outcomes_count":
                counters.get("completed_shadow_outcomes_count", 0),
            "scaffold_no_market_data_records_count":
                counters.get("scaffold_no_market_data_records_count", 0),
            "halt_path_records_count":
                counters.get("halt_path_records_count", 0),
        },
        "safety": {
            "broker_paper_canary_still_blocked": True,
            "live_trading_unsupported":          True,
        },
    }
    HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_PATH.write_text(
        json.dumps(health, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    md = render_health_md(
        verdict=verdict, rationale=rationale,
        counters=counters,
        last_workflow_run_id=args.workflow_run_id,
        last_workflow_run_conclusion=args.workflow_run_conclusion,
        last_collector_status=args.collector_status,
        last_resolver_status=args.resolver_status,
        diagnostic_token_counts=diag_counts,
        generated_at_iso=generated_at_iso,
    )
    HEALTH_DOC.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_DOC.write_text(md, encoding="utf-8")

    print(json.dumps({
        "status":  "EVALUATED",
        "verdict": verdict,
        "version": "v3.27.1",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
