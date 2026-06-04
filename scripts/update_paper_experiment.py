"""v3.18.0 (2026-06-04) — CLI entrypoint for paper-experiment-update workflow.

This is the deterministic glue that:
  1. Reads journal/autonomy/<date>.jsonl for closed trades on a given date.
  2. Calls shared.paper_experiment.record_paper_trade for each.
  3. Regenerates the edge_evidence_report and writes
     docs/edge_evidence_LATEST.md.

Fail-soft everywhere. No external API calls. No live broker calls.

Usage:
    python -m scripts.update_paper_experiment
    python -m scripts.update_paper_experiment --date 2026-06-04
    python -m scripts.update_paper_experiment --window-days 90
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shared"))

try:
    from shared.paper_experiment import (             # type: ignore
        record_paper_trade,
        generate_edge_evidence_report,
        compute_strategy_metrics,
    )
except Exception:
    from paper_experiment import (                    # type: ignore
        record_paper_trade,
        generate_edge_evidence_report,
        compute_strategy_metrics,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _audit_path(d: date) -> Path:
    base = Path(
        os.environ.get("AUDIT_TRADING_DIR")
        or _REPO_ROOT / "journal" / "autonomy"
    )
    return base / f"{d.isoformat()}.jsonl"


def _iter_decisions(d: date):
    path = _audit_path(d)
    if not path.exists():
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _extract_closed_trades(d: date) -> list[dict]:
    """Best-effort extraction of closed-trade records from the autonomy
    audit log. We look for CLOSE_POSITION decisions that include enough
    fields to reconstruct entry/exit/qty/side. Anything ambiguous is
    skipped to keep the ledger honest.
    """
    out: list[dict] = []
    for rec in _iter_decisions(d):
        if rec.get("decision_type") not in ("CLOSE_POSITION",
                                             "EMERGENCY_CLOSE"):
            continue
        rm = rec.get("risk_metrics") or {}
        # Best-effort field discovery — different writers use slightly
        # different shapes. We only record if we have entry/exit/qty/side.
        entry = rm.get("entry") or rm.get("entry_price")
        exit_ = rm.get("exit")  or rm.get("exit_price")
        qty   = rm.get("qty")   or rm.get("quantity")
        side  = rm.get("side")  or rm.get("direction")
        strat = rec.get("strategy") or rm.get("strategy") or "unknown"
        symbols = rec.get("affected_symbols") or []
        sym = symbols[0] if symbols else (rm.get("symbol") or "?")
        if entry is None or exit_ is None or qty is None or side is None:
            continue
        out.append({
            "strategy": strat,
            "symbol":   sym,
            "entry":    entry,
            "exit":     exit_,
            "qty":      qty,
            "side":     side,
            "fees":             rm.get("fees", 0.0),
            "spread_at_entry":  rm.get("spread_at_entry", 0.0),
            "slippage_at_entry": rm.get("slippage_at_entry", 0.0),
            "regime":           rm.get("regime"),
            "confidence_at_entry": rm.get("confidence_at_entry"),
            "opened_at":        rm.get("opened_at"),
            "closed_at":        rec.get("timestamp") or rm.get("closed_at"),
        })
    return out


def _ingest_day(d: date) -> int:
    trades = _extract_closed_trades(d)
    for t in trades:
        record_paper_trade(
            strategy=t["strategy"],
            symbol=t["symbol"],
            entry=t["entry"],
            exit=t["exit"],
            qty=t["qty"],
            side=t["side"],
            fees=t.get("fees", 0.0),
            spread_at_entry=t.get("spread_at_entry", 0.0),
            slippage_at_entry=t.get("slippage_at_entry", 0.0),
            regime=t.get("regime"),
            confidence_at_entry=t.get("confidence_at_entry"),
            opened_at=t.get("opened_at"),
            closed_at=t.get("closed_at"),
        )
    return len(trades)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Update paper experiment ledger.")
    p.add_argument("--date", default=None,
                   help="UTC date to ingest (default: today).")
    p.add_argument("--lookback-days", type=int, default=3,
                   help="Also ingest the last N days (default: 3).")
    p.add_argument("--window-days", type=int, default=180,
                   help="Report window in days (default: 180).")
    p.add_argument("--report-path", default=None,
                   help="Output path for edge_evidence report.")
    args = p.parse_args(argv)

    today = (date.fromisoformat(args.date)
             if args.date else datetime.now(timezone.utc).date())

    total = 0
    for delta in range(args.lookback_days + 1):
        day = today - timedelta(days=delta)
        try:
            total += _ingest_day(day)
        except Exception:
            # Per spec, never raise from this module.
            continue

    report_path = (Path(args.report_path) if args.report_path
                   else _REPO_ROOT / "docs" / "edge_evidence_LATEST.md")
    md = generate_edge_evidence_report(out_path=str(report_path),
                                       window_days=args.window_days)
    print(f"[update_paper_experiment] ingested={total} trades")
    print(f"[update_paper_experiment] report -> {report_path}")
    print(f"[update_paper_experiment] report length={len(md)} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
