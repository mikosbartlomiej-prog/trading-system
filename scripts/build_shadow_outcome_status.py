#!/usr/bin/env python3
"""v3.23 (2026-06-15) — Shadow Outcome status reporter.

Reads shadow_ledger and shadow_outcomes JSONL files from the last 7
days and produces both a machine-readable status JSON and a human
markdown report.

HARD SAFETY
-----------
- NEVER imports ``shared.alpaca_orders``.
- NEVER makes a network call.
- NEVER mutates any other file (only writes the two output artefacts).

Outputs
-------
- ``learning-loop/shadow_evidence/shadow_outcome_status_latest.json``
- ``docs/SHADOW_OUTCOME_STATUS.md``

Both artefacts re-state the standing markers in their footer to make
audit board reviews trivial.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT       = Path(__file__).resolve().parent.parent
SHADOW_LEDGER   = REPO_ROOT / "learning-loop" / "shadow_ledger"
SHADOW_OUTCOMES = REPO_ROOT / "learning-loop" / "shadow_outcomes"
STATUS_JSON     = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                    / "shadow_outcome_status_latest.json")
STATUS_MD       = REPO_ROOT / "docs" / "SHADOW_OUTCOME_STATUS.md"

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "SHADOW_ONLY",
    "LLM_ADVISORY_ONLY_CONFIRMED",
)


def _today_utc() -> datetime:
    return datetime.now(timezone.utc)


def _date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _safe_load_jsonl(p: Path) -> list[dict[str, Any]]:
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return rows


def _load_last_7_days(dir_path: Path) -> list[dict[str, Any]]:
    today = _today_utc()
    out: list[dict[str, Any]] = []
    for delta in range(7):
        d = today - timedelta(days=delta)
        p = dir_path / f"{_date_str(d)}.jsonl"
        out.extend(_safe_load_jsonl(p))
    return out


def _summarise(fills: list[dict[str, Any]],
                outcomes: list[dict[str, Any]],
                ) -> dict[str, Any]:
    shadow_fills_count        = len(
        [f for f in fills if f.get("record_type") ==
            "SHADOW_FILL_HYPOTHETICAL"])
    resolved_outcomes         = [
        o for o in outcomes
        if o.get("record_type") == "SHADOW_OUTCOME_OBSERVATION"]
    pending_outcomes_count    = 0  # the resolved ledger never contains pending
    resolved_outcomes_count   = len(resolved_outcomes)

    hit_target_first_n = sum(
        1 for o in resolved_outcomes
        if bool(o.get("hit_target_first")))
    hit_stop_first_n   = sum(
        1 for o in resolved_outcomes
        if bool(o.get("hit_stop_first")))

    def _rate(n: int, d: int) -> float | None:
        if d == 0:
            return None
        return round(float(n) / float(d), 4)

    hit_target_first_rate = _rate(hit_target_first_n,
                                    resolved_outcomes_count)
    hit_stop_first_rate   = _rate(hit_stop_first_n,
                                    resolved_outcomes_count)

    pnls = [
        float(o.get("hypothetical_pnl") or 0.0)
        for o in resolved_outcomes
    ]
    if pnls:
        avg_hypothetical_pnl: float | None = round(
            sum(pnls) / len(pnls), 6)
    else:
        avg_hypothetical_pnl = None

    return {
        "shadow_fills_count":         shadow_fills_count,
        "pending_outcomes_count":     pending_outcomes_count,
        "resolved_outcomes_count":    resolved_outcomes_count,
        "hit_target_first_count":     hit_target_first_n,
        "hit_stop_first_count":       hit_stop_first_n,
        "hit_target_first_rate":      hit_target_first_rate,
        "hit_stop_first_rate":        hit_stop_first_rate,
        "avg_hypothetical_pnl":       avg_hypothetical_pnl,
    }


def _render_markdown(summary: dict[str, Any],
                      generated_at_iso: str) -> str:
    lines: list[str] = []
    lines.append("# Shadow outcome status\n")
    lines.append(
        f"_Generated_: {generated_at_iso}  ")
    lines.append("_Window_: last 7 days (UTC)\n")
    lines.append(
        "**Source records** are shadow simulations (no broker order "
        "submitted, no paper trade). Outcomes are hypothetical "
        "observations only and MUST NOT be tallied as paper-trade "
        "edge evidence.\n")
    lines.append("## Counters\n")
    lines.append(f"- Shadow fills:                 "
                  f"{summary['shadow_fills_count']}")
    lines.append(f"- Resolved outcomes:            "
                  f"{summary['resolved_outcomes_count']}")
    lines.append(f"- Pending outcomes (this view): "
                  f"{summary['pending_outcomes_count']}")
    lines.append(f"- Target-hit-first count:       "
                  f"{summary['hit_target_first_count']}")
    lines.append(f"- Stop-hit-first count:         "
                  f"{summary['hit_stop_first_count']}")
    lines.append(f"- Target-hit-first rate:        "
                  f"{summary['hit_target_first_rate']}")
    lines.append(f"- Stop-hit-first rate:          "
                  f"{summary['hit_stop_first_rate']}")
    lines.append(f"- Average hypothetical PnL:     "
                  f"{summary['avg_hypothetical_pnl']}\n")
    lines.append("## Interpretation\n")
    if summary['shadow_fills_count'] == 0:
        lines.append(
            "**No shadow fills yet.** This is the expected state on a "
            "fresh repo or before the runner has been wired to "
            "`shared.shadow_simulator.emit_shadow_fill`. Phase 2 work "
            "should add the wire-in plus a cron-driven outcome "
            "resolution step.\n")
    else:
        lines.append(
            "Shadow fill records are present. None of these constitute "
            "broker activity or paper-trade edge — they are observation "
            "only. Audit board: do NOT mutate readiness counters from "
            "this artefact.\n")
    lines.append("## Standing markers\n")
    for m in STANDING_MARKERS:
        lines.append(f"- `{m}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    generated_at = _today_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    fills    = _load_last_7_days(SHADOW_LEDGER)
    outcomes = _load_last_7_days(SHADOW_OUTCOMES)
    summary  = _summarise(fills, outcomes)
    payload  = {
        "version":             "v3.23",
        "generated_at":        generated_at,
        "window_days":         7,
        "summary":             summary,
        "standing_markers":    list(STANDING_MARKERS),
        "is_paper_trade_view": False,
    }
    try:
        STATUS_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(STATUS_JSON, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
    except Exception:
        # fail-soft: still try the markdown
        pass
    md = _render_markdown(summary, generated_at)
    try:
        STATUS_MD.parent.mkdir(parents=True, exist_ok=True)
        STATUS_MD.write_text(md, encoding="utf-8")
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
