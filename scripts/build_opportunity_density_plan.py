#!/usr/bin/env python3
"""v3.27.0 (2026-06-15) — Opportunity Density Plan (ETAP 10).

Synthesizes ALL v3.26+v3.27 discovery artefacts into a single,
concise operator plan. NEVER recommends auto-lowering a threshold.
NEVER recommends enabling broker/live. NEVER promises profit.
NEVER counts replay / near-miss / shadow as paper edge.

Inputs (all read-only)
----------------------
- ``learning-loop/strategy_threshold_reality_latest.json``
- ``learning-loop/replay_discovery_latest.json`` (or
  ``learning-loop/replay_entry_candidate_discovery_latest.json``)
- ``learning-loop/universe_opportunity_review_latest.json``
- ``learning-loop/shadow_candidate_queue_latest.json``
- ``learning-loop/trigger_watchlist_latest.json``
- ``learning-loop/near_miss/*.jsonl`` (last 7 days aggregate)
- ``learning-loop/strategy_variant_quarantine_latest.json``
- ``learning-loop/monitor_emission_status_latest.json`` (or
  ``learning-loop/monitor_runtime_diag_status_latest.json``)
- ``learning-loop/confidence_precalibration_readiness_latest.json``

Outputs
-------
- ``docs/OPPORTUNITY_DENSITY_PLAN.md``
- ``learning-loop/opportunity_density_plan_latest.json``

Sections rendered
-----------------
A. Strategies closest to firing (top 5)
B. Symbols with most near-misses (top 10)
C. Variants worth observing (top 5 from quarantine)
D. Monitors needing diagnostic attention (any WIRED_BUT_NOT_FIRING)
E. Universe changes (observe-only adds, NO trade-eligible promotion)
F. Thresholds for operator review (top 3 by TOO_STRICT vote)
G. Data we need to collect over next 7/14/30 days

Hard-safety rules
-----------------
- NEVER imports ``alpaca_orders``.
- NEVER makes a network call.
- NEVER suggests "lower threshold X to Y" — only "operator review".
- NEVER recommends turning on broker/paper/live.
- NEVER promises profit; uses observational language only.
- Standing markers reproduced in every artefact.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

LL = REPO_ROOT / "learning-loop"
DOCS = REPO_ROOT / "docs"

# Input artefacts (resolved at runtime; missing files are tolerated).
STRATEGY_REALITY     = LL / "strategy_threshold_reality_latest.json"
REPLAY_DISCOVERY     = LL / "replay_discovery_latest.json"
REPLAY_DISCOVERY_ALT = LL / "replay_entry_candidate_discovery_latest.json"
UNIVERSE_REVIEW      = LL / "universe_opportunity_review_latest.json"
SHADOW_QUEUE         = LL / "shadow_candidate_queue_latest.json"
TRIGGER_WATCHLIST    = LL / "trigger_watchlist_latest.json"
NEAR_MISS_DIR        = LL / "near_miss"
VARIANT_QUARANTINE   = LL / "strategy_variant_quarantine_latest.json"
MONITOR_EMISSION     = LL / "monitor_emission_status_latest.json"
MONITOR_EMISSION_ALT = LL / "monitor_runtime_diag_status_latest.json"
PRECAL_READINESS     = LL / "confidence_precalibration_readiness_latest.json"

OUTPUT_JSON = LL / "opportunity_density_plan_latest.json"
OUTPUT_MD   = DOCS / "OPPORTUNITY_DENSITY_PLAN.md"

VERSION = "v3.27.0"

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "DENSITY_PLAN_NEVER_LOWERS_THRESHOLDS",
    "DENSITY_PLAN_NEVER_PROMISES_PROFIT",
    "DENSITY_PLAN_NEVER_PROMOTES_VARIANTS",
    "DENSITY_PLAN_NEVER_ENABLES_BROKER",
    "REPLAY_NEVER_COUNTS_AS_PAPER_EDGE",
    "NEAR_MISS_NEVER_COUNTS_AS_PAPER_EDGE",
    "SHADOW_NEVER_COUNTS_AS_PAPER_EDGE",
)


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_read_json(p: Path) -> dict[str, Any] | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_near_miss_rows(
    *,
    base_dir: Path,
    days: int = 7,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    if not base_dir.exists():
        return []
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    end_date = as_of.date()
    start_date = end_date - timedelta(days=days - 1)
    for p in sorted(base_dir.glob("*.jsonl")):
        try:
            file_date = datetime.strptime(p.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < start_date or file_date > end_date:
            continue
        try:
            with p.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            continue
    return rows


# ─── Section A: strategies closest to firing ─────────────────────────────────


def _section_a_strategies_closest_to_firing(
    *,
    reality: dict[str, Any] | None,
    replay: dict[str, Any] | None,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Combine candidate counts (replay) and near-miss rate (reality)."""
    score_by_strategy: dict[str, dict[str, Any]] = {}
    if isinstance(replay, dict):
        per_strat: dict[str, int] = defaultdict(int)
        for row in (replay.get("rows") or []):
            if not isinstance(row, dict):
                continue
            s = row.get("strategy")
            if not isinstance(s, str):
                continue
            per_strat[s] += int(row.get("candidates") or 0)
        for s, c in per_strat.items():
            score_by_strategy.setdefault(s, {})["replay_candidates"] = c

    if isinstance(reality, dict):
        for s in (reality.get("strategies") or []):
            sid = s.get("strategy_id")
            if not isinstance(sid, str):
                continue
            entry = score_by_strategy.setdefault(sid, {})
            entry["recommendation"] = s.get("recommendation")
            entry["threshold_realism"] = s.get("threshold_realism")
            metrics = s.get("metrics") or []
            entry["near_miss_rate"] = max(
                (m.get("near_miss_rate") or 0.0) for m in metrics
            ) if metrics else 0.0
            entry["actual_signals_fired"] = s.get("actual_signals_fired", 0)

    rows: list[dict[str, Any]] = []
    for s, d in score_by_strategy.items():
        rows.append({
            "strategy_id":          s,
            "replay_candidates":    int(d.get("replay_candidates", 0)),
            "near_miss_rate":       round(float(d.get("near_miss_rate", 0.0)), 4),
            "actual_signals_fired": int(d.get("actual_signals_fired", 0)),
            "recommendation":       d.get("recommendation"),
            "threshold_realism":    d.get("threshold_realism"),
            "advisory_note":        (
                "operator-review only; auto-threshold changes refused"
            ),
        })
    # Rank: more replay candidates first; higher near-miss rate breaks ties.
    rows.sort(key=lambda r: (
        -r["replay_candidates"], -r["near_miss_rate"]
    ))
    return rows[:top_n]


