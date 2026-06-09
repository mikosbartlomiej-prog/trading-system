#!/usr/bin/env python3
"""v3.27.0 (2026-06-09) — auto-update SHADOW_EVIDENCE_PROGRESS.md.

Reads ``learning-loop/shadow_evidence/evidence_counters_latest.json``
and rewrites a structured section of
``docs/SHADOW_EVIDENCE_PROGRESS.md`` between the markers
``<!-- v3.27 auto-progress-start -->`` and
``<!-- v3.27 auto-progress-end -->`` so the operator-facing doc
always reflects the live counter values.

NEVER submits orders. NEVER imports ``shared/alpaca_orders.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

DOC_PATH = REPO_ROOT / "docs" / "SHADOW_EVIDENCE_PROGRESS.md"
MARKER_START = "<!-- v3.27 auto-progress-start -->"
MARKER_END   = "<!-- v3.27 auto-progress-end -->"


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def _refuse_if_broker_enabled() -> str | None:
    for name in (
        "ALLOW_BROKER_PAPER", "EDGE_GATE_ENABLED",
        "BROKER_EXECUTION_ENABLED",
        "LIVE_TRADING", "LIVE_ENABLED", "GO_LIVE",
        "LIVE_TRADING_ENABLED",
    ):
        if _env_truthy(name):
            return f"REFUSED_{name}_IS_TRUTHY"
    return None


def render_progress_block(
    counters: dict,
    *,
    last_collector_status: str | None,
    last_outcome_resolver_status: str | None,
    daily_learning_stable: bool,
    trade_reconstruction_stable: bool,
) -> str:
    """Render the auto-progress section. Pure function."""
    now_iso = datetime.now(timezone.utc).isoformat()
    rm = counters.get("real_market_opportunities_count", 0)
    cs = counters.get("completed_shadow_outcomes_count", 0)
    si = counters.get("safety_invariants") or {}
    return f"""{MARKER_START}

## Automated progress snapshot (v3.27)

**Last auto-update:** `{now_iso}`
**Source:** `learning-loop/shadow_evidence/evidence_counters_latest.json`
**Generator:** `scripts/update_shadow_evidence_progress.py`

### Canary-gate counters

| Metric | Current | Target |
|---|---:|---:|
| `real_market_opportunities_count` | **{rm}** | 50 |
| `completed_shadow_outcomes_count` | **{cs}** | 20 |
| `audit_bypass_findings_count` | {counters.get('audit_bypass_findings_count', 0)} | 0 |
| `exposure_cap_breach_count` | {counters.get('exposure_cap_breach_count', 0)} | 0 |
| `repeated_buy_violation_count` | {counters.get('repeated_buy_violation_count', 0)} | 0 |
| `unexplained_broker_state_conflicts_count` | {counters.get('unexplained_broker_state_conflicts_count', 0)} | 0 |

### Observational counters

| Metric | Current |
|---|---:|
| `scaffold_no_market_data_records_count` | {counters.get('scaffold_no_market_data_records_count', 0)} |
| `halt_path_records_count` | {counters.get('halt_path_records_count', 0)} |
| `halt_path_opportunities_count` | {counters.get('halt_path_opportunities_count', 0)} |
| `normal_non_halt_opportunities_count` (legacy) | {counters.get('normal_non_halt_opportunities_count', 0)} |
| `would_block_by_crypto_exposure_count` | {counters.get('would_block_by_crypto_exposure_count', 0)} |
| `would_block_by_drawdown_guard_count` | {counters.get('would_block_by_drawdown_guard_count', 0)} |
| `would_block_by_recent_loss_cooldown_count` | {counters.get('would_block_by_recent_loss_cooldown_count', 0)} |

### Readiness verdicts

| Tier | Verdict |
|---|---|
| Signal/shadow unlock | `SIGNAL_SHADOW_UNLOCK_READY` |
| Broker paper canary | **`BROKER_PAPER_CANARY_NOT_READY`** |
| Live trading | `LIVE_TRADING_NOT_SUPPORTED` |

### Automated run telemetry

| Field | Value |
|---|---|
| Last collector status | `{last_collector_status or 'n/a'}` |
| Last outcome resolver status | `{last_outcome_resolver_status or 'n/a'}` |
| `daily_learning_stable` | `{str(daily_learning_stable).lower()}` |
| `trade_reconstruction_stable` | `{str(trade_reconstruction_stable).lower()}` |

### Safety invariants from counters file

- `broker_order_submitted_ever`: `{str(si.get('broker_order_submitted_ever', False)).lower()}`
- `live_trading_enabled`: `{str(si.get('live_trading_enabled', False)).lower()}`
- `broker_paper_enabled`: `{str(si.get('broker_paper_enabled', False)).lower()}`
- `edge_gate_enabled`: `{str(si.get('edge_gate_enabled', False)).lower()}`
- `baseline_reset`: `{str(si.get('baseline_reset', False)).lower()}`
- `drawdown_guard_lowered`: `{str(si.get('drawdown_guard_lowered', False)).lower()}`

{MARKER_END}
"""


def upsert_progress_block(text: str, new_block: str) -> str:
    if MARKER_START in text and MARKER_END in text:
        before = text.split(MARKER_START, 1)[0]
        after = text.split(MARKER_END, 1)[1]
        return before + new_block + after
    # No markers yet — append at the end.
    return text.rstrip() + "\n\n" + new_block


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Auto-update SHADOW_EVIDENCE_PROGRESS.md from "
                    "live counters.",
    )
    parser.add_argument("--collector-status", default=None,
                          help="Optional last collector status token to "
                               "embed in the report.")
    parser.add_argument("--resolver-status", default=None,
                          help="Optional last outcome resolver status "
                               "token to embed in the report.")
    parser.add_argument("--daily-learning-stable", action="store_true")
    parser.add_argument("--trade-reconstruction-stable",
                          action="store_true")
    args = parser.parse_args(argv)

    refuse = _refuse_if_broker_enabled()
    if refuse is not None:
        print(json.dumps({"status": refuse, "version": "v3.27.0"}))
        return 1

    counters_path = (REPO_ROOT / "learning-loop" / "shadow_evidence"
                       / "evidence_counters_latest.json")
    if not counters_path.exists():
        print(json.dumps({
            "status": "COUNTERS_FILE_MISSING",
            "path": str(counters_path),
        }))
        return 1
    counters = json.loads(counters_path.read_text(encoding="utf-8"))

    block = render_progress_block(
        counters,
        last_collector_status=args.collector_status,
        last_outcome_resolver_status=args.resolver_status,
        daily_learning_stable=bool(args.daily_learning_stable),
        trade_reconstruction_stable=bool(args.trade_reconstruction_stable),
    )
    if DOC_PATH.exists():
        text = DOC_PATH.read_text(encoding="utf-8")
    else:
        text = "# Shadow Evidence Progress\n"
    new_text = upsert_progress_block(text, block)
    DOC_PATH.write_text(new_text, encoding="utf-8")

    print(json.dumps({
        "status":           "UPDATED",
        "version":          "v3.27.0",
        "doc_path":         str(DOC_PATH.relative_to(REPO_ROOT)),
        "real_market_opportunities_count":
            counters.get("real_market_opportunities_count", 0),
        "completed_shadow_outcomes_count":
            counters.get("completed_shadow_outcomes_count", 0),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
