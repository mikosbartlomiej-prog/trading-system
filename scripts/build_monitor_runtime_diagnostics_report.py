#!/usr/bin/env python3
"""v3.24 (2026-06-15) — ETAP 9 — Monitor runtime diagnostics reporter.

Reads the last 7 days of JSONL diagnostic files from
``learning-loop/monitor_runtime_diag/<YYYY-MM-DD>.jsonl``, aggregates
counts per monitor + token, and writes:

  * ``docs/MONITOR_RUNTIME_DIAGNOSTICS.md`` — human-readable matrix
  * ``learning-loop/monitor_runtime_diag_status_latest.json`` — machine
    payload for downstream agents

HARD SAFETY
-----------
Pure local I/O. No network. No broker. No paid services. Read-only on
diag files; the reporter never mutates them.
"""

from __future__ import annotations

import json
import os
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DIAG_DIR = REPO_ROOT / "learning-loop" / "monitor_runtime_diag"
LEDGER_DIR = REPO_ROOT / "learning-loop" / "opportunity_ledger"
DOCS_OUT = REPO_ROOT / "docs" / "MONITOR_RUNTIME_DIAGNOSTICS.md"
JSON_OUT = REPO_ROOT / "learning-loop" / "monitor_runtime_diag_status_latest.json"


# v3.25: 10 monitors expected in the per-monitor table.
KNOWN_MONITORS = (
    "crypto-monitor",
    "price-monitor",
    "options-monitor",
    "options-exit-monitor",
    "exit-monitor",
    "defense-monitor",
    "twitter-monitor",
    "reddit-monitor",
    "geo-monitor",
    "politician-monitor",
)


# v3.25: strategy → monitor map used for SYNTHESIZED_VIEW when no
# native diagnostic JSONL rows exist yet. Mirrors the canonical map in
# scripts/gate_distribution_report.py — keep these in sync.
STRATEGY_TO_MONITOR_SYN = {
    "crypto-momentum":             "crypto-monitor",
    "crypto-oversold-bounce":      "crypto-monitor",
    "crypto-breakdown":            "crypto-monitor",
    "momentum-long":               "price-monitor",
    "momentum-long-loose":         "price-monitor",
    "overbought-short":            "price-monitor",
    "options-momentum":            "options-monitor",
    "geo-defense":                 "geo-monitor",
    "geo-energy":                  "geo-monitor",
    "geo-gold":                    "geo-monitor",
    "geo-xom":                     "geo-monitor",
    "geo-news":                    "geo-monitor",
    "defense-long":                "defense-monitor",
    "defense-short":               "defense-monitor",
    "twitter-news":                "twitter-monitor",
    "twitter-news-review":         "twitter-monitor",
    "twitter-A-direct":            "twitter-monitor",
    "twitter-B-escalation-defense": "twitter-monitor",
    "twitter-B-escalation-energy":  "twitter-monitor",
    "twitter-C-deescalation-spy":   "twitter-monitor",
    "twitter-C-deescalation-xle":   "twitter-monitor",
    "twitter-D-macro-bull":         "twitter-monitor",
    "twitter-D-macro-bear-gld":     "twitter-monitor",
    "twitter-D-macro-bear-spy":     "twitter-monitor",
    "reddit-sentiment":             "reddit-monitor",
    "politician-djt-form4":         "politician-monitor",
    "politician-stock-act":         "politician-monitor",
    "position-manager":             "exit-monitor",
}


KNOWN_TOKENS = (
    "RAN",
    "INPUT_EMPTY",
    "NO_SIGNAL",
    "SIGNAL_DETECTED",
    "EMIT_ATTEMPTED",
    "EMIT_SUCCESS",
    "EMIT_FAILED",
)


def _iter_diag_files(days: int = 7) -> list[Path]:
    """Return up to ``days`` recent JSONL diag files (today + lookback)."""
    if not DIAG_DIR.exists():
        return []
    today = datetime.now(timezone.utc).date()
    candidates = []
    for d in range(days):
        day = today - timedelta(days=d)
        fp = DIAG_DIR / f"{day.isoformat()}.jsonl"
        if fp.exists():
            candidates.append(fp)
    return candidates


