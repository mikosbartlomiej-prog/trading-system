#!/usr/bin/env python3
"""v3.23.0 (2026-06-15) — Confidence-score reality check reporter.

Surfaces whether the confidence engine is producing real, varied
data — or whether it's silently defaulting every component to 0.5 and
every overall score to null. The shadow runner uses confidence as a
gate; if every row has confidence_score=null, the gate is dormant
and any "shadow_eligible" count derived from it is meaningless.

Outputs:

- ``learning-loop/shadow_evidence/confidence_reality_check_latest.json``
- ``docs/CONFIDENCE_REALITY_CHECK.md``

HARD SAFETY RULES (cannot be opted out of)
------------------------------------------
- NEVER submits orders.
- NEVER imports ``alpaca_orders``.
- NEVER calls broker / network endpoints.
- NEVER mutates state.json or runtime_state.json.
- Every output carries the v3.23 standing markers footer.
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

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = REPO_ROOT / "learning-loop" / "opportunity_ledger"
EVIDENCE_DIR = REPO_ROOT / "learning-loop" / "shadow_evidence"
STATE_PATH = REPO_ROOT / "learning-loop" / "state.json"
CALIBRATION_DIR = EVIDENCE_DIR / "confidence_calibration"

LATEST_JSON_PATH = EVIDENCE_DIR / "confidence_reality_check_latest.json"
LATEST_MD_PATH = REPO_ROOT / "docs" / "CONFIDENCE_REALITY_CHECK.md"

CONF_BUCKETS = ("0.0-0.5", "0.5-0.65", "0.65-0.80", "0.80+", "null")

# Components we expect the confidence engine to produce. Matches
# ``shared/confidence.py`` v3.12 spec.
EXPECTED_COMPONENTS = (
    "data_quality",
    "signal_strength",
    "regime_alignment",
    "system_health",
    "risk_state",
    "sample_size",
    "track_record",
    "calibration",
)


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


def _confidence_bucket(score: Any) -> str:
    if score is None:
        return "null"
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "null"
    if s < 0.5:
        return "0.0-0.5"
    if s < 0.65:
        return "0.5-0.65"
    if s < 0.80:
        return "0.65-0.80"
    return "0.80+"


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


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_rows(repo_root: Path, as_of: datetime,
                days: int) -> list[dict]:
    ledger_dir = repo_root / "learning-loop" / "opportunity_ledger"
    rows: list[dict] = []
    for delta in range(days):
        d = (as_of - timedelta(days=delta)).date()
        rows.extend(_load_jsonl(ledger_dir / f"{d.isoformat()}.jsonl"))
    return rows


def _verdict_for(score: Any) -> str:
    """Mirror shared/confidence.py thresholds (BLOCK<0.50, ALERT_ONLY
    >=0.50 and <0.65, ALLOW>=0.65)."""
    if score is None:
        return "unknown"
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if s < 0.50:
        return "BLOCK"
    if s < 0.65:
        return "ALERT_ONLY"
    return "ALLOW"


def build_check(
    *,
    as_of: datetime,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    if repo_root is None:
        repo_root = REPO_ROOT
    rows = _load_rows(repo_root, as_of, days=7)
    total = len(rows)
    n_score_not_null = 0
    n_components_nonempty = 0
    score_dist: dict[str, int] = {b: 0 for b in CONF_BUCKETS}
    verdict_dist: dict[str, int] = collections.Counter()
    # Per-component variance tracker. value_set[component] = set of seen
    # non-null values; we use it to determine "always default" vs
    # "has real data".
    component_value_sets: dict[str, set] = {
        c: set() for c in EXPECTED_COMPONENTS}
    component_seen_count: dict[str, int] = {
        c: 0 for c in EXPECTED_COMPONENTS}

    for row in rows:
        score = row.get("confidence_score")
        if score is not None:
            n_score_not_null += 1
        score_dist[_confidence_bucket(score)] += 1
        verdict_dist[_verdict_for(score)] += 1
        comps = row.get("confidence_components") or {}
        if isinstance(comps, dict) and comps:
            n_components_nonempty += 1
            for c in EXPECTED_COMPONENTS:
                v = comps.get(c)
                if v is not None:
                    component_seen_count[c] += 1
                    # Round to 3 decimals before adding to the set so
                    # micro-float-noise doesn't inflate "variance".
                    try:
                        component_value_sets[c].add(
                            round(float(v), 3))
                    except (TypeError, ValueError):
                        pass

    # Classify components.
    components_always_default: list[str] = []
    components_with_real_data: list[str] = []
    for c in EXPECTED_COMPONENTS:
        seen = component_value_sets[c]
        if not seen:
            # Never observed at all. Treat as "always default" — the
            # engine doesn't produce this component yet, so any value
            # plugged in for it is the configured default (typically
            # 0.5 per ``shared/confidence.py``).
            components_always_default.append(c)
            continue
        # If the only value(s) seen are within 0.005 of the canonical
        # 0.5 default → "always default".
        if all(abs(v - 0.5) < 0.005 for v in seen):
            components_always_default.append(c)
        else:
            components_with_real_data.append(c)

    # Sample-size cap status. Strategies with trades_lifetime < 10 are
    # treated as low-sample by the confidence engine (sample_size
    # component caps low). Honor ``repo_root`` so tests can seed an
    # isolated state.json without touching the live one.
    state = _load_json(repo_root / "learning-loop" / "state.json")
    strategies = state.get("strategies", {}) or {}
    low_sample_strategies = sorted([
        name for name, cfg in strategies.items()
        if isinstance(cfg, dict)
        and isinstance(cfg.get("trades_lifetime"), int)
        and cfg["trades_lifetime"] < 10
    ])

    # Calibration history.
    calibrated_yet = False
    calibration_dir = repo_root / "learning-loop" / "shadow_evidence" / \
        "confidence_calibration"
    if calibration_dir.exists():
        # Any non-empty file in that dir = at least one calibration run.
        for p in calibration_dir.glob("*.json"):
            try:
                if p.stat().st_size > 0:
                    calibrated_yet = True
                    break
            except Exception:
                continue

    pct = lambda n, d: round(100.0 * n / d, 2) if d else 0.0

    out: dict[str, Any] = {
        "version":               "v3.23.0",
        "generated_at_iso":      datetime.now(timezone.utc).isoformat(),
        "as_of":                 as_of.isoformat(),
        "git_head":              _git_head(),
        "rows_total_7d":         total,
        "rows_with_confidence_score_nonnull": n_score_not_null,
        "rows_with_confidence_score_nonnull_pct": pct(
            n_score_not_null, total),
        "rows_with_confidence_components_nonempty":
            n_components_nonempty,
        "rows_with_confidence_components_nonempty_pct": pct(
            n_components_nonempty, total),
        "score_distribution":    score_dist,
        "confidence_verdict_distribution": dict(verdict_dist),
        "components_always_default": components_always_default,
        "components_with_real_data": components_with_real_data,
        "expected_components":   list(EXPECTED_COMPONENTS),
        "low_sample_strategy_count": len(low_sample_strategies),
        "low_sample_strategies":  low_sample_strategies,
        "calibrated_yet":        calibrated_yet,
        "calibration_dir_exists": calibration_dir.exists(),
        "standing_markers":      list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":   False,
            "allow_broker_paper":  False,
            "live_trading_supported": False,
        },
    }
    return out


def render_md(check: dict[str, Any]) -> str:
    score_dist_rows = "\n".join(
        f"| `{k}` | {v} |"
        for k, v in check["score_distribution"].items())
    verdict_rows = "\n".join(
        f"| `{k}` | {v} |"
        for k, v in sorted(check["confidence_verdict_distribution"].items()))
    if not verdict_rows:
        verdict_rows = "| (none) | 0 |"
    comps_default = "\n".join(
        f"- `{c}`" for c in check["components_always_default"])
    if not comps_default:
        comps_default = "- (none)"
    comps_real = "\n".join(
        f"- `{c}`" for c in check["components_with_real_data"])
    if not comps_real:
        comps_real = "- (none)"
    low_sample = "\n".join(
        f"- `{s}`" for s in check["low_sample_strategies"])
    if not low_sample:
        low_sample = "- (none)"
    standing = "\n".join(f"- `{m}`" for m in check["standing_markers"])

    return f"""# Confidence Reality Check (v3.23.0)

