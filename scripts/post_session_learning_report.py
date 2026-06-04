"""v3.19.0 (2026-06-04) — CLI for post-session learning report.

Runs shared.post_session_learning.run_post_session_analysis and writes
both `docs/post_session_LATEST.md` and `docs/post_session_LATEST.json`.

Fail-soft everywhere. No live broker calls. No state.json writes.

Usage:
    python -m scripts.post_session_learning_report
    python -m scripts.post_session_learning_report --date 2026-06-04
    python -m scripts.post_session_learning_report --window-days 7
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shared"))

try:
    from post_session_learning import run_post_session_analysis  # type: ignore
except Exception:
    try:
        from shared.post_session_learning import run_post_session_analysis  # type: ignore
    except Exception as e:
        print(f"FATAL: cannot import post_session_learning ({e})",
              file=sys.stderr)
        sys.exit(0)  # exit 0 because workflow status must not fail on import


def _render_markdown(report: dict) -> str:
    lines: list[str] = []
    lines.append("# Post-Session Learning Report (paper trading)")
    lines.append("")
    lines.append(
        "*Advisory only. Paper trading evidence. Never auto-disables, "
        "never auto-promotes, never enables EDGE_GATE_ENABLED.*"
    )
    lines.append("")
    lines.append(f"Date: {report.get('date','?')}  ·  "
                 f"Window days: {report.get('window_days',1)}  ·  "
                 f"Generated: {report.get('generated_at')}")
    lines.append("")
    lines.append(f"Trades in window: {report.get('n_trades_in_window', 0)}  ·  "
                 f"Audit events: {report.get('n_audit_events', 0)}")
    lines.append("")

    warnings = report.get("warnings") or []
    if warnings:
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## Recommendations")
    recs = report.get("recommendations") or {}
    if not recs:
        lines.append("_No strategies observed in window._")
    else:
        lines.append("| Strategy | Recommendation |")
        lines.append("|---|---|")
        for strat in sorted(recs.keys()):
            lines.append(f"| {strat} | {recs[strat]} |")
    lines.append("")

    findings = report.get("findings") or []
    lines.append(f"## Findings ({len(findings)})")
    if not findings:
        lines.append("_No anomalies detected._")
    else:
        for f in findings:
            sev = f.get("severity", "?")
            ftype = f.get("type", "?")
            strat = f.get("strategy", "?")
            desc = f.get("description", "")
            recm = f.get("recommendation", "")
            lines.append(f"- **[{sev}] [{ftype}] {strat}** — {desc}  "
                         f"_Recommendation: {recm}_")
    lines.append("")

    # Per-strategy summary
    strategies = report.get("strategies") or {}
    if strategies:
        lines.append("## Per-strategy summary")
        lines.append("")
        lines.append("| Strategy | n | WR | PF | Expectancy | NetPnL | MaxDD |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for strat in sorted(strategies.keys()):
            s = strategies[strat]
            lines.append(
                f"| {strat} | {s.get('n_closed',0)} | "
                f"{s.get('win_rate',0)*100:.1f}% | "
                f"{s.get('profit_factor',0):.2f} | "
                f"{s.get('expectancy',0):+.4f} | "
                f"{s.get('net_pnl_after_fees_slippage',0):+.2f} | "
                f"{s.get('max_drawdown',0)*100:.1f}% |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate post-session learning report (paper only)")
    parser.add_argument("--date", type=str, default=None,
                        help="ISO date (UTC). Default: today.")
    parser.add_argument("--window-days", type=int, default=1,
                        help="How many prior days to include (>=1).")
    parser.add_argument("--no-emit-audit", action="store_true",
                        help="Skip per-recommendation audit emission.")
    parser.add_argument("--out-md", type=str, default=None,
                        help="Path to Markdown report (default: "
                             "docs/post_session_LATEST.md)")
    parser.add_argument("--out-json", type=str, default=None,
                        help="Path to JSON report (default: "
                             "docs/post_session_LATEST.json)")
    args = parser.parse_args(argv)

    try:
        report = run_post_session_analysis(
            date=args.date,
            window_days=args.window_days,
            emit_audit=not args.no_emit_audit,
        )
    except Exception as e:
        # Fail-soft: produce minimal report rather than crashing.
        report = {
            "date":               args.date or "?",
            "window_days":        args.window_days,
            "n_trades_in_window": 0,
            "n_audit_events":     0,
            "strategies":         {},
            "symbols":             {},
            "regimes":             {},
            "confidence_buckets":  {},
            "time_windows":        {},
            "findings":            [],
            "recommendations":     {},
            "warnings":            [f"analysis crashed: {e}"],
            "paper_only":          True,
            "generated_at":        datetime.now(timezone.utc).isoformat(
                                      timespec="seconds"),
        }

    out_md = Path(args.out_md) if args.out_md else (
        _REPO_ROOT / "docs" / "post_session_LATEST.md")
    out_json = Path(args.out_json) if args.out_json else (
        _REPO_ROOT / "docs" / "post_session_LATEST.json")

    try:
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(_render_markdown(report), encoding="utf-8")
    except OSError as e:
        print(f"WARN: could not write markdown report ({e})", file=sys.stderr)

    try:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, indent=2, sort_keys=True,
                                       default=str),
                            encoding="utf-8")
    except OSError as e:
        print(f"WARN: could not write JSON report ({e})", file=sys.stderr)

    print(f"post_session_learning_report → {out_md} / {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