def _aggregate(files: list[Path]) -> dict:
    counts: dict = defaultdict(lambda: defaultdict(int))
    total_rows = 0
    earliest: str | None = None
    latest: str | None = None
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    monitor = str(rec.get("monitor") or "unknown")
                    token = str(rec.get("token") or "UNKNOWN")
                    counts[monitor][token] += 1
                    total_rows += 1
                    ts = rec.get("timestamp")
                    if isinstance(ts, str):
                        if earliest is None or ts < earliest:
                            earliest = ts
                        if latest is None or ts > latest:
                            latest = ts
        except Exception:
            # Diag files are append-only; partial reads are tolerated.
            continue

    # Materialise to plain dicts so json.dumps works cleanly.
    materialised = {
        m: {t: int(counts[m].get(t, 0)) for t in KNOWN_TOKENS + ("UNKNOWN",)}
        for m in sorted(counts.keys())
    }

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(REPO_ROOT))
        except ValueError:
            return str(p)

    return {
        "files_scanned":   [_rel(p) for p in files],
        "total_rows":      total_rows,
        "earliest_record": earliest,
        "latest_record":   latest,
        "per_monitor":     materialised,
    }


def _synthesize_from_ledger(days: int = 7) -> dict:
    """v3.25 fallback aggregator.

    When ``learning-loop/monitor_runtime_diag/`` is empty (no monitor has
    called ``monitor_runtime_diag.record_diag()`` in production yet),
    synthesize a coarse view from ``learning-loop/opportunity_ledger/``.

    Inference rules (deterministic, read-only):
      * RAN >= 1 if monitor has ANY ledger row attributed
      * EMIT_ATTEMPTED counts ledger rows (each ledger row was an emit)
      * EMIT_SUCCESS counts ledger rows where ``confidence_status != ERROR``
        and the row was persisted (presence in the file == success)
      * EMIT_FAILED counts rows where ``raw_signal.confidence_status ==
        ERROR``
      * SIGNAL_DETECTED counts rows where ``raw_signal.signal_state ==
        DETECTED``
      * NO_SIGNAL counts rows where ``signal_state in {NO_SIGNAL, ''}``
      * INPUT_EMPTY left at 0 (not inferrable from ledger; only the
        native diag path can record it)
    """
    if not LEDGER_DIR.exists():
        return {
            "files_scanned":   [],
            "total_rows":      0,
            "earliest_record": None,
            "latest_record":   None,
            "per_monitor":     {},
            "synthesized":     True,
        }
    today = datetime.now(timezone.utc).date()
    files: list[Path] = []
    for d in range(days):
        day = today - timedelta(days=d)
        fp = LEDGER_DIR / f"{day.isoformat()}.jsonl"
        if fp.exists():
            files.append(fp)

    counts: dict = defaultdict(lambda: defaultdict(int))
    total_rows = 0
    earliest: str | None = None
    latest: str | None = None

    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    strat = str(rec.get("strategy") or "")
                    monitor = STRATEGY_TO_MONITOR_SYN.get(strat, "unknown")
                    if monitor == "unknown":
                        continue
                    raw = rec.get("raw_signal") or {}
                    ss = str(raw.get("signal_state") or "").upper().strip()
                    cs = str(raw.get("confidence_status") or "").upper().strip()

                    # Every ledger row implies a RAN cycle and an
                    # EMIT_ATTEMPTED call.
                    counts[monitor]["RAN"] += 1
                    counts[monitor]["EMIT_ATTEMPTED"] += 1
                    if cs == "ERROR":
                        counts[monitor]["EMIT_FAILED"] += 1
                    else:
                        counts[monitor]["EMIT_SUCCESS"] += 1
                    if ss == "DETECTED":
                        counts[monitor]["SIGNAL_DETECTED"] += 1
                    elif ss in ("", "NO_SIGNAL", "REJECT"):
                        counts[monitor]["NO_SIGNAL"] += 1
                    total_rows += 1

                    ts = rec.get("timestamp")
                    if isinstance(ts, str):
                        if earliest is None or ts < earliest:
                            earliest = ts
                        if latest is None or ts > latest:
                            latest = ts
        except Exception:
            continue

    materialised = {
        m: {t: int(counts[m].get(t, 0)) for t in KNOWN_TOKENS + ("UNKNOWN",)}
        for m in sorted(counts.keys())
    }
    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(REPO_ROOT))
        except ValueError:
            return str(p)

    return {
        "files_scanned":   [_rel(p) for p in files],
        "total_rows":      total_rows,
        "earliest_record": earliest,
        "latest_record":   latest,
        "per_monitor":     materialised,
        "synthesized":     True,
    }


