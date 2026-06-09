#!/usr/bin/env python3
"""v3.27.2 (2026-06-09) — automated evidence progress monitor.

The v3.27.1 evaluator answers ONE question per cron tick — "is the
workflow healthy *this* tick?" — but it cannot tell whether the
pipeline is making PROGRESS toward the v3.25 thresholds
(50 real opportunities / 20 outcomes) or whether it is silently
stuck on a single failure mode across many ticks.

v3.27.2 layers a deterministic multi-run progress monitor on top:

- Appends one record to ``workflow_health_history.jsonl`` each
  invocation (rolling history of every cron tick) — pure JSONL, append
  only, never rewritten.
- Reads recent successful runs (last N) and applies a small rule
  matrix to produce ONE progress status (``AUTOMATED_EVIDENCE_*``).
- Refreshes ``first_real_market_record_status.json`` — a deterministic
  artifact that tells the operator whether any v3.27 record with
  ``evidence_quality == REAL_MARKET_DATA`` exists on disk yet.

HARD SAFETY (cannot be opted out of)
------------------------------------
- NEVER submits orders.
- NEVER modifies positions.
- NEVER imports the broker-orders module.
- NEVER stores secret values.
- NEVER counts no-signal diagnostics as opportunities.
- NEVER advances the broker-paper canary readiness gate.
- NEVER lowers ``drawdown_guard``.
- Refuses (exit 1) if any of
  ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED`` /
  ``BROKER_EXECUTION_ENABLED`` / ``LIVE_TRADING`` /
  ``LIVE_ENABLED`` / ``GO_LIVE`` / ``LIVE_TRADING_ENABLED``
  is truthy.
- Standing markers ``BROKER_PAPER_CANARY_STILL_BLOCKED`` and
  ``LIVE_TRADING_UNSUPPORTED`` are returned with EVERY status —
  there is no status that unblocks broker paper or live trading.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

EVIDENCE_DIR = REPO_ROOT / "learning-loop" / "shadow_evidence"
HEALTH_LATEST   = EVIDENCE_DIR / "workflow_health_latest.json"
HEALTH_HISTORY  = EVIDENCE_DIR / "workflow_health_history.jsonl"
COUNTERS_PATH   = EVIDENCE_DIR / "evidence_counters_latest.json"
FIRST_RECORD_STATUS = EVIDENCE_DIR / "first_real_market_record_status.json"

# ─── Progress status enum ───────────────────────────────────────────────────

AUTOMATED_EVIDENCE_PROGRESSING                  = "AUTOMATED_EVIDENCE_PROGRESSING"
AUTOMATED_EVIDENCE_HEALTHY_BUT_NO_SIGNALS_YET   = (
    "AUTOMATED_EVIDENCE_HEALTHY_BUT_NO_SIGNALS_YET")
AUTOMATED_EVIDENCE_STUCK_NO_MARKET_DATA         = (
    "AUTOMATED_EVIDENCE_STUCK_NO_MARKET_DATA")
AUTOMATED_EVIDENCE_STUCK_INSUFFICIENT_BARS      = (
    "AUTOMATED_EVIDENCE_STUCK_INSUFFICIENT_BARS")
AUTOMATED_EVIDENCE_STUCK_AUTH                   = "AUTOMATED_EVIDENCE_STUCK_AUTH"
AUTOMATED_EVIDENCE_STUCK_PROVIDER_ERROR         = (
    "AUTOMATED_EVIDENCE_STUCK_PROVIDER_ERROR")
AUTOMATED_EVIDENCE_STUCK_GENERATOR_TOO_RESTRICTIVE = (
    "AUTOMATED_EVIDENCE_STUCK_GENERATOR_TOO_RESTRICTIVE")
AUTOMATED_EVIDENCE_REQUIRES_MORE_RUNS           = (
    "AUTOMATED_EVIDENCE_REQUIRES_MORE_RUNS")

ALL_PROGRESS_STATUSES: frozenset[str] = frozenset({
    AUTOMATED_EVIDENCE_PROGRESSING,
    AUTOMATED_EVIDENCE_HEALTHY_BUT_NO_SIGNALS_YET,
    AUTOMATED_EVIDENCE_STUCK_NO_MARKET_DATA,
    AUTOMATED_EVIDENCE_STUCK_INSUFFICIENT_BARS,
    AUTOMATED_EVIDENCE_STUCK_AUTH,
    AUTOMATED_EVIDENCE_STUCK_PROVIDER_ERROR,
    AUTOMATED_EVIDENCE_STUCK_GENERATOR_TOO_RESTRICTIVE,
    AUTOMATED_EVIDENCE_REQUIRES_MORE_RUNS,
})

# Standing markers — always present alongside the progress status.
BROKER_PAPER_CANARY_STILL_BLOCKED = "BROKER_PAPER_CANARY_STILL_BLOCKED"
LIVE_TRADING_UNSUPPORTED          = "LIVE_TRADING_UNSUPPORTED"

# Threshold tuning for the rule matrix.
MIN_SUCCESS_RUNS_FOR_TREND        = 2
INSUFFICIENT_BARS_TICKS_REQUIRED  = 2
AUTH_FAILED_TICKS_REQUIRED        = 2
PROVIDER_ERROR_TICKS_REQUIRED     = 2
NO_MARKET_DATA_TICKS_REQUIRED     = 2
GENERATOR_TOO_RESTRICTIVE_TICKS   = 3


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


def _safe_load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    # Skip malformed lines defensively.
                    continue
    except Exception:
        return []
    return out


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    # Append-only — never rewrite.
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


# ─── History append ──────────────────────────────────────────────────────────

def append_health_snapshot_to_history(
    latest: dict,
    *,
    history_path: Path = HEALTH_HISTORY,
    now_iso: str | None = None,
) -> dict:
    """Idempotently append the latest health snapshot to the history.

    Idempotent on ``(workflow_run_id, generated_at_iso)`` — running the
    monitor twice for the same workflow run does NOT duplicate the entry.
    Returns the entry actually written, or the existing matching entry
    if the snapshot was a duplicate.
    """
    if not latest:
        # Nothing to append.
        return {}
    entry = {
        "appended_at_iso":     now_iso or datetime.now(timezone.utc).isoformat(),
        "generated_at_iso":    latest.get("generated_at_iso"),
        "workflow_run_id":     latest.get("last_workflow_run_id"),
        "workflow_conclusion": latest.get("last_workflow_run_conclusion"),
        "collector_status":    latest.get("last_collector_status"),
        "resolver_status":     latest.get("last_resolver_status"),
        "secrets_status":      latest.get("secrets_status"),
        "verdict":             latest.get("verdict"),
        "diagnostic_token_counts": latest.get(
            "diagnostic_token_counts") or {},
        "counters_snapshot":   latest.get("counters_snapshot") or {},
        "standing_markers":    latest.get("standing_markers") or [],
        "safety":              latest.get("safety") or {},
    }
    # Dedup on (workflow_run_id, generated_at_iso).
    existing = _read_jsonl(history_path)
    for h in existing:
        if (h.get("workflow_run_id") == entry["workflow_run_id"]
                and h.get("generated_at_iso")
                    == entry["generated_at_iso"]):
            return h
    _append_jsonl(history_path, entry)
    return entry


# ─── Rule-matrix progress evaluator ──────────────────────────────────────────

def _success_runs(history: list[dict]) -> list[dict]:
    """Return successful workflow runs in chronological order."""
    return [h for h in history
            if h.get("workflow_conclusion") == "success"]


def _real_market_opportunities_count(history: list[dict]) -> int:
    out = 0
    if not history:
        return 0
    last = history[-1] or {}
    cs = last.get("counters_snapshot") or {}
    return int(cs.get("real_market_opportunities_count", 0) or 0)


def _is_market_session(now: datetime) -> bool:
    """Naive US-session check: weekday and 13:30-20:00 UTC.

    Pure heuristic — used only to interpret MARKET_CLOSED tokens as
    healthy outside session vs concerning inside session.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_utc = now.astimezone(timezone.utc)
    weekday = now_utc.weekday()
    if weekday >= 5:           # Saturday/Sunday
        return False
    minutes = now_utc.hour * 60 + now_utc.minute
    return 13 * 60 + 30 <= minutes <= 20 * 60


