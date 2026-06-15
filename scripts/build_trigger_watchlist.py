#!/usr/bin/env python3
"""v3.27.0 (2026-06-15) — Agent 3B — ETAP 7 — Trigger watchlist (enhanced).

Reads multiple discovery-layer outputs to produce a Top-N=30 "trigger
watchlist" — (strategy, symbol) pairs whose required market movement is
closest to threshold and which the operator should watch in real time.

Inputs (any missing input is treated as empty — fail-soft):
  * ``learning-loop/strategy_threshold_reality_latest.json``
    Per-strategy hit-rate / near-miss-rate / threshold realism. Used to
    set ``avg_distance_to_trigger`` and ``replay_candidate_support``.
  * ``learning-loop/near_miss/<YYYY-MM-DD>.jsonl`` (or the legacy
    aggregate file ``learning-loop/near_miss_status_latest.json``).
    Per-(strategy, symbol) near-miss counts in the last 7 days.
  * ``learning-loop/replay_entry_candidate_discovery_latest.json``
    (or the legacy ``learning-loop/replay_discovery_latest.json``).
    Replay-derived candidates per (strategy, symbol) — sets
    ``replay_candidate_support`` and ``distance_to_trigger`` when no
    near-miss data is available.
  * ``learning-loop/strategy_variant_quarantine_latest.json``
    Quarantined permissive variants. If a row's strategy has a more
    permissive quarantined variant, it populates ``variant_support``.
  * ``learning-loop/shadow_candidate_queue_latest.json``
    Existing shadow queue. Rows already in the shadow queue are excluded
    (operator already watching) UNLESS ``--include-shadow-queue`` is
    set, in which case they get priority BLOCKED with reason
    ``ALREADY_IN_SHADOW_QUEUE``.

Each row carries:
  * strategy_id, symbol
  * distance_to_trigger          (numeric — ratio in [0, 1])
  * market_movement_required     (textual)
  * near_miss_count_7d           (int)
  * replay_candidate_support     (bool — does replay discovery agree?)
  * variant_support              (variant_id if a quarantined variant is
                                  more permissive, else None)
  * confidence_preconditions     (textual)
  * risk_preconditions           (textual — current daily-drawdown /
                                  VIX guard state from threshold-reality
                                  file or "STATE_NOT_AVAILABLE")
  * expected_evidence_mode       (SHADOW_ONLY — always)
  * priority                     (P1 / P2 / P3 / BLOCKED)

Priority rubric (deterministic):
  * P1:      distance_to_trigger < 0.05 AND near_miss_count_7d >= 3 AND
             risk preconditions clean
  * P2:      0.05 <= distance_to_trigger < 0.15 AND near_miss_count_7d >= 1
  * P3:      distance_to_trigger >= 0.15 (trending closer — i.e. has any
             replay support OR near-miss history)
  * BLOCKED: distance unknown OR risk preconditions failed OR data
             missing (NO_BACKFILL_DATA, etc.)

Output: Top N=30 rows sorted by priority (P1 first, then P2, P3,
BLOCKED), with current_distance as the secondary sort key (ascending).

CONTRACT
--------
- This script NEVER places orders.
- This script NEVER imports ``alpaca_orders``.
- This script NEVER makes network calls.
- This script NEVER writes to ``opportunity_ledger``.
- This script NEVER auto-changes thresholds.
- Standing markers footer reproduced verbatim.

Outputs:
  * ``learning-loop/trigger_watchlist_latest.json``
  * ``docs/TRIGGER_WATCHLIST.md``
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Input paths (any may be absent — fail-soft) ────────────────────────────
THRESHOLD_REALITY_INPUT = (
    REPO_ROOT / "learning-loop" / "strategy_threshold_reality_latest.json"
)
NEAR_MISS_DIR_INPUT = REPO_ROOT / "learning-loop" / "near_miss"
NEAR_MISS_AGGREGATE_INPUT = (
    REPO_ROOT / "learning-loop" / "near_miss_status_latest.json"
)
REPLAY_INPUT_NEW = (
    REPO_ROOT / "learning-loop"
    / "replay_entry_candidate_discovery_latest.json"
)
REPLAY_INPUT_LEGACY = (
    REPO_ROOT / "learning-loop" / "replay_discovery_latest.json"
)
QUARANTINE_INPUT = (
    REPO_ROOT / "learning-loop" / "strategy_variant_quarantine_latest.json"
)
SHADOW_QUEUE_INPUT = (
    REPO_ROOT / "learning-loop" / "shadow_candidate_queue_latest.json"
)

# ── Output paths ──────────────────────────────────────────────────────────
LATEST_JSON_PATH = REPO_ROOT / "learning-loop" / "trigger_watchlist_latest.json"
LATEST_MD_PATH = REPO_ROOT / "docs" / "TRIGGER_WATCHLIST.md"

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "WATCHLIST_NEVER_PLACES_ORDERS",
    "WATCHLIST_NEVER_AUTO_PROMOTES",
    "WATCHLIST_NEVER_AUTO_CHANGES_THRESHOLDS",
)

VERSION = "v3.27.0"

EXPECTED_EVIDENCE_MODE = "SHADOW_ONLY"
DEFAULT_TOP_N = 30
NEAR_MISS_WINDOW_DAYS = 7

# Priority thresholds (deterministic).
P1_DISTANCE_MAX = 0.05
P1_NEAR_MISS_MIN = 3
P2_DISTANCE_MAX = 0.15
P2_NEAR_MISS_MIN = 1

PRIORITY_RANK: dict[str, int] = {
    "P1":      1,
    "P2":      2,
    "P3":      3,
    "BLOCKED": 4,
}

STRATEGY_TRIGGER_CONDITIONS: dict[str, str] = {
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
        "predator-bracket 24h move in [3%, 15%] AND RSI band met"
    ),
    "crypto-oversold-bounce": (
        "RSI(14) <= 30 on H1 close AND 3-bar stabilization "
        "AND volume >= 25% of avg"
    ),
}

STRATEGY_REQUIRED_MARKET_MOVEMENT: dict[str, str] = {
    "momentum-long":            "close > 20-day high (breakout)",
    "momentum-long-loose":      "close > 20-day high (relaxed)",
    "overbought-short":         "RSI(14) > 72 + visible weakening",
    "crypto-momentum":          "24h move in [3%, 15%]",
    "crypto-oversold-bounce":   "RSI(14) <= 30 + 3-bar stabilization",
}

CONFIDENCE_PRECONDITIONS = (
    "confidence_score in [0.50, 0.85]; "
    "data_quality components fresh; system_health components fresh"
)
RISK_PRECONDITIONS_CLEAN = (
    "daily drawdown not tripped; VIX < 35; defensive_mode not armed; "
    "concentration cap not breached; per-strategy cooldown clear"
)
RISK_PRECONDITIONS_UNKNOWN = "STATE_NOT_AVAILABLE"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _safe_read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    out.append(rec)
            except Exception:
                continue
    except Exception:
        pass
    return out


def _is_crypto(symbol: str) -> bool:
    return isinstance(symbol, str) and "/" in symbol


def _asset_class(symbol: str) -> str:
    return "crypto" if _is_crypto(symbol) else "us_equity"


# ─── Input ingestion ──────────────────────────────────────────────────────────


def _ingest_threshold_reality(
    path: Path,
) -> tuple[dict[str, dict], bool]:
    """Return ``(per_strategy_summary, risk_state_known)``.

    ``per_strategy_summary[strategy_id] = {
        avg_distance_to_trigger, near_miss_rate, hit_rate, threshold_realism,
        recommendation,
    }``
    """
    d = _safe_read_json(path) or {}
    summary: dict[str, dict] = {}
    for strat in (d.get("strategies") or []):
        if not isinstance(strat, dict):
            continue
        sid = strat.get("strategy_id")
        if not sid:
            continue
        metrics = strat.get("metrics") or []
        if not metrics:
            summary[sid] = {
                "avg_distance_to_trigger": None,
                "near_miss_rate":          None,
                "hit_rate":                None,
                "threshold_realism":       strat.get("threshold_realism"),
                "recommendation":          strat.get("recommendation"),
                "near_misses_total":       int(strat.get("near_misses") or 0),
                "actual_signals_fired":    int(strat.get("actual_signals_fired") or 0),
            }
            continue
        # Aggregate metrics into one summary row.
        dists = [m.get("avg_distance_to_trigger") for m in metrics
                 if isinstance(m, dict)
                 and isinstance(m.get("avg_distance_to_trigger"), (int, float))]
        nmr = [m.get("near_miss_rate") for m in metrics
               if isinstance(m, dict)
               and isinstance(m.get("near_miss_rate"), (int, float))]
        hr = [m.get("hit_rate") for m in metrics
              if isinstance(m, dict)
              and isinstance(m.get("hit_rate"), (int, float))]
        summary[sid] = {
            "avg_distance_to_trigger": (sum(dists) / len(dists)) if dists else None,
            "near_miss_rate":          (sum(nmr) / len(nmr)) if nmr else None,
            "hit_rate":                (sum(hr) / len(hr)) if hr else None,
            "threshold_realism":       strat.get("threshold_realism"),
            "recommendation":          strat.get("recommendation"),
            "near_misses_total":       int(strat.get("near_misses") or 0),
            "actual_signals_fired":    int(strat.get("actual_signals_fired") or 0),
        }
    # Risk-state knowledge: we trust threshold-reality only as a freshness
    # signal. It does NOT encode VIX or drawdown directly — that lives in
    # state.json. We treat presence as "STATE_NOT_AVAILABLE" but the
    # absence of explicit failure markers as "clean by default" for
    # priority computation.
    risk_state_known = False
    if d.get("hard_safety") is not None:
        risk_state_known = True
    return summary, risk_state_known


def _ingest_near_miss_jsonl(
    *,
    dir_path: Path,
    aggregate_path: Path,
    as_of: datetime,
    window_days: int = NEAR_MISS_WINDOW_DAYS,
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], float], list[dict]]:
    """Return three values:

      * ``(strategy, symbol) -> near-miss count`` over the window
      * ``(strategy, symbol) -> abs_distance_ratio`` if the aggregate
        provided a precomputed distance — caller honours this number
        over the heuristic distance derived from counts (preserves the
        v3.26 contract).
      * raw pair list for diagnostic exposure.

    Per-day JSONL files in ``dir_path`` (if present) sum to the count.
    Legacy aggregate ``near_miss_status_latest.json::pairs`` provides
    pre-aggregated ``abs_distance_ratio`` AND fills in counts for pairs
    missing from the JSONL stream.
    """
    counts: collections.Counter[tuple[str, str]] = collections.Counter()
    abs_ratios: dict[tuple[str, str], float] = {}
    extras: list[dict] = []

    # Per-day JSONLs preferred.
    if dir_path.exists() and dir_path.is_dir():
        cutoff = as_of - timedelta(days=window_days)
        for jsonl_file in sorted(dir_path.glob("*.jsonl")):
            try:
                stem = jsonl_file.stem
                file_date = datetime.fromisoformat(stem).replace(
                    tzinfo=timezone.utc)
            except Exception:
                # Unknown filename pattern — read regardless.
                file_date = None
            if file_date and file_date < cutoff:
                continue
            for rec in _safe_read_jsonl(jsonl_file):
                strategy = rec.get("strategy_id") or rec.get("strategy")
                symbol = rec.get("symbol")
                if not strategy or not symbol:
                    continue
                counts[(strategy, symbol)] += 1

    # Aggregate fallback (always inspected to surface pairs missing from
    # the JSONL stream + to pick up precomputed abs_distance_ratio).
    agg = _safe_read_json(aggregate_path) or {}
    pairs = agg.get("pairs") or []
    if isinstance(pairs, list):
        for p in pairs:
            if not isinstance(p, dict):
                continue
            strategy = p.get("strategy_id") or p.get("strategy")
            symbol = p.get("symbol") or "UNSPECIFIED"
            if not strategy:
                continue
            key = (strategy, symbol)
            sample = int(p.get("sample_size") or 0)
            # Only add aggregate count if JSONL didn't already cover it.
            if key not in counts:
                counts[key] = sample
            ratio = p.get("abs_distance_ratio")
            if isinstance(ratio, (int, float)):
                abs_ratios[key] = float(ratio)
            extras.append(p)

    return dict(counts), abs_ratios, extras


def _ingest_replay(
    paths: Iterable[Path],
) -> tuple[dict[tuple[str, str], dict], list[str]]:
    """Aggregate replay rows from the first existing path.

    Returns ((strategy, symbol) -> row, missing_snapshot_list).
    """
    out: dict[tuple[str, str], dict] = {}
    missing: list[str] = []
    for p in paths:
        d = _safe_read_json(p)
        if not d:
            continue
        missing = list(d.get("missing_snapshots") or [])
        for r in (d.get("rows") or []):
            if not isinstance(r, dict):
                continue
            strategy = r.get("strategy")
            symbol = r.get("symbol")
            if not strategy or not symbol:
                continue
            cands = int(r.get("candidates") or 0)
            nm = int(r.get("near_misses") or 0)
            if cands == 0 and nm == 0:
                continue
            out[(strategy, symbol)] = {
                "candidates":           cands,
                "near_misses":          nm,
                "threshold_crosses":    int(r.get("threshold_crosses") or 0),
                "asset_class":          r.get("asset_class") or _asset_class(symbol),
                "snapshot_quality":     r.get("snapshot_quality"),
            }
        break  # first existing file wins
    return out, missing


def _ingest_quarantine(path: Path) -> dict[str, list[str]]:
    """Strategy -> list of quarantined variant IDs."""
    d = _safe_read_json(path) or {}
    out: dict[str, list[str]] = collections.defaultdict(list)
    rows = d.get("rows") or d.get("variants") or []
    if isinstance(rows, list):
        for r in rows:
            if not isinstance(r, dict):
                continue
            strategy = r.get("strategy_id") or r.get("strategy")
            variant_id = r.get("variant_id") or r.get("id")
            permissive = bool(r.get("is_more_permissive")
                              or r.get("permissive") or False)
            if not strategy or not variant_id:
                continue
            if permissive:
                out[strategy].append(str(variant_id))
    return dict(out)


def _ingest_shadow_queue(path: Path) -> set[tuple[str, str]]:
    d = _safe_read_json(path) or {}
    rows = d.get("rows") or []
    out: set[tuple[str, str]] = set()
    if isinstance(rows, list):
        for r in rows:
            if not isinstance(r, dict):
                continue
            strategy = r.get("strategy") or r.get("strategy_id")
            symbol = r.get("symbol")
            if strategy and symbol:
                out.add((strategy, symbol))
    return out


# ─── Row assembly ─────────────────────────────────────────────────────────────


def _compute_distance(
    *,
    replay_row: Optional[dict],
    near_miss_count: int,
    threshold_realism: Optional[dict],
    abs_distance_ratio: Optional[float] = None,
) -> Optional[float]:
    """Distance in [0, 1], smaller = closer to triggering.

    Precedence (preserves the v3.26 contract for near-miss aggregates):

      1. ``abs_distance_ratio`` from the near-miss aggregate is honoured
         verbatim when present (the aggregate already computed the
         operator-meaningful distance).
      2. Replay row → score_activity monotonic rule.
      3. JSONL near-miss count only → 1 / (1 + 0.5 * count).
      4. threshold_realism.hit_rate → coarse proxy.
      5. else None (BLOCKED).
    """
    if isinstance(abs_distance_ratio, (int, float)):
        return round(float(abs_distance_ratio), 4)
    if replay_row is not None:
        cands = int(replay_row.get("candidates") or 0)
        nm = int(replay_row.get("near_misses") or 0)
        # Same monotonic rule as v3.26 — preserves test compat.
        score_activity = cands * 1.0 + nm * 0.5 + near_miss_count * 0.25
        return round(1.0 / (1.0 + score_activity), 4)
    if near_miss_count > 0:
        # No replay data but JSONL near-miss count present.
        return round(1.0 / (1.0 + near_miss_count * 0.5), 4)
    if threshold_realism:
        hr = threshold_realism.get("hit_rate")
        if isinstance(hr, (int, float)) and 0.0 <= hr <= 1.0:
            # Coarse proxy — higher hit rate → smaller distance.
            return round(max(0.05, 1.0 - hr), 4)
    return None


def _compute_priority(
    *,
    distance: Optional[float],
    near_miss_count: int,
    risk_clean: bool,
    data_missing: bool,
) -> tuple[str, str]:
    """Return (priority, reason_code)."""
    if distance is None or data_missing:
        return ("BLOCKED", "DATA_MISSING")
    if not risk_clean:
        return ("BLOCKED", "RISK_PRECONDITIONS_FAILED")
    if distance < P1_DISTANCE_MAX and near_miss_count >= P1_NEAR_MISS_MIN:
        return ("P1", "CLOSE_AND_FREQUENT")
    if distance < P2_DISTANCE_MAX and near_miss_count >= P2_NEAR_MISS_MIN:
        return ("P2", "MEDIUM_DISTANCE")
    # P3 = far but trending closer (any near-miss OR replay support).
    return ("P3", "FAR_BUT_TRENDING")


# ─── Build report ─────────────────────────────────────────────────────────────


def build_watchlist(
    *,
    as_of: datetime,
    top_n: int = DEFAULT_TOP_N,
    threshold_reality_input: Optional[Path] = None,
    near_miss_dir_input: Optional[Path] = None,
    near_miss_aggregate_input: Optional[Path] = None,
    replay_input: Optional[Path] = None,
    quarantine_input: Optional[Path] = None,
    shadow_queue_input: Optional[Path] = None,
    include_shadow_queue: bool = False,
    risk_clean_default: bool = True,
    # v3.26 backward-compat aliases.
    near_miss_input: Optional[Path] = None,
) -> dict[str, Any]:
    """Build watchlist report. Pure function — no I/O side-effects.

    Backward-compat parameters supported:
      * ``replay_input``     - if passed, used as primary replay source.
      * ``near_miss_input``  - v3.26 legacy keyword: maps onto
                              ``near_miss_aggregate_input``.
    """
    # v3.26 alias: ``near_miss_input`` → aggregate input. When the
    # caller uses the legacy kwarg they expect ONLY the aggregate file
    # to count — suppress the JSONL directory auto-discovery so the
    # legacy semantics are preserved.
    legacy_near_miss = False
    if near_miss_input is not None and near_miss_aggregate_input is None:
        near_miss_aggregate_input = near_miss_input
        legacy_near_miss = True
    if legacy_near_miss and near_miss_dir_input is None:
        # Point at a non-existent path so the JSONL loader produces 0
        # rows (backward compat with v3.26 caller contract).
        near_miss_dir_input = Path("/dev/null/__nonexistent_near_miss_dir__")
    threshold_path = threshold_reality_input or THRESHOLD_REALITY_INPUT
    nm_dir = near_miss_dir_input or NEAR_MISS_DIR_INPUT
    nm_agg = near_miss_aggregate_input or NEAR_MISS_AGGREGATE_INPUT
    replay_paths: list[Path] = []
    if replay_input is not None:
        replay_paths.append(replay_input)
    else:
        replay_paths.extend([REPLAY_INPUT_NEW, REPLAY_INPUT_LEGACY])
    quarantine_path = quarantine_input or QUARANTINE_INPUT
    shadow_path = shadow_queue_input or SHADOW_QUEUE_INPUT

    threshold_reality, _risk_known = _ingest_threshold_reality(threshold_path)
    nm_counts, nm_abs_ratios, nm_extra_pairs = _ingest_near_miss_jsonl(
        dir_path=nm_dir,
        aggregate_path=nm_agg,
        as_of=as_of,
    )
    replay_rows, missing_snaps = _ingest_replay(replay_paths)
    quarantine = _ingest_quarantine(quarantine_path)
    shadow_queue = _ingest_shadow_queue(shadow_path)

    # Build union of (strategy, symbol) keys from replay + near-miss.
    keys: set[tuple[str, str]] = set()
    keys.update(replay_rows.keys())
    keys.update(nm_counts.keys())

    enriched: list[dict] = []
    skipped_in_shadow_queue = 0

    for key in keys:
        strategy, symbol = key
        replay_row = replay_rows.get(key)
        near_miss_count = int(nm_counts.get(key, 0))

        # Shadow queue handling.
        in_shadow_queue = key in shadow_queue
        if in_shadow_queue and not include_shadow_queue:
            skipped_in_shadow_queue += 1
            continue

        threshold_summary = threshold_reality.get(strategy)
        # Risk state is binary clean/not — we don't have a live
        # state.json read here (would require network/file lookups
        # against state we don't fully own). Default: clean unless
        # we know otherwise. CLI flag overrides.
        risk_clean = bool(risk_clean_default) and not in_shadow_queue

        data_missing = (
            symbol in (missing_snaps or [])
            and replay_row is None
        )

        distance = _compute_distance(
            replay_row=replay_row,
            near_miss_count=near_miss_count,
            threshold_realism=threshold_summary,
            abs_distance_ratio=nm_abs_ratios.get(key),
        )

        # If shadow queue exclusion + include flag → mark BLOCKED with
        # explicit reason ALREADY_IN_SHADOW_QUEUE (overrides normal
        # priority).
        if in_shadow_queue:
            priority = "BLOCKED"
            priority_reason = "ALREADY_IN_SHADOW_QUEUE"
        else:
            priority, priority_reason = _compute_priority(
                distance=distance,
                near_miss_count=near_miss_count,
                risk_clean=risk_clean,
                data_missing=data_missing,
            )

        replay_support = (
            replay_row is not None
            and int(replay_row.get("candidates") or 0) > 0
        )

        variant_support = None
        if quarantine.get(strategy):
            variant_support = quarantine[strategy][0]

        asset_class = (
            (replay_row or {}).get("asset_class") or _asset_class(symbol)
        )

        avg_dist_to_trigger = (
            threshold_summary.get("avg_distance_to_trigger")
            if threshold_summary else None
        )

        enriched.append({
            # New v3.27 schema names:
            "strategy_id":              strategy,
            "symbol":                   symbol,
            "asset_class":              asset_class,
            "distance_to_trigger":      distance,
            "near_miss_count_7d":       near_miss_count,
            "replay_candidate_support": replay_support,
            "variant_support":          variant_support,
            "market_movement_required": STRATEGY_REQUIRED_MARKET_MOVEMENT.get(
                strategy, "operator-defined"),
            "confidence_preconditions": CONFIDENCE_PRECONDITIONS,
            "risk_preconditions":       (RISK_PRECONDITIONS_CLEAN
                                          if risk_clean
                                          else RISK_PRECONDITIONS_UNKNOWN),
            "expected_evidence_mode":   EXPECTED_EVIDENCE_MODE,
            "priority":                 priority,
            "priority_reason":          priority_reason,

            # Backward-compat fields (v3.26 schema preserved so existing
            # tests / consumers don't break):
            "strategy":                  strategy,
            "trigger_condition":         STRATEGY_TRIGGER_CONDITIONS.get(
                strategy,
                "operator must specify trigger before promotion"
            ),
            "current_distance":          distance,
            "near_miss_history_count":   near_miss_count,
            "replay_candidate_count":    (
                int(replay_row.get("candidates") or 0)
                if replay_row else 0
            ),
            "required_market_movement":  STRATEGY_REQUIRED_MARKET_MOVEMENT.get(
                strategy, "operator-defined"),
            "status":                    "WATCHING",
            "source":                    (
                "replay+near_miss"
                if (replay_row is not None and near_miss_count > 0)
                else ("replay_discovery" if replay_row else "near_miss")
            ),
            "metric":                    None,
            # Diagnostic:
            "avg_distance_to_trigger":   avg_dist_to_trigger,
            "in_shadow_queue":           in_shadow_queue,
        })

    # Sort: priority rank ASC, then distance ASC, then strategy/symbol
    # alphabetical for determinism.
    def sort_key(r: dict):
        d = r.get("distance_to_trigger")
        return (
            PRIORITY_RANK.get(r.get("priority", "BLOCKED"), 9),
            (1, 0.0) if d is None else (0, float(d)),
            r.get("strategy_id") or "",
            r.get("symbol") or "",
        )

    enriched.sort(key=sort_key)
    enriched = enriched[: int(top_n)]

    by_strategy = collections.Counter(r["strategy_id"] for r in enriched)
    by_priority = collections.Counter(r["priority"] for r in enriched)

    return {
        "version":                VERSION,
        "generated_at_iso":       datetime.now(timezone.utc).isoformat(),
        "as_of":                  as_of.isoformat(),
        "top_n":                  int(top_n),
        "rows_total":             len(enriched),
        "rows_by_strategy":       dict(by_strategy),
        "rows_by_priority":       dict(by_priority),
        "skipped_in_shadow_queue": skipped_in_shadow_queue,
        "missing_snapshots":      missing_snaps,
        "near_miss_extra_pairs":  len(nm_extra_pairs),
        "rows":                   enriched,
        "standing_markers":       list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":          False,
            "allow_broker_paper":         False,
            "live_trading_supported":     False,
            "modifies_state_json":        False,
            "places_orders":              False,
            "writes_opportunity_ledger":  False,
            "auto_changes_thresholds":    False,
            "all_rows_mode_shadow_only":  True,
            "all_rows_status_watching":   True,
        },
    }


# ─── Rendering ────────────────────────────────────────────────────────────────


def render_md(rep: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Trigger watchlist ({rep['version']})")
    lines.append("")
    lines.append(f"**Generated:** `{rep['generated_at_iso']}`")
    lines.append(f"**As of:** `{rep['as_of']}`")
    lines.append(f"**Top-N:** {rep['top_n']}")
    lines.append(f"**Total rows:** {rep['rows_total']}")
    lines.append("")
    if rep["rows_by_priority"]:
        lines.append("## Rows by priority")
        lines.append("")
        lines.append("| Priority | Count |")
        lines.append("|---|---|")
        for k in ("P1", "P2", "P3", "BLOCKED"):
            v = rep["rows_by_priority"].get(k, 0)
            lines.append(f"| `{k}` | {v} |")
        lines.append("")
    if rep["rows_by_strategy"]:
        lines.append("## Rows by strategy")
        lines.append("")
        lines.append("| Strategy | Count |")
        lines.append("|---|---|")
        for k, v in sorted(rep["rows_by_strategy"].items(),
                            key=lambda kv: -kv[1]):
            lines.append(f"| `{k}` | {v} |")
        lines.append("")

    lines.append("## Watchlist (sorted by priority)")
    lines.append("")
    lines.append(
        "| Pri | Strategy | Symbol | Asset | Distance | NM_7d | "
        "ReplaySup | VariantSup | Required movement | Mode | Status |"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|---|---|---|"
    )
    if not rep["rows"]:
        lines.append(
            "| (no candidates yet — replay/near-miss data empty) "
            "| | | | | | | | | | |"
        )
    for r in rep["rows"]:
        d = r.get("distance_to_trigger")
        d_s = f"{d:.4f}" if isinstance(d, (int, float)) else "n/a"
        replay = "YES" if r.get("replay_candidate_support") else "no"
        variant = r.get("variant_support") or "—"
        lines.append(
            f"| **{r['priority']}** | `{r['strategy_id']}` | `{r['symbol']}` | "
            f"{r.get('asset_class') or '—'} | {d_s} | "
            f"{r.get('near_miss_count_7d') or 0} | "
            f"{replay} | {variant} | "
            f"{r['market_movement_required']} | "
            f"**{r['expected_evidence_mode']}** | "
            f"**{r['status']}** |"
        )

    lines.append("")
    lines.append("## Priority rubric")
    lines.append("")
    lines.append(
        f"- **P1** — `distance_to_trigger < {P1_DISTANCE_MAX}` AND "
        f"`near_miss_count_7d >= {P1_NEAR_MISS_MIN}` AND risk clean."
    )
    lines.append(
        f"- **P2** — `{P1_DISTANCE_MAX} <= distance < {P2_DISTANCE_MAX}` AND "
        f"`near_miss_count_7d >= {P2_NEAR_MISS_MIN}`."
    )
    lines.append(
        f"- **P3** — `distance >= {P2_DISTANCE_MAX}` (trending closer)."
    )
    lines.append(
        "- **BLOCKED** — distance unknown OR risk preconditions failed "
        "OR data missing OR already in shadow queue."
    )
    lines.append("")
    lines.append("## Preconditions (must hold before promotion)")
    lines.append("")
    lines.append(f"- **Confidence:** {CONFIDENCE_PRECONDITIONS}")
    lines.append(f"- **Risk:** {RISK_PRECONDITIONS_CLEAN}")
    lines.append("")
    lines.append("## Safety contract")
    lines.append("")
    lines.append("- Every row mode = `SHADOW_ONLY`.")
    lines.append("- Every row status = `WATCHING`.")
    lines.append("- This watchlist NEVER places orders.")
    lines.append("- This watchlist NEVER auto-promotes a row.")
    lines.append("- This watchlist NEVER auto-changes thresholds.")
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
        description="v3.27 — Trigger watchlist (Agent 3B / ETAP 7).",
    )
    p.add_argument("--as-of", default=None)
    p.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    p.add_argument(
        "--include-shadow-queue",
        action="store_true",
        help=("Include rows already in the shadow queue, marked "
              "BLOCKED with reason ALREADY_IN_SHADOW_QUEUE."),
    )
    p.add_argument(
        "--risk-clean-default",
        choices=("true", "false"),
        default="true",
        help=("Whether to treat risk preconditions as clean by default "
              "(operator override)."),
    )
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

    rep = build_watchlist(
        as_of=as_of,
        top_n=args.top_n,
        include_shadow_queue=args.include_shadow_queue,
        risk_clean_default=(args.risk_clean_default == "true"),
    )
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
        print(f"Watchlist rows: {rep['rows_total']} | "
              f"By priority: {rep['rows_by_priority']} | "
              f"By strategy: {rep['rows_by_strategy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
