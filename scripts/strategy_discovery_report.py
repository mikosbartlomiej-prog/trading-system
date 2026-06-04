#!/usr/bin/env python3
"""v3.21.0 — scripts/strategy_discovery_report.py

Generate a Strategy Discovery Sandbox report.

Reads (best-effort):
  * ``learning-loop/strategy_ranking.json``   — ranking summary used by
    the Strategy Quality Gate (when present).
  * ``learning-loop/opportunity_ledger/<date>.jsonl`` for the last 7 days
    — opportunity rejection ratios per strategy.
  * Existing variants in ``learning-loop/variant_quarantine/*.json``
    via ``shared.strategy_variant_quarantine.list_variants``.

Writes:
  * ``reports/strategy-discovery/<date>.md``  — human report.
  * ``reports/strategy-discovery/latest.md``  — copy / link to today.

CLI:
    python3 scripts/strategy_discovery_report.py [--no-write] [--dry-run]

Defaults are safe: ``--dry-run`` is implied for the registration step
unless ``--register`` is passed. The script does NOT mutate runtime
strategies and does NOT call any broker. INVARIANT.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared"))

try:
    from strategy_discovery_sandbox import (              # type: ignore
        identify_candidates,
        generate_proposals,
        register_proposals_with_quarantine,
        INVARIANTS,
    )
    from strategy_variant_quarantine import list_variants  # type: ignore
except ImportError:
    from shared.strategy_discovery_sandbox import (        # type: ignore
        identify_candidates,
        generate_proposals,
        register_proposals_with_quarantine,
        INVARIANTS,
    )
    from shared.strategy_variant_quarantine import (       # type: ignore
        list_variants,
    )


def _safe_read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _safe_read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
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


def _load_strategy_ranking() -> list[dict]:
    """Best-effort load of strategy_ranking.json. Empty list if missing."""
    path = REPO_ROOT / "learning-loop" / "strategy_ranking.json"
    data = _safe_read_json(path)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        return [x for x in data["rows"] if isinstance(x, dict)]
    return []


def _load_opportunity_ledger(days: int = 7) -> list[dict]:
    """Concatenate last ``days`` opportunity-ledger JSONL files."""
    base = REPO_ROOT / "learning-loop" / "opportunity_ledger"
    if not base.exists():
        return []
    out: list[dict] = []
    today = datetime.now(timezone.utc).date()
    for delta in range(days):
        d = today - timedelta(days=delta)
        out.extend(_safe_read_jsonl(base / f"{d.isoformat()}.jsonl"))
    return out


def _existing_variants_by_parent() -> dict[str, list[dict]]:
    by_parent: dict[str, list[dict]] = {}
    for v in list_variants():
        parent = v.get("parent_strategy")
        if isinstance(parent, str) and parent:
            by_parent.setdefault(parent, []).append(v)
    return by_parent


def _render_markdown(
    *,
    candidates: list[dict],
    proposals_per_candidate: list[list[dict]],
    invariants: list[tuple[str, bool]],
    registered: list[dict] | None,
) -> str:
    lines: list[str] = []
    lines.append("# Strategy Discovery Sandbox report")
    lines.append("")
    lines.append(f"Generated: `{datetime.now(timezone.utc).isoformat()}` (UTC)")
    lines.append("")
    lines.append("## Invariants")
    lines.append("")
    for name, value in invariants:
        lines.append(f"- `{name}` = `{value}`")
    lines.append("")
    if not candidates:
        lines.append("## Summary")
        lines.append("")
        lines.append(
            "No candidates identified for this run. Strategies are either"
            " healthy (no discovery needed) or outright rejected by"
            " Strategy Quality Gate (different remedy)."
        )
        lines.append("")
    else:
        lines.append("## Candidates")
        lines.append("")
        lines.append("| Strategy | Trigger | n_trades | Evidence | Rejection ratio |")
        lines.append("|---|---|---|---|---|")
        for c in candidates:
            lines.append(
                f"| `{c.get('strategy')}` | "
                f"`{c.get('trigger')}` | "
                f"{c.get('n_trades')} | "
                f"`{c.get('evidence_status') or '(unknown)'}` | "
                f"{c.get('rejection_ratio', 0.0):.2f} |"
            )
        lines.append("")
        lines.append("## Variant proposals")
        lines.append("")
        for c, props in zip(candidates, proposals_per_candidate):
            lines.append(f"### `{c.get('strategy')}` "
                         f"— trigger `{c.get('trigger')}`")
            lines.append("")
            if not props:
                lines.append("- (none generated)")
                lines.append("")
                continue
            for p in props:
                lines.append(
                    f"- **kind**: `{p.get('kind')}` — "
                    f"params `{json.dumps(p.get('params'), sort_keys=True)}`"
                )
                lines.append(
                    f"  - rationale: {p.get('change_rationale')}"
                )
                lines.append(
                    f"  - expected: {p.get('expected_effect')}"
                )
                lines.append(
                    f"  - risk: {p.get('risk_note')}"
                )
            lines.append("")
    if registered is not None:
        lines.append("## Registered with quarantine")
        lines.append("")
        if not registered:
            lines.append("- (none)")
        else:
            for rec in registered:
                if "error" in rec:
                    lines.append(
                        f"- ERROR: `{rec.get('parent_strategy', '?')}` "
                        f"({rec.get('kind', '?')}) — {rec.get('error')}"
                    )
                else:
                    lines.append(
                        f"- `{rec.get('id')}` parent=`{rec.get('parent_strategy')}` "
                        f"status=`{rec.get('status')}` "
                        f"kind=`{rec.get('sandbox_kind', '?')}`"
                    )
        lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "Quarantined variants are **never** auto-applied to runtime. "
        "Promotion is governed by the Multi-Agent Audit Board and the "
        "Strategy Quality Gate; this report is informational only."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Strategy Discovery Sandbox report.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print the report to stdout instead of writing to reports/.",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help=(
            "Register the proposals in the variant quarantine zone. "
            "Default: identify-only (no quarantine writes)."
        ),
    )
    args = parser.parse_args()

    ranking = _load_strategy_ranking()
    ledger = _load_opportunity_ledger(days=7)
    existing = _existing_variants_by_parent()

    candidates = identify_candidates(
        strategy_ranking=ranking,
        opportunity_ledger=ledger,
        existing_variants=existing,
    )

    proposals_per_candidate: list[list[dict]] = []
    flat_proposals: list = []
    for c in candidates:
        plist = generate_proposals(c)
        proposals_per_candidate.append([p.to_dict() for p in plist])
        flat_proposals.extend(plist)

    registered: list[dict] | None = None
    if args.register:
        registered = register_proposals_with_quarantine(flat_proposals)

    md = _render_markdown(
        candidates=candidates,
        proposals_per_candidate=proposals_per_candidate,
        invariants=list(INVARIANTS),
        registered=registered,
    )

    if args.no_write:
        sys.stdout.write(md)
        return 0

    out_dir = REPO_ROOT / "reports" / "strategy-discovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).date().isoformat()
    out_path = out_dir / f"{date}.md"
    out_path.write_text(md, encoding="utf-8")
    (out_dir / "latest.md").write_text(md, encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
