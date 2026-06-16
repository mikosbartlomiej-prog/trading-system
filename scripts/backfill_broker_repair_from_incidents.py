#!/usr/bin/env python3
"""v3.29 ETAP 3 (2026-06-16) — Backfill broker_repair_required from past P13 events.

CONTRACT (do not loosen)
------------------------
This script is **read-only** w.r.t. the broker. It NEVER:

* calls the broker,
* imports ``alpaca_orders``,
* makes any network call,
* places, cancels, or modifies orders,
* clears safe_mode,
* mutates risk thresholds,
* flips ``LIVE_TRADING`` / ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED``.

PURPOSE
-------
After the v3.28 deploy that introduced ``shared/broker_repair_required.py``
and the v3.29 P13-retry-storm containment, several symbols (notably
AVAXUSD on 2026-06-15) already had a real broker-repair incident in
the audit history but were never marked in the quarantine state
because the containment module didn't exist at the time. This script
scans the last 30 days of ``journal/autonomy/*.jsonl`` for
``P13_BRACKET_INTERLOCK`` CRITICAL events and marks the
corresponding (symbol, day) pairs as ``BROKER_REPAIR_REQUIRED_BACKFILLED``
unless an operator marker already explicitly cleared them.

Decision per (symbol, day)
--------------------------
1. ``operator_repair_state.has_repair_confirmation(symbol)`` is True
   → SKIP (operator already handled it).
2. ``broker_repair_required`` already has an entry for ``symbol``
   → SKIP (idempotent re-run).
3. failed_close_count for (symbol, day) >= 3 AND no SAFE_MODE_EXITED
   on that day → mark via
   ``broker_repair_required.mark_repair_required`` with
   ``incident_type="P13_BRACKET_INTERLOCK_BACKFILLED"``.
4. Otherwise → SKIP (not enough evidence; keep going).

Outputs
-------
* ``docs/BROKER_REPAIR_BACKFILL_STATUS.md`` (table per (symbol, day)
  with action taken).
* On disk: ``learning-loop/broker_repair_required_latest.json``
  receives new entries from ``mark_repair_required`` (atomic write
  handled by the underlying module).

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT``
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# ── Standing invariants (asserted by tests) ───────────────────────────────────
LIVE_TRADING_UNSUPPORTED = True
NO_ORDER_PLACEMENT = True
NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT = True
EDGE_GATE_ENABLED = False
ALLOW_BROKER_PAPER = False


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


# Lazy imports so tests can monkeypatch via sys.modules.
def _get_broker_repair_module():
    import broker_repair_required  # type: ignore
    return broker_repair_required


def _get_operator_repair_module():
    import operator_repair_state  # type: ignore
    return operator_repair_state


DEFAULT_LOOKBACK_DAYS = 30
P13_FAIL_THRESHOLD = 3   # ≥3 failed closes → mark
INCIDENT_TYPE = "P13_BRACKET_INTERLOCK_BACKFILLED"

# Symbols pattern used to harvest mentions from event payloads.
# We accept e.g. ``AVAXUSD``, ``ETHUSD``, ``AAPL`` and `BTC/USD`.
_SYMBOL_PAT = re.compile(r"\b([A-Z]{2,6}(?:/[A-Z]{2,6})?)\b")


# ── Path helpers ──────────────────────────────────────────────────────────────

def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "journal" / "autonomy"


def _docs_dir() -> Path:
    env = os.environ.get("BROKER_REPAIR_BACKFILL_DOCS_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "docs"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# ── Audit scanning ────────────────────────────────────────────────────────────

@dataclass
class P13DaySummary:
    symbol: str
    day_iso: str
    failed_close_count: int = 0
    alpaca_403_count: int = 0
    safe_mode_entered_count: int = 0
    safe_mode_exited_count: int = 0
    samples: list[dict] = field(default_factory=list)


def _iter_jsonl(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _row_has_p13(row: dict) -> bool:
    """True iff the row evidences a P13 bracket-interlock event."""
    text_fields = [
        str(row.get("decision_type") or ""),
        str(row.get("reason") or ""),
        str(row.get("action_taken") or ""),
        str(row.get("decision") or ""),
        str(row.get("pattern") or ""),
    ]
    blob = " | ".join(text_fields).upper()
    if "P13" in blob and ("BRACKET" in blob or "INTERLOCK" in blob):
        return True
    # incident_pattern_detector flags pattern explicitly
    pattern = str(row.get("pattern") or "").lower()
    return "p13" in pattern


def _row_is_failed_close(row: dict) -> bool:
    """True iff the row evidences a failed close attempt (the P13 cascade marker)."""
    decision = str(row.get("decision") or "").upper()
    decision_type = str(row.get("decision_type") or "").upper()
    result = str(row.get("result") or "").lower()
    status = str(row.get("status") or "").lower()
    action_taken = str(row.get("action_taken") or "").lower()
    errors_blob = " ".join(str(x) for x in (row.get("errors") or [])).lower()
    reason = str(row.get("reason") or "").lower()
    blob = " ".join([action_taken, errors_blob, reason])

    is_close_attempt = (
        "CLOSE_POSITION" in decision_type
        or "EMERGENCY_CLOSE" in decision_type
        or "CLOSE_POSITION" in decision
        or "safe_close" in action_taken.lower()
        or "close-to-flat" in action_taken.lower()
    )
    failed = (
        "FAILED" in decision.upper()
        or "fail" in result
        or "fail" in status
        or "403" in blob
        or "insufficient" in blob
    )
    return is_close_attempt and failed


def _row_is_alpaca_403(row: dict) -> bool:
    blob = " ".join([
        str(row.get("reason") or ""),
        str(row.get("action_taken") or ""),
        " ".join(str(x) for x in (row.get("errors") or [])),
    ]).lower()
    return "403" in blob or "insufficient balance" in blob or "insufficient_balance" in blob


def _symbols_from_row(row: dict) -> set[str]:
    """Best-effort symbol extraction from an audit row."""
    syms: set[str] = set()
    for sym in (row.get("affected_symbols") or []):
        s = str(sym).strip().upper()
        if s:
            syms.add(s)
    # Single-symbol field
    s = row.get("symbol")
    if s:
            syms.add(str(s).strip().upper())
    # Reason/action text — fallback heuristic
    for blob in (str(row.get("reason") or ""), str(row.get("action_taken") or "")):
        # Only harvest from text that already passed P13/close gates.
        for m in _SYMBOL_PAT.findall(blob):
            up = m.upper()
            # Exclude obvious noise tokens.
            if up in {"P13", "P01", "P02", "USD", "EUR", "GBP", "FAILED", "OK", "ALPACA"}:
                continue
            syms.add(up)
    return syms


def _row_day_iso(row: dict) -> Optional[str]:
    ts = str(row.get("timestamp") or row.get("ts_iso") or "")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except (TypeError, ValueError):
        return None


def scan_p13_events(*, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> dict[tuple[str, str], P13DaySummary]:
    """Aggregate failed-close events keyed by (symbol, day_iso)."""
    summaries: dict[tuple[str, str], P13DaySummary] = {}
    d = _audit_dir()
    if not d.exists():
        return summaries

    cutoff = _now().date() - timedelta(days=int(lookback_days))
    for path in sorted(d.glob("*.jsonl")):
        try:
            day_dt = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day_dt < cutoff:
            continue

        for row in _iter_jsonl(path):
            day_iso = _row_day_iso(row) or path.stem

            is_p13 = _row_has_p13(row)
            is_failed_close = _row_is_failed_close(row)
            is_403 = _row_is_alpaca_403(row)
            is_safe_enter = str(row.get("decision_type") or "") == "SAFE_MODE_ENTERED"
            is_safe_exit  = str(row.get("decision_type") or "") == "SAFE_MODE_EXITED"

            # Be inclusive: any row that contains either P13 marker, failed
            # close, 403, or SAFE_MODE_* transition is interesting.
            if not (is_p13 or is_failed_close or is_403 or is_safe_enter or is_safe_exit):
                continue

            for sym in _symbols_from_row(row) or {""}:
                if not sym:
                    continue
                key = (sym, day_iso)
                summary = summaries.setdefault(
                    key,
                    P13DaySummary(symbol=sym, day_iso=day_iso),
                )
                if is_failed_close:
                    summary.failed_close_count += 1
                if is_403:
                    summary.alpaca_403_count += 1
                if is_safe_enter:
                    summary.safe_mode_entered_count += 1
                if is_safe_exit:
                    summary.safe_mode_exited_count += 1
                if len(summary.samples) < 3:
                    summary.samples.append({
                        "decision_type": row.get("decision_type"),
                        "reason":        (str(row.get("reason") or "")[:140]),
                    })
    return summaries


# ── Decision logic ────────────────────────────────────────────────────────────

@dataclass
class BackfillAction:
    symbol: str
    day_iso: str
    action: str         # MARKED / SKIPPED_OPERATOR_MARKER / SKIPPED_ALREADY_MARKED / SKIPPED_INSUFFICIENT
    reason: str
    failed_close_count: int
    safe_mode_entered_count: int
    safe_mode_exited_count: int


def _decide(summary: P13DaySummary, *, brr_mod, operator_mod) -> BackfillAction:
    sym = summary.symbol
    # Rule 1: operator marker takes precedence.
    try:
        has_marker = bool(operator_mod.has_repair_confirmation(sym))
    except Exception:
        has_marker = False
    if has_marker:
        return BackfillAction(
            symbol=sym, day_iso=summary.day_iso, action="SKIPPED_OPERATOR_MARKER",
            reason="operator marker exists",
            failed_close_count=summary.failed_close_count,
            safe_mode_entered_count=summary.safe_mode_entered_count,
            safe_mode_exited_count=summary.safe_mode_exited_count,
        )

    # Rule 2: already marked → idempotent.
    try:
        already = bool(brr_mod.is_repair_required(sym))
    except Exception:
        already = False
    if already:
        return BackfillAction(
            symbol=sym, day_iso=summary.day_iso, action="SKIPPED_ALREADY_MARKED",
            reason="symbol already in broker_repair_required state",
            failed_close_count=summary.failed_close_count,
            safe_mode_entered_count=summary.safe_mode_entered_count,
            safe_mode_exited_count=summary.safe_mode_exited_count,
        )

    # Rule 3: enough evidence + no exit → mark.
    if summary.failed_close_count >= P13_FAIL_THRESHOLD and summary.safe_mode_exited_count == 0:
        return BackfillAction(
            symbol=sym, day_iso=summary.day_iso, action="MARKED",
            reason=(f"failed_close_count={summary.failed_close_count} >= {P13_FAIL_THRESHOLD} "
                    f"AND no SAFE_MODE_EXITED on day"),
            failed_close_count=summary.failed_close_count,
            safe_mode_entered_count=summary.safe_mode_entered_count,
            safe_mode_exited_count=summary.safe_mode_exited_count,
        )

    return BackfillAction(
        symbol=sym, day_iso=summary.day_iso, action="SKIPPED_INSUFFICIENT",
        reason=(f"failed_close_count={summary.failed_close_count} < {P13_FAIL_THRESHOLD} "
                f"or SAFE_MODE_EXITED_count={summary.safe_mode_exited_count} > 0"),
        failed_close_count=summary.failed_close_count,
        safe_mode_entered_count=summary.safe_mode_entered_count,
        safe_mode_exited_count=summary.safe_mode_exited_count,
    )


def _worst_day_per_symbol(
    summaries: dict[tuple[str, str], P13DaySummary],
) -> dict[str, P13DaySummary]:
    """Reduce (symbol, day) → (symbol → worst-day summary).

    "Worst" = highest ``failed_close_count``. Tie-breaker = most recent
    day. This lets the decision logic act on the day that actually
    triggered the repair-required condition (e.g. 2026-06-15 for AVAXUSD
    with 208 failed closes), not the earliest day in the lookback
    window (which often has fewer events).
    """
    worst: dict[str, P13DaySummary] = {}
    for (sym, _day), summary in summaries.items():
        current = worst.get(sym)
        if current is None:
            worst[sym] = summary
            continue
        if summary.failed_close_count > current.failed_close_count:
            worst[sym] = summary
        elif (summary.failed_close_count == current.failed_close_count
              and summary.day_iso > current.day_iso):
            worst[sym] = summary
    return worst


def _aggregate_safe_mode_exited(
    summaries: dict[tuple[str, str], P13DaySummary],
) -> dict[str, int]:
    """Total SAFE_MODE_EXITED events per symbol across the lookback."""
    totals: dict[str, int] = defaultdict(int)
    for (sym, _day), summary in summaries.items():
        totals[sym] += summary.safe_mode_exited_count
    return totals


def run_backfill(*, lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                 dry_run: bool = False) -> list[BackfillAction]:
    """Run the backfill once. Returns a list of actions taken.

    Aggregation contract
    --------------------
    For each symbol we (a) pick the WORST (highest failed_close_count)
    day from the lookback window for the decision, and (b) check
    SAFE_MODE_EXITED *across all days* (i.e. "did the operator at
    any point actually clear safe_mode?"). This prevents an earlier
    low-count day from preempting a later high-count day's mark.
    """
    brr = _get_broker_repair_module()
    ors = _get_operator_repair_module()
    summaries = scan_p13_events(lookback_days=lookback_days)
    actions: list[BackfillAction] = []

    worst_per_symbol = _worst_day_per_symbol(summaries)
    exits_per_symbol = _aggregate_safe_mode_exited(summaries)

    # Emit one decision per symbol — using the worst day, with the
    # aggregate SAFE_MODE_EXITED count substituted in so the
    # "no SAFE_MODE_EXITED in window" check works.
    for sym, summary in sorted(worst_per_symbol.items(), key=lambda x: x[0]):
        # Substitute aggregated exits so the decision rule honours
        # "did operator clear safe_mode at *any* point during the
        # lookback window".
        decision_summary = P13DaySummary(
            symbol=summary.symbol,
            day_iso=summary.day_iso,
            failed_close_count=summary.failed_close_count,
            alpaca_403_count=summary.alpaca_403_count,
            safe_mode_entered_count=summary.safe_mode_entered_count,
            safe_mode_exited_count=exits_per_symbol.get(sym, 0),
        )
        decision = _decide(decision_summary, brr_mod=brr, operator_mod=ors)
        actions.append(decision)
        if decision.action != "MARKED":
            continue
        if dry_run:
            continue
        try:
            brr.mark_repair_required(
                sym,
                incident_type=INCIDENT_TYPE,
                error=(f"backfill from audit on {summary.day_iso}: "
                       f"{summary.failed_close_count} failed closes, "
                       f"{summary.alpaca_403_count} 403s, "
                       f"{summary.safe_mode_entered_count} SAFE_MODE_ENTERED "
                       f"(no SAFE_MODE_EXITED in {lookback_days}d window)"),
                manual_action_required=(
                    "Run scripts/record_operator_repair_confirmation.py --operator-confirmed "
                    "then clear via shared/broker_repair_required.clear_repair(symbol, marker_path)."
                ),
                allowed_next_actions=("operator_marker_required",),
                safe_mode_reason=INCIDENT_TYPE,
            )
        except Exception as e:
            decision.action = "MARK_FAILED"
            decision.reason = f"{decision.reason}; mark failed: {type(e).__name__}: {e}"
    return actions


# ── Reporting ─────────────────────────────────────────────────────────────────

def _standing_markers() -> list[str]:
    return [
        "EDGE_GATE_ENABLED=false",
        "ALLOW_BROKER_PAPER=false",
        "LIVE_TRADING_UNSUPPORTED",
        "NO_ORDER_PLACEMENT",
        "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
    ]


def write_status_markdown(actions: list[BackfillAction]) -> Path:
    d = _docs_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / "BROKER_REPAIR_BACKFILL_STATUS.md"

    by_action: dict[str, int] = defaultdict(int)
    for a in actions:
        by_action[a.action] += 1

    rows = []
    for a in actions:
        rows.append(
            f"| {a.symbol} | {a.day_iso} | `{a.action}` | "
            f"{a.failed_close_count} | {a.safe_mode_entered_count} | "
            f"{a.safe_mode_exited_count} | {a.reason} |"
        )

    body = [
        "# Broker repair backfill status",
        "",
        f"_Generated at {_now_iso()} by `scripts/backfill_broker_repair_from_incidents.py`._",
        "",
        "## Summary",
        "",
        f"- Total decisions: {len(actions)}",
        *(f"- `{k}`: {v}" for k, v in sorted(by_action.items())),
        "",
        "## Per-symbol/day decisions",
        "",
        "| Symbol | Day | Action | FailedCloses | SafeModeEntered | SafeModeExited | Reason |",
        "|--------|-----|--------|--------------|-----------------|----------------|--------|",
        *rows,
        "",
        "## What this script does NOT do",
        "",
        "- It does NOT call the broker.",
        "- It does NOT close positions.",
        "- It does NOT cancel orders.",
        "- It does NOT clear `safe_mode`.",
        "- It does NOT flip any trading flag.",
        "",
        "## Standing markers",
        "",
        *(f"- `{m}`" for m in _standing_markers()),
        "",
    ]
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(body))
    return p


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="backfill_broker_repair_from_incidents.py",
        description=(
            "Read-only audit scanner that backfills broker_repair_required "
            "for past P13 incidents. Never calls the broker."
        ),
    )
    p.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS,
                   help=f"How many days back to scan (default {DEFAULT_LOOKBACK_DAYS}).")
    p.add_argument("--dry-run", default="false",
                   help="When 'true' run scanner + decide but do not mark.")
    return p.parse_args(argv)


def _str_to_bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "on"}


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    dry_run = _str_to_bool(args.dry_run)
    actions = run_backfill(lookback_days=int(args.lookback_days), dry_run=dry_run)
    md_path = write_status_markdown(actions)
    summary: dict[str, int] = defaultdict(int)
    for a in actions:
        summary[a.action] += 1
    print(f"backfill_broker_repair_from_incidents: total_decisions={len(actions)}")
    for k, v in sorted(summary.items()):
        print(f"  {k}: {v}")
    print(f"  status_markdown: {md_path}")
    if dry_run:
        print("  (dry-run mode — no marks applied)")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "P13_FAIL_THRESHOLD",
    "INCIDENT_TYPE",
    "BackfillAction",
    "P13DaySummary",
    "scan_p13_events",
    "run_backfill",
    "write_status_markdown",
    "main",
]