**Generated:** `{check["generated_at_iso"]}`
**As of:** `{check["as_of"]}`
**Git HEAD:** `{check["git_head"]}`
**Calibrated yet:** `{check["calibrated_yet"]}`

## Population over last 7 days

| Metric | Value |
|---|---|
| Total ledger rows (7d) | `{check["rows_total_7d"]}` |
| Rows with `confidence_score` non-null | `{check["rows_with_confidence_score_nonnull"]}` (`{check["rows_with_confidence_score_nonnull_pct"]}%`) |
| Rows with `confidence_components` non-empty | `{check["rows_with_confidence_components_nonempty"]}` (`{check["rows_with_confidence_components_nonempty_pct"]}%`) |

## Score distribution

| Bucket | Count |
|---|---|
{score_dist_rows}

## Verdict distribution

| Verdict | Count |
|---|---|
{verdict_rows}

## Components currently producing default 0.5 only

{comps_default}

## Components with observed variance

{comps_real}

## Low-sample strategies (trades_lifetime < 10)

Total: `{check["low_sample_strategy_count"]}`

{low_sample}

## Calibration status

- `calibration_dir_exists`: `{check["calibration_dir_exists"]}`
- `calibrated_yet`: `{check["calibrated_yet"]}`

## Standing markers

{standing}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the v3.23 confidence reality check report.")
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
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    check = build_check(as_of=as_of)
    md = render_md(check)

    if args.json:
        print(json.dumps(check, indent=2, sort_keys=True))

    if not args.no_write:
        LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_JSON_PATH.write_text(
            json.dumps(check, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_MD_PATH.write_text(md, encoding="utf-8")
        print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
        print(f"Wrote {LATEST_MD_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
