#!/usr/bin/env python3
"""v3.20.0 (2026-06-04) — Evidence Lower Bounds report.

Generates ``docs/EVIDENCE_LOWER_BOUNDS_LATEST.md`` summarising the
Wilson + bootstrap lower bounds per strategy. Reads only PAPER ledger
records — backtest/replay records are explicitly excluded so we do not
inflate confidence with overfit historical replays.

This is a *read-only* triage script. It NEVER calls the broker, NEVER
calls a paid API, NEVER auto-flips ``EDGE_GATE_ENABLED``, NEVER mutates
runtime state, NEVER prints recommendations to trade live.

Usage::

    python3 scripts/evidence_lower_bounds_report.py
    python3 scripts/evidence_lower_bounds_report.py --window-days 90
    python3 scripts/evidence_lower_bounds_report.py --out docs/EV.md
    python3 scripts/evidence_lower_bounds_report.py --bootstrap-n 500
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shared"))


def _load_paper_ledger(window_days: int) -> list[dict]:
    try:
        from paper_experiment import load_paper_ledger  # type: ignore
        return load_paper_ledger(window_days=window_days)
    except Exception:
        return []


def _group_by_strategy(records: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        s = r.get("strategy")
        if not isinstance(s, str) or not s:
            continue
        out.setdefault(s, []).append(r)
    return out


def _format_pct(x: float) -> str:
    return f"{x:.0%}"


def _format_money(x: float) -> str:
    return f"{x:+,.2f}"


def _build_report(per_strategy: dict[str, dict], window_days: int,
                  bootstrap_n: int) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = []
    lines.append("# Evidence Lower Bounds — paper ledger only")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append(f"Window: {window_days} days")
    lines.append(f"Bootstrap resamples: {bootstrap_n}")
    lines.append("")
    lines.append("**This report uses ONLY PAPER-source records.** Backtest "
                 "and replay records are intentionally excluded — they are "
                 "triage only and never approve edge.")
    lines.append("")
    lines.append("This is a paper-trading evidence snapshot. The system "
                 "does NOT recommend live trading on the strength of any "
                 "row in this table.")
    lines.append("")
    if not per_strategy:
        lines.append("_No paper records in this window. Nothing to score._")
        return "\n".join(lines) + "\n"

    headers = [
        "strategy", "n", "WR mean", "WR LB (Wilson 95%)",
        "PF mean", "PF LB (5%)", "Expectancy LB",
        "DD upper bound", "Worst-20 window", "P(neg expectancy)",
        "Sufficient (n>=50)", "Status",
    ]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for name in sorted(per_strategy):
        d = per_strategy[name]
        row = [
            name,
            str(d.get("n_closed", 0)),
            _format_pct(d.get("win_rate_mean", 0.0)),
            _format_pct(d.get("win_rate_lower_cb", 0.0)),
            f"{d.get('profit_factor_mean', 0.0):.2f}",
            f"{d.get('profit_factor_lower_bound', 0.0):.2f}",
            _format_money(d.get("expectancy_lower_bound", 0.0)),
            _format_pct(d.get("drawdown_upper_bound", 0.0)),
            _format_money(d.get("worst_20_trade_window", 0.0)),
            f"{d.get('probability_of_negative_expectancy', 1.0):.2f}",
            "yes" if d.get("sample_size_sufficiency") else "no",
            d.get("status", "EVIDENCE_TOO_WEAK"),
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evidence lower-bounds report (paper-only).")
    parser.add_argument("--window-days", type=int, default=180,
                        help="Lookback window in days (default 180).")
    parser.add_argument("--bootstrap-n", type=int, default=1000,
                        help="Bootstrap resamples (default 1000).")
    parser.add_argument("--out", type=str, default=None,
                        help="Output path. Defaults to "
                             "docs/EVIDENCE_LOWER_BOUNDS_LATEST.md")
    parser.add_argument("--json", action="store_true",
                        help="Also write a sibling JSON dump.")
    args = parser.parse_args()

    from evidence_lower_bounds import (  # type: ignore  # noqa: E402
        compute_strategy_evidence_bounds,
    )

    records = _load_paper_ledger(args.window_days)
    grouped = _group_by_strategy(records)

    per_strategy: dict[str, dict] = {}
    for name, recs in grouped.items():
        per_strategy[name] = compute_strategy_evidence_bounds(
            name, recs, bootstrap_n=args.bootstrap_n)

    out_path = Path(args.out) if args.out else (
        _REPO_ROOT / "docs" / "EVIDENCE_LOWER_BOUNDS_LATEST.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_build_report(per_strategy, args.window_days,
                                       args.bootstrap_n), encoding="utf-8")

    if args.json:
        import json
        json_path = out_path.with_suffix(".json")
        json_path.write_text(
            json.dumps(per_strategy, indent=2, sort_keys=True,
                       default=str), encoding="utf-8")

    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
