#!/usr/bin/env python3
"""v3.23.0 (2026-06-15) — Strategy coverage reporter.

For every strategy referenced by either:

- ``shared/shadow_opportunity_generator.py::_strategy_registry()``,
- ``learning-loop/state.json::strategies``, or
- the ledger over the last 7 days,

emit a single per-strategy row with: registry presence, monitor
source, 7-day signal/no-signal/rejection/shadow-eligible counts,
observe-only / paid-data flags, and a single status enum
(``ACTIVE`` / ``DORMANT`` / ``OBSERVE_ONLY`` / ``DEAD`` / ``ZOMBIE``).

Outputs:

- ``learning-loop/shadow_evidence/strategy_coverage_latest.json``
- ``docs/STRATEGY_COVERAGE_STATUS.md``

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
EVIDENCE_DIR = REPO_ROOT / "learning-loop" / "shadow_evidence"
LEDGER_DIR = REPO_ROOT / "learning-loop" / "opportunity_ledger"
STATE_PATH = REPO_ROOT / "learning-loop" / "state.json"

LATEST_JSON_PATH = EVIDENCE_DIR / "strategy_coverage_latest.json"
LATEST_MD_PATH = REPO_ROOT / "docs" / "STRATEGY_COVERAGE_STATUS.md"

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
    "options-momentum":       "options-monitor",
    "alloc-exit":             "allocator",
    "alloc-reduce":           "allocator",
    "allocator-rebalance":    "allocator",
}

# Strategies that require paid market data (e.g. options chains).
PAID_DATA_STRATEGIES = ("options-momentum",)


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


def _resolve_monitor(strategy: str) -> str:
    return STRATEGY_TO_MONITOR.get(strategy or "", "unknown")


def _is_shadow_eligible(row: dict) -> bool:
    rd = (row.get("risk_decision") or "").upper()
    if rd not in ("APPROVE", "DETECTED"):
        return False
    score = row.get("confidence_score")
    if score is None:
        return False
    try:
        return float(score) >= 0.50
    except (TypeError, ValueError):
        return False


def _load_registry() -> dict[str, dict]:
    """Call shared/shadow_opportunity_generator.py::_strategy_registry()."""
    # When run via ``python3 scripts/build_strategy_coverage_report.py``
    # sys.path[0] is the ``scripts/`` dir, not the repo root, so a
    # bare ``import backtest.strategies`` inside the registry function
    # fails. Add both the repo root AND the shared/ dir so both
    # ``import backtest`` and ``import shadow_opportunity_generator``
    # resolve correctly.
    added = []
    for p in (str(REPO_ROOT), str(REPO_ROOT / "shared")):
        if p not in sys.path:
            sys.path.insert(0, p)
            added.append(p)
    try:
        import shadow_opportunity_generator as sog  # type: ignore
        reg = sog._strategy_registry()
        if not isinstance(reg, dict):
            return {}
        return reg
    except Exception:
        return {}
    finally:
        # Defensive cleanup so test runs don't accumulate sys.path
        # entries.
        for p in added:
            try:
                sys.path.remove(p)
            except ValueError:
                pass


def _classify(
    *,
    name: str,
    registry_present: bool,
    in_state: bool,
    observe_only: bool,
    signals: int,
    no_signal: int,
    rejections: int,
    enabled: bool,
) -> str:
    """Return the strategy status enum.

    ZOMBIE catches three inconsistency modes:
    1. Present in registry but not state.json
    2. Present in state.json but not registry
    3. Present in neither, yet has live ledger activity
       (e.g. allocator-emitted client_order_id prefixes that
       aren't real strategies)
    """
    if registry_present and observe_only:
        return "OBSERVE_ONLY"
    if registry_present and not in_state:
        return "ZOMBIE"
    if (not registry_present) and in_state:
        return "ZOMBIE"
    if (not registry_present) and (not in_state):
        # Ledger-only artifact: client_order_id prefix that doesn't
        # match any declared strategy. Treat as ZOMBIE regardless of
        # signals/rejections so it surfaces in audits.
        return "ZOMBIE"
    if not enabled and (signals + no_signal + rejections) == 0:
        return "DEAD"
    if signals == 0 and (no_signal + rejections) > 0:
        return "DORMANT"
    if signals > 0:
        return "ACTIVE"
    return "DEAD"


def build_coverage(
    *,
    as_of: datetime,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    if repo_root is None:
        repo_root = REPO_ROOT
    registry = _load_registry()
    # Honor ``repo_root`` so tests can seed an isolated state.json.
    state = _load_json(repo_root / "learning-loop" / "state.json")
    state_strats = state.get("strategies", {}) or {}
    rows = _load_rows(repo_root, as_of, days=7)

    # Per-strategy 7-day aggregates from the ledger.
    by_strategy_rows: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_strategy_rows[r.get("strategy") or "unknown"].append(r)

    all_names = (set(registry.keys()) | set(state_strats.keys())
                 | set(by_strategy_rows.keys()))
    rows_by_strat: list[dict] = []
    status_dist: dict[str, int] = collections.Counter()

    for name in sorted(all_names):
        reg = registry.get(name, {}) or {}
        in_reg = name in registry
        in_state = name in state_strats
        observe_only = bool(reg.get("observe_only", False))
        requires_paid = name in PAID_DATA_STRATEGIES
        monitor = _resolve_monitor(name)
        if monitor == "unknown" and in_reg:
            monitor = reg.get("asset_class", "unknown")

        rrows = by_strategy_rows.get(name, [])
        signals = 0
        no_signal = 0
        rejections = 0
        shadow_eligible = 0
        for row in rrows:
            rd = (row.get("risk_decision") or "").upper()
            if rd == "DETECTED" or rd == "APPROVE":
                signals += 1
            elif rd == "NO_SIGNAL":
                no_signal += 1
            elif rd == "REJECT":
                rejections += 1
            if _is_shadow_eligible(row):
                shadow_eligible += 1

        enabled = True
        if in_state:
            cfg = state_strats[name]
            if isinstance(cfg, dict):
                enabled = bool(cfg.get("enabled", True))
        status = _classify(
            name=name,
            registry_present=in_reg,
            in_state=in_state,
            observe_only=observe_only,
            signals=signals,
            no_signal=no_signal,
            rejections=rejections,
            enabled=enabled,
        )
        status_dist[status] += 1
        rows_by_strat.append({
            "strategy":          name,
            "registry_present":  in_reg,
            "in_state":          in_state,
            "monitor_source":    monitor,
            "observe_only":      observe_only,
            "requires_paid_data": requires_paid,
            "enabled":           enabled,
            "signals_count_7d":  signals,
            "no_signal_count_7d": no_signal,
            "rejections_7d":     rejections,
            "shadow_eligible_7d": shadow_eligible,
            "status":            status,
        })

    out: dict[str, Any] = {
        "version":           "v3.23.0",
        "generated_at_iso":  datetime.now(timezone.utc).isoformat(),
        "as_of":             as_of.isoformat(),
        "git_head":          _git_head(),
        "strategies_total":  len(rows_by_strat),
        "status_distribution": dict(status_dist),
        "strategies":        rows_by_strat,
        "registry_size":     len(registry),
        "state_strategies_size": len(state_strats),
        "standing_markers":  list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":   False,
            "allow_broker_paper":  False,
            "live_trading_supported": False,
        },
    }
    return out


def render_md(cov: dict[str, Any]) -> str:
    status_rows = "\n".join(
        f"| `{k}` | {v} |"
        for k, v in sorted(cov["status_distribution"].items()))
    if not status_rows:
        status_rows = "| (none) | 0 |"
    header = ("| Strategy | Monitor | Status | Registry | In state | "
              "Observe-only | Paid data | Signals 7d | No-signal 7d | "
              "Rejections 7d | Shadow-eligible 7d |\n"
              "|---|---|---|---|---|---|---|---|---|---|---|")
    body = "\n".join(
        f"| `{r['strategy']}` | `{r['monitor_source']}` | "
        f"`{r['status']}` | `{r['registry_present']}` | "
        f"`{r['in_state']}` | `{r['observe_only']}` | "
        f"`{r['requires_paid_data']}` | `{r['signals_count_7d']}` | "
        f"`{r['no_signal_count_7d']}` | `{r['rejections_7d']}` | "
        f"`{r['shadow_eligible_7d']}` |"
        for r in cov["strategies"])
    if not body:
        body = "| (none) | | | | | | | | | | |"
    standing = "\n".join(f"- `{m}`" for m in cov["standing_markers"])

    return f"""# Strategy Coverage Status (v3.23.0)

**Generated:** `{cov["generated_at_iso"]}`
**As of:** `{cov["as_of"]}`
**Git HEAD:** `{cov["git_head"]}`
**Strategies total:** `{cov["strategies_total"]}` (registry: `{cov["registry_size"]}`, state.json: `{cov["state_strategies_size"]}`)

## Status distribution

| Status | Count |
|---|---|
{status_rows}

## Per-strategy detail

{header}
{body}

## Status enum

- `ACTIVE` — at least one DETECTED/APPROVE signal in 7d
- `DORMANT` — only NO_SIGNAL / REJECT in 7d, no DETECTED
- `OBSERVE_ONLY` — registry marks observe_only=True (geo-defense, options-momentum)
- `DEAD` — disabled + zero ledger activity in 7d
- `ZOMBIE` — present in only one of (registry / state.json); inconsistent

## Standing markers

{standing}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the v3.23 strategy coverage report.")
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

    cov = build_coverage(as_of=as_of)
    md = render_md(cov)

    if args.json:
        print(json.dumps(cov, indent=2, sort_keys=True))

    if not args.no_write:
        LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_JSON_PATH.write_text(
            json.dumps(cov, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_MD_PATH.write_text(md, encoding="utf-8")
        print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
        print(f"Wrote {LATEST_MD_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
