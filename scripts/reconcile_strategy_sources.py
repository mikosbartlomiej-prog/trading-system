#!/usr/bin/env python3
"""v3.24 (2026-06-15) — Strategy source reconciliation (ETAP 5).

WHY
---
The previous ``build_strategy_coverage_report.py`` collapsed 5+
inconsistency modes into a single ``ZOMBIE`` bucket. That's enough
for a triage dashboard, but it does not tell the operator WHICH kind
of zombie they are looking at, or what (safe) action to take.

This reconciler enumerates EVERY strategy ID seen across the union of
five sources and assigns one of nine status enums:

  * ACTIVE_RUNTIME_SOURCE     — registry + monitor + recent ledger rows
  * ACTIVE_SHADOW_SOURCE       — registry + signal_at fn, no monitor traffic
  * OBSERVE_ONLY                — registry observe_only=True OR no signal_at
  * BACKTEST_ONLY               — backtest/strategies.py only
  * ZOMBIE_STATE_ONLY           — state.json only (no registry, monitor, backtest)
  * ZOMBIE_REGISTRY_ONLY        — registry only (no monitor traffic, no state)
  * DEAD_ORPHAN                 — present nowhere "active"
  * DISABLED_INTENTIONALLY      — explicit enabled=false OR paused_until future
  * ACTIVE_MONITOR_UNREGISTERED — ledger / monitor traffic, no registry/state row

This reconciler ALSO performs MECHANICALLY SAFE auto-actions:

  * ZOMBIE_REGISTRY_ONLY with no signal_at => converted to observe_only=True
    (status change only; never deletes registry entries).
  * ZOMBIE_STATE_ONLY entries are FLAGGED for operator review; NEVER
    auto-deleted from state.json.
  * DEAD_ORPHAN entries are FLAGGED for operator review; NEVER
    auto-deleted from state.json.

OUTPUTS
-------
- ``learning-loop/strategy_source_reconciliation_latest.json``
- ``docs/STRATEGY_SOURCE_RECONCILIATION.md``

HARD SAFETY RULES (cannot be opted out of)
------------------------------------------
- NEVER imports ``alpaca_orders``.
- NEVER calls broker / network endpoints.
- NEVER deletes state.json entries.
- NEVER mutates registry entries in this reconciler — the "auto"
  conversion is only emitted into the OUTPUT report; updating the
  shadow_opportunity_generator registry is a separate operator action.
- Every output carries the v3.24 standing markers footer.
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

LATEST_JSON_PATH = (REPO_ROOT / "learning-loop"
                    / "strategy_source_reconciliation_latest.json")
LATEST_MD_PATH = REPO_ROOT / "docs" / "STRATEGY_SOURCE_RECONCILIATION.md"
LEDGER_DIR = REPO_ROOT / "learning-loop" / "opportunity_ledger"
STATE_PATH = REPO_ROOT / "learning-loop" / "state.json"

STANDING_MARKERS: tuple[str, ...] = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES",
    "REAL_MARKET_EVIDENCE_REMAINS_REQUIRED",
    "STRATEGY_RECONCILIATION_IS_READ_ONLY",
)

VERSION = "v3.24.0"

# Status enums.
ACTIVE_RUNTIME_SOURCE         = "ACTIVE_RUNTIME_SOURCE"
ACTIVE_SHADOW_SOURCE          = "ACTIVE_SHADOW_SOURCE"
ACTIVE_MONITOR_UNREGISTERED   = "ACTIVE_MONITOR_UNREGISTERED"
OBSERVE_ONLY                  = "OBSERVE_ONLY"
BACKTEST_ONLY                 = "BACKTEST_ONLY"
ZOMBIE_STATE_ONLY             = "ZOMBIE_STATE_ONLY"
ZOMBIE_REGISTRY_ONLY          = "ZOMBIE_REGISTRY_ONLY"
DEAD_ORPHAN                   = "DEAD_ORPHAN"
DISABLED_INTENTIONALLY        = "DISABLED_INTENTIONALLY"


# ─── Filesystem / git helpers ─────────────────────────────────────────────────


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


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return rows
    return rows


def _load_ledger_rows(repo_root: Path, as_of: datetime, days: int
                      ) -> list[dict]:
    ledger_dir = repo_root / "learning-loop" / "opportunity_ledger"
    rows: list[dict] = []
    for delta in range(days):
        d = (as_of - timedelta(days=delta)).date()
        rows.extend(_load_jsonl(ledger_dir / f"{d.isoformat()}.jsonl"))
    return rows


# ─── Source extraction ───────────────────────────────────────────────────────


def _load_registry(*, repo_root: Path | None = None) -> dict[str, dict]:
    """Call ``shared/shadow_opportunity_generator.py::_strategy_registry``.

    Returns the raw dict (strategy name -> spec) or {} on import error.
    """
    if repo_root is None:
        repo_root = REPO_ROOT
    added: list[str] = []
    for p in (str(repo_root), str(repo_root / "shared")):
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
        for p in added:
            try:
                sys.path.remove(p)
            except ValueError:
                pass


def _load_backtest_strategies(*, repo_root: Path | None = None
                              ) -> set[str]:
    """Statically parse ``backtest/strategies.py`` for ``*_signal_at`` fns.

    Returns a set of strategy IDs derived from function names. Function
    ``momentum_long_signal_at`` -> strategy id ``momentum-long``. Skips
    helper underscore functions like ``_rsi``.
    """
    if repo_root is None:
        repo_root = REPO_ROOT
    path = repo_root / "backtest" / "strategies.py"
    if not path.exists():
        return set()
    names: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            fn_name = node.name
            if fn_name.startswith("_"):
                continue
            if not fn_name.endswith("_signal_at"):
                continue
            # strip suffix and convert underscores to dashes
            strat_id = fn_name[: -len("_signal_at")].replace("_", "-")
            names.add(strat_id)
    return names


def _load_backtest_registry(*, repo_root: Path | None = None
                            ) -> dict[str, dict]:
    """Statically extract ``backtest/strategy_registry.py::REGISTRY`` keys.

    Returns dict of strategy_name -> {"readiness": ..., "signal_fn_name":
    ...}. Best-effort — never crashes on syntax issues.
    """
    if repo_root is None:
        repo_root = REPO_ROOT
    path = repo_root / "backtest" / "strategy_registry.py"
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "REGISTRY":
                    if isinstance(node.value, ast.Dict):
                        for k, v in zip(node.value.keys, node.value.values):
                            if isinstance(k, ast.Constant) and isinstance(
                                    k.value, str):
                                meta: dict = {}
                                if isinstance(v, ast.Call):
                                    for kw in v.keywords:
                                        if kw.arg == "readiness" and isinstance(
                                                kw.value, ast.Name):
                                            meta["readiness"] = kw.value.id
                                        elif kw.arg == "signal_fn_name":
                                            if isinstance(kw.value, ast.Constant):
                                                meta["signal_fn_name"] = (
                                                    kw.value.value)
                                out[k.value] = meta
    return out


# Strategy IDs encountered in monitor.py files via "strategy" key in dicts.
_MONITOR_STRATEGY_RX = re.compile(
    r'"strategy"\s*:\s*"([a-zA-Z0-9_\-]+)"',
)
# Module-level STRATEGY_NAME = "..." (covers reddit-monitor + similar).
_MONITOR_NAME_CONST_RX = re.compile(
    r'^\s*STRATEGY_NAME\s*=\s*"([a-zA-Z0-9_\-]+)"\s*$',
    re.MULTILINE,
)


def _scan_monitor_strategies(*, repo_root: Path | None = None
                             ) -> dict[str, list[str]]:
    """Grep every ``*-monitor/monitor.py`` for strategy literals.

    Returns dict of strategy_id -> [monitor_dir, ...].
    """
    if repo_root is None:
        repo_root = REPO_ROOT
    out: dict[str, set[str]] = collections.defaultdict(set)
    for mon_dir in sorted(repo_root.glob("*-monitor")):
        mp = mon_dir / "monitor.py"
        if not mp.exists():
            continue
        try:
            text = mp.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in _MONITOR_STRATEGY_RX.finditer(text):
            strat = m.group(1)
            # filter the meta-variable placeholders and pure identifiers
            if strat and not strat.endswith("_"):
                out[strat].add(mon_dir.name)
        for m in _MONITOR_NAME_CONST_RX.finditer(text):
            strat = m.group(1)
            if strat:
                out[strat].add(mon_dir.name)
    return {k: sorted(v) for k, v in out.items()}


# ─── Classification ──────────────────────────────────────────────────────────


def _is_paused_in_future(paused_until: Any, as_of: datetime) -> bool:
    if not paused_until:
        return False
    if not isinstance(paused_until, str):
        return False
    try:
        d = datetime.fromisoformat(paused_until.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d > as_of
    except (ValueError, TypeError):
        return False


def _suggest_action(status: str, *, name: str, observe_only: bool,
                    has_signal_at: bool, monitor_sources: list[str],
                    ) -> str:
    if status == ACTIVE_RUNTIME_SOURCE:
        return "no action; live and recording ledger rows"
    if status == ACTIVE_SHADOW_SOURCE:
        return ("no action; shadow-only registry entry; verify no "
                "monitor traffic expected")
    if status == ACTIVE_MONITOR_UNREGISTERED:
        return ("operator: add strategy to shadow_opportunity_generator "
                "registry OR confirm this is an admin-only client_order_id "
                "prefix (e.g. allocator tag)")
    if status == OBSERVE_ONLY:
        return "no action; observe-only registry entry"
    if status == BACKTEST_ONLY:
        return ("operator: either register in shadow_opportunity_generator "
                "OR document as research-only")
    if status == ZOMBIE_STATE_ONLY:
        return ("operator review — flagged but NOT deleted. Consider "
                "removing from state.json or registering in "
                "shadow_opportunity_generator")
    if status == ZOMBIE_REGISTRY_ONLY:
        if not has_signal_at:
            return ("auto-suggest: convert registry entry to "
                    "observe_only=True (no signal_at function)")
        return ("operator review — registry entry has signal_at but no "
                "monitor / ledger traffic")
    if status == DEAD_ORPHAN:
        return ("operator review — flagged but NOT deleted. Likely "
                "renamed strategy or stale audit prefix")
    if status == DISABLED_INTENTIONALLY:
        return "no action; intentional disable / pause respected"
    return "no action"


def _classify_strategy(
    *,
    name: str,
    in_registry: bool,
    in_state: bool,
    in_backtest_fn: bool,
    in_monitor: bool,
    in_ledger_7d: bool,
    has_recent_ledger: bool,
    observe_only_flag: bool,
    has_signal_at: bool,
    enabled: bool,
    paused_in_future: bool,
) -> str:
    # Highest priority: explicit disable / future pause.
    if (in_state and not enabled) or paused_in_future:
        return DISABLED_INTENTIONALLY

    # Observe-only signal (declared via registry).
    if in_registry and (observe_only_flag or not has_signal_at):
        # Still observe-only even if has_signal_at when flag is set.
        if observe_only_flag:
            return OBSERVE_ONLY
        # No signal_at function = registry observe-only-by-default.
        if not has_signal_at:
            # but if also has monitor traffic, it's unregistered-active
            # not observe-only.
            if in_monitor or in_ledger_7d:
                pass  # fall through to ACTIVE_MONITOR_UNREGISTERED check
            else:
                return OBSERVE_ONLY

    # Has monitor traffic AND ledger AND registry.
    if in_registry and in_monitor and has_recent_ledger:
        return ACTIVE_RUNTIME_SOURCE

    # Registry-only with a functioning signal fn, no monitor traffic.
    if in_registry and has_signal_at and not in_monitor:
        if has_recent_ledger:
            # ledger but no monitor: still shadow generation source.
            return ACTIVE_SHADOW_SOURCE
        return ACTIVE_SHADOW_SOURCE

    # Has monitor / ledger traffic but no registry row.
    if (in_monitor or in_ledger_7d) and not in_registry:
        # Still possibly in state.json (allocator-* tags).
        return ACTIVE_MONITOR_UNREGISTERED

    # Backtest function exists but nowhere registered / used.
    if in_backtest_fn and not in_registry and not in_state and not in_monitor:
        return BACKTEST_ONLY

    # State-only.
    if in_state and not in_registry and not in_backtest_fn and not in_monitor:
        if has_recent_ledger:
            return ACTIVE_MONITOR_UNREGISTERED
        return ZOMBIE_STATE_ONLY

    # Registry-only (no monitor traffic AND no state entry).
    if in_registry and not in_state and not in_monitor and not in_ledger_7d:
        return ZOMBIE_REGISTRY_ONLY

    # Registry + state but neither monitor traffic nor ledger:
    if in_registry and in_state and not in_monitor and not in_ledger_7d:
        return ZOMBIE_REGISTRY_ONLY

    # Catch-all: dead orphan (nowhere active).
    if not (in_registry or in_state or in_backtest_fn or in_monitor
            or in_ledger_7d):
        return DEAD_ORPHAN

    # Mixed leftover.
    return DEAD_ORPHAN


# ─── Build ───────────────────────────────────────────────────────────────────


def build_reconciliation(
    *,
    as_of: datetime,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    if repo_root is None:
        repo_root = REPO_ROOT
    registry = _load_registry(repo_root=repo_root)
    state = _load_json(repo_root / "learning-loop" / "state.json")
    state_strats = state.get("strategies", {}) or {}
    backtest_fns = _load_backtest_strategies(repo_root=repo_root)
    backtest_reg = _load_backtest_registry(repo_root=repo_root)
    monitor_strategies = _scan_monitor_strategies(repo_root=repo_root)
    ledger_rows = _load_ledger_rows(repo_root, as_of, days=7)

    ledger_strats: dict[str, dict] = collections.defaultdict(lambda: {
        "count": 0, "last_seen": ""
    })
    for r in ledger_rows:
        s = r.get("strategy")
        if not isinstance(s, str) or not s:
            continue
        rec = ledger_strats[s]
        rec["count"] += 1
        ts = r.get("timestamp") or ""
        if isinstance(ts, str) and ts > rec.get("last_seen", ""):
            rec["last_seen"] = ts

    all_strategies = (
        set(registry.keys())
        | set(state_strats.keys())
        | set(monitor_strategies.keys())
        | set(backtest_fns)
        | set(backtest_reg.keys())
        | set(ledger_strats.keys())
    )

    rows: list[dict] = []
    status_dist: dict[str, int] = collections.Counter()
    flags: list[dict] = []
    auto_conversions: list[dict] = []

    for name in sorted(all_strategies):
        reg = registry.get(name, {}) or {}
        in_registry = name in registry
        in_state = name in state_strats
        in_backtest_fn = name in backtest_fns
        in_monitor = name in monitor_strategies
        in_ledger_7d = name in ledger_strats
        observe_only_flag = bool(reg.get("observe_only", False))
        has_signal_at = (
            in_registry and reg.get("signal_at") is not None
        )

        state_cfg = state_strats.get(name, {}) if in_state else {}
        if not isinstance(state_cfg, dict):
            state_cfg = {}
        enabled = bool(state_cfg.get("enabled", True))
        paused_in_future = _is_paused_in_future(
            state_cfg.get("paused_until"), as_of)

        has_recent_ledger = bool(ledger_strats.get(name, {}).get("count", 0))

        status = _classify_strategy(
            name=name,
            in_registry=in_registry,
            in_state=in_state,
            in_backtest_fn=in_backtest_fn,
            in_monitor=in_monitor,
            in_ledger_7d=in_ledger_7d,
            has_recent_ledger=has_recent_ledger,
            observe_only_flag=observe_only_flag,
            has_signal_at=has_signal_at,
            enabled=enabled,
            paused_in_future=paused_in_future,
        )
        status_dist[status] += 1

        suggested = _suggest_action(
            status,
            name=name,
            observe_only=observe_only_flag,
            has_signal_at=has_signal_at,
            monitor_sources=monitor_strategies.get(name, []),
        )

        # Mechanical safe auto-conversion: ZOMBIE_REGISTRY_ONLY
        # with no signal_at -> observe_only=True flag in the OUTPUT.
        if status == ZOMBIE_REGISTRY_ONLY and not has_signal_at:
            auto_conversions.append({
                "strategy":       name,
                "from":           "ZOMBIE_REGISTRY_ONLY",
                "to_recommended": "OBSERVE_ONLY",
                "action":         ("set observe_only=True in "
                                    "shadow_opportunity_generator registry"),
            })

        # Operator-flag (NOT auto-deleted) cases.
        if status in (ZOMBIE_STATE_ONLY, DEAD_ORPHAN):
            flags.append({
                "strategy":       name,
                "status":         status,
                "suggested":      ("operator review — flagged but NOT "
                                    "deleted from state.json"),
                "in_state":       in_state,
                "in_registry":    in_registry,
                "in_backtest_fn": in_backtest_fn,
                "in_monitor":     in_monitor,
                "in_ledger_7d":   in_ledger_7d,
            })

        rows.append({
            "strategy":         name,
            "status":           status,
            "in_registry":      in_registry,
            "in_state":         in_state,
            "in_backtest_fn":   in_backtest_fn,
            "in_monitor":       in_monitor,
            "monitor_sources":  monitor_strategies.get(name, []),
            "in_ledger_7d":     in_ledger_7d,
            "ledger_count_7d":  ledger_strats.get(name, {}).get("count", 0),
            "observe_only":     observe_only_flag,
            "has_signal_at":    has_signal_at,
            "enabled":          enabled,
            "paused_until":     state_cfg.get("paused_until"),
            "trades_lifetime":  state_cfg.get("trades_lifetime"),
            "backtest_readiness":
                backtest_reg.get(name, {}).get("readiness"),
            "suggested_action": suggested,
        })

    return {
        "version":            VERSION,
        "generated_at_iso":   datetime.now(timezone.utc).isoformat(),
        "as_of":              as_of.isoformat(),
        "git_head":           _git_head(),
        "totals": {
            "registry":         len(registry),
            "state":            len(state_strats),
            "backtest_fns":     len(backtest_fns),
            "backtest_reg":     len(backtest_reg),
            "monitor_seen":     len(monitor_strategies),
            "ledger_7d_seen":   len(ledger_strats),
            "union":            len(rows),
        },
        "status_distribution": dict(status_dist),
        "strategies":          rows,
        "auto_conversions":    auto_conversions,
        "operator_flags":      flags,
        "standing_markers":    list(STANDING_MARKERS),
        "safety": {
            "edge_gate_enabled":      False,
            "allow_broker_paper":     False,
            "live_trading_supported": False,
            "modifies_state_json":    False,
            "modifies_registry":      False,
        },
    }


# ─── Rendering ───────────────────────────────────────────────────────────────


def render_md(rec: dict[str, Any]) -> str:
    sd = rec["status_distribution"]
    status_rows = "\n".join(
        f"| `{k}` | {v} |"
        for k, v in sorted(sd.items()))
    if not status_rows:
        status_rows = "| (none) | 0 |"

    header = (
        "| Strategy | Status | In Registry | In State | Backtest fn | "
        "Monitor | Ledger 7d | Observe-only | Has signal_at | Enabled | "
        "Suggested action |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|"
    )

    def _f(b: Any) -> str:
        return "yes" if b else "no"

    body = "\n".join(
        f"| `{r['strategy']}` | `{r['status']}` | {_f(r['in_registry'])} | "
        f"{_f(r['in_state'])} | {_f(r['in_backtest_fn'])} | "
        f"{_f(r['in_monitor'])} ({', '.join(r['monitor_sources']) or '-'}) | "
        f"{r['ledger_count_7d']} | {_f(r['observe_only'])} | "
        f"{_f(r['has_signal_at'])} | {_f(r['enabled'])} | "
        f"{r['suggested_action']} |"
        for r in rec["strategies"]
    )
    if not body:
        body = "| (none) | | | | | | | | | | |"

    auto_section_rows = (
        "\n".join(
            f"| `{c['strategy']}` | `{c['from']}` → `{c['to_recommended']}` | "
            f"{c['action']} |"
            for c in rec["auto_conversions"]
        )
        if rec["auto_conversions"]
        else "| (none) | | |"
    )
    flag_section_rows = (
        "\n".join(
            f"| `{f['strategy']}` | `{f['status']}` | {f['suggested']} |"
            for f in rec["operator_flags"]
        )
        if rec["operator_flags"]
        else "| (none) | | |"
    )

    standing = "\n".join(f"- `{m}`" for m in rec["standing_markers"])

    totals = rec["totals"]
    return f"""# Strategy Source Reconciliation ({rec["version"]})

