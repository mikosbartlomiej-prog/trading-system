#!/usr/bin/env python3
"""v3.24 (2026-06-15) — Gate-distribution explainer (ETAP 6).

WHY
---
``shadow_eligible_count`` is the single number the operator looks at
to decide whether the v3.22+ wiring is producing usable shadow
evidence. When that number is ZERO, the operator should see — at a
glance — WHICH gate is responsible: confidence null? risk reject?
no signal? data-quality failure?

This reporter aggregates the opportunity ledger over the last 7 days
and breaks down every row by:

  * monitor (resolved via STRATEGY_TO_MONITOR map)
  * strategy
  * risk_decision  (DETECTED / APPROVE / REJECT / NO_SIGNAL /
                    HALTED_BY_DRAWDOWN_GUARD / HALTED_BY_VIX_GUARD)
  * confidence_decision  (ALLOW / ALERT_ONLY / BLOCK / ERROR /
                            OBSERVE_ONLY_SKIP / NULL)
  * top gate blocker  (first failed gate from rejection_reasons /
                       raw_signal.blocking_reason)
  * data-failure token  (raw_signal.diagnostic_token /
                          confidence_error / blocking_reason)

When ``shadow_eligible_count == 0``, the markdown report MUST surface
the dominant explanation tokens at the top.

OUTPUTS
-------
- ``learning-loop/gate_distribution_latest.json``
- ``docs/GATE_DISTRIBUTION_STATUS.md``

HARD SAFETY RULES
-----------------
- NEVER imports ``alpaca_orders``.
- NEVER calls broker / network endpoints.
- NEVER mutates state.json or runtime_state.json.
- Pure read-only aggregation.
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

LATEST_JSON_PATH = (REPO_ROOT / "learning-loop"
                    / "gate_distribution_latest.json")
LATEST_MD_PATH = REPO_ROOT / "docs" / "GATE_DISTRIBUTION_STATUS.md"
LEDGER_DIR = REPO_ROOT / "learning-loop" / "opportunity_ledger"

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "GATE_DISTRIBUTION_IS_READ_ONLY",
)

VERSION = "v3.24.0"

STRATEGY_TO_MONITOR = {
    "crypto-momentum":        "crypto-monitor",
    "crypto-oversold-bounce": "crypto-monitor",
    "crypto-breakdown":       "crypto-monitor",
    "momentum-long":          "price-monitor",
    "momentum-long-loose":    "price-monitor",
    "overbought-short":       "price-monitor",
    "geo-defense":            "geo-monitor",
    "geo-energy":             "geo-monitor",
    "geo-gold":               "geo-monitor",
    "geo-xom":                "geo-monitor",
    "geo-news":               "geo-monitor",
    "options-momentum":       "options-monitor",
    "alloc-exit":             "allocator",
    "alloc-reduce":           "allocator",
    "allocator-rebalance":    "allocator",
    "defense-long":           "defense-monitor",
    "defense-short":          "defense-monitor",
    "twitter-news":           "twitter-monitor",
    "twitter-news-review":    "twitter-monitor",
    "twitter-A-direct":       "twitter-monitor",
    "twitter-B-escalation-defense": "twitter-monitor",
    "twitter-B-escalation-energy":  "twitter-monitor",
    "twitter-C-deescalation-spy":   "twitter-monitor",
    "twitter-C-deescalation-xle":   "twitter-monitor",
    "twitter-D-macro-bull":         "twitter-monitor",
    "twitter-D-macro-bear-gld":     "twitter-monitor",
    "twitter-D-macro-bear-spy":     "twitter-monitor",
    "reddit-sentiment":             "reddit-monitor",
    "politician-djt-form4":         "politician-monitor",
    "politician-stock-act":         "politician-monitor",
    "position-manager":             "exit-monitor",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True, check=True, text=True, timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return out
    return out


def _load_ledger_rows(repo_root: Path, as_of: datetime, days: int
                      ) -> list[dict]:
    ledger_dir = repo_root / "learning-loop" / "opportunity_ledger"
    rows: list[dict] = []
    for delta in range(days):
        d = (as_of - timedelta(days=delta)).date()
        rows.extend(_load_jsonl(ledger_dir / f"{d.isoformat()}.jsonl"))
    return rows


def _monitor_of(strategy: str | None) -> str:
    if not strategy:
        return "unknown"
    return STRATEGY_TO_MONITOR.get(strategy, "unknown")


def _row_risk_decision(row: dict) -> str:
    rd = (row.get("risk_decision") or "").upper().strip()
    if not rd:
        # Some rows pre-v3.22 carry signal_state in raw_signal.
        raw = row.get("raw_signal") or {}
        ss = (raw.get("signal_state") or "").upper().strip()
        if ss:
            return ss
        return "UNKNOWN"
    return rd


def _row_confidence_decision(row: dict) -> str:
    raw = row.get("raw_signal") or {}
    cd = (raw.get("confidence_decision") or "").upper().strip()
    cs = (raw.get("confidence_status") or "").upper().strip()
    if cs == "OBSERVE_ONLY_SKIP":
        return "OBSERVE_ONLY_SKIP"
    if cs == "ERROR":
        return "ERROR"
    if cd in ("ALLOW", "ALERT_ONLY", "BLOCK"):
        return cd
    if row.get("confidence_score") is None:
        return "NULL"
    return cd or "NULL"


def _row_top_blocker(row: dict) -> str:
    """First failed gate (BLOCK / DEFER / DOWNSIZE) from rejection_reasons.

    Falls back to the raw_signal.blocking_reason when no gate decisions
    were recorded.
    """
    reasons = row.get("rejection_reasons") or []
    if isinstance(reasons, list) and reasons:
        # Each is "gate: reason" — return the first.
        return str(reasons[0])
    raw = row.get("raw_signal") or {}
    br = raw.get("blocking_reason")
    if br:
        return f"raw:{br}"
    # Also support gate_decisions explicit.
    gds = row.get("gate_decisions") or []
    if isinstance(gds, list):
        for g in gds:
            if not isinstance(g, dict):
                continue
            dec = (g.get("decision") or "").upper()
            if dec in ("BLOCK", "DEFER", "DOWNSIZE", "ALERT_ONLY", "REJECT"):
                return f"{g.get('gate', 'unknown')}: {g.get('reason', dec)}"
    return "NO_BLOCKER"


def _row_data_failure_token(row: dict) -> str | None:
    """Extract a data-failure token if any was recorded."""
    raw = row.get("raw_signal") or {}
    for key in (
        "diagnostic_token",
        "data_failure",
        "data_quality_failure",
        "confidence_error",
        "blocking_reason",
    ):
        val = raw.get(key)
        if val:
            return f"{key}={val}"
    return None


def _is_shadow_eligible(row: dict) -> bool:
    """v3.22+ definition: APPROVE-style risk + numeric confidence >= 0.50."""
    rd = _row_risk_decision(row)
    if rd not in ("APPROVE", "DETECTED"):
        return False
    score = row.get("confidence_score")
    if score is None:
        return False
    try:
        return float(score) >= 0.50
    except (TypeError, ValueError):
        return False


# ─── Build ────────────────────────────────────────────────────────────────────


def build_distribution(
    *,
    as_of: datetime,
    repo_root: Path | None = None,
    days: int = 7,
) -> dict[str, Any]:
    if repo_root is None:
        repo_root = REPO_ROOT
    rows = _load_ledger_rows(repo_root, as_of, days=days)
    total_rows = len(rows)

    rows_by_monitor: dict[str, int] = collections.Counter()
    rows_by_strategy: dict[str, int] = collections.Counter()
    rows_by_risk_decision: dict[str, int] = collections.Counter()
    rows_by_confidence_decision: dict[str, int] = collections.Counter()
    rows_by_gate_blocker: dict[str, int] = collections.Counter()
    rows_by_data_failure_token: dict[str, int] = collections.Counter()
    shadow_eligible_count = 0

    # per-strategy / per-monitor breakdowns of top blocker
    top_blocker_per_strategy: dict[str, dict[str, int]] = collections.defaultdict(
        collections.Counter)
    top_blocker_per_monitor: dict[str, dict[str, int]] = collections.defaultdict(
        collections.Counter)

    for r in rows:
        strat = r.get("strategy") or "unknown"
        monitor = _monitor_of(strat)
        rows_by_monitor[monitor] += 1
        rows_by_strategy[strat] += 1
        rd = _row_risk_decision(r)
        rows_by_risk_decision[rd] += 1
        cd = _row_confidence_decision(r)
        rows_by_confidence_decision[cd] += 1
        blocker = _row_top_blocker(r)
        rows_by_gate_blocker[blocker] += 1
        tok = _row_data_failure_token(r)
        if tok:
            rows_by_data_failure_token[tok] += 1

        top_blocker_per_strategy[strat][blocker] += 1
        top_blocker_per_monitor[monitor][blocker] += 1

        if _is_shadow_eligible(r):
            shadow_eligible_count += 1

    # Reduce per-strategy / per-monitor to "most common blocker".
    def _reduce(d: dict[str, dict[str, int]]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for key, ctr in d.items():
            if not ctr:
                continue
            top_blocker, top_count = ctr.most_common(1)[0]
            out[key] = {
                "top_blocker": top_blocker,
                "count":       top_count,
                "share_pct":   round(
                    100.0 * top_count / max(sum(ctr.values()), 1), 1),
            }
        return out

    top_per_strategy_reduced = _reduce(top_blocker_per_strategy)
    top_per_monitor_reduced = _reduce(top_blocker_per_monitor)

    # Build dominant explanations when shadow_eligible_count==0.
    dominant_explanation: list[dict] = []
    if shadow_eligible_count == 0 and total_rows > 0:
        # Top contributors to NULL confidence + risk blocks.
        cd_null_share = rows_by_confidence_decision.get("NULL", 0) / total_rows
        if cd_null_share > 0:
            dominant_explanation.append({
                "factor":     "confidence_decision=NULL",
                "share_pct":  round(cd_null_share * 100.0, 1),
                "explanation": (
                    "confidence_score is NULL — emit path did not run, "
                    "monitor missed back-fill, or downstream consumer "
                    "did not persist the field."),
            })
        for risk_blocker in (
            "REJECT",
            "HALTED_BY_DRAWDOWN_GUARD",
            "HALTED_BY_VIX_GUARD",
            "NO_SIGNAL",
        ):
            count = rows_by_risk_decision.get(risk_blocker, 0)
            if count > 0:
                dominant_explanation.append({
                    "factor":     f"risk_decision={risk_blocker}",
                    "share_pct":  round(100.0 * count / total_rows, 1),
                    "explanation": (
                        f"{count}/{total_rows} rows blocked at "
                        f"the risk gate ({risk_blocker})"),
                })
        for cd_blocker in ("BLOCK", "ERROR"):
            count = rows_by_confidence_decision.get(cd_blocker, 0)
            if count > 0:
                dominant_explanation.append({
                    "factor":     f"confidence_decision={cd_blocker}",
                    "share_pct":  round(100.0 * count / total_rows, 1),
                    "explanation": (
                        f"{count}/{total_rows} rows blocked at "
                        f"the confidence gate ({cd_blocker})"),
                })
        if not dominant_explanation:
            dominant_explanation.append({
                "factor":     "all_rows_below_confidence_threshold",
                "share_pct":  100.0,
                "explanation": (
                    "All ledger rows have numeric confidence_score "
                    "< 0.50; no shadow-eligible rows."),
            })

    # ── Shadow-eligibility distribution (v3.25 explicit) ──
    # Rows fall into one of four buckets that operators use to triage:
    #   * eligible            — APPROVE/DETECTED + numeric conf >= 0.50
    #   * conf_null           — confidence_score is None
    #   * conf_below_thresh   — confidence_score is numeric but < 0.50
    #   * risk_blocked        — risk_decision NOT in (APPROVE, DETECTED)
    shadow_eligibility_distribution: dict[str, int] = collections.Counter()
    for r in rows:
        rd = _row_risk_decision(r)
        score = r.get("confidence_score")
        if rd not in ("APPROVE", "DETECTED"):
            shadow_eligibility_distribution["risk_blocked"] += 1
            continue
        if score is None:
            shadow_eligibility_distribution["conf_null"] += 1
            continue
        try:
            if float(score) >= 0.50:
                shadow_eligibility_distribution["eligible"] += 1
            else:
                shadow_eligibility_distribution["conf_below_thresh"] += 1
        except (TypeError, ValueError):
            shadow_eligibility_distribution["conf_null"] += 1

    # ── Actionable next-fix advice (v3.25) ──
    # Deterministic operator-facing hints based on dominant blockers.
    # NEVER recommends lowering risk thresholds or enabling broker paths.
    actionable: list[dict] = []
    if total_rows > 0:
        cd_null = rows_by_confidence_decision.get("NULL", 0)
        observe_only = rows_by_confidence_decision.get("OBSERVE_ONLY_SKIP", 0)
        risk_reject = rows_by_risk_decision.get("REJECT", 0)
        no_signal = rows_by_risk_decision.get("NO_SIGNAL", 0)
        drawdown_halt = rows_by_risk_decision.get(
            "HALTED_BY_DRAWDOWN_GUARD", 0)
        approve_or_det = (
            rows_by_risk_decision.get("APPROVE", 0)
            + rows_by_risk_decision.get("DETECTED", 0)
        )
        # Bias hints toward what is highest-impact for shadow_eligible_count.
        if cd_null > 0 and approve_or_det > 0:
            actionable.append({
                "priority":  "P1",
                "hint": (
                    f"{approve_or_det} APPROVE/DETECTED rows lack numeric "
                    "confidence_score. Wire post-decision confidence "
                    "back-fill so eligible rows can accumulate."),
            })
        if observe_only > 0:
            actionable.append({
                "priority":  "P2",
                "hint": (
                    f"{observe_only} OBSERVE_ONLY_SKIP rows present. "
                    "Verify v3.24 confidence emitter promotes top-level "
                    "fields (or extend readers to consume raw_signal.* "
                    "sentinels)."),
            })
        if no_signal > 0 and approve_or_det == 0:
            actionable.append({
                "priority":  "P3",
                "hint": (
                    f"{no_signal} NO_SIGNAL rows but zero APPROVE/DETECTED. "
                    "Monitors are scanning; strategies are not detecting "
                    "setups. Review setup criteria — do NOT lower risk "
                    "thresholds."),
            })
        if risk_reject > total_rows * 0.50:
            actionable.append({
                "priority":  "P3",
                "hint": (
                    f"{risk_reject}/{total_rows} rows REJECTed. Check top "
                    "blocker per strategy — fix data-quality or filter "
                    "criteria, NOT risk thresholds."),
            })
        if drawdown_halt > 0:
            actionable.append({
                "priority":  "INFO",
                "hint": (
                    f"{drawdown_halt} rows halted by drawdown guard "
                    "(expected protective behaviour)."),
            })
        if not actionable:
            actionable.append({
                "priority":  "INFO",
                "hint": (
                    "No dominant blocker detected; pipeline appears idle "
                    "or healthy — continue local observation."),
            })

    return {
        "version":             VERSION,
        "generated_at_iso":    datetime.now(timezone.utc).isoformat(),
        "as_of":               as_of.isoformat(),
        "git_head":            _git_head(),
        "window_days":         days,
        "total_rows":          total_rows,
        "shadow_eligible_count": shadow_eligible_count,
        "shadow_eligibility_distribution":
            dict(shadow_eligibility_distribution),
        "rows_by_monitor":     dict(rows_by_monitor),
        "rows_by_strategy":    dict(rows_by_strategy),
        "rows_by_risk_decision":      dict(rows_by_risk_decision),
        "rows_by_confidence_decision": dict(rows_by_confidence_decision),
        "rows_by_gate_blocker":        dict(rows_by_gate_blocker),
        "rows_by_data_failure_token":  dict(rows_by_data_failure_token),
        "top_blocker_per_strategy":    top_per_strategy_reduced,
        "top_blocker_per_monitor":     top_per_monitor_reduced,
        "dominant_explanation":        dominant_explanation,
        "actionable_next_fix":         actionable,
        "standing_markers":            list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":      False,
            "allow_broker_paper":     False,
            "live_trading_supported": False,
            "modifies_state_json":    False,
        },
    }


# ─── Rendering ────────────────────────────────────────────────────────────────


def _table(d: dict[str, int], header_a: str, header_b: str = "Count"
           ) -> str:
    if not d:
        return f"| {header_a} | {header_b} |\n|---|---|\n| (none) | 0 |"
    lines = [f"| {header_a} | {header_b} |", "|---|---|"]
    for k, v in sorted(d.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{k}` | {v} |")
    return "\n".join(lines)


def render_md(rep: dict[str, Any]) -> str:
    dominant_section = ""
    if rep["shadow_eligible_count"] == 0 and rep["total_rows"] > 0:
        rows = [
            "| Factor | Share % | Explanation |",
            "|---|---|---|",
        ]
        for e in rep["dominant_explanation"]:
            rows.append(
                f"| `{e['factor']}` | {e['share_pct']}% | {e['explanation']} |"
            )
        dominant_section = (
            "## Why `shadow_eligible_count = 0`\n\n"
            + "\n".join(rows)
            + "\n"
        )

    # Top 3 blockers overall
    top_blockers = sorted(
        rep["rows_by_gate_blocker"].items(),
        key=lambda kv: -kv[1])[:3]
    if top_blockers:
        tb_lines = [
            "| Blocker | Count |",
            "|---|---|",
        ]
        for k, v in top_blockers:
            tb_lines.append(f"| `{k}` | {v} |")
        top_blockers_section = "\n".join(tb_lines)
    else:
        top_blockers_section = "(no rows)"

    by_strat_rows: list[str] = [
        "| Strategy | Top blocker | Count | Share |",
        "|---|---|---|---|",
    ]
    for s, info in sorted(
            rep["top_blocker_per_strategy"].items(),
            key=lambda kv: -kv[1]["count"]):
        by_strat_rows.append(
            f"| `{s}` | `{info['top_blocker']}` | "
            f"{info['count']} | {info['share_pct']}% |"
        )
    if len(by_strat_rows) == 2:
        by_strat_rows.append("| (none) | | | |")

    by_mon_rows: list[str] = [
        "| Monitor | Top blocker | Count | Share |",
        "|---|---|---|---|",
    ]
    for m, info in sorted(
            rep["top_blocker_per_monitor"].items(),
            key=lambda kv: -kv[1]["count"]):
        by_mon_rows.append(
            f"| `{m}` | `{info['top_blocker']}` | "
            f"{info['count']} | {info['share_pct']}% |"
        )
    if len(by_mon_rows) == 2:
        by_mon_rows.append("| (none) | | | |")

    standing = "\n".join(f"- `{m}`" for m in rep["standing_markers"])

    # Shadow-eligibility distribution
    shadow_dist = rep.get("shadow_eligibility_distribution") or {}
    if shadow_dist:
        sd_lines = [
            "| Bucket | Count |",
            "|---|---|",
        ]
        for k, v in sorted(shadow_dist.items(), key=lambda kv: -kv[1]):
            sd_lines.append(f"| `{k}` | {v} |")
        shadow_dist_section = "\n".join(sd_lines)
    else:
        shadow_dist_section = "(no rows)"

    # Actionable next-fix
    actionable = rep.get("actionable_next_fix") or []
    if actionable:
        an_lines = [
            "| Priority | Hint |",
            "|---|---|",
        ]
        for a in actionable:
            an_lines.append(f"| `{a['priority']}` | {a['hint']} |")
        actionable_section = "\n".join(an_lines)
    else:
        actionable_section = "(none)"

    return f"""# Gate Distribution Status ({rep["version"]})

