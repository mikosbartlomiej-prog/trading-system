#!/usr/bin/env python3
"""v3.27.0 (2026-06-15) — Shadow candidate queue seeder (ETAP 6).

Combines four source materials:
- near-miss aggregate (``learning-loop/near_miss_status_latest.json``)
- replay candidates (``learning-loop/replay_discovery_latest.json``)
- quarantined variants (``learning-loop/strategy_variant_quarantine_latest.json``)
- trigger watchlist (``learning-loop/trigger_watchlist_latest.json``)

into a SHADOW_ONLY candidate queue. Each row represents a
(strategy[, variant], symbol) pair that the operator MIGHT promote to
shadow observation IF the right real-market condition occurs. Rows
start ``status = WAITING_FOR_REAL_MARKET_TRIGGER``.

Hard-safety rules
-----------------
- Every row ``mode = "SHADOW_ONLY"``.
- Every row ``status = "WAITING_FOR_REAL_MARKET_TRIGGER"``.
- NEVER creates a shadow fill.
- NEVER counts a row as an opportunity (the writer of the queue file
  does NOT touch ``opportunity_ledger``).
- NEVER counts a row as paper evidence.
- NEVER imports ``alpaca_orders`` / ``requests`` / ``urllib`` / sockets.
- NEVER touches state.json / runtime_state.json.

Outputs
-------
- ``docs/SHADOW_CANDIDATE_QUEUE.md``
- ``learning-loop/shadow_candidate_queue_latest.json``
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ─── Paths ────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent

NEAR_MISS_STATUS_PATH = (
    REPO_ROOT / "learning-loop" / "near_miss_status_latest.json"
)
REPLAY_DISCOVERY_PATH = (
    REPO_ROOT / "learning-loop" / "replay_discovery_latest.json"
)
VARIANT_LATEST_PATH = (
    REPO_ROOT / "learning-loop" / "strategy_variant_quarantine_latest.json"
)
TRIGGER_WATCHLIST_PATH = (
    REPO_ROOT / "learning-loop" / "trigger_watchlist_latest.json"
)
STATE_JSON_PATH = REPO_ROOT / "learning-loop" / "state.json"

LATEST_JSON_PATH = (
    REPO_ROOT / "learning-loop" / "shadow_candidate_queue_latest.json"
)
LATEST_MD_PATH = REPO_ROOT / "docs" / "SHADOW_CANDIDATE_QUEUE.md"

VERSION = "v3.27.0"

# ─── Standing markers ─────────────────────────────────────────────────────────

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "SHADOW_CANDIDATE_NEVER_AUTO_PROMOTED",
    "SHADOW_CANDIDATE_NEVER_PLACES_ORDERS",
    "SHADOW_CANDIDATE_NEVER_CREATES_SHADOW_FILL",
    "QUEUE_NEVER_INFLATES_SHADOW_ELIGIBILITY",
    "QUEUE_NEVER_TOUCHES_STATE_JSON",
    "SEEDER_DOES_NOT_FETCH_NETWORK",
)

# ─── Closed enums ─────────────────────────────────────────────────────────────

MODE_SHADOW_ONLY = "SHADOW_ONLY"
STATUS_WAITING = "WAITING_FOR_REAL_MARKET_TRIGGER"

# Source labels accepted on emitted rows.
SOURCE_REAL = "REAL"
SOURCE_REPLAY = "REPLAY"
SOURCE_BACKFILL = "BACKFILL"
SOURCE_VARIANT = "VARIANT"
SOURCE_WATCHLIST = "WATCHLIST"
ALLOWED_SOURCES: frozenset[str] = frozenset({
    SOURCE_REAL, SOURCE_REPLAY, SOURCE_BACKFILL,
    SOURCE_VARIANT, SOURCE_WATCHLIST,
})

# Confidence expectation defaults — pulled from existing builder.
CONFIDENCE_EXPECTATION_DEFAULT = "0.50 - 0.75 (builder default)"

STRATEGY_TRIGGER_TEMPLATES: dict[str, str] = {
    "momentum-long": (
        "close crosses above 20-day high AND volume > 1.5x 20-day avg "
        "AND RSI(14) in [50, 70]"
    ),
    "momentum-long-loose": (
        "close crosses above 20-day high AND volume > 1.2x 20-day avg "
        "AND RSI(14) in [45, 75]"
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


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


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


def _safe_read_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _asset_class_for(symbol: str) -> str:
    return "crypto" if "/" in symbol else "us_equity"


def _data_requirements_for(asset_class: str) -> str:
    if asset_class == "crypto":
        return "H1 bars + RSI(14) + 24h move pct + volume avg multiplier"
    return "daily bars + RSI(14) + 20d high/low + volume avg"


def _risk_preconditions_from_state() -> list[str]:
    """READ-ONLY snapshot — never mutates state.json."""
    data = _safe_read_json(STATE_JSON_PATH)
    if not isinstance(data, dict):
        return []
    out: list[str] = []

    # daily drawdown
    today = data.get("today_stats") if isinstance(data.get("today_stats"), dict) else {}
    pnl_pct = (
        today.get("daily_pnl_pct")
        if isinstance(today, dict) else None
    )
    if pnl_pct is None:
        pnl_pct = data.get("daily_pnl_pct")
    pnl_f = _safe_float(pnl_pct)
    if pnl_f is not None and pnl_f <= -3.0:
        out.append(f"DAILY_DRAWDOWN_TRIPPED:{pnl_f:.2f}%")

    # VIX
    vix = today.get("vix") if isinstance(today, dict) else None
    if vix is None:
        vix = data.get("vix")
    vix_f = _safe_float(vix)
    if vix_f is not None and vix_f >= 35.0:
        out.append(f"VIX_ELEVATED:{vix_f:.1f}")

    # defensive mode
    dm = data.get("defensive_mode")
    if isinstance(dm, dict) and dm.get("armed"):
        out.append("DEFENSIVE_MODE_ARMED")

    # peak_equity guard
    peak_eq = _safe_float(data.get("peak_equity"))
    if peak_eq is None or peak_eq <= 0:
        out.append("PEAK_EQUITY_UNKNOWN")

    return out


def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
        if v != v:
            return None
        return v
    except (TypeError, ValueError):
        return None


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        v = int(x)
        return v
    except (TypeError, ValueError):
        return default


# ─── Row constructor (enforces hard invariants) ───────────────────────────────


def _make_row(
    *,
    strategy: str,
    symbol: str,
    reason: str,
    source: str,
    required_trigger: Optional[str] = None,
    variant_id: Optional[str] = None,
    current_distance_to_trigger: Optional[float] = None,
    confidence_expectation: Optional[str] = None,
    risk_preconditions: Optional[list[str]] = None,
    data_requirements: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    if source not in ALLOWED_SOURCES:
        raise ValueError(
            f"refusing to build shadow candidate row with non-whitelisted "
            f"source={source!r}; allowed={sorted(ALLOWED_SOURCES)}"
        )
    asset_class = _asset_class_for(symbol)
    trig = required_trigger or STRATEGY_TRIGGER_TEMPLATES.get(
        strategy,
        "operator must define trigger before shadow can begin"
    )
    row = {
        "strategy_id":                  str(strategy),
        "variant_id":                   variant_id,
        "symbol":                       str(symbol),
        "asset_class":                  asset_class,
        "reason":                       str(reason),
        "source":                       source,
        "required_real_time_condition": str(trig),
        "current_distance_to_trigger":  (
            float(current_distance_to_trigger)
            if current_distance_to_trigger is not None else None
        ),
        "expected_confidence_range":    confidence_expectation
                                        or CONFIDENCE_EXPECTATION_DEFAULT,
        "risk_preconditions":           list(risk_preconditions or []),
        "data_requirements":            data_requirements
                                        or _data_requirements_for(asset_class),
        "mode":                         MODE_SHADOW_ONLY,
        "status":                       STATUS_WAITING,
        # HARD invariants — never overridable.
        "is_paper_trade":               False,
        "is_real_market_opportunity":   False,
        "is_shadow_fill":               False,
        "is_signal":                    False,
    }
    if isinstance(extra, dict):
        for k, v in extra.items():
            if k not in row:
                row[k] = v
    return row


# ─── Source 1: near-miss aggregate ────────────────────────────────────────────


def collect_from_near_miss(
    *,
    near_miss_path: Path = NEAR_MISS_STATUS_PATH,
    risk_preconditions: Optional[list[str]] = None,
    min_sample: int = 3,
) -> list[dict]:
    nm = _safe_read_json(near_miss_path)
    if not isinstance(nm, dict):
        return []
    out: list[dict] = []
    pairs = nm.get("pairs") if isinstance(nm.get("pairs"), list) else []
    flagged_pairs = {
        (p.get("strategy_id"), p.get("metric_name"))
        for p in (nm.get("flagged") or [])
        if isinstance(p, dict)
    }
    for p in pairs:
        if not isinstance(p, dict):
            continue
        strategy = p.get("strategy_id")
        if not isinstance(strategy, str):
            continue
        sample = _safe_int(p.get("sample_size"))
        if sample < min_sample:
            continue
        # Best-effort symbol: near-miss aggregate is per (strategy, metric)
        # not per-symbol, so we use "ALL_OBSERVED_SYMBOLS" marker.
        symbol = p.get("symbol") or "ALL_OBSERVED_SYMBOLS"
        is_flagged = (strategy, p.get("metric_name")) in flagged_pairs
        reason = (
            f"near-miss aggregate sample={sample} "
            f"p95_abs_distance={p.get('p95_abs_distance')} "
            f"ratio={p.get('abs_distance_ratio')}"
        )
        if is_flagged:
            reason += " (advisory_flag=true)"
        row = _make_row(
            strategy=strategy,
            symbol=symbol,
            reason=reason,
            source=SOURCE_REAL,    # near-miss aggregate is derived from REAL ledger rows
            risk_preconditions=risk_preconditions,
            extra={
                "near_miss_sample_size": sample,
                "advisory_flag":         bool(is_flagged),
            },
        )
        out.append(row)
    return out


# ─── Source 2: replay candidates ──────────────────────────────────────────────


def collect_from_replay(
    *,
    replay_path: Path = REPLAY_DISCOVERY_PATH,
    risk_preconditions: Optional[list[str]] = None,
    min_candidates: int = 1,
    min_near_misses: int = 3,
) -> list[dict]:
    rep = _safe_read_json(replay_path)
    if not isinstance(rep, dict):
        return []
    rows = rep.get("rows") if isinstance(rep.get("rows"), list) else []
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        strategy = r.get("strategy")
        symbol = r.get("symbol")
        if not isinstance(strategy, str) or not isinstance(symbol, str):
            continue
        cands = _safe_int(r.get("candidates"))
        nm = _safe_int(r.get("near_misses"))
        if cands < min_candidates and nm < min_near_misses:
            continue
        reason_parts = []
        if cands >= min_candidates:
            reason_parts.append(f"replay candidates: {cands}")
        if nm >= min_near_misses:
            reason_parts.append(f"replay near-misses: {nm}")
        reason = "; ".join(reason_parts) or "replay match"
        row = _make_row(
            strategy=strategy,
            symbol=symbol,
            reason=reason,
            source=SOURCE_REPLAY,
            risk_preconditions=risk_preconditions,
            extra={
                "replay_candidate_count": cands,
                "replay_near_miss_count": nm,
                "asset_class_replay":     r.get("asset_class"),
            },
        )
        out.append(row)
    return out


# ─── Source 3: quarantined variants ───────────────────────────────────────────


def collect_from_variants(
    *,
    variant_path: Path = VARIANT_LATEST_PATH,
    risk_preconditions: Optional[list[str]] = None,
    default_universe: Optional[dict[str, list[str]]] = None,
) -> list[dict]:
    """Each QUARANTINED variant generates one shadow-queue row per
    relevant symbol on the parent's universe. We DO NOT promote the
    variant — we just expose it as a watching candidate.
    """
    data = _safe_read_json(variant_path)
    if not isinstance(data, dict):
        return []
    variants = data.get("variants")
    if not isinstance(variants, list):
        return []

    default_universe = default_universe or {
        "crypto-momentum":        ["BTC/USD", "ETH/USD", "SOL/USD"],
        "crypto-oversold-bounce": ["BTC/USD", "ETH/USD"],
        "momentum-long":          ["AAPL", "MSFT", "NVDA", "AMZN", "META"],
        "momentum-long-loose":    ["AAPL", "MSFT", "NVDA", "AMZN", "META"],
        "overbought-short":       ["AAPL", "NVDA"],
    }

    out: list[dict] = []
    for v in variants:
        if not isinstance(v, dict):
            continue
        status = v.get("status")
        if status not in ("QUARANTINED", "REPLAY_TESTING", "SHADOW_OBSERVE"):
            continue
        # ALWAYS verify allowed_modes does NOT contain live/paper before
        # surfacing the variant in the candidate queue.
        modes = v.get("allowed_modes") or []
        bad = {m.lower() for m in modes if isinstance(m, str)} & {
            "live", "paper", "broker_paper"
        }
        if bad:
            continue  # silently drop unsafe variant (audit lives elsewhere)
        parent = v.get("parent_strategy")
        if not isinstance(parent, str):
            continue
        symbols = default_universe.get(parent, []) or []
        rationale = (
            v.get("change_rationale")
            or v.get("description")
            or "quarantined variant — operator review"
        )
        for sym in symbols:
            row = _make_row(
                strategy=parent,
                symbol=sym,
                reason=(
                    f"quarantined variant {v.get('id')!r}: "
                    f"{rationale[:160]}"
                ),
                source=SOURCE_VARIANT,
                variant_id=v.get("id"),
                risk_preconditions=risk_preconditions,
                extra={
                    "variant_status":      status,
                    "allowed_modes":       list(modes),
                    "promotion_criteria":  v.get("promotion_criteria") or [],
                    "rejection_criteria":  v.get("rejection_criteria") or [],
                },
            )
            out.append(row)
    return out


# ─── Source 4: trigger watchlist ──────────────────────────────────────────────


def collect_from_watchlist(
    *,
    watchlist_path: Path = TRIGGER_WATCHLIST_PATH,
    risk_preconditions: Optional[list[str]] = None,
) -> list[dict]:
    w = _safe_read_json(watchlist_path)
    if not isinstance(w, dict):
        return []
    rows = w.get("rows") if isinstance(w.get("rows"), list) else []
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        strategy = r.get("strategy_id") or r.get("strategy")
        symbol = r.get("symbol")
        if not isinstance(strategy, str) or not isinstance(symbol, str):
            continue
        reason = (
            f"watchlist row: distance={r.get('current_distance_to_trigger')}"
        )
        row = _make_row(
            strategy=strategy,
            symbol=symbol,
            reason=reason,
            source=SOURCE_WATCHLIST,
            current_distance_to_trigger=_safe_float(
                r.get("current_distance_to_trigger")
            ),
            risk_preconditions=risk_preconditions,
        )
        out.append(row)
    return out


# ─── Dedupe ───────────────────────────────────────────────────────────────────


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    """Deterministic dedupe by (strategy_id, variant_id, symbol, source).

    Same (strategy, variant, symbol) from different sources is kept —
    each provides distinct information. Identical full key is collapsed.
    """
    seen: set[tuple[str, Optional[str], str, str]] = set()
    out: list[dict] = []
    for r in rows:
        key = (
            str(r.get("strategy_id")),
            r.get("variant_id"),
            str(r.get("symbol")),
            str(r.get("source")),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# ─── Build ────────────────────────────────────────────────────────────────────


def build_queue(
    *,
    near_miss_path: Path = NEAR_MISS_STATUS_PATH,
    replay_path: Path = REPLAY_DISCOVERY_PATH,
    variant_path: Path = VARIANT_LATEST_PATH,
    watchlist_path: Path = TRIGGER_WATCHLIST_PATH,
    state_path: Path = STATE_JSON_PATH,
) -> dict[str, Any]:
    risk = _risk_preconditions_from_state() if state_path.exists() else []
    rows_real = collect_from_near_miss(
        near_miss_path=near_miss_path, risk_preconditions=risk,
    )
    rows_replay = collect_from_replay(
        replay_path=replay_path, risk_preconditions=risk,
    )
    rows_variant = collect_from_variants(
        variant_path=variant_path, risk_preconditions=risk,
    )
    rows_watch = collect_from_watchlist(
        watchlist_path=watchlist_path, risk_preconditions=risk,
    )

    all_rows = _dedupe_rows(
        rows_real + rows_replay + rows_variant + rows_watch
    )
    by_source = Counter(r["source"] for r in all_rows)
    by_strategy = Counter(r["strategy_id"] for r in all_rows)

    # HARD safety re-stamp — defensive guarantee in case anything mutated
    # the dict in transit.
    for r in all_rows:
        r["mode"] = MODE_SHADOW_ONLY
        r["status"] = STATUS_WAITING
        r["is_paper_trade"] = False
        r["is_real_market_opportunity"] = False
        r["is_shadow_fill"] = False
        r["is_signal"] = False

    return {
        "version":              VERSION,
        "generated_at_iso":     _utc_now_iso(),
        "as_of":                _utc_now_iso(),
        "git_head":             _git_head(),
        "rows":                 all_rows,
        "rows_total":           len(all_rows),
        "rows_by_source":       dict(by_source),
        "rows_by_strategy":     dict(by_strategy),
        "active_risk_blockers": risk,
        "standing_markers":     list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":            False,
            "allow_broker_paper":           False,
            "live_trading_supported":       False,
            "modifies_state_json":          False,
            "places_orders":                False,
            "writes_opportunity_ledger":    False,
            "creates_shadow_fill":          False,
            "fetches_network":              False,
            "all_rows_mode_shadow_only":    all(
                r["mode"] == MODE_SHADOW_ONLY for r in all_rows
            ),
            "all_rows_waiting_for_trigger": all(
                r["status"] == STATUS_WAITING for r in all_rows
            ),
        },
    }


# ─── Render markdown ──────────────────────────────────────────────────────────


def render_markdown(rep: dict) -> str:
    lines: list[str] = []
    lines.append(f"# Shadow candidate queue ({rep['version']})")
    lines.append("")
    lines.append(f"**Generated:** `{rep['generated_at_iso']}`")
    lines.append(f"**git_head:** `{rep.get('git_head', 'unknown')}`")
    lines.append(f"**Total rows:** {rep['rows_total']}")
    risk = rep.get("active_risk_blockers") or []
    lines.append(
        "**Active risk blockers:** "
        + (", ".join(risk) if risk else "none")
    )
    lines.append("")
    lines.append(
        "Every row stays at `WAITING_FOR_REAL_MARKET_TRIGGER` until a "
        "real-time event satisfies the trigger. This queue NEVER auto-"
        "promotes, NEVER places orders, NEVER creates a shadow fill, "
        "NEVER inflates shadow-eligibility counters."
    )
    lines.append("")
    by_src = rep.get("rows_by_source", {})
    if by_src:
        lines.append("## Rows by source")
        lines.append("")
        lines.append("| Source | Count |")
        lines.append("|---|---|")
        for k, v in sorted(by_src.items()):
            lines.append(f"| `{k}` | {v} |")
        lines.append("")
    by_strat = rep.get("rows_by_strategy", {})
    if by_strat:
        lines.append("## Rows by strategy")
        lines.append("")
        lines.append("| Strategy | Count |")
        lines.append("|---|---|")
        for k, v in sorted(by_strat.items()):
            lines.append(f"| `{k}` | {v} |")
        lines.append("")
    lines.append("## Candidate rows")
    lines.append("")
    lines.append(
        "| Strategy | Variant | Symbol | Asset | Source | Reason | "
        "Trigger | Confidence | Risk Pre | Mode | Status |"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|---|---|---|"
    )
    if not rep["rows"]:
        lines.append(
            "| (empty queue — no near-miss / replay / variant / watchlist "
            "rows met threshold) | | | | | | | | | | |"
        )
    for r in rep["rows"]:
        variant = r.get("variant_id") or "—"
        risk_pre = ", ".join(r.get("risk_preconditions") or []) or "none"
        lines.append(
            f"| `{r['strategy_id']}` | `{variant}` | `{r['symbol']}` | "
            f"`{r['asset_class']}` | `{r['source']}` | "
            f"{r['reason'][:120]} | "
            f"{r['required_real_time_condition'][:80]} | "
            f"{r['expected_confidence_range']} | "
            f"{risk_pre} | `{r['mode']}` | `{r['status']}` |"
        )
    lines.append("")
    lines.append("## Standing markers")
    lines.append("")
    for s in rep.get("standing_markers", []):
        lines.append(f"- `{s}`")
    return "\n".join(lines) + "\n"


# ─── Persistence ──────────────────────────────────────────────────────────────


def write_outputs(rep: dict) -> None:
    LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    LATEST_JSON_PATH.write_text(json.dumps(rep, indent=2, sort_keys=True),
                                encoding="utf-8")
    LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    LATEST_MD_PATH.write_text(render_markdown(rep), encoding="utf-8")


# ─── CLI ──────────────────────────────────────────────────────────────────────


def run() -> dict:
    rep = build_queue()
    write_outputs(rep)
    return rep


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip writing the JSON+MD outputs")
    args = parser.parse_args(argv)
    rep = build_queue()
    if not args.dry_run:
        write_outputs(rep)
    summary = {
        "version":          rep["version"],
        "generated_at_iso": rep["generated_at_iso"],
        "rows_total":       rep["rows_total"],
        "rows_by_source":   rep["rows_by_source"],
        "rows_by_strategy": rep["rows_by_strategy"],
        "active_risk_blockers": rep["active_risk_blockers"],
        "standing_markers": rep["standing_markers"],
        "safety":           rep["safety"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