def _real_count_increased(history: list[dict]) -> bool:
    if len(history) < 2:
        return False
    prev = history[-2].get("counters_snapshot") or {}
    last = history[-1].get("counters_snapshot") or {}
    return (int(last.get("real_market_opportunities_count", 0) or 0)
            > int(prev.get("real_market_opportunities_count", 0) or 0))


def _token_present_consecutively(history: list[dict],
                                   token: str,
                                   *, count: int) -> bool:
    succ = _success_runs(history)
    if len(succ) < count:
        return False
    last = succ[-count:]
    for h in last:
        diag = h.get("diagnostic_token_counts") or {}
        if int(diag.get(token, 0) or 0) <= 0:
            return False
    return True


def _token_dominant_consecutively(history: list[dict],
                                    token: str,
                                    *, count: int,
                                    require_session: bool = False,
                                    now: datetime | None = None,
                                    ) -> bool:
    """``token`` is the most-frequent diagnostic for the last ``count``
    successful runs (strictly more than any other token)."""
    succ = _success_runs(history)
    if len(succ) < count:
        return False
    if require_session and not _is_market_session(
            now or datetime.now(timezone.utc)):
        return False
    last = succ[-count:]
    for h in last:
        diag = h.get("diagnostic_token_counts") or {}
        if not diag:
            return False
        max_token = max(diag.items(), key=lambda kv: kv[1])
        if max_token[0] != token or max_token[1] <= 0:
            return False
        # token must strictly dominate (not tie).
        others = [v for k, v in diag.items() if k != token]
        if any(v >= max_token[1] for v in others):
            return False
    return True