def _render_markdown(agg: dict) -> str:
    lines: list[str] = []
    lines.append("# Monitor Runtime Diagnostics")
    lines.append("")
    lines.append("**Source:** v3.24 runtime diagnostics — generated by "
                 "`scripts/build_monitor_runtime_diagnostics_report.py`.")
    lines.append("")
    lines.append(f"**Files scanned:** {len(agg.get('files_scanned') or [])}  ")
    lines.append(f"**Total diag rows:** {agg.get('total_rows', 0)}  ")
    lines.append(f"**Earliest record:** `{agg.get('earliest_record') or 'n/a'}`  ")
    lines.append(f"**Latest record:** `{agg.get('latest_record') or 'n/a'}`")
    if agg.get("synthesized"):
        lines.append("")
        lines.append(
            "> **v3.25 SYNTHESIZED_VIEW** — native diagnostic JSONL dir is "
            "empty. Counts below are inferred from the opportunity ledger; "
            "INPUT_EMPTY remains 0 because it is not inferrable from "
            "ledger rows.")
    lines.append("")
    lines.append("## Token counts per monitor (last 7 days)")
    lines.append("")
    header = "| Monitor | " + " | ".join(KNOWN_TOKENS) + " | Status |"
    sep    = "|---" * (len(KNOWN_TOKENS) + 2) + "|"
    lines.append(header)
    lines.append(sep)
    per = agg.get("per_monitor") or {}
    seen = list(per.keys())
    # Ensure all KNOWN_MONITORS appear even if absent in data.
    for m in KNOWN_MONITORS:
        if m not in seen:
            seen.append(m)
    for m in seen:
        row = per.get(m) or {t: 0 for t in KNOWN_TOKENS}
        cells = " | ".join(str(int(row.get(t, 0))) for t in KNOWN_TOKENS)
        # Status: ACTIVE if RAN>0 and EMIT_SUCCESS>0; DEGRADED if RAN>0 and
        # EMIT_FAILED>0; SILENT if no rows.
        ran = int(row.get("RAN", 0))
        emit_ok = int(row.get("EMIT_SUCCESS", 0))
        emit_fail = int(row.get("EMIT_FAILED", 0))
        if ran == 0:
            status = "SILENT"
        elif emit_fail > 0 and emit_ok == 0:
            status = "DEGRADED"
        elif emit_ok > 0:
            status = "ACTIVE"
        else:
            status = "RAN_NO_EMIT"
        lines.append(f"| `{m}` | {cells} | `{status}` |")
    lines.append("")
    lines.append("## Standing markers")
    lines.append("")
    lines.append("- HARD-SAFETY HELD: NO BROKER CALL, NO NETWORK CALL.")
    lines.append("- FREE OPERATION: zero paid services, zero LLM calls.")
    lines.append("- v3.24 builder version stamped on confidence rows.")
    lines.append("- v3.25 SYNTHESIZED_VIEW marker active when diag dir empty.")
    lines.append("")
    lines.append(f"_Last generated: {datetime.now(timezone.utc).isoformat()}_")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    files = _iter_diag_files(days=7)
    agg = _aggregate(files)

    # v3.25: when no native diag rows exist, fall back to a synthesized
    # view derived from the opportunity ledger.
    if agg.get("total_rows", 0) == 0:
        agg = _synthesize_from_ledger(days=7)

    # Write JSON payload for downstream agents.
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = OrderedDict([
        ("generated_at",   datetime.now(timezone.utc).isoformat()),
        ("builder_version", "v3.25.0"),
        ("view_mode",       "synthesized" if agg.get("synthesized") else "native"),
        ("hard_safety", {
            "broker_call": False,
            "network_call": False,
            "paid_service": False,
        }),
        ("aggregate", agg),
    ])
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # Write Markdown report.
    DOCS_OUT.parent.mkdir(parents=True, exist_ok=True)
    md = _render_markdown(agg)
    with open(DOCS_OUT, "w", encoding="utf-8") as f:
        f.write(md)

    def _safe_rel(p: Path) -> str:
        try:
            return str(p.relative_to(REPO_ROOT))
        except ValueError:
            return str(p)

    print(f"Wrote {_safe_rel(DOCS_OUT)} "
          f"({len(md.encode('utf-8'))} bytes)")
    print(f"Wrote {_safe_rel(JSON_OUT)} "
          f"({JSON_OUT.stat().st_size} bytes)")
    print(f"Files scanned: {len(files)} | total rows: {agg.get('total_rows', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
