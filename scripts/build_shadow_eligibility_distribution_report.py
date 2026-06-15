#!/usr/bin/env python3
"""v3.25 — Shadow Eligibility Distribution Reporter.

For each post-v3.24 opportunity_ledger row, asks
:func:`shared.shadow_eligibility.evaluate_shadow_eligibility` for a verdict
and aggregates the counts by decision token.

This reporter NEVER constructs a ShadowFill. It only counts.

HARD SAFETY
-----------
- NEVER imports ``alpaca_orders`` (verified by unit test AST scan).
- NEVER calls submit_order / place_order / safe_close /
  place_stock_order / place_crypto_order / place_option_order /
  close_position / close_all_positions / any broker entry point.
- NEVER makes a network call. Pure local file I/O.
- Fail-soft: every parse error is silently skipped; the script always
  exits 0.
- Standing markers footer is preserved on every output.

Usage
-----
::

    python3 scripts/build_shadow_eligibility_distribution_report.py
    python3 scripts/build_shadow_eligibility_distribution_report.py --cutoff-iso 2026-06-15T11:35:05+00:00
    python3 scripts/build_shadow_eligibility_distribution_report.py --json --no-write

Exit codes
----------
``0`` always.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "shared"))


VERSION = "v3.25.0"
DEFAULT_CUTOFF_ISO = "2026-06-15T11:35:05+00:00"
DEFAULT_LEDGER_DIR = REPO_ROOT / "learning-loop" / "opportunity_ledger"
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "learning-loop" / "shadow_evidence" /
    "shadow_eligibility_distribution_latest.json"
)
DEFAULT_OUTPUT_MD = REPO_ROOT / "docs" / "SHADOW_ELIGIBILITY_STATUS.md"


STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT_BY_REPORTER",
    "PURE_LOCAL_FILE_OPERATIONS",
    "NEAR_MISS_IS_NOT_TRADE_EVIDENCE",
    "SHADOW_IS_NOT_BROKER_PAPER",
    "LLM_ADVISORY_ONLY",
)

# Reference list of all 10 decision tokens the report must always
# include (zero counts where applicable).
ALL_DECISION_TOKENS: tuple[str, ...] = (
    "ELIGIBLE",
    "NOT_ELIGIBLE_NO_CONFIDENCE",
    "NOT_ELIGIBLE_CONFIDENCE_LOW",
    "NOT_ELIGIBLE_RISK_BLOCK",
    "NOT_ELIGIBLE_NO_SIGNAL",
    "NOT_ELIGIBLE_DRAWDOWN_GUARD",
    "NOT_ELIGIBLE_DATA_FAILURE",
    "NOT_ELIGIBLE_CANARY_DEFERRED",
    "NOT_ELIGIBLE_OBSERVE_ONLY",
    "NOT_ELIGIBLE_UNKNOWN",
)


def _row_timestamp(r: dict) -> str:
    return (
        r.get("timestamp")
        or r.get("emit_timestamp")
        or r.get("written_iso")
        or ""
    )


def load_rows(
    ledger_dir: Path,
    cutoff_iso: str,
    max_files: int = 7,
) -> list[dict]:
    """Load post-cutoff rows from the most recent N ledger files."""
    files = sorted(ledger_dir.glob("*.jsonl"))[-max_files:]
    out: list[dict] = []
    for f in files:
        try:
            with open(f) as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if _row_timestamp(r) >= cutoff_iso:
                        out.append(r)
        except OSError:
            continue
    return out


def compute_distribution(rows: list[dict]) -> dict[str, Any]:
    """Compute eligibility distribution + sample reasons per token."""
    # Lazy import — reporter must run even if module is shimmed.
    try:
        from shadow_eligibility import evaluate_shadow_eligibility
    except ImportError:
        from shared.shadow_eligibility import evaluate_shadow_eligibility

    by_token: Counter = Counter({t: 0 for t in ALL_DECISION_TOKENS})
    sample_reasons: dict[str, list[str]] = {t: [] for t in ALL_DECISION_TOKENS}
    eligible_rows: list[dict] = []

    for r in rows:
        try:
            verdict = evaluate_shadow_eligibility(r)
        except Exception:
            # Fail-soft: malformed row counts as UNKNOWN.
            by_token["NOT_ELIGIBLE_UNKNOWN"] += 1
            sample_reasons["NOT_ELIGIBLE_UNKNOWN"].append(
                "evaluate raised")
            continue
        tok = verdict.decision.value
        by_token[tok] += 1
        if len(sample_reasons[tok]) < 3 and verdict.reason:
            sample_reasons[tok].append(verdict.reason)
        if tok == "ELIGIBLE":
            eligible_rows.append(r)

    n = len(rows)
    eligible = by_token.get("ELIGIBLE", 0)
    pct = round(100.0 * eligible / n, 2) if n else 0.0

    return {
        "rows_evaluated":          n,
        "eligible_count":          eligible,
        "eligible_pct":            pct,
        "by_decision":             dict(by_token),
        "sample_reasons":          {k: v for k, v in sample_reasons.items() if v},
        "eligible_row_signal_ids": [
            r.get("signal_id") or r.get("raw_signal", {}).get("signal_id")
            for r in eligible_rows
        ],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Shadow Eligibility Distribution Status")
    lines.append("")
    lines.append(f"- **Version**: `{payload['version']}`")
    lines.append(f"- **Generated**: `{payload['generated_at']}`")
    lines.append(f"- **Cutoff (post-v3.24)**: `{payload['cutoff_iso']}`")
    lines.append(f"- **Rows evaluated**: {payload['rows_evaluated']}")
    lines.append(
        f"- **ELIGIBLE rows**: {payload['eligible_count']} "
        f"({payload['eligible_pct']}%)")
    lines.append("")
    lines.append("## Decision distribution")
    lines.append("")
    lines.append("| Token | Count |")
    lines.append("|---|---:|")
    for tok in ALL_DECISION_TOKENS:
        lines.append(
            f"| `{tok}` | {payload['by_decision'].get(tok, 0)} |")
    lines.append("")
    if payload.get("sample_reasons"):
        lines.append("## Sample reasons per token")
        lines.append("")
        for tok, reasons in payload["sample_reasons"].items():
            lines.append(f"- **{tok}**:")
            for r in reasons:
                lines.append(f"  - `{r}`")
        lines.append("")
    lines.append("## Standing markers")
    lines.append("")
    for m in payload["standing_markers"]:
        lines.append(f"- `{m}`")
    lines.append("")
    return "\n".join(lines) + "\n"


def build_payload(
    rows: list[dict],
    cutoff_iso: str,
) -> dict[str, Any]:
    dist = compute_distribution(rows)
    return {
        "version":           VERSION,
        "cutoff_iso":        cutoff_iso,
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "standing_markers":  list(STANDING_MARKERS),
        **dist,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Shadow eligibility distribution reporter (v3.25).",
    )
    p.add_argument("--ledger-dir", type=Path, default=DEFAULT_LEDGER_DIR)
    p.add_argument("--cutoff-iso", type=str, default=DEFAULT_CUTOFF_ISO)
    p.add_argument("--max-files", type=int, default=7)
    p.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    p.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    p.add_argument("--no-write", action="store_true",
                   help="Do not write any output files; print summary only.")
    p.add_argument("--json", action="store_true",
                   help="Print full JSON payload to stdout.")
    args = p.parse_args(argv)

    rows = load_rows(args.ledger_dir, args.cutoff_iso, args.max_files)
    payload = build_payload(rows, args.cutoff_iso)

    if not args.no_write:
        try:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n")
            args.output_md.parent.mkdir(parents=True, exist_ok=True)
            args.output_md.write_text(render_markdown(payload))
        except OSError as e:
            print(f"[WARN] write failed: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"v3.25 shadow-eligibility distribution — "
              f"{payload['rows_evaluated']} rows, "
              f"{payload['eligible_count']} ELIGIBLE "
              f"({payload['eligible_pct']}%)")
        for tok in ALL_DECISION_TOKENS:
            n = payload["by_decision"].get(tok, 0)
            if n:
                print(f"  {tok}: {n}")
        print(f"standing_markers={'|'.join(STANDING_MARKERS)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