def evaluate_progress(
    history: list[dict],
    *,
    now: datetime | None = None,
    real_signal_emitted_token: str = "REAL_MARKET_SIGNAL_RECORDS_EMITTED",
    no_signal_token: str = "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL",
    insufficient_bars_token: str = "INSUFFICIENT_BARS_FOR_SIGNAL",
    market_closed_token: str = "MARKET_CLOSED_OR_NO_BARS",
    auth_failed_token: str = "MARKET_DATA_AUTH_FAILED",
    provider_error_token: str = "MARKET_DATA_PROVIDER_ERROR",
) -> tuple[str, list[str]]:
    """Pure rule matrix returning ``(status, rationale_lines)``.

    Precedence (top wins):
    1. real signals emitted OR real opportunity count increased
       → PROGRESSING.
    2. AUTH_FAILED in last 2 successful runs → STUCK_AUTH.
    3. PROVIDER_ERROR in last 2 successful runs → STUCK_PROVIDER_ERROR.
    4. INSUFFICIENT_BARS dominant in last 2 successful runs
       → STUCK_INSUFFICIENT_BARS.
    5. MARKET_CLOSED_OR_NO_BARS dominant in last 2 successful runs
       AND now is inside US market session → STUCK_NO_MARKET_DATA.
    6. REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL dominant in last 3
       successful runs → STUCK_GENERATOR_TOO_RESTRICTIVE.
    7. <2 successful runs available → REQUIRES_MORE_RUNS.
    8. Otherwise → HEALTHY_BUT_NO_SIGNALS_YET.

    Standing markers are returned by the caller (not encoded here).
    """
    rationale: list[str] = []
    succ = _success_runs(history)

    # Rule 1 — progressing.
    if _real_count_increased(history):
        rationale.append(
            "real_market_opportunities_count increased between last two runs")
        return AUTOMATED_EVIDENCE_PROGRESSING, rationale
    if succ:
        latest_diag = (succ[-1].get("diagnostic_token_counts") or {})
        if int(latest_diag.get(real_signal_emitted_token, 0) or 0) > 0:
            rationale.append(
                f"latest run emitted {latest_diag[real_signal_emitted_token]}"
                f" {real_signal_emitted_token} records")
            return AUTOMATED_EVIDENCE_PROGRESSING, rationale

    # Rule 2 — auth.
    if _token_present_consecutively(
            history, auth_failed_token,
            count=AUTH_FAILED_TICKS_REQUIRED):
        rationale.append(
            f"{auth_failed_token} present in last "
            f"{AUTH_FAILED_TICKS_REQUIRED} successful runs")
        return AUTOMATED_EVIDENCE_STUCK_AUTH, rationale

    # Rule 3 — provider error.
    if _token_present_consecutively(
            history, provider_error_token,
            count=PROVIDER_ERROR_TICKS_REQUIRED):
        rationale.append(
            f"{provider_error_token} present in last "
            f"{PROVIDER_ERROR_TICKS_REQUIRED} successful runs")
        return AUTOMATED_EVIDENCE_STUCK_PROVIDER_ERROR, rationale

    # Rule 4 — insufficient bars.
    if _token_dominant_consecutively(
            history, insufficient_bars_token,
            count=INSUFFICIENT_BARS_TICKS_REQUIRED):
        rationale.append(
            f"{insufficient_bars_token} dominates last "
            f"{INSUFFICIENT_BARS_TICKS_REQUIRED} successful runs")
        return AUTOMATED_EVIDENCE_STUCK_INSUFFICIENT_BARS, rationale

    # Rule 5 — market closed inside session.
    if _token_dominant_consecutively(
            history, market_closed_token,
            count=NO_MARKET_DATA_TICKS_REQUIRED,
            require_session=True, now=now):
        rationale.append(
            f"{market_closed_token} dominates last "
            f"{NO_MARKET_DATA_TICKS_REQUIRED} successful runs "
            f"during US market session")
        return AUTOMATED_EVIDENCE_STUCK_NO_MARKET_DATA, rationale

    # Rule 6 — generator too restrictive.
    if _token_dominant_consecutively(
            history, no_signal_token,
            count=GENERATOR_TOO_RESTRICTIVE_TICKS):
        rationale.append(
            f"{no_signal_token} dominates last "
            f"{GENERATOR_TOO_RESTRICTIVE_TICKS} successful runs")
        return AUTOMATED_EVIDENCE_STUCK_GENERATOR_TOO_RESTRICTIVE, rationale

    # Rule 7 — not enough runs.
    if len(succ) < MIN_SUCCESS_RUNS_FOR_TREND:
        rationale.append(
            f"only {len(succ)} successful runs in history; need "
            f"≥{MIN_SUCCESS_RUNS_FOR_TREND} for trend evaluation")
        return AUTOMATED_EVIDENCE_REQUIRES_MORE_RUNS, rationale

    # Rule 8 — fall-through.
    rationale.append(
        "successful runs are healthy; no signals emitted yet")
    return AUTOMATED_EVIDENCE_HEALTHY_BUT_NO_SIGNALS_YET, rationale


