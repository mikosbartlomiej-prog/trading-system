#!/usr/bin/env python3
"""v3.26.0 (2026-06-15) — Agent 3B — ETAP 7 — Shadow candidate queue.

Combines:
  * the replay-discovery output (``learning-loop/replay_discovery_latest.json``)
  * the near-miss aggregate (``learning-loop/near_miss_status_latest.json``)
  * the quarantine variant list (currently empty — placeholder for
    future SHADOW_ONLY variants)

into a candidate queue. Each row represents a (strategy, symbol) pair
that the operator MIGHT promote to shadow observation IF the right
real-time market condition occurs. Status remains
``WAITING_FOR_REAL_MARKET_TRIGGER`` until a real-time event flips it.

CONTRACT
--------
- Every row mode = ``SHADOW_ONLY``.
- Every row status = ``WAITING_FOR_REAL_MARKET_TRIGGER``.
- This script NEVER imports ``alpaca_orders``.
- This script NEVER makes network calls.
- This script NEVER places orders.
- This script NEVER writes to ``opportunity_ledger``.
- This script NEVER triggers a shadow-evidence collection itself.
- Standing markers footer reproduced verbatim.

Outputs:
  * ``learning-loop/shadow_candidate_queue_latest.json``
  * ``docs/SHADOW_CANDIDATE_QUEUE.md``
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
REPLAY_INPUT = REPO_ROOT / "learning-loop" / "replay_discovery_latest.json"
NEAR_MISS_INPUT = REPO_ROOT / "learning-loop" / "near_miss_status_latest.json"
QUARANTINE_DIR = REPO_ROOT / "learning-loop" / "quarantine_variants"
STATE_PATH = REPO_ROOT / "learning-loop" / "state.json"
LATEST_JSON_PATH = (REPO_ROOT / "learning-loop"
                    / "shadow_candidate_queue_latest.json")
LATEST_MD_PATH = REPO_ROOT / "docs" / "SHADOW_CANDIDATE_QUEUE.md"

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "SHADOW_CANDIDATE_NEVER_AUTO_PROMOTED",
    "SHADOW_CANDIDATE_NEVER_PLACES_ORDERS",
    "QUEUE_NEVER_INFLATES_SHADOW_ELIGIBILITY",
)

VERSION = "v3.26.0"

MODE_SHADOW_ONLY = "SHADOW_ONLY"
STATUS_WAITING = "WAITING_FOR_REAL_MARKET_TRIGGER"

# Strategy-specific trigger templates (textual hints — operator-readable,
# never executed). These describe what a real-time bar event would have
# to satisfy for the candidate to flip to "READY_FOR_SHADOW_OBSERVATION".
STRATEGY_TRIGGER_TEMPLATES: dict[str, str] = {
    "momentum-long": (
        "close crosses above 20-day high "
        "AND volume > 1.5x 20-day avg AND RSI(14) in [50, 70]"
    ),
    "momentum-long-loose": (
        "close crosses above 20-day high "
        "AND volume > 1.2x 20-day avg AND RSI(14) in [45, 75]"
    ),
    "overbought-short": (
        "RSI(14) > 72 AND 2-of-3 weakening conditions met"
    ),
    "crypto-momentum": (
        "predator-bracket 24h move in [3%, 15%] AND RSI band met "
        "AND volume > avg multiplier"
    ),
    "crypto-oversold-bounce": (
        "RSI(14) <= 30 on H1 close AND 3-bar stabilization "
        "AND volume >= 25% of avg"
    ),
}

CONFIDENCE_EXPECTATION_DEFAULT = "0.50 - 0.75 (builder default)"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _safe_read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_quarantine_variants(qdir: Path) -> list[dict]:
    """Future-proof: directory may not exist yet. Return [] if absent."""
    if not qdir.exists() or not qdir.is_dir():
        return []
    out: list[dict] = []
    for f in sorted(qdir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            out.append(data)
        elif isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
    return out


def _active_risk_blockers() -> list[str]:
    """Pull active risk blockers from state.json — VIX, drawdown, etc.

    Read-only. Returns []  if state.json absent or malformed.
    """
    data = _safe_read_json(STATE_PATH)
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    # Daily drawdown
    pnl_pct = data.get("daily_pnl_pct") or data.get("today_stats", {}).get("daily_pnl_pct")
    if isinstance(pnl_pct, (int, float)) and pnl_pct <= -3.0:
        out.append(f"DAILY_DRAWDOWN_TRIPPED:{pnl_pct:.1f}%")
    # VIX
    vix = data.get("vix") or data.get("today_stats", {}).get("vix")
    if isinstance(vix, (int, float)) and vix >= 35.0:
        out.append(f"VIX_ELEVATED:{vix:.1f}")
    # defensive_mode armed
    dm = data.get("defensive_mode") or {}
    if isinstance(dm, dict) and dm.get("armed"):
        out.append("DEFENSIVE_MODE_ARMED")
    return out


# ─── Build ────────────────────────────────────────────────────────────────────


def build_queue(
    *,
    as_of: datetime,
    replay_input: Optional[Path] = None,
    near_miss_input: Optional[Path] = None,
    quarantine_dir: Optional[Path] = None,
    min_near_miss: int = 3,
    min_candidates: int = 1,
) -> dict[str, Any]:
    """Build the candidate queue. Pure compute — no writes."""
    replay = _safe_read_json(replay_input or REPLAY_INPUT) or {}
    near_miss = _safe_read_json(near_miss_input or NEAR_MISS_INPUT) or {}
    quarantine = _load_quarantine_variants(quarantine_dir or QUARANTINE_DIR)
    risk_blockers = _active_risk_blockers()

    rows: list[dict] = []
    seen_keys: set[tuple[str, str, Optional[str]]] = set()

    # ── Source 1: replay-discovery rows ─────────────────────────────────────
    for r in replay.get("rows", []):
        if not isinstance(r, dict):
            continue
        strategy = r.get("strategy")
        symbol = r.get("symbol")
        cands = int(r.get("candidates") or 0)
        nm = int(r.get("near_misses") or 0)
        if not strategy or not symbol:
            continue
        if cands < min_candidates and nm < min_near_miss:
            continue
        key = (strategy, symbol, None)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        reason_parts = []
        if cands >= min_candidates:
            reason_parts.append(f"replay candidates 7d: {cands}")
        if nm >= min_near_miss:
            reason_parts.append(f"near-miss replay count: {nm}")
        rows.append({
            "strategy":                       strategy,
            "variant_id":                     None,
            "symbol":                         symbol,
            "asset_class":                    r.get("asset_class") or
                                              ("crypto" if "/" in symbol else "us_equity"),
            "reason":                         "; ".join(reason_parts),
            "required_real_time_condition":   STRATEGY_TRIGGER_TEMPLATES.get(
                strategy,
                "operator must define trigger before shadow can begin"
            ),
            "confidence_expectation":         CONFIDENCE_EXPECTATION_DEFAULT,
            "risk_blockers":                  list(risk_blockers),
            "data_requirements":              "daily bars (us_equity) or H1 bars (crypto)",
            "mode":                           MODE_SHADOW_ONLY,
            "status":                         STATUS_WAITING,
            "source":                         "replay_discovery",
            "replay_candidate_count":         cands,
            "near_miss_count":                nm,
        })

    # ── Source 2: near-miss aggregate ───────────────────────────────────────
    flagged = near_miss.get("flagged") if isinstance(near_miss, dict) else None
    if isinstance(flagged, list):
        for f in flagged:
            if not isinstance(f, dict):
                continue
            strategy = f.get("strategy_id") or f.get("strategy")
            symbol = f.get("symbol")
            if not strategy:
                continue
            if not symbol:
                symbol = "UNSPECIFIED"
            sample = int(f.get("sample_size") or 0)
            if sample < min_near_miss:
                continue
            key = (strategy, symbol, None)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append({
                "strategy":                       strategy,
                "variant_id":                     None,
                "symbol":                         symbol,
                "asset_class":                    "us_equity" if symbol != "UNSPECIFIED" and "/" not in symbol else "crypto",
                "reason":                         (
                    f"near-miss aggregate sample={sample}; "
                    f"reason={f.get('advisory_reason', 'operator review')}"),
                "required_real_time_condition":   STRATEGY_TRIGGER_TEMPLATES.get(
                    strategy,
                    "operator must define trigger before shadow can begin"
                ),
                "confidence_expectation":         CONFIDENCE_EXPECTATION_DEFAULT,
                "risk_blockers":                  list(risk_blockers),
                "data_requirements":              "metric-specific bars",
                "mode":                           MODE_SHADOW_ONLY,
                "status":                         STATUS_WAITING,
                "source":                         "near_miss_aggregate",
                "replay_candidate_count":         0,
                "near_miss_count":                sample,
            })

    # ── Source 3: quarantined SHADOW_ONLY variants ──────────────────────────
    for variant in quarantine:
        if not isinstance(variant, dict):
            continue
        if (variant.get("mode") or "").upper() != MODE_SHADOW_ONLY:
            # Only SHADOW_ONLY variants are eligible.
            continue
        strategy = variant.get("parent_strategy") or variant.get("strategy")
        variant_id = variant.get("variant_id") or variant.get("id")
        symbols = variant.get("symbols") or [variant.get("symbol")]
        if not isinstance(symbols, list):
            symbols = [symbols]
        for symbol in symbols:
            if not strategy or not symbol:
                continue
            key = (strategy, symbol, variant_id)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append({
                "strategy":                       strategy,
                "variant_id":                     variant_id,
                "symbol":                         symbol,
                "asset_class":                    variant.get("asset_class")
                                                  or ("crypto" if "/" in symbol else "us_equity"),
                "reason":                         (
                    f"quarantined variant: {variant.get('rationale', 'awaiting trigger')}"),
                "required_real_time_condition":   variant.get("trigger_condition")
                    or STRATEGY_TRIGGER_TEMPLATES.get(
                        strategy,
                        "operator must define trigger before shadow can begin"),
                "confidence_expectation":         variant.get("confidence_expectation")
                    or CONFIDENCE_EXPECTATION_DEFAULT,
                "risk_blockers":                  list(risk_blockers),
                "data_requirements":              variant.get("data_requirements")
                    or "metric-specific bars",
                "mode":                           MODE_SHADOW_ONLY,
                "status":                         STATUS_WAITING,
                "source":                         "quarantine_variant",
                "replay_candidate_count":         0,
                "near_miss_count":                0,
            })

    by_source = collections.Counter(r["source"] for r in rows)

    return {
        "version":          VERSION,
        "generated_at_iso": datetime.now(timezone.utc).isoformat(),
        "as_of":            as_of.isoformat(),
        "rows":             rows,
        "rows_total":       len(rows),
        "rows_by_source":   dict(by_source),
        "active_risk_blockers": risk_blockers,
        "standing_markers": list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":            False,
            "allow_broker_paper":           False,
            "live_trading_supported":       False,
            "modifies_state_json":          False,
            "places_orders":                False,
            "writes_opportunity_ledger":    False,
            "all_rows_mode_shadow_only":    True,
            "all_rows_waiting_for_trigger": True,
        },
    }


# ─── Rendering ────────────────────────────────────────────────────────────────


def render_md(rep: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Shadow candidate queue ({rep['version']})")
    lines.append("")
    lines.append(f"**Generated:** `{rep['generated_at_iso']}`")
    lines.append(f"**As of:** `{rep['as_of']}`")
    lines.append(f"**Total rows:** {rep['rows_total']}")
    lines.append(f"**Active risk blockers:** "
                 f"{', '.join(rep['active_risk_blockers']) or 'none'}")
    lines.append("")
    lines.append("Each row is a candidate. Status remains "
                 f"`{STATUS_WAITING}` until a real-market event "
                 "satisfies the trigger condition. This queue NEVER "
                 "auto-promotes a row.")
    lines.append("")
    by_src = rep["rows_by_source"]
    if by_src:
        lines.append("## Rows by source")
        lines.append("")
        lines.append("| Source | Count |")
        lines.append("|---|---|")
        for k, v in sorted(by_src.items()):
            lines.append(f"| `{k}` | {v} |")
        lines.append("")

    lines.append("## Candidate rows")
    lines.append("")
    lines.append(
        "| Strategy | Variant | Symbol | Asset | Reason | Trigger | "
        "Confidence Exp. | Risk Blockers | Mode | Status |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    if not rep["rows"]:
        lines.append("| (no candidates yet — empty queue is expected) | | | | | | | | | |")
    for r in rep["rows"]:
        risk = ", ".join(r.get("risk_blockers") or []) or "none"
        lines.append(
            f"| `{r['strategy']}` | "
            f"{r.get('variant_id') or '—'} | "
            f"`{r['symbol']}` | {r['asset_class']} | "
            f"{r['reason']} | {r['required_real_time_condition']} | "
            f"{r['confidence_expectation']} | {risk} | "
            f"**{r['mode']}** | **{r['status']}** |"
        )

    lines.append("")
    lines.append("## Safety contract")
    lines.append("")
    lines.append("- Every row mode = `SHADOW_ONLY`.")
    lines.append("- Every row status = `WAITING_FOR_REAL_MARKET_TRIGGER`.")
    lines.append("- This queue NEVER places orders.")
    lines.append("- This queue NEVER auto-promotes a row.")
    lines.append("- This queue NEVER inflates shadow eligibility counters.")
    lines.append("- This script NEVER imports `alpaca_orders`.")
    lines.append("- This script NEVER makes network calls.")
    lines.append("")
    lines.append("## Standing markers")
    lines.append("")
    for m in rep["standing_markers"]:
        lines.append(f"- `{m}`")
    lines.append("")
    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="v3.26 — Shadow candidate queue (Agent 3B / ETAP 7).",
    )
    p.add_argument("--as-of", default=None)
    p.add_argument("--min-near-miss", type=int, default=3)
    p.add_argument("--min-candidates", type=int, default=1)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-write", action="store_true")
    args = p.parse_args(argv)

    if args.as_of:
        try:
            as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        except ValueError:
            print(f"Invalid --as-of: {args.as_of}", file=sys.stderr)
            return 2
    else:
        as_of = datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    rep = build_queue(
        as_of=as_of,
        min_near_miss=args.min_near_miss,
        min_candidates=args.min_candidates,
    )
    md = render_md(rep)
    # v3.28 — ETAP 10 — annotate discovery report with the active
    # BROKER_REPAIR_REQUIRED incident, if any. Banner is informational
    # only and NEVER changes the report content. Fail-soft: helper
    # absent → no-op.
    try:
        from _discovery_incident_banner import prepend_incident_banner  # type: ignore
        md = prepend_incident_banner(md)
    except Exception:
        pass

    if args.json:
        print(json.dumps(rep, indent=2, sort_keys=True))

    if not args.no_write:
        LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_JSON_PATH.write_text(
            json.dumps(rep, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_MD_PATH.write_text(md, encoding="utf-8")
        print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
        print(f"Wrote {LATEST_MD_PATH.relative_to(REPO_ROOT)}")
        print(f"Queue rows: {rep['rows_total']} | "
              f"By source: {rep['rows_by_source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
