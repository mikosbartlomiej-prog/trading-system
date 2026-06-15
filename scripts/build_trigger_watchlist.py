#!/usr/bin/env python3
"""v3.26.0 (2026-06-15) — Agent 3B — ETAP 8 — Trigger watchlist.

Reads near-miss aggregate + replay-discovery + recent ledger to produce
a Top-N (default 20) "trigger watchlist" — (strategy, symbol) pairs
whose required market movement is closest to the threshold and which
the operator should watch in real time.

Each row carries:
  * strategy, symbol
  * trigger_condition (textual)
  * current_distance     (RSI distance ratio or near-miss p95 distance)
  * near_miss_history_count
  * required_market_movement
  * confidence_preconditions
  * risk_preconditions
  * expected_evidence_mode = ``SHADOW_ONLY``
  * status = ``WATCHING``

CONTRACT
--------
- This script NEVER places orders.
- This script NEVER imports ``alpaca_orders``.
- This script NEVER makes network calls.
- This script NEVER writes to ``opportunity_ledger``.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
NEAR_MISS_INPUT = REPO_ROOT / "learning-loop" / "near_miss_status_latest.json"
REPLAY_INPUT = REPO_ROOT / "learning-loop" / "replay_discovery_latest.json"
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
)

VERSION = "v3.26.0"

EXPECTED_EVIDENCE_MODE = "SHADOW_ONLY"
DEFAULT_STATUS = "WATCHING"

STRATEGY_TRIGGER_CONDITIONS: dict[str, str] = {
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
RISK_PRECONDITIONS = (
    "daily drawdown not tripped; VIX < 35; defensive_mode not armed; "
    "concentration cap not breached; per-strategy cooldown clear"
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _safe_read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ─── Candidate extraction ─────────────────────────────────────────────────────


def _from_replay(replay: dict) -> list[dict]:
    """One row per (strategy, symbol) with at least one near-miss or
    candidate in the replay window. Distance = inverse of cands+near_miss.
    """
    out: list[dict] = []
    for r in (replay.get("rows") or []):
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
        # current_distance: rough inverse of activity; bounded.
        score_activity = cands * 1.0 + nm * 0.5
        # Lower current_distance = closer to trigger. Use 1 / (1 + score).
        current_distance = round(1.0 / (1.0 + score_activity), 4)
        out.append({
            "strategy":      strategy,
            "symbol":        symbol,
            "asset_class":   r.get("asset_class")
                             or ("crypto" if "/" in symbol else "us_equity"),
            "current_distance":         current_distance,
            "near_miss_history_count":  nm,
            "replay_candidate_count":   cands,
            "source":                   "replay_discovery",
        })
    return out


def _from_near_miss(near_miss: dict) -> list[dict]:
    """One row per (strategy, symbol-or-metric) flagged by the near-miss
    aggregate (the reporter from v3.24 ETAP 10). Distance = the reported
    abs_distance_ratio (already normalized [0, 1]).
    """
    out: list[dict] = []
    pairs = (near_miss.get("pairs") or [])
    if not isinstance(pairs, list):
        return out
    for p in pairs:
        if not isinstance(p, dict):
            continue
        strategy = p.get("strategy_id") or p.get("strategy")
        if not strategy:
            continue
        symbol = p.get("symbol") or "UNSPECIFIED"
        ratio = p.get("abs_distance_ratio")
        if not isinstance(ratio, (int, float)):
            ratio = None
        sample = int(p.get("sample_size") or 0)
        out.append({
            "strategy":                 strategy,
            "symbol":                   symbol,
            "asset_class":              ("crypto" if "/" in symbol else "us_equity"),
            "current_distance":         round(float(ratio), 4) if ratio is not None else None,
            "near_miss_history_count":  sample,
            "replay_candidate_count":   0,
            "source":                   "near_miss_aggregate",
            "metric":                   p.get("metric_name"),
        })
    return out


def _merge_and_rank(rows: list[dict], top_n: int) -> list[dict]:
    """Deduplicate by (strategy, symbol) — preserve the row with the
    smallest current_distance — and then sort ascending by
    current_distance (None at the end).
    """
    best: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["strategy"], r["symbol"])
        existing = best.get(key)
        new_dist = r.get("current_distance")
        if existing is None:
            best[key] = r
            continue
        ex_dist = existing.get("current_distance")
        # Prefer the one with the lower (closer) distance.
        if (ex_dist is None and new_dist is not None) or (
            new_dist is not None and ex_dist is not None and new_dist < ex_dist
        ):
            # Merge histories.
            merged = dict(r)
            merged["near_miss_history_count"] = (
                int(existing.get("near_miss_history_count") or 0)
                + int(r.get("near_miss_history_count") or 0)
            )
            merged["replay_candidate_count"] = (
                int(existing.get("replay_candidate_count") or 0)
                + int(r.get("replay_candidate_count") or 0)
            )
            merged["source"] = f"{existing.get('source')}+{r.get('source')}"
            best[key] = merged
        else:
            # Merge histories into existing.
            existing["near_miss_history_count"] = (
                int(existing.get("near_miss_history_count") or 0)
                + int(r.get("near_miss_history_count") or 0)
            )
            existing["replay_candidate_count"] = (
                int(existing.get("replay_candidate_count") or 0)
                + int(r.get("replay_candidate_count") or 0)
            )
            existing["source"] = f"{existing.get('source')}+{r.get('source')}"

    def sort_key(r: dict):
        d = r.get("current_distance")
        return (1, 0.0) if d is None else (0, float(d))

    out = sorted(best.values(), key=sort_key)
    return out[: int(top_n)]


# ─── Build report ─────────────────────────────────────────────────────────────


def build_watchlist(
    *,
    as_of: datetime,
    top_n: int = 20,
    replay_input: Optional[Path] = None,
    near_miss_input: Optional[Path] = None,
) -> dict[str, Any]:
    replay = _safe_read_json(replay_input or REPLAY_INPUT) or {}
    near_miss = _safe_read_json(near_miss_input or NEAR_MISS_INPUT) or {}

    rows = _from_replay(replay) + _from_near_miss(near_miss)
    ranked = _merge_and_rank(rows, top_n)

    enriched: list[dict] = []
    for r in ranked:
        strategy = r["strategy"]
        enriched.append({
            "strategy":                  strategy,
            "symbol":                    r["symbol"],
            "asset_class":               r.get("asset_class"),
            "trigger_condition":         STRATEGY_TRIGGER_CONDITIONS.get(
                strategy,
                "operator must specify trigger before promotion"
            ),
            "current_distance":          r.get("current_distance"),
            "near_miss_history_count":   r.get("near_miss_history_count"),
            "replay_candidate_count":    r.get("replay_candidate_count"),
            "required_market_movement":  STRATEGY_REQUIRED_MARKET_MOVEMENT.get(
                strategy,
                "operator-defined"
            ),
            "confidence_preconditions":  CONFIDENCE_PRECONDITIONS,
            "risk_preconditions":        RISK_PRECONDITIONS,
            "expected_evidence_mode":    EXPECTED_EVIDENCE_MODE,
            "status":                    DEFAULT_STATUS,
            "source":                    r.get("source"),
            "metric":                    r.get("metric"),
        })

    by_strategy = collections.Counter(r["strategy"] for r in enriched)

    return {
        "version":          VERSION,
        "generated_at_iso": datetime.now(timezone.utc).isoformat(),
        "as_of":            as_of.isoformat(),
        "top_n":            int(top_n),
        "rows_total":       len(enriched),
        "rows_by_strategy": dict(by_strategy),
        "rows":             enriched,
        "standing_markers": list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":         False,
            "allow_broker_paper":        False,
            "live_trading_supported":    False,
            "modifies_state_json":       False,
            "places_orders":             False,
            "writes_opportunity_ledger": False,
            "all_rows_mode_shadow_only": True,
            "all_rows_status_watching":  True,
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
    if rep["rows_by_strategy"]:
        lines.append("## Rows by strategy")
        lines.append("")
        lines.append("| Strategy | Count |")
        lines.append("|---|---|")
        for k, v in sorted(rep["rows_by_strategy"].items(),
                            key=lambda kv: -kv[1]):
            lines.append(f"| `{k}` | {v} |")
        lines.append("")

    lines.append("## Watchlist")
    lines.append("")
    lines.append(
        "| Strategy | Symbol | Asset | Distance | Near-history | Replay-cands | "
        "Trigger | Required movement | Mode | Status |"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|---|---|"
    )
    if not rep["rows"]:
        lines.append("| (no candidates yet — replay/near-miss data empty) | | | | | | | | | |")
    for r in rep["rows"]:
        d = r.get("current_distance")
        d_s = f"{d:.4f}" if isinstance(d, (int, float)) else "n/a"
        lines.append(
            f"| `{r['strategy']}` | `{r['symbol']}` | "
            f"{r.get('asset_class') or '—'} | {d_s} | "
            f"{r.get('near_miss_history_count') or 0} | "
            f"{r.get('replay_candidate_count') or 0} | "
            f"{r['trigger_condition']} | "
            f"{r['required_market_movement']} | "
            f"**{r['expected_evidence_mode']}** | "
            f"**{r['status']}** |"
        )

    lines.append("")
    lines.append("## Preconditions (must hold before promotion)")
    lines.append("")
    lines.append(f"- **Confidence:** {CONFIDENCE_PRECONDITIONS}")
    lines.append(f"- **Risk:** {RISK_PRECONDITIONS}")
    lines.append("")
    lines.append("## Safety contract")
    lines.append("")
    lines.append("- Every row mode = `SHADOW_ONLY`.")
    lines.append("- Every row status = `WATCHING`.")
    lines.append("- This watchlist NEVER places orders.")
    lines.append("- This watchlist NEVER auto-promotes a row.")
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
        description="v3.26 — Trigger watchlist (Agent 3B / ETAP 8).",
    )
    p.add_argument("--as-of", default=None)
    p.add_argument("--top-n", type=int, default=20)
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

    rep = build_watchlist(as_of=as_of, top_n=args.top_n)
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
              f"By strategy: {rep['rows_by_strategy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