# ─── First-real-record status ────────────────────────────────────────────────

def scan_records_for_real_market_record(
    repo_root: Path,
) -> dict | None:
    """Return the FIRST chronologically-encountered REAL_MARKET_DATA
    record, or None if none exist. Pure on-disk scan — never fabricates.
    """
    evidence_dir = repo_root / "learning-loop" / "shadow_evidence"
    if not evidence_dir.exists():
        return None
    # Records files: ``records_YYYY-MM-DD.jsonl``. Sort by filename so
    # the chronologically-earliest date wins for "first" semantics.
    candidates = sorted(evidence_dir.glob("records_*.jsonl"))
    for path in candidates:
        for rec in _read_jsonl(path):
            if rec.get("evidence_quality") == "REAL_MARKET_DATA":
                return rec
    return None


def build_first_real_record_status(
    *,
    repo_root: Path = REPO_ROOT,
    progress_status: str,
    rationale: list[str],
    history: list[dict],
    now_iso: str | None = None,
) -> dict:
    """Render the ``first_real_market_record_status.json`` payload."""
    first = scan_records_for_real_market_record(repo_root)
    seen = first is not None
    succ = _success_runs(history)
    diag_dominant: str | None = None
    if succ:
        last_diag = succ[-1].get("diagnostic_token_counts") or {}
        if last_diag:
            diag_dominant = max(
                last_diag.items(), key=lambda kv: kv[1])[0]
    payload = {
        "version":                            "v3.27.2",
        "generated_at_iso":                   now_iso or
            datetime.now(timezone.utc).isoformat(),
        "first_real_market_record_seen":      seen,
        "first_real_market_record_at":        (
            first.get("timestamp_iso") if first else None),
        "first_real_market_symbol":           (
            first.get("symbol") if first else None),
        "first_real_market_strategy":         (
            first.get("strategy") if first else None),
        "current_waiting_reason":             progress_status,
        "current_waiting_rationale":          rationale,
        "diagnostic_dominant_token":          diag_dominant,
        "runs_observed":                      len(history),
        "successful_runs_observed":           len(succ),
        "next_expected_automation_window":    (
            "next scheduled cron tick at :35 each hour during US "
            "market session (cron `35 13-19 * * 1-5` UTC)"),
        "safety": {
            "broker_paper_canary_still_blocked": True,
            "live_trading_unsupported":          True,
        },
        "standing_markers": [
            BROKER_PAPER_CANARY_STILL_BLOCKED,
            LIVE_TRADING_UNSUPPORTED,
        ],
    }
    return payload