**Generated:** `{rep["generated_at_iso"]}`
**As of:** `{rep["as_of"]}`
**Git HEAD:** `{rep["git_head"]}`
**Window:** last {rep["window_days"]} days
**Total ledger rows:** `{rep["total_rows"]}`
**Shadow-eligible rows:** `{rep["shadow_eligible_count"]}`

{dominant_section}
## Top 3 blockers overall

{top_blockers_section}

## Top blocker per monitor

{chr(10).join(by_mon_rows)}

## Top blocker per strategy

{chr(10).join(by_strat_rows)}

## Rows by monitor

{_table(rep["rows_by_monitor"], "Monitor")}

## Rows by strategy

{_table(rep["rows_by_strategy"], "Strategy")}

## Rows by risk_decision

{_table(rep["rows_by_risk_decision"], "Risk decision")}

## Rows by confidence_decision

{_table(rep["rows_by_confidence_decision"], "Confidence decision")}

## Rows by gate blocker

{_table(rep["rows_by_gate_blocker"], "Gate blocker")}

## Rows by data-failure token

{_table(rep["rows_by_data_failure_token"], "Token")}

## Shadow eligibility distribution

{shadow_dist_section}

## Actionable next-fix advice

{actionable_section}

## Standing markers

{standing}
"""


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the v3.24 gate distribution report.")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    if args.as_of:
        try:
            as_of = datetime.fromisoformat(
                args.as_of.replace("Z", "+00:00"))
        except ValueError:
            print(f"Invalid --as-of: {args.as_of}", file=sys.stderr)
            return 2
    else:
        as_of = datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    rep = build_distribution(as_of=as_of, days=args.days)
    md = render_md(rep)

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
        # Surface essentials at CLI for the operator.
        print(
            f"shadow_eligible_count = {rep['shadow_eligible_count']} "
            f"(of {rep['total_rows']} rows)")
        if rep["dominant_explanation"]:
            print("Dominant explanations:")
            for e in rep["dominant_explanation"][:3]:
                print(f"  - {e['factor']} ({e['share_pct']}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