# ─── Section B: symbols with most near-misses ────────────────────────────────


def _section_b_top_symbols_by_near_misses(
    *,
    near_miss_rows: list[dict[str, Any]],
    top_n: int = 10,
) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    by_strategy: dict[str, Counter[str]] = defaultdict(Counter)
    for r in near_miss_rows:
        if not isinstance(r, dict):
            continue
        sym = r.get("symbol")
        if not isinstance(sym, str) or not sym:
            continue
        counter[sym] += 1
        strat = r.get("strategy_id") or r.get("strategy")
        if isinstance(strat, str):
            by_strategy[sym][strat] += 1
    out: list[dict[str, Any]] = []
    for sym, n in counter.most_common(top_n):
        top_strat = by_strategy[sym].most_common(1)
        out.append({
            "symbol":            sym,
            "near_miss_count":   int(n),
            "top_strategy":      top_strat[0][0] if top_strat else None,
            "advisory_note":     "observational; never auto-promotes",
        })
    return out


# ─── Section C: variants worth observing ─────────────────────────────────────


def _section_c_variants_worth_observing(
    *,
    quarantine: dict[str, Any] | None,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    if not isinstance(quarantine, dict):
        return []
    rows = (quarantine.get("rows")
            or quarantine.get("variants")
            or [])
    out: list[dict[str, Any]] = []
    for v in rows:
        if not isinstance(v, dict):
            continue
        out.append({
            "variant_id":    (v.get("variant_id")
                              or v.get("id")
                              or v.get("name")),
            "strategy_id":   (v.get("strategy_id")
                              or v.get("parent_strategy")),
            "status":        (v.get("status")
                              or v.get("dataclass_status")
                              or "QUARANTINED"),
            "observed_for":  (v.get("days_observed")
                              or v.get("observation_days")
                              or 0),
            "advisory_note": (
                "observe-only; never promoted to active runtime"
            ),
        })
    # Stable order: highest observation count first.
    out.sort(key=lambda r: -(int(r.get("observed_for") or 0)))
    return out[:top_n]


# ─── Section D: monitors needing diagnostic attention ────────────────────────


def _section_d_monitors_needing_attention(
    *,
    emission: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Surface monitors that are wired but produce no signals.

    The schema differs between ``monitor_emission_status_latest.json``
    and ``monitor_runtime_diag_status_latest.json``. Both layouts are
    handled defensively.
    """
    if not isinstance(emission, dict):
        return []
    out: list[dict[str, Any]] = []

    # Layout A: explicit per-monitor status field.
    per_monitor = (emission.get("per_monitor")
                   or emission.get("monitors")
                   or {})
    if isinstance(per_monitor, dict):
        for mon, d in per_monitor.items():
            if not isinstance(d, dict):
                continue
            status = d.get("status")
            if isinstance(status, str) and status.upper() in (
                "WIRED_BUT_NOT_FIRING",
                "SILENT", "NO_SIGNAL", "STALE",
            ):
                out.append({
                    "monitor":          mon,
                    "status":           status,
                    "advisory_note":    "diagnostic review only",
                })
                continue
            # Heuristic: positive RAN count but zero SIGNAL_DETECTED.
            ran = int(d.get("RAN") or 0)
            sigd = int(d.get("SIGNAL_DETECTED") or 0)
            emit_failed = int(d.get("EMIT_FAILED") or 0)
            if ran > 0 and sigd == 0:
                out.append({
                    "monitor":       mon,
                    "status":        "WIRED_BUT_NOT_FIRING",
                    "ran":           ran,
                    "signals":       sigd,
                    "advisory_note": "diagnostic review only",
                })
            elif emit_failed > 0:
                out.append({
                    "monitor":       mon,
                    "status":        "EMIT_FAILURE_PRESENT",
                    "ran":           ran,
                    "emit_failed":   emit_failed,
                    "advisory_note": "diagnostic review only",
                })

    # Layout B (older): top-level aggregate counts.
    agg = emission.get("aggregate")
    if isinstance(agg, dict):
        per = agg.get("per_monitor")
        if isinstance(per, dict):
            for mon, d in per.items():
                if any(o.get("monitor") == mon for o in out):
                    continue
                if not isinstance(d, dict):
                    continue
                ran = int(d.get("RAN") or 0)
                sigd = int(d.get("SIGNAL_DETECTED") or 0)
                if ran > 0 and sigd == 0:
                    out.append({
                        "monitor":       mon,
                        "status":        "WIRED_BUT_NOT_FIRING",
                        "ran":           ran,
                        "signals":       sigd,
                        "advisory_note": "diagnostic review only",
                    })
    return out


# ─── Section E: universe changes (observe-only) ──────────────────────────────


def _section_e_universe_changes_observe_only(
    *,
    universe: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(universe, dict):
        return {
            "observe_only_additions":   [],
            "remove_advisory":          [],
            "note": ("universe artefact unavailable; "
                     "no observe-only additions surfaced"),
        }
    rows = universe.get("rows") or []
    observe = [
        {
            "symbol":         r.get("symbol"),
            "asset_class":    r.get("asset_class"),
            "recommendation": r.get("recommendation"),
            "advisory_note":  ("observe-only; never trade-eligible "
                                "promotion"),
        }
        for r in rows
        if isinstance(r, dict)
        and r.get("recommendation") in ("ADD_FOR_OBSERVATION", "OBSERVE")
    ]
    remove = [
        {
            "symbol":         r.get("symbol"),
            "recommendation": r.get("recommendation"),
            "advisory_note":  "operator review only",
        }
        for r in rows
        if isinstance(r, dict)
        and r.get("recommendation") == "REMOVE_LOW_QUALITY"
    ]
    return {
        "observe_only_additions":   observe,
        "remove_advisory":          remove,
        "note": ("Universe changes are NEVER auto-applied; this is "
                 "an operator-review surface."),
    }


# ─── Section F: thresholds for operator review ───────────────────────────────


def _section_f_thresholds_for_review(
    *,
    reality: dict[str, Any] | None,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    if not isinstance(reality, dict):
        return []
    candidates: list[dict[str, Any]] = []
    for s in (reality.get("strategies") or []):
        sid = s.get("strategy_id")
        for m in (s.get("metrics") or []):
            realism = m.get("threshold_realism")
            if realism in ("TOO_STRICT", "TOO_LOOSE"):
                candidates.append({
                    "strategy_id":      sid,
                    "metric_name":      m.get("metric_name"),
                    "threshold":        m.get("threshold"),
                    "threshold_realism": realism,
                    "hit_rate":         m.get("hit_rate"),
                    "near_miss_rate":   m.get("near_miss_rate"),
                    "sample_size":      m.get("sample_size"),
                    "advisory_note": (
                        "operator-review only; reporter NEVER "
                        "auto-lowers any threshold"
                    ),
                })
    # Prefer TOO_STRICT first (those have the highest opportunity-density
    # blocked pool); within each, prefer high near-miss rate.
    def _key(c: dict[str, Any]) -> tuple[int, float]:
        prio = 0 if c["threshold_realism"] == "TOO_STRICT" else 1
        return (prio, -float(c.get("near_miss_rate") or 0.0))
    candidates.sort(key=_key)
    return candidates[:top_n]


# ─── Section G: data we need to collect over next 7/14/30 days ───────────────


def _section_g_data_collection_plan(
    *,
    reality: dict[str, Any] | None,
    precal: dict[str, Any] | None,
) -> dict[str, Any]:
    """Translate sample-size gaps into per-strategy ETA estimates."""
    rows: list[dict[str, Any]] = []
    if isinstance(reality, dict):
        for s in (reality.get("strategies") or []):
            sid = s.get("strategy_id")
            evals = int(s.get("evaluations", 0))
            fired = int(s.get("actual_signals_fired", 0))
            metrics = s.get("metrics") or []
            sample = max((int(m.get("sample_size") or 0)
                          for m in metrics), default=0)
            # ETA bands: 7d (<10 sample), 14d (<30), 30d (<50).
            if sample < 10:
                eta = "7d_minimum"
            elif sample < 30:
                eta = "14d_recommended"
            else:
                eta = "30d_full_review"
            rows.append({
                "strategy_id":       sid,
                "evaluations":       evals,
                "actual_signals_fired": fired,
                "current_sample":    sample,
                "eta_band":          eta,
                "advisory_note": ("estimate based on current "
                                  "evaluation rate; NEVER auto-acts"),
            })

    precal_v327 = (precal or {}).get("source_separation", {})
    return {
        "per_strategy_eta": rows,
        "global": {
            "production_positive_rows":
                int(precal_v327.get("production_positive_rows", 0)),
            "replay_positive_rows":
                int(precal_v327.get("replay_positive_rows", 0)),
            "near_miss_rows":
                int(precal_v327.get("near_miss_rows", 0)),
            "outcomes_available":
                bool(precal_v327.get("outcomes_available", False)),
            "verdict_v327":
                precal_v327.get("verdict_v327"),
        },
        "note": (
            "Estimates only — calibration is NEVER recommended "
            "without real outcomes. Replay/near-miss never count "
            "as paper edge."
        ),
    }


# ─── Build ────────────────────────────────────────────────────────────────────


def build_plan(*, as_of: datetime | None = None) -> dict[str, Any]:
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    elif as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    reality = _safe_read_json(STRATEGY_REALITY)
    replay = (_safe_read_json(REPLAY_DISCOVERY)
              or _safe_read_json(REPLAY_DISCOVERY_ALT))
    universe = _safe_read_json(UNIVERSE_REVIEW)
    shadow_queue = _safe_read_json(SHADOW_QUEUE)
    trigger_watchlist = _safe_read_json(TRIGGER_WATCHLIST)
    quarantine = _safe_read_json(VARIANT_QUARANTINE)
    emission = (_safe_read_json(MONITOR_EMISSION)
                or _safe_read_json(MONITOR_EMISSION_ALT))
    precal = _safe_read_json(PRECAL_READINESS)
    near_miss_rows = _load_near_miss_rows(
        base_dir=NEAR_MISS_DIR, days=7, as_of=as_of)

    section_a = _section_a_strategies_closest_to_firing(
        reality=reality, replay=replay, top_n=5)
    section_b = _section_b_top_symbols_by_near_misses(
        near_miss_rows=near_miss_rows, top_n=10)
    section_c = _section_c_variants_worth_observing(
        quarantine=quarantine, top_n=5)
    section_d = _section_d_monitors_needing_attention(emission=emission)
    section_e = _section_e_universe_changes_observe_only(
        universe=universe)
    section_f = _section_f_thresholds_for_review(
        reality=reality, top_n=3)
    section_g = _section_g_data_collection_plan(
        reality=reality, precal=precal)

    return {
        "version":           VERSION,
        "generated_at_iso":  _now_iso(),
        "as_of":             as_of.isoformat(),
        "git_head":          _git_head(),
        "inputs_available": {
            "strategy_threshold_reality":
                STRATEGY_REALITY.exists(),
            "replay_discovery":
                (REPLAY_DISCOVERY.exists()
                 or REPLAY_DISCOVERY_ALT.exists()),
            "universe_opportunity_review":
                UNIVERSE_REVIEW.exists(),
            "shadow_candidate_queue":
                SHADOW_QUEUE.exists(),
            "trigger_watchlist":
                TRIGGER_WATCHLIST.exists(),
            "near_miss_dir_present":
                NEAR_MISS_DIR.exists(),
            "near_miss_rows_7d":
                len(near_miss_rows),
            "strategy_variant_quarantine":
                VARIANT_QUARANTINE.exists(),
            "monitor_emission_status":
                (MONITOR_EMISSION.exists()
                 or MONITOR_EMISSION_ALT.exists()),
            "confidence_precalibration_readiness":
                PRECAL_READINESS.exists(),
        },
        "sections": {
            "A_strategies_closest_to_firing":
                section_a,
            "B_top_symbols_by_near_misses":
                section_b,
            "C_variants_worth_observing":
                section_c,
            "D_monitors_needing_attention":
                section_d,
            "E_universe_changes_observe_only":
                section_e,
            "F_thresholds_for_operator_review":
                section_f,
            "G_data_collection_plan":
                section_g,
        },
        "standing_markers":  list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":          False,
            "allow_broker_paper":         False,
            "live_trading_supported":     False,
            "modifies_state_json":        False,
            "auto_adjusts_thresholds":    False,
            "imports_alpaca_orders":      False,
            "makes_network_calls":        False,
            "recommends_auto_lowering":   False,
            "recommends_broker_enable":   False,
            "promises_profit":            False,
            "promotes_variants":          False,
            "counts_replay_as_edge":      False,
            "counts_near_miss_as_edge":   False,
            "counts_shadow_as_edge":      False,
        },
    }


# ─── Rendering ────────────────────────────────────────────────────────────────


def _md_table_a(rows: list[dict[str, Any]]) -> str:
    out = [
        "| Strategy | Replay candidates | Near-miss rate | Signals fired | Recommendation | Realism |",
        "|---|---|---|---|---|---|",
    ]
    if not rows:
        out.append("| (none) | | | | | |")
        return "\n".join(out)
    for r in rows:
        out.append(
            f"| `{r['strategy_id']}` | {r['replay_candidates']} | "
            f"{r['near_miss_rate']} | {r['actual_signals_fired']} | "
            f"`{r.get('recommendation') or '-'}` | "
            f"`{r.get('threshold_realism') or '-'}` |"
        )
    return "\n".join(out)


def _md_table_b(rows: list[dict[str, Any]]) -> str:
    out = [
        "| Symbol | Near-miss count | Top strategy |",
        "|---|---|---|",
    ]
    if not rows:
        out.append("| (none) | | |")
        return "\n".join(out)
    for r in rows:
        out.append(
            f"| `{r['symbol']}` | {r['near_miss_count']} | "
            f"`{r.get('top_strategy') or '-'}` |"
        )
    return "\n".join(out)


def _md_table_c(rows: list[dict[str, Any]]) -> str:
    out = [
        "| Variant | Strategy | Status | Days observed |",
        "|---|---|---|---|",
    ]
    if not rows:
        out.append("| (none) | | | |")
        return "\n".join(out)
    for r in rows:
        out.append(
            f"| `{r.get('variant_id') or '-'}` | "
            f"`{r.get('strategy_id') or '-'}` | "
            f"`{r.get('status') or '-'}` | "
            f"{r.get('observed_for') or 0} |"
        )
    return "\n".join(out)


def _md_table_d(rows: list[dict[str, Any]]) -> str:
    out = [
        "| Monitor | Status | RAN | Signals | Note |",
        "|---|---|---|---|---|",
    ]
    if not rows:
        out.append("| (none) | | | | |")
        return "\n".join(out)
    for r in rows:
        out.append(
            f"| `{r['monitor']}` | `{r.get('status')}` | "
            f"{r.get('ran', '-')} | {r.get('signals', '-')} | "
            f"{r.get('advisory_note', '')} |"
        )
    return "\n".join(out)


def _md_table_e(sec: dict[str, Any]) -> str:
    add_rows = sec.get("observe_only_additions") or []
    rem_rows = sec.get("remove_advisory") or []
    out = [
        "**Observe-only additions** (NEVER trade-eligible):",
        "",
        "| Symbol | Asset class | Recommendation |",
        "|---|---|---|",
    ]
    if not add_rows:
        out.append("| (none) | | |")
    else:
        for r in add_rows:
            out.append(
                f"| `{r.get('symbol') or '-'}` | "
                f"`{r.get('asset_class') or '-'}` | "
                f"`{r.get('recommendation') or '-'}` |"
            )
    out.append("")
    out.append("**Operator-review remove candidates:**")
    out.append("")
    out.append("| Symbol | Recommendation |")
    out.append("|---|---|")
    if not rem_rows:
        out.append("| (none) | |")
    else:
        for r in rem_rows:
            out.append(
                f"| `{r.get('symbol') or '-'}` | "
                f"`{r.get('recommendation') or '-'}` |"
            )
    return "\n".join(out)


def _md_table_f(rows: list[dict[str, Any]]) -> str:
    out = [
        "| Strategy | Metric | Threshold | Realism | Hit rate | Near-miss rate | Sample |",
        "|---|---|---|---|---|---|---|",
    ]
    if not rows:
        out.append("| (none) | | | | | | |")
        return "\n".join(out)
    for r in rows:
        out.append(
            f"| `{r.get('strategy_id') or '-'}` | "
            f"`{r.get('metric_name') or '-'}` | "
            f"{r.get('threshold')} | "
            f"`{r.get('threshold_realism') or '-'}` | "
            f"{r.get('hit_rate')} | "
            f"{r.get('near_miss_rate')} | "
            f"{r.get('sample_size')} |"
        )
    return "\n".join(out)


def _md_table_g(sec: dict[str, Any]) -> str:
    rows = sec.get("per_strategy_eta") or []
    glob = sec.get("global") or {}
    out = [
        "**Global snapshot:**",
        "",
        f"- Production positive rows: `{glob.get('production_positive_rows', 0)}`",
        f"- Replay positive rows: `{glob.get('replay_positive_rows', 0)}`",
        f"- Near-miss rows (7d): `{glob.get('near_miss_rows', 0)}`",
        f"- Outcomes available: `{glob.get('outcomes_available', False)}`",
        f"- Verdict (v3.27): `{glob.get('verdict_v327') or 'unknown'}`",
        "",
        "**Per-strategy ETA estimates:**",
        "",
        "| Strategy | Sample | ETA band | Evaluations | Signals fired |",
        "|---|---|---|---|---|",
    ]
    if not rows:
        out.append("| (none) | | | | |")
        return "\n".join(out)
    for r in rows:
        out.append(
            f"| `{r.get('strategy_id') or '-'}` | "
            f"{r.get('current_sample')} | "
            f"`{r.get('eta_band')}` | "
            f"{r.get('evaluations')} | "
            f"{r.get('actual_signals_fired')} |"
        )
    return "\n".join(out)


def render_md(plan: dict[str, Any]) -> str:
    sec = plan["sections"]
    standing = "\n".join(f"- `{m}`" for m in plan["standing_markers"])

    return f"""# Opportunity Density Plan ({plan["version"]})

**Generated:** `{plan["generated_at_iso"]}`
**As of:** `{plan["as_of"]}`
**Git HEAD:** `{plan["git_head"]}`

> Reporter NEVER recommends auto-lowering thresholds. NEVER recommends
> enabling broker / paper / live. NEVER promises profit. NEVER counts
> replay / near-miss / shadow records as paper edge. Every row carries
> an explicit `advisory_note` reaffirming the operator-review framing.

## A. Strategies closest to firing (top 5)

{_md_table_a(sec["A_strategies_closest_to_firing"])}

## B. Symbols with most near-misses (top 10)

{_md_table_b(sec["B_top_symbols_by_near_misses"])}

## C. Variants worth observing (top 5 from quarantine)

{_md_table_c(sec["C_variants_worth_observing"])}

> Quarantined variants are NEVER promoted to active runtime by this
> reporter. They are surfaced for observation only.

## D. Monitors needing diagnostic attention (WIRED_BUT_NOT_FIRING)

{_md_table_d(sec["D_monitors_needing_attention"])}

## E. Universe changes (observe-only adds, NO trade-eligible promotion)

{_md_table_e(sec["E_universe_changes_observe_only"])}

## F. Thresholds for operator review (top 3 by TOO_STRICT vote)

{_md_table_f(sec["F_thresholds_for_operator_review"])}

> This reporter NEVER auto-lowers any threshold — it surfaces the
> three most-blocked thresholds and asks the operator to review them.

## G. Data collection plan (next 7 / 14 / 30 days)

{_md_table_g(sec["G_data_collection_plan"])}

## Safety contract

- Reporter NEVER imports `alpaca_orders`.
- Reporter NEVER makes a network call.
- Reporter NEVER auto-lowers any threshold.
- Reporter NEVER enables broker / paper / live execution paths.
- Reporter NEVER promises profit.
- Reporter NEVER promotes a quarantined variant to active runtime.
- Reporter NEVER counts replay/near-miss/shadow rows as paper edge.

## Standing markers

{standing}
"""


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the v3.27 opportunity density plan.")
    parser.add_argument("--as-of", default=None)
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

    plan = build_plan(as_of=as_of)
    md = render_md(plan)

    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))

    if not args.no_write:
        OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_JSON.write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_MD.write_text(md, encoding="utf-8")
        print(f"Wrote {OUTPUT_JSON.relative_to(REPO_ROOT)}")
        print(f"Wrote {OUTPUT_MD.relative_to(REPO_ROOT)}")
        sec = plan["sections"]
        print(
            f"Sections: A={len(sec['A_strategies_closest_to_firing'])} "
            f"B={len(sec['B_top_symbols_by_near_misses'])} "
            f"C={len(sec['C_variants_worth_observing'])} "
            f"D={len(sec['D_monitors_needing_attention'])} "
            f"E={len(sec['E_universe_changes_observe_only'].get('observe_only_additions', []))} "
            f"F={len(sec['F_thresholds_for_operator_review'])} "
            f"G={len(sec['G_data_collection_plan'].get('per_strategy_eta', []))}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