def write_first_real_record_status(
    payload: dict,
    *,
    path: Path = FIRST_RECORD_STATUS,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Automated shadow evidence progress monitor.",
    )
    parser.add_argument(
        "--history-path", default=str(HEALTH_HISTORY),
        help="Path to the JSONL workflow_health history file.",
    )
    parser.add_argument(
        "--no-append", action="store_true",
        help="Do not append a new snapshot to the history; only "
              "re-evaluate progress from existing entries.",
    )
    args = parser.parse_args(argv)

    refuse = _refuse_if_broker_enabled()
    if refuse is not None:
        print(json.dumps({"status": refuse}))
        return 1

    latest = _safe_load_json(HEALTH_LATEST)
    history_path = Path(args.history_path)

    appended: dict = {}
    if not args.no_append:
        appended = append_health_snapshot_to_history(
            latest, history_path=history_path)

    history = _read_jsonl(history_path)
    now = datetime.now(timezone.utc)
    status, rationale = evaluate_progress(history, now=now)
    payload = build_first_real_record_status(
        progress_status=status,
        rationale=rationale,
        history=history,
    )
    write_first_real_record_status(payload)

    summary = {
        "status":           "MONITORED",
        "version":          "v3.27.2",
        "progress_status":  status,
        "rationale":        rationale,
        "history_path":     str(history_path.relative_to(REPO_ROOT)
                                  if history_path.is_absolute() else history_path),
        "history_entries":  len(history),
        "appended_entry":   bool(appended),
        "first_real_record_seen": payload["first_real_market_record_seen"],
        "standing_markers": [
            BROKER_PAPER_CANARY_STILL_BLOCKED,
            LIVE_TRADING_UNSUPPORTED,
        ],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
