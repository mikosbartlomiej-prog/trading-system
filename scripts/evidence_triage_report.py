#!/usr/bin/env python3
"""v3.19.0 (2026-06-04) — Evidence triage report.

Generates three local Markdown reports under ``docs/``:

  - docs/backtest_triage_LATEST.md     — backtest signals → strategy candidates
  - docs/replay_triage_LATEST.md       — replay results → stress test outcomes
  - docs/evidence_divergence_LATEST.md — paper vs backtest vs replay WR delta

NEVER calls the broker. NEVER calls a paid API. Reads JSONL only from the
three dedicated ledger directories. Always exits 0 — a missing ledger is
not a failure, it just means there is nothing to triage yet.

The divergence report flags strategies whose backtest WR (or replay WR)
diverges by more than ``--threshold`` (default 0.30 = 30 percentage
points) from the paper WR — that pattern usually signals overfitting on
historical data and should NEVER be treated as edge approval.

Usage:
    python3 scripts/evidence_triage_report.py
    python3 scripts/evidence_triage_report.py --window-days 90 --threshold 0.25
    python3 scripts/evidence_triage_report.py --out-dir /tmp/reports
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shared"))

from paper_experiment import (  # type: ignore  # noqa: E402
    compute_strategy_metrics,
    load_backtest_ledger,
    load_replay_ledger,
    load_paper_ledger,
)
from evidence_source import EvidenceSource  # type: ignore  # noqa: E402


def _strategies_seen(records: list[dict]) -> set[str]:
    out: set[str] = set()
    for r in records:
        s = r.get("strategy")
        if isinstance(s, str) and s:
            out.add(s)
    return out


def _metrics_table(strategies: list[str], window_days: int,
                    source: EvidenceSource) -> list[dict]:
    rows: list[dict] = []
    for name in sorted(strategies):
        m = compute_strategy_metrics(name, window_days=window_days,
                                       source_filter=source)
        rows.append({"strategy": name, **m})
    return rows


def _render_triage_md(title: str, kind_label: str,
                       rows: list[dict], window_days: int) -> str:
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(
        "*This report is a TRIAGE view, not edge approval. "
        f"Records here are {kind_label}; they do NOT contribute to "
        "EDGE_GATE_ENABLED.*"
    )
    lines.append("")
    lines.append(
        f"Window: last {window_days} days. "
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}."
    )
    lines.append("")
    if not rows:
        lines.append("_No records in window._")
        lines.append("")
        return "\n".join(lines) + "\n"
    lines.append("| Strategy | n_closed | WR | PF | Expectancy | NetPnL | MaxDD |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for m in rows:
        lines.append(
            f"| {m['strategy']} | {m.get('n_closed',0)} | "
            f"{m.get('win_rate',0.0)*100:.1f}% | "
            f"{m.get('profit_factor',0.0):.2f} | "
            f"{m.get('expectancy',0.0):+.4f} | "
            f"{m.get('net_pnl_after_fees_slippage',0.0):+.2f} | "
            f"{m.get('max_drawdown',0.0)*100:.1f}% |"
        )
    lines.append("")
    lines.append("> Triage only. NOT a recommendation for live or paper trading.")
    return "\n".join(lines) + "\n"


def _render_divergence_md(rows: list[dict], window_days: int,
                           threshold: float) -> str:
    lines: list[str] = []
    lines.append("# Evidence Divergence Report")
    lines.append("")
    lines.append(
        "*Compares paper WR to backtest WR and replay WR per strategy. "
        "Large divergence is a SIGNAL that the strategy is overfit to "
        "historical data, NOT a green light. NEVER use this to approve "
        "live trading.*"
    )
    lines.append("")
    lines.append(
        f"Window: last {window_days} days. Divergence threshold: "
        f"{threshold:.2f} (= {threshold*100:.0f} percentage points). "
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}."
    )
    lines.append("")
    lines.append("| Strategy | paper n | paper WR | backtest WR | replay WR | "
                 "|paper-backtest| | |paper-replay| | flag |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
    if not rows:
        lines.append("| _empty_ | – | – | – | – | – | – | – |")
    for r in rows:
        flag = "overfitting_warning" if r.get("overfitting") else "ok"
        bwr = r.get("backtest_wr")
        rwr = r.get("replay_wr")
        dwb = r.get("delta_paper_backtest")
        dwr = r.get("delta_paper_replay")

        def _fmt(p):
            return f"{p*100:.1f}%" if isinstance(p, (int, float)) else "–"

        def _fmt_d(p):
            return f"{abs(p)*100:.1f}pp" if isinstance(p, (int, float)) else "–"

        lines.append(
            f"| {r['strategy']} | {r.get('paper_n', 0)} | "
            f"{_fmt(r.get('paper_wr'))} | {_fmt(bwr)} | {_fmt(rwr)} | "
            f"{_fmt_d(dwb)} | {_fmt_d(dwr)} | {flag} |"
        )
    lines.append("")
    lines.append("Divergence flag meanings:")
    lines.append("- **overfitting_warning** — backtest or replay WR differs "
                 "from paper WR by more than the threshold.")
    lines.append("- **ok** — no large divergence detected, OR sample too small "
                 "to compare.")
    lines.append("")
    lines.append("> This report exists for triage. Backtest and replay "
                 "evidence CANNOT approve edge.")
    return "\n".join(lines) + "\n"


def evidence_divergence(window_days: int = 180,
                          threshold: float = 0.30) -> list[dict]:
    """Compute divergence between paper / backtest / replay per strategy.

    Returns a list of per-strategy rows. ``overfitting`` is True when
    the absolute WR delta between paper and either of the triage sources
    exceeds ``threshold``.
    """
    paper = load_paper_ledger(window_days)
    back = load_backtest_ledger(window_days)
    repl = load_replay_ledger(window_days)
    strategies = sorted(_strategies_seen(paper) | _strategies_seen(back)
                         | _strategies_seen(repl))
    rows: list[dict] = []
    for s in strategies:
        m_paper = compute_strategy_metrics(s, window_days=window_days,
                                             source_filter=EvidenceSource.PAPER)
        m_back = compute_strategy_metrics(s, window_days=window_days,
                                            source_filter=EvidenceSource.BACKTEST)
        m_repl = compute_strategy_metrics(s, window_days=window_days,
                                            source_filter=EvidenceSource.REPLAY)
        paper_wr = m_paper.get("win_rate") if m_paper.get("n_closed", 0) else None
        back_wr = m_back.get("win_rate") if m_back.get("n_closed", 0) else None
        repl_wr = m_repl.get("win_rate") if m_repl.get("n_closed", 0) else None

        def _delta(a, b):
            if a is None or b is None:
                return None
            return a - b

        d_pb = _delta(paper_wr, back_wr)
        d_pr = _delta(paper_wr, repl_wr)
        overfit = False
        if d_pb is not None and abs(d_pb) > threshold:
            overfit = True
        if d_pr is not None and abs(d_pr) > threshold:
            overfit = True
        rows.append({
            "strategy":              s,
            "paper_n":               int(m_paper.get("n_closed", 0)),
            "paper_wr":              paper_wr,
            "backtest_n":            int(m_back.get("n_closed", 0)),
            "backtest_wr":           back_wr,
            "replay_n":              int(m_repl.get("n_closed", 0)),
            "replay_wr":             repl_wr,
            "delta_paper_backtest":  d_pb,
            "delta_paper_replay":    d_pr,
            "overfitting":           overfit,
        })
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--window-days", type=int, default=180)
    p.add_argument("--threshold", type=float, default=0.30,
                    help="WR divergence threshold (default 0.30 = 30pp)")
    p.add_argument("--out-dir", type=str, default=str(_REPO_ROOT / "docs"),
                    help="Where to write reports (default: ./docs)")
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    window_days = max(1, int(args.window_days))

    backtest_records = load_backtest_ledger(window_days)
    replay_records = load_replay_ledger(window_days)

    backtest_rows = _metrics_table(
        sorted(_strategies_seen(backtest_records)),
        window_days, EvidenceSource.BACKTEST,
    )
    replay_rows = _metrics_table(
        sorted(_strategies_seen(replay_records)),
        window_days, EvidenceSource.REPLAY,
    )

    (out_dir / "backtest_triage_LATEST.md").write_text(
        _render_triage_md(
            "Backtest Triage", "historical replays (BACKTEST source)",
            backtest_rows, window_days,
        ),
        encoding="utf-8",
    )
    (out_dir / "replay_triage_LATEST.md").write_text(
        _render_triage_md(
            "Replay Triage", "event-driven replays (REPLAY source)",
            replay_rows, window_days,
        ),
        encoding="utf-8",
    )

    divergence_rows = evidence_divergence(window_days, args.threshold)
    (out_dir / "evidence_divergence_LATEST.md").write_text(
        _render_divergence_md(divergence_rows, window_days, args.threshold),
        encoding="utf-8",
    )

    print(f"Wrote {out_dir / 'backtest_triage_LATEST.md'}")
    print(f"Wrote {out_dir / 'replay_triage_LATEST.md'}")
    print(f"Wrote {out_dir / 'evidence_divergence_LATEST.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
