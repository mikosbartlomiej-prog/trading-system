#!/usr/bin/env python3
"""v3.29 (2026-06-16) — Daily operational brief.

Single-page operator-readable digest that summarises the state of the
whole system. Pulls from the v3.27/v3.28/v3.29 reporter outputs that
already live under ``learning-loop/`` and renders one consolidated
Markdown brief plus a JSON sidecar.

Outputs
-------
- ``learning-loop/daily_operational_brief_latest.json``
- ``docs/DAILY_OPERATIONAL_BRIEF.md``

HARD SAFETY
-----------
- NEVER imports ``shared.alpaca_orders`` or ``alpaca_orders``.
- NEVER imports any broker SDK.
- NEVER makes a network call.
- NEVER mutates state.json or runtime_state.json.
- NEVER flips any flag.
- NEVER submits orders, never cancels orders, never closes positions.
- Inputs that are missing or unparseable degrade to ``UNKNOWN`` rows.

Standing markers footer is included.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

LATEST_JSON_PATH = (REPO_ROOT / "learning-loop"
                     / "daily_operational_brief_latest.json")
LATEST_MD_PATH   = REPO_ROOT / "docs" / "DAILY_OPERATIONAL_BRIEF.md"

STANDING_MARKERS = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(rel: str) -> dict | None:
    p = REPO_ROOT / rel
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _system_activation() -> dict:
    """Best-effort: master gate verdict. Fail-soft to UNKNOWN."""
    try:
        try:
            from system_activation_gate import evaluate  # type: ignore
        except ImportError:
            from shared.system_activation_gate import evaluate  # type: ignore
        return evaluate().to_dict()
    except Exception as e:
        return {
            "decision": "UNKNOWN",
            "reason":   f"system_activation_read_error: "
                         f"{type(e).__name__}: {e}",
            "shadow_permitted": False,
        }


def build_brief() -> dict:
    """Aggregate every available reporter output into one brief."""
    out: dict[str, Any] = {
        "generated_at_iso":   _now_iso(),
        "schema_version":     "v3.29",
        "module":             "scripts.generate_daily_operational_brief",
        "standing_markers":   list(STANDING_MARKERS),
    }

    out["system_activation"] = _system_activation()

    # Each entry: (label, relative path under learning-loop/)
    inputs = [
        ("heartbeat_freshness",
         "learning-loop/heartbeat_freshness_latest.json"),
        ("evidence_throughput_sla",
         "learning-loop/evidence_throughput_sla_latest.json"),
        ("real_market_evidence_status",
         "learning-loop/shadow_evidence/"
         "real_market_evidence_status_latest.json"),
        ("monitor_runtime_diag",
         "learning-loop/monitor_runtime_diag_status_latest.json"),
        ("gate_distribution",
         "learning-loop/gate_distribution_latest.json"),
        ("near_miss_status",
         "learning-loop/near_miss_status_latest.json"),
        ("confidence_precalibration_readiness",
         "learning-loop/confidence_precalibration_readiness_latest.json"),
        ("strategy_threshold_reality",
         "learning-loop/strategy_threshold_reality_latest.json"),
        ("replay_discovery",
         "learning-loop/replay_discovery_latest.json"),
        ("backfill_snapshot_status",
         "learning-loop/backfill_snapshot_status_latest.json"),
        ("near_miss_seed_status",
         "learning-loop/near_miss_seed_status_latest.json"),
        ("strategy_variant_quarantine",
         "learning-loop/strategy_variant_quarantine_latest.json"),
        ("shadow_candidate_queue",
         "learning-loop/shadow_candidate_queue_latest.json"),
        ("opportunity_density_plan",
         "learning-loop/opportunity_density_plan_latest.json"),
        ("equity_gap_reconciliation",
         "learning-loop/equity_gap_reconciliation_latest.json"),
        ("safe_mode_consistency",
         "learning-loop/safe_mode_consistency_latest.json"),
        ("broker_repair_required",
         "learning-loop/broker_repair_required_latest.json"),
        ("llm_advisory_activation",
         "learning-loop/llm_advisory/activation_status_latest.json"),
        ("llm_advisory_quality_review",
         "learning-loop/llm_advisory/quality_review_latest.json"),
    ]

    component_status: dict[str, dict] = {}
    for label, rel in inputs:
        data = _read_json(rel)
        if data is None:
            component_status[label] = {
                "status":   "MISSING",
                "source":   rel,
                "summary":  "no artefact present (cron may not have run "
                            "yet, or this reporter is not configured)",
            }
            continue
        verdict = data.get("verdict") or data.get("status") or data.get("decision")
        component_status[label] = {
            "status":   "OK_PRESENT",
            "verdict":  verdict,
            "source":   rel,
            "summary":  _short_summary(label, data),
        }
    out["components"] = component_status

    return out


def _short_summary(label: str, data: dict) -> str:
    """Short, human-readable one-liner per reporter."""
    try:
        if label == "heartbeat_freshness":
            stale = data.get("stale_components") or []
            return f"stale_components={len(stale)}"
        if label == "evidence_throughput_sla":
            total = data.get("total_rows_24h")
            verdict = data.get("verdict")
            return f"rows_24h={total} verdict={verdict}"
        if label == "broker_repair_required":
            entries = data.get("entries") or data
            if isinstance(entries, dict):
                return f"entries={len(entries)}"
            return f"raw_keys={list(data.keys())[:4]}"
        if label == "safe_mode_consistency":
            return f"verdict={data.get('verdict')}"
        if label == "system_activation":
            return f"decision={data.get('decision')}"
        # generic
        for k in ("decision", "verdict", "status", "summary"):
            if k in data:
                return f"{k}={data.get(k)}"
        return "present"
    except Exception:
        return "present_unparseable"


def render_md(brief: dict) -> str:
    sa = brief.get("system_activation") or {}
    decision = sa.get("decision", "UNKNOWN")
    reason   = sa.get("reason", "")
    shadow_ok = sa.get("shadow_permitted", False)

    lines: list[str] = []
    lines.append("# Daily Operational Brief (v3.29)")
    lines.append("")
    lines.append(f"_Generated:_ `{brief.get('generated_at_iso', '')}`")
    lines.append("")
    lines.append("## Master verdict")
    lines.append("")
    lines.append(f"- System activation decision: `{decision}`")
    lines.append(f"- Reason: `{reason}`")
    lines.append(f"- Shadow simulator permitted: "
                 f"`{'YES' if shadow_ok else 'NO'}`")
    lines.append("")
    lines.append("## Component reporters")
    lines.append("")
    lines.append("| Component | Status | Verdict / Summary | Source |")
    lines.append("|-----------|--------|-------------------|--------|")
    comps = brief.get("components") or {}
    for label in sorted(comps.keys()):
        c = comps[label]
        status  = c.get("status", "UNKNOWN")
        verdict = c.get("verdict") or ""
        summary = c.get("summary") or ""
        source  = c.get("source", "")
        lines.append(f"| `{label}` | `{status}` | "
                     f"`{verdict}` / {summary} | `{source}` |")
    lines.append("")
    lines.append("## Operator action checklist")
    lines.append("")
    if shadow_ok:
        lines.append("- [x] No incident state is blocking shadow simulation.")
    else:
        lines.append("- [ ] Master verdict is NOT in "
                     "{ALLOCATOR_ALLOWED, SYSTEM_ACTIVE_SHADOW_ONLY}; "
                     "investigate the component(s) above before flipping "
                     "any flag.")
    lines.append("- [ ] Do NOT enable broker paper. "
                 "`ALLOW_BROKER_PAPER=false` stays pinned.")
    lines.append("- [ ] Do NOT enable live trading. "
                 "`LIVE_TRADING_UNSUPPORTED`.")
    lines.append("- [ ] Do NOT auto-clear safe_mode.")
    lines.append("- [ ] Do NOT let any LLM mutate state, flip flags, or "
                 "place orders.")
    lines.append("")
    lines.append("## Standing markers")
    for m in brief.get("standing_markers") or STANDING_MARKERS:
        lines.append(f"- `{m}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_This brief is built by aggregating already-on-disk "
                 "reporter artefacts. It never opens a network "
                 "connection, never submits an order, never cancels an "
                 "order, never closes a position, never mutates "
                 "state.json or runtime_state.json._")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    brief = build_brief()
    md = render_md(brief)

    if args.json:
        print(json.dumps(brief, indent=2, sort_keys=True))

    if not args.no_write:
        LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_JSON_PATH.write_text(
            json.dumps(brief, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_MD_PATH.write_text(md, encoding="utf-8")
        print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
        print(f"Wrote {LATEST_MD_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