**Generated:** `{rec["generated_at_iso"]}`
**As of:** `{rec["as_of"]}`
**Git HEAD:** `{rec["git_head"]}`

## Source totals

| Source | Count |
|---|---|
| Shadow registry | {totals["registry"]} |
| state.json | {totals["state"]} |
| backtest/strategies.py functions | {totals["backtest_fns"]} |
| backtest/strategy_registry.py entries | {totals["backtest_reg"]} |
| monitors with `"strategy"` literals | {totals["monitor_seen"]} |
| ledger last 7 days | {totals["ledger_7d_seen"]} |
| **Union (rows below)** | {totals["union"]} |

## Status distribution

| Status | Count |
|---|---|
{status_rows}

## Auto-suggested safe conversions

| Strategy | From → To | Action |
|---|---|---|
{auto_section_rows}

## Operator flags (NOT auto-deleted)

| Strategy | Status | Note |
|---|---|---|
{flag_section_rows}

## Per-strategy detail

{header}
{body}

## Status enum

- `ACTIVE_RUNTIME_SOURCE`     — registry + monitor + recent ledger rows
- `ACTIVE_SHADOW_SOURCE`      — registry + signal_at fn; no monitor traffic
- `ACTIVE_MONITOR_UNREGISTERED` — monitor / ledger traffic; not in registry
- `OBSERVE_ONLY`              — registry observe_only=True OR no signal_at
- `BACKTEST_ONLY`             — backtest function only
- `ZOMBIE_STATE_ONLY`         — only state.json
- `ZOMBIE_REGISTRY_ONLY`      — only registry, no monitor / ledger / state
- `DEAD_ORPHAN`               — nowhere active
- `DISABLED_INTENTIONALLY`    — explicit enabled=false or paused_until future

## Safety contract

- This reconciler is READ-ONLY.
- It does NOT delete state.json entries.
- It does NOT mutate the shadow_opportunity_generator registry.
- It does NOT submit orders or call the broker.
- Operator must approve every conversion / deletion manually.

## Standing markers

{standing}
"""


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the v3.24 strategy source reconciliation.")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--json", action="store_true",
                          help="Print full JSON to stdout")
    parser.add_argument("--no-write", action="store_true",
                          help="Do not write output files")
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

    rec = build_reconciliation(as_of=as_of)
    md = render_md(rec)

    if args.json:
        print(json.dumps(rec, indent=2, sort_keys=True))

    if not args.no_write:
        LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_JSON_PATH.write_text(
            json.dumps(rec, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_MD_PATH.write_text(md, encoding="utf-8")
        print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
        print(f"Wrote {LATEST_MD_PATH.relative_to(REPO_ROOT)}")
        print(
            f"Status distribution: {rec['status_distribution']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
