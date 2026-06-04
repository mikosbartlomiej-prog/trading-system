#!/usr/bin/env python3
"""v3.20.0 (2026-06-04) — Strategy Robustness sandbox report.

Generates ``docs/STRATEGY_ROBUSTNESS_LATEST.md`` summarising the
robustness suite outputs per strategy.

Sandbox-only. NEVER calls the broker, NEVER calls a paid API, NEVER
mutates runtime state, NEVER auto-optimizes parameters.

Usage::

    python3 scripts/strategy_robustness_report.py
    python3 scripts/strategy_robustness_report.py --window-days 90
    python3 scripts/strategy_robustness_report.py --out docs/SR.md
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


def _build_report(per_strategy: dict[str, dict], window_days: int) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = []
    lines.append("# Strategy Robustness — sandbox report")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append(f"Window: {window_days} days (paper ledger)")
    lines.append("")
    lines.append("The sandbox NEVER optimizes parameters and NEVER mutates "
                 "the runtime. It runs deterministic perturbations and "
                 "splits on the paper ledger only.")
    lines.append("")
    lines.append("This report is a paper-trading diagnostic. It does NOT "
                 "recommend live trading.")
    lines.append("")
    if not per_strategy:
        lines.append("_No paper records in this window. Nothing to test._")
        return "\n".join(lines) + "\n"

    headers = [
        "strategy", "n", "Robustness", "Max degradation",
        "Overfit suspicion", "One-symbol dep", "One-day dep",
        "One-regime dep", "Top warnings",
    ]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for name in sorted(per_strategy):
        d = per_strategy[name]
        warns = d.get("fragility_warnings") or []
        warns_str = "; ".join(warns[:3]) if warns else "-"
        row = [
            name,
            str(d.get("n_trades", 0)),
            f"{d.get('robustness_score', 0.0):.2f}",
            _format_pct(d.get("max_relative_degradation", 0.0)),
            "yes" if d.get("overfit_suspicion") else "no",
            "yes" if d.get("dependency_on_one_symbol") else "no",
            "yes" if d.get("dependency_on_one_day") else "no",
            "yes" if d.get("dependency_on_one_regime") else "no",
            warns_str,
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strategy robustness sandbox report (paper-only).")
    parser.add_argument("--window-days", type=int, default=180,
                        help="Lookback window in days (default 180).")
    parser.add_argument("--out", type=str, default=None,
                        help="Output path. Defaults to "
                             "docs/STRATEGY_ROBUSTNESS_LATEST.md")
    parser.add_argument("--json", action="store_true",
                        help="Also write a sibling JSON dump.")
    args = parser.parse_args()

    from strategy_robustness import (  # type: ignore  # noqa: E402
        run_robustness_suite,
    )

    records = _load_paper_ledger(args.window_days)
    grouped = _group_by_strategy(records)

    per_strategy: dict[str, dict] = {}
    for name, recs in grouped.items():
        per_strategy[name] = run_robustness_suite(name, recs)

    out_path = Path(args.out) if args.out else (
        _REPO_ROOT / "docs" / "STRATEGY_ROBUSTNESS_LATEST.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_build_report(per_strategy, args.window_days),
                         encoding="utf-8")

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
