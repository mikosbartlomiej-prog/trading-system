#!/usr/bin/env python3
"""scripts/build_monitor_emission_status.py — v3.23 Agent 3C (2026-06-15).

Per-monitor runtime emission status reporter.

For each of the 10 in-scope monitors:

  * Source path
  * Last-modified commit (git log -1 -- <monitor.py>)
  * AST scan of monitor source: does the file contain a call to
    ``emit_signal_opportunity`` (directly OR via the ``emit_monitor_signal``
    thin wrapper)? (Y/N)
  * Recent opportunity_ledger rows attributed to this monitor over the last
    7 days. The ledger row schema (v3.20.0) does not carry an explicit
    ``source_monitor`` field, so we use a STRATEGY -> MONITOR map below to
    attribute rows.
  * Last ledger row timestamp for this monitor.
  * Most recent autonomy JSONL event referencing the monitor name (if any).
  * Verdict:
      - ACTIVE              — wired AND has ledger rows in the 7-day window
      - WIRED_BUT_NOT_FIRING — wired BUT zero ledger rows in the window
      - DORMANT             — not wired AND zero ledger rows
      - NOT_APPLICABLE      — monitor is an exit / dispatch lane that
                              legitimately never emits opportunities

Outputs:
  - learning-loop/shadow_evidence/monitor_emission_status_latest.json
  - docs/MONITOR_EMISSION_STATUS.md  (standing markers footer included)

HARD SAFETY
-----------
This script is observability-only:

  * Never imports ``alpaca_orders``
  * Never imports ``broker_paper_adapter``
  * Never calls ``submit_order`` / ``place_order`` / ``safe_close``
  * Never mutates any state file (writes ARTEFACTS, not runtime state)
  * Never reads or sets LIVE_TRADING / EDGE_GATE_ENABLED / ALLOW_BROKER_PAPER

EDGE_GATE_ENABLED = false (unchanged).
ALLOW_BROKER_PAPER = false (unchanged).
LIVE_TRADING_UNSUPPORTED.
NO_ORDER_PLACEMENT.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── Monitor catalogue ──────────────────────────────────────────────────────

# 10 monitors in scope. Path is relative to the repo root.
MONITORS: tuple[tuple[str, str], ...] = (
    ("price-monitor",         "price-monitor/monitor.py"),
    ("options-monitor",       "options-monitor/monitor.py"),
    ("crypto-monitor",        "crypto-monitor/monitor.py"),
    ("defense-monitor",       "defense-monitor/monitor.py"),
    ("twitter-monitor",       "twitter-monitor/monitor.py"),
    ("reddit-monitor",        "reddit-monitor/monitor.py"),
    ("geo-monitor",           "geo-monitor/monitor.py"),
    ("politician-monitor",    "politician-monitor/monitor.py"),
    ("exit-monitor",          "exit-monitor/monitor.py"),
    ("options-exit-monitor",  "options-exit-monitor/monitor.py"),
)


# Exit / dispatch lanes that legitimately never emit opportunity signals.
# These are still inspected for wiring marker presence and their ledger
# attribution is best-effort, but a NOT_APPLICABLE verdict is allowed.
NOT_APPLICABLE_MONITORS: frozenset[str] = frozenset({
    "exit-monitor",
    "options-exit-monitor",
})


# Strategy -> monitor attribution map.
# The ledger row schema persisted today (v3.20.0) carries ``strategy`` but
# not ``source_monitor``. This map is the bridge.
#
# Sources for the entries:
#   * crypto-monitor/monitor.py: "crypto-momentum", "crypto-breakdown",
#     "crypto-oversold-bounce"
#   * price-monitor/monitor.py: "momentum-long", "leveraged-etf"
#   * options-monitor/monitor.py: "options-momentum"
#   * defense-monitor/monitor.py: "defense-news"
#   * reddit-monitor/monitor.py: "reddit-sentiment"
#   * twitter-monitor/monitor.py: "twitter-*"
#   * geo-monitor/monitor.py: "geo-news"
#   * politician-monitor/monitor.py: "politician-djt", "politician-tracker"
#   * exit-monitor/monitor.py: "exit-monitor" (operator-level)
#   * options-exit-monitor/monitor.py: "options-exit"
STRATEGY_TO_MONITOR: dict[str, str] = {
    "crypto-momentum":         "crypto-monitor",
    "crypto-breakdown":        "crypto-monitor",
    "crypto-oversold-bounce":  "crypto-monitor",
    "momentum-long":           "price-monitor",
    "leveraged-etf":           "price-monitor",
    "options-momentum":        "options-monitor",
    "defense-news":            "defense-monitor",
    "reddit-sentiment":        "reddit-monitor",
    "geo-news":                "geo-monitor",
    "politician-djt":          "politician-monitor",
    "politician-tracker":      "politician-monitor",
    "exit-monitor":            "exit-monitor",
    "options-exit":            "options-exit-monitor",
}


# ─── Helpers ────────────────────────────────────────────────────────────────


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _git_last_modified_iso(rel_path: str) -> Optional[str]:
    """Best-effort: git log -1 --format=%cI -- <rel_path>."""
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%cI", "--", rel_path],
            cwd=str(_REPO_ROOT),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip()
        return out or None
    except Exception:
        return None


def _git_last_modified_sha(rel_path: str) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%H", "--", rel_path],
            cwd=str(_REPO_ROOT),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip()
        return out or None
    except Exception:
        return None


def _emit_marker_in_source(src: str) -> bool:
    """Match the v3.22 monitor-wiring test contract.

    A monitor is considered "wired" when ANY of these substrings appear:
      - ``emit_signal_opportunity``
      - ``emit_monitor_signal``
    The ``NOT_APPLICABLE`` header is handled separately because we want to
    surface dispatch-only monitors explicitly rather than collapsing them
    into ``wired=True``.
    """
    if not src:
        return False
    return ("emit_signal_opportunity" in src) or ("emit_monitor_signal" in src)


def _not_applicable_header_in_source(src: str) -> bool:
    return bool(src) and "NOT_APPLICABLE" in src


def _attribute_monitor(strategy: str) -> Optional[str]:
    if not strategy:
        return None
    if strategy in STRATEGY_TO_MONITOR:
        return STRATEGY_TO_MONITOR[strategy]
    # twitter-* prefixes are dynamic per category.
    if strategy.startswith("twitter-"):
        return "twitter-monitor"
    return None


def _iter_ledger_rows_for_window(now: datetime, window_days: int):
    """Yield (row, monitor_name_or_none) for ledger files inside the window."""
    led_dir = _REPO_ROOT / "learning-loop" / "opportunity_ledger"
    if not led_dir.exists():
        return
    cutoff = (now - timedelta(days=window_days)).date()
    for path in sorted(led_dir.glob("*.jsonl")):
        try:
            file_date = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except Exception:
            continue
        if file_date < cutoff:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            strategy = (row.get("strategy") or "").strip()
            monitor = _attribute_monitor(strategy)
            yield row, monitor


def _scan_ledger(now: datetime, window_days: int) -> dict:
    """Per-monitor counts + last_timestamp over the window."""
    counts: dict[str, int] = {name: 0 for name, _ in MONITORS}
    last_ts: dict[str, Optional[str]] = {name: None for name, _ in MONITORS}
    unattributed = 0
    total_rows = 0
    for row, monitor in _iter_ledger_rows_for_window(now, window_days):
        total_rows += 1
        if monitor is None:
            unattributed += 1
            continue
        counts[monitor] = counts.get(monitor, 0) + 1
        ts = str(row.get("timestamp") or "")
        if ts:
            cur = last_ts.get(monitor)
            if cur is None or ts > cur:
                last_ts[monitor] = ts
    return {
        "counts":        counts,
        "last_ts":       last_ts,
        "unattributed":  unattributed,
        "total_rows":    total_rows,
    }


def _scan_autonomy(now: datetime, window_days: int) -> dict[str, Optional[str]]:
    """Best-effort: latest JSONL line referencing each monitor name string."""
    last: dict[str, Optional[str]] = {name: None for name, _ in MONITORS}
    auto_dir = _REPO_ROOT / "journal" / "autonomy"
    if not auto_dir.exists():
        return last
    cutoff = (now - timedelta(days=window_days)).date()
    for path in sorted(auto_dir.glob("*.jsonl"), reverse=True):
        try:
            file_date = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except Exception:
            continue
        if file_date < cutoff:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            for name, _ in MONITORS:
                if name in line and last[name] is None:
                    last[name] = line[:240]
    return last


# ─── Verdict logic ──────────────────────────────────────────────────────────


def _verdict(name: str, wired: bool, ledger_count: int) -> str:
    if name in NOT_APPLICABLE_MONITORS:
        # Exit / dispatch monitors. If they happen to attribute rows we
        # still report ACTIVE, otherwise NOT_APPLICABLE.
        if ledger_count > 0:
            return "ACTIVE"
        return "NOT_APPLICABLE"
    if wired and ledger_count > 0:
        return "ACTIVE"
    if wired:
        return "WIRED_BUT_NOT_FIRING"
    return "DORMANT"


# ─── Core evaluate ──────────────────────────────────────────────────────────


def evaluate(now: datetime | None = None,
             window_days: int = 7) -> dict:
    """Pure evaluation — no I/O side-effects.

    Returns a structured dict that ``_render_markdown`` and the JSON
    artefact writer consume.
    """
    now = now or datetime.now(timezone.utc)
    ledger = _scan_ledger(now, window_days)
    autonomy_last = _scan_autonomy(now, window_days)

    rows: list[dict] = []
    counts = {
        "ACTIVE":               0,
        "WIRED_BUT_NOT_FIRING": 0,
        "DORMANT":              0,
        "NOT_APPLICABLE":       0,
    }
    for name, rel_path in MONITORS:
        src_path = _REPO_ROOT / rel_path
        src = _read_file(src_path)
        wired = _emit_marker_in_source(src)
        not_applicable_header = _not_applicable_header_in_source(src)
        ledger_count = int(ledger["counts"].get(name, 0))
        last_ts = ledger["last_ts"].get(name)
        verdict = _verdict(name, wired, ledger_count)
        # Surface the NOT_APPLICABLE header explicitly if present.
        if not_applicable_header and name not in NOT_APPLICABLE_MONITORS:
            verdict = "NOT_APPLICABLE"
        counts[verdict] = counts.get(verdict, 0) + 1
        rows.append({
            "monitor":                       name,
            "source_path":                   rel_path,
            "exists":                        src_path.exists(),
            "wired_emit_path":               wired,
            "carries_not_applicable_header": not_applicable_header,
            "last_modified_commit_iso":      _git_last_modified_iso(rel_path),
            "last_modified_commit_sha":      _git_last_modified_sha(rel_path),
            "ledger_rows_in_window":         ledger_count,
            "ledger_window_days":            window_days,
            "last_ledger_timestamp":         last_ts,
            "last_autonomy_reference":       autonomy_last.get(name),
            "verdict":                       verdict,
        })

    return {
        "generated_at_iso":     now.isoformat(),
        "window_days":          window_days,
        "summary":              {
            "active":                counts.get("ACTIVE", 0),
            "wired_but_not_firing":  counts.get("WIRED_BUT_NOT_FIRING", 0),
            "dormant":               counts.get("DORMANT", 0),
            "not_applicable":        counts.get("NOT_APPLICABLE", 0),
            "total":                 len(MONITORS),
            "unattributed_rows":     ledger["unattributed"],
            "total_rows_scanned":    ledger["total_rows"],
        },
        "monitors":             rows,
        "safety": {
            "edge_gate_enabled":         False,
            "allow_broker_paper":        False,
            "live_trading_unsupported":  True,
            "no_order_placement":        True,
        },
        "standing_markers": [
            "EDGE_GATE_ENABLED = false",
            "ALLOW_BROKER_PAPER = false",
            "LIVE_TRADING_UNSUPPORTED",
            "NO_ORDER_PLACEMENT",
        ],
        "version":              "v3.23.0",
    }


# ─── Renderers ──────────────────────────────────────────────────────────────


def _render_markdown(report: dict, head_sha: str | None = None) -> str:
    lines: list[str] = []
    lines.append("# Monitor Emission Status")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at_iso']}`")
    if head_sha:
        lines.append(f"- HEAD: `{head_sha}`")
    lines.append(f"- Window: last `{report['window_days']}` days")
    lines.append(f"- Version: `{report['version']}`")
    lines.append("")
    s = report["summary"]
    lines.append(
        f"- Summary: ACTIVE={s['active']}, "
        f"WIRED_BUT_NOT_FIRING={s['wired_but_not_firing']}, "
        f"DORMANT={s['dormant']}, "
        f"NOT_APPLICABLE={s['not_applicable']}, "
        f"TOTAL={s['total']}"
    )
    lines.append(
        f"- Ledger rows scanned: {s['total_rows_scanned']}; "
        f"unattributed (no strategy->monitor map): {s['unattributed_rows']}"
    )
    lines.append("")
    lines.append("## Per-monitor table")
    lines.append("")
    lines.append("| Monitor | Wired | Ledger rows (window) | Last ledger ts | Verdict |")
    lines.append("|---|---|---|---|---|")
    for row in report["monitors"]:
        wired_cell = "Y" if row["wired_emit_path"] else "N"
        last_ts = row.get("last_ledger_timestamp") or "—"
        lines.append(
            f"| `{row['monitor']}` "
            f"| {wired_cell} "
            f"| {row['ledger_rows_in_window']} "
            f"| {last_ts} "
            f"| **{row['verdict']}** |"
        )
    lines.append("")
    lines.append("## Strategy -> monitor attribution map")
    lines.append("")
    lines.append("| Strategy | Monitor |")
    lines.append("|---|---|")
    for strat, mon in sorted(STRATEGY_TO_MONITOR.items()):
        lines.append(f"| `{strat}` | `{mon}` |")
    lines.append("")
    # Standing markers footer (verbatim — tests grep for these).
    lines.append("## Standing markers")
    lines.append("")
    lines.append("- EDGE_GATE_ENABLED = false")
    lines.append("- ALLOW_BROKER_PAPER = false")
    lines.append("- LIVE_TRADING_UNSUPPORTED")
    lines.append("- NO_ORDER_PLACEMENT")
    lines.append("")
    lines.append(
        "_This report is observability-only. It never places orders, "
        "never imports `alpaca_orders`, never mutates runtime state._"
    )
    lines.append("")
    return "\n".join(lines)


def _current_head_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_REPO_ROOT),
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip()
        return out or None
    except Exception:
        return None


def _write_artefacts(report: dict) -> None:
    json_path = _REPO_ROOT / "learning-loop" / "shadow_evidence" / "monitor_emission_status_latest.json"
    md_path   = _REPO_ROOT / "docs" / "MONITOR_EMISSION_STATUS.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_render_markdown(report, head_sha=_current_head_sha()), encoding="utf-8")


# ─── CLI ────────────────────────────────────────────────────────────────────


def _parse_as_of(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as e:
        raise SystemExit(f"--as-of parse failed: {e}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Per-monitor emission status reporter (v3.23 Agent 3C)"
    )
    p.add_argument("--as-of", type=str, default=None,
                   help="Override 'now' (ISO-8601) for tests")
    p.add_argument("--window-days", type=int, default=7,
                   help="Ledger lookback window in days (default 7)")
    p.add_argument("--json", action="store_true",
                   help="Print the report as JSON to stdout")
    p.add_argument("--no-write", action="store_true",
                   help="Skip writing artefact files (for tests)")
    args = p.parse_args(argv)

    now = _parse_as_of(args.as_of)
    report = evaluate(now=now, window_days=int(args.window_days))

    if not args.no_write:
        try:
            _write_artefacts(report)
        except Exception as e:
            print(f"  artefact write failed (non-fatal): {e}")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_markdown(report, head_sha=_current_head_sha()))

    return 0


if __name__ == "__main__":
    sys.exit(main())
