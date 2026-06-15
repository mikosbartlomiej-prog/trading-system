#!/usr/bin/env python3
"""scripts/check_evidence_throughput_sla.py — v3.22 ETAP 11 (2026-06-15).

Reads the shadow-evidence counters + workflow_health_history and emits a
deterministic SLA verdict for "is the pipeline actually producing
signals / opportunities?".

Inputs (both relative to repo root):
  - learning-loop/shadow_evidence/evidence_counters_latest.json
  - learning-loop/shadow_evidence/workflow_health_history.jsonl

Definition of "signals + opportunities" for THIS sprint (no schema
guesses): we take the last N entries' counters_snapshot and look at
``completed_shadow_outcomes_count + real_market_opportunities_count +
normal_non_halt_opportunities_count`` from each snapshot AND a top-level
``signals`` / ``opportunities`` count when supplied directly inside an
entry (used by the unit tests). A cycle counts as "non-zero" iff any of
the above is positive.

SLA verdicts vs the latest N (consecutive) market-hours cycles where N=1,2,3+:
  - 0 in 1 cycle  → WARN
  - 0 in 2 cycles → FINDING_P1
  - 0 in 3+ cycles → FINDING_P0
  - a single non-zero observation resets the counter

Exit codes: 0 ok, 1 warn, 2 p1, 3 p0.

Artefacts:
  - learning-loop/shadow_evidence/throughput_sla_latest.json
  - docs/EVIDENCE_THROUGHPUT_SLA_STATUS.md

NEVER places trades. NEVER imports ``alpaca_orders``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SHADOW_DIR = _REPO_ROOT / "learning-loop" / "shadow_evidence"
EVIDENCE_LATEST_PATH = SHADOW_DIR / "evidence_counters_latest.json"
WORKFLOW_HISTORY_PATH = SHADOW_DIR / "workflow_health_history.jsonl"

OUTPUT_JSON_PATH = SHADOW_DIR / "throughput_sla_latest.json"
OUTPUT_MD_PATH   = _REPO_ROOT / "docs" / "EVIDENCE_THROUGHPUT_SLA_STATUS.md"


VERDICT_OK   = "OK"
VERDICT_WARN = "WARN"
VERDICT_P1   = "FINDING_P1"
VERDICT_P0   = "FINDING_P0"

VERDICT_EXIT_CODES = {
    VERDICT_OK:   0,
    VERDICT_WARN: 1,
    VERDICT_P1:   2,
    VERDICT_P0:   3,
}


# ─── Helpers ────────────────────────────────────────────────────────────────

def _load_json_safe(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_jsonl_safe(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def _entry_signal_opportunity_total(entry: dict) -> int:
    """Compute a single non-negative count meaning 'signals+opportunities
    seen in this cycle'.

    Test-friendly contract: if the entry has explicit top-level integer
    keys ``signals`` / ``opportunities``, use those; otherwise fall back
    to the ``counters_snapshot`` shape produced in production.
    """
    if not isinstance(entry, dict):
        return 0
    explicit = 0
    found_explicit = False
    for k in ("signals", "opportunities"):
        v = entry.get(k)
        if isinstance(v, (int, float)):
            explicit += int(v)
            found_explicit = True
    if found_explicit:
        return max(0, explicit)

    snap = entry.get("counters_snapshot") or {}
    if not isinstance(snap, dict):
        return 0
    total = 0
    for k in (
        "completed_shadow_outcomes_count",
        "real_market_opportunities_count",
        "normal_non_halt_opportunities_count",
    ):
        v = snap.get(k)
        if isinstance(v, (int, float)):
            total += int(v)
    return max(0, total)


def _consecutive_zero_count(entries: list[dict]) -> int:
    """How many CONSECUTIVE most-recent entries had zero signals.

    Walks backwards from the end. Stops at first non-zero (which
    resets the counter per spec).
    """
    n = 0
    for e in reversed(entries):
        if _entry_signal_opportunity_total(e) == 0:
            n += 1
        else:
            break
    return n


def _verdict_for_zero_count(zero_cycles: int) -> str:
    if zero_cycles <= 0:
        return VERDICT_OK
    if zero_cycles == 1:
        return VERDICT_WARN
    if zero_cycles == 2:
        return VERDICT_P1
    return VERDICT_P0


# ─── Core evaluation ────────────────────────────────────────────────────────

def evaluate(now: datetime | None = None,
              evidence_path: Path = EVIDENCE_LATEST_PATH,
              history_path: Path = WORKFLOW_HISTORY_PATH,
              max_history: int = 200) -> dict:
    now = now or datetime.now(timezone.utc)

    counters = _load_json_safe(evidence_path) or {}
    if not isinstance(counters, dict):
        counters = {}

    history = _load_jsonl_safe(history_path)
    if max_history and len(history) > max_history:
        history = history[-max_history:]

    zero_cycles = _consecutive_zero_count(history)
    verdict = _verdict_for_zero_count(zero_cycles)

    # Cross-check: if the latest evidence counter file ALSO shows nothing,
    # use it as supporting evidence. Does not change the verdict; just
    # surfaced in the report.
    counter_total = 0
    for k in (
        "completed_shadow_outcomes_count",
        "real_market_opportunities_count",
        "normal_non_halt_opportunities_count",
    ):
        v = counters.get(k)
        if isinstance(v, (int, float)):
            counter_total += int(v)

    report = {
        "generated_at_iso":     now.isoformat(),
        "history_entries_seen": len(history),
        "consecutive_zero_cycles": zero_cycles,
        "verdict":              verdict,
        "exit_code":            VERDICT_EXIT_CODES[verdict],
        "evidence_counters_total": counter_total,
        "thresholds": {
            "warn_zero_cycles": 1,
            "p1_zero_cycles":   2,
            "p0_zero_cycles":   3,
        },
        "version": "v3.22.0",
    }

    # Surface the latest cycle for diagnostics.
    if history:
        latest_entry = history[-1]
        report["latest_cycle"] = {
            "appended_at_iso":      latest_entry.get("appended_at_iso"),
            "signals_opportunities": _entry_signal_opportunity_total(latest_entry),
            "collector_status":      latest_entry.get("collector_status"),
            "workflow_conclusion":   latest_entry.get("workflow_conclusion"),
        }

    return report


# ─── Renderers ──────────────────────────────────────────────────────────────

def _render_markdown(report: dict) -> str:
    lines: list[str] = []
    lines.append("# Evidence Throughput SLA Status")
    lines.append("")
    lines.append(f"- Generated at: `{report['generated_at_iso']}`")
    lines.append(f"- Verdict: **{report['verdict']}** (exit_code={report['exit_code']})")
    lines.append(f"- Consecutive zero cycles: `{report['consecutive_zero_cycles']}`")
    lines.append(f"- History entries scanned: `{report['history_entries_seen']}`")
    lines.append(f"- evidence_counters_latest total: `{report['evidence_counters_total']}`")
    lc = report.get("latest_cycle")
    if lc:
        lines.append("")
        lines.append("## Latest cycle")
        lines.append("")
        lines.append(f"- appended_at: `{lc.get('appended_at_iso')}`")
        lines.append(f"- signals+opportunities: `{lc.get('signals_opportunities')}`")
        lines.append(f"- collector_status: `{lc.get('collector_status')}`")
        lines.append(f"- workflow_conclusion: `{lc.get('workflow_conclusion')}`")
    lines.append("")
    lines.append("## Thresholds")
    lines.append("")
    th = report["thresholds"]
    lines.append(f"- WARN at `{th['warn_zero_cycles']}` consecutive empty cycle")
    lines.append(f"- FINDING_P1 at `{th['p1_zero_cycles']}` consecutive empty cycles")
    lines.append(f"- FINDING_P0 at `{th['p0_zero_cycles']}`+ consecutive empty cycles")
    lines.append("")
    lines.append("## Standing markers")
    lines.append("")
    lines.append("- EDGE_GATE_ENABLED = false")
    lines.append("- ALLOW_BROKER_PAPER = false")
    lines.append("- LIVE_TRADING_UNSUPPORTED")
    lines.append("- NO_ORDER_PLACEMENT")
    lines.append("")
    lines.append("_This report is observability-only. It never places orders, "
                 "never imports `alpaca_orders`, never mutates runtime state._")
    lines.append("")
    return "\n".join(lines) + "\n"


def _write_artefacts(report: dict) -> None:
    OUTPUT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    OUTPUT_MD_PATH.write_text(_render_markdown(report), encoding="utf-8")


# ─── CLI ────────────────────────────────────────────────────────────────────

def _parse_as_of(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as e:
        raise SystemExit(f"--as-of parse failed: {e}")


def main() -> int:
    p = argparse.ArgumentParser(description="Evidence throughput SLA check (v3.22 ETAP 11)")
    p.add_argument("--as-of", type=str, default=None,
                   help="Override 'now' (ISO-8601) for tests")
    p.add_argument("--json", action="store_true",
                   help="Print the report as JSON to stdout")
    p.add_argument("--no-write", action="store_true",
                   help="Skip writing artefact files (for tests)")
    p.add_argument("--evidence-path", type=str, default=None,
                   help="Override evidence_counters_latest.json path")
    p.add_argument("--history-path", type=str, default=None,
                   help="Override workflow_health_history.jsonl path")
    args = p.parse_args()

    now = _parse_as_of(args.as_of)
    evidence_path = Path(args.evidence_path) if args.evidence_path else EVIDENCE_LATEST_PATH
    history_path  = Path(args.history_path)  if args.history_path  else WORKFLOW_HISTORY_PATH

    report = evaluate(
        now=now,
        evidence_path=evidence_path,
        history_path=history_path,
    )

    if not args.no_write:
        try:
            _write_artefacts(report)
        except Exception as e:
            print(f"  artefact write failed (non-fatal): {e}")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_markdown(report))

    return int(report["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
