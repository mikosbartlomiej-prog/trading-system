#!/usr/bin/env python3
"""v3.31 ETAP 7 (2026-06-16) — Post-repair activation path simulator.

CONTRACT (do not loosen)
------------------------
This script is **read-only**. It NEVER:

* calls the broker,
* imports ``alpaca_orders``,
* mutates system state (safe_mode, broker_repair_required, runtime_state),
* writes operator markers,
* makes network calls,
* flips ``LIVE_TRADING`` / ``ALLOW_BROKER_PAPER`` / ``EDGE_GATE_ENABLED``.

It only WRITES two report files:

* ``docs/POST_REPAIR_ACTIVATION_PATH.md``
* ``learning-loop/post_repair_activation_path_latest.json``

PURPOSE
-------
Tell the operator, in plain language, *what gate decision WOULD become*
after the operator finishes:

1. recording all required operator-confirmation markers,
2. applying the safe-mode reconciliation proposal manually,
3. applying the broker-repair clearance proposal manually.

The simulator runs the activation gate in-memory under multiple "what-if"
overrides — it never persists any of those overrides. After printing the
hypothetical path it also reminds the operator that **execution remains
disabled by design** until a separate audited PR enables it.

Verdicts
--------
* ``BLOCKED_OPERATOR_MARKER_REQUIRED``
* ``BLOCKED_SAFE_MODE_RECONCILIATION_REQUIRED``
* ``BLOCKED_BROKER_REPAIR_REQUIRED``
* ``BLOCKED_FRESH_INCIDENT``
* ``READY_FOR_SHADOW_ONLY_AFTER_OPERATOR_CLEARANCE``
* ``READY_FOR_ALLOCATOR_AFTER_OPERATOR_CLEARANCE``
* ``EXECUTION_STILL_DISABLED_BY_DESIGN`` (always present in output —
  v3.30 contract: even if allocator becomes allowed, broker execution
  is architecturally gated separately.)

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# ── Standing invariants (asserted by tests) ───────────────────────────────────
LIVE_TRADING_UNSUPPORTED = True
NO_ORDER_PLACEMENT = True
NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT = True
EDGE_GATE_ENABLED = False
ALLOW_BROKER_PAPER = False


V_BLOCKED_MARKERS                    = "BLOCKED_OPERATOR_MARKER_REQUIRED"
V_BLOCKED_SAFE_MODE_RECONCILIATION   = "BLOCKED_SAFE_MODE_RECONCILIATION_REQUIRED"
V_BLOCKED_BROKER_REPAIR              = "BLOCKED_BROKER_REPAIR_REQUIRED"
V_BLOCKED_FRESH_INCIDENT             = "BLOCKED_FRESH_INCIDENT"
V_READY_SHADOW                       = "READY_FOR_SHADOW_ONLY_AFTER_OPERATOR_CLEARANCE"
V_READY_ALLOCATOR                    = "READY_FOR_ALLOCATOR_AFTER_OPERATOR_CLEARANCE"

#: Architectural marker — always surfaced in the report.
EXECUTION_NOTE = "EXECUTION_STILL_DISABLED_BY_DESIGN"

#: Fresh P13 lookback (same window as activation gate uses).
FRESH_P13_LOOKBACK_HOURS = 24


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


# ── Path helpers ──────────────────────────────────────────────────────────────

def _audit_dir() -> Path:
    env = os.environ.get("AUDIT_TRADING_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "journal" / "autonomy"


def _runtime_state_path() -> Path:
    env = os.environ.get("RUNTIME_STATE_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "runtime_state.json"


def _safe_mode_consistency_path() -> Path:
    env = os.environ.get("SAFE_MODE_CONSISTENCY_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "safe_mode_consistency_latest.json"


def _markers_dir() -> Path:
    env = os.environ.get("OPERATOR_MARKERS_DIR")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "operator_markers"


def _broker_repair_path() -> Path:
    env = os.environ.get("BROKER_REPAIR_REQUIRED_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "broker_repair_required_latest.json"


def _equity_gap_path() -> Path:
    env = os.environ.get("EQUITY_GAP_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "equity_gap_reconciliation_latest.json"


def _out_md_path() -> Path:
    env = os.environ.get("POST_REPAIR_OUT_MD")
    if env:
        return Path(env)
    return _REPO_ROOT / "docs" / "POST_REPAIR_ACTIVATION_PATH.md"


def _out_json_path() -> Path:
    env = os.environ.get("POST_REPAIR_OUT_JSON")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "post_repair_activation_path_latest.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# ── Readers (read-only, fail-soft) ────────────────────────────────────────────

def _parse_iso(s: object) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_broker_repair_state() -> dict[str, dict]:
    raw = _read_json(_broker_repair_path())
    entries = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {str(k): v for k, v in entries.items() if isinstance(v, dict)}


def _read_safe_mode_consistency_verdict() -> str:
    raw = _read_json(_safe_mode_consistency_path())
    return str(raw.get("verdict") or "") if isinstance(raw, dict) else ""


def _read_runtime_safe_mode_active() -> bool:
    raw = _read_json(_runtime_state_path())
    sm = raw.get("safe_mode") if isinstance(raw, dict) else None
    if not isinstance(sm, dict):
        return False
    return bool(sm.get("active", False))


def _read_equity_gap_verdict() -> str:
    raw = _read_json(_equity_gap_path())
    return str(raw.get("verdict") or "") if isinstance(raw, dict) else ""


def _read_operator_markers() -> dict[str, dict]:
    out: dict[str, dict] = {}
    d = _markers_dir()
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        name = p.name
        if name.endswith("_template.json"):
            continue
        if name.startswith("safe_mode_reconciliation_proposal_"):
            continue
        if name.startswith("broker_repair_clearance_proposal_"):
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        sym = payload.get("symbol")
        source = str(payload.get("source") or "")
        if not sym or source != "OPERATOR_MANUAL_CONFIRMATION":
            continue
        out[str(sym)] = payload
        out[str(sym).replace("/", "_").replace(" ", "_")] = payload
    return out


def _aliases_for_symbol(symbol: str) -> set[str]:
    try:
        from symbol_normalization import aliases_for  # type: ignore
    except ImportError:
        try:
            from shared.symbol_normalization import aliases_for  # type: ignore
        except ImportError:
            return {str(symbol)}
    try:
        return aliases_for(symbol) or {str(symbol)}
    except Exception:
        return {str(symbol)}


def _fresh_p13_count(*, hours: int = FRESH_P13_LOOKBACK_HOURS) -> int:
    out = 0
    d = _audit_dir()
    if not d.exists():
        return 0
    cutoff = _now() - timedelta(hours=hours)
    days_back = max(2, hours // 24 + 2)
    for delta in range(0, days_back + 1):
        day = (_now() - timedelta(days=delta)).date().isoformat()
        p = d / f"{day}.jsonl"
        if not p.exists():
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    reason = str(row.get("reason") or "")
                    dt = str(row.get("decision_type") or "")
                    if not ("P13_BRACKET_INTERLOCK" in reason
                            or "P13_bracket_interlock" in reason
                            or "P13_BRACKET_INTERLOCK" in dt):
                        continue
                    ts = _parse_iso(row.get("timestamp") or row.get("ts_iso"))
                    if ts is None or ts < cutoff:
                        continue
                    out += 1
        except OSError:
            continue
    return out


def _classify_marker_coverage(
    blocked_symbols: list[str],
    markers: dict[str, dict],
) -> tuple[list[str], list[str]]:
    with_marker: list[str] = []
    without_marker: list[str] = []
    for sym in blocked_symbols:
        aliases = set()
        try:
            aliases.update(_aliases_for_symbol(sym))
        except Exception:
            aliases.add(sym)
        for a in list(aliases):
            aliases.add(str(a).replace("/", "_").replace(" ", "_"))
        if any(a in markers for a in aliases):
            with_marker.append(sym)
        else:
            without_marker.append(sym)
    return with_marker, without_marker


# ── Simulator ─────────────────────────────────────────────────────────────────

@dataclass
class ActivationSimulation:
    schema_version: str
    evaluated_at_iso: str
    current_verdict: str
    simulated_verdict: str
    blocked_symbols: list[str]
    symbols_with_marker: list[str]
    symbols_without_marker: list[str]
    safe_mode_consistency_verdict: str
    runtime_safe_mode_active: bool
    equity_gap_verdict: str
    fresh_p13_count: int
    execution_note: str
    blockers_current: list[str]
    blockers_simulated: list[str]
    standing_markers: list[str]
    llm_advisory_status: str = "informational_only"

    def to_dict(self) -> dict:
        return asdict(self)


def _standing_markers() -> list[str]:
    return [
        "EDGE_GATE_ENABLED=false",
        "ALLOW_BROKER_PAPER=false",
        "LIVE_TRADING_UNSUPPORTED",
        "NO_ORDER_PLACEMENT",
        "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
    ]


def _current_state_blockers(*,
                            blocked_symbols: list[str],
                            symbols_without_marker: list[str],
                            sm_consistency_verdict: str,
                            sm_runtime_active: bool,
                            equity_gap_verdict: str,
                            fresh_p13: int) -> tuple[str, list[str]]:
    """Compute the *current* verdict + blockers without simulating anything."""
    blockers: list[str] = []

    if symbols_without_marker:
        blockers.append(
            f"operator_confirmation_required={sorted(symbols_without_marker)}")

    if (sm_consistency_verdict
            and sm_consistency_verdict not in ("CONSISTENT", "")):
        blockers.append(f"safe_mode_consistency={sm_consistency_verdict}")
    if sm_runtime_active:
        blockers.append("safe_mode_active")
    if blocked_symbols:
        blockers.append(f"broker_repair_required={sorted(blocked_symbols)}")
    if equity_gap_verdict and equity_gap_verdict != "EQUITY_GAP_OK":
        blockers.append(f"equity_gap_verdict={equity_gap_verdict}")
    if fresh_p13 > 0:
        blockers.append(f"fresh_p13_count={fresh_p13}")

    # Pick the first matching verdict in precedence order.
    if symbols_without_marker:
        verdict = V_BLOCKED_MARKERS
    elif (sm_consistency_verdict not in ("CONSISTENT", "")) or sm_runtime_active:
        verdict = V_BLOCKED_SAFE_MODE_RECONCILIATION
    elif blocked_symbols:
        verdict = V_BLOCKED_BROKER_REPAIR
    elif fresh_p13 > 0:
        verdict = V_BLOCKED_FRESH_INCIDENT
    else:
        # No blockers — simulator can declare READY for shadow.
        verdict = V_READY_SHADOW

    return verdict, blockers


def _simulated_state_blockers(*,
                              equity_gap_verdict: str,
                              fresh_p13: int) -> tuple[str, list[str]]:
    """Compute the verdict *as if* operator finished all 3 steps.

    The simulation overrides (in-memory only) all three things:

    1. Every blocked symbol has an operator marker recorded,
    2. Safe-mode reconciliation proposal has been applied (consistency
       check returns CONSISTENT + runtime_state.safe_mode is not active),
    3. Broker-repair clearance proposal has been applied (every symbol
       is cleared).

    But this method still respects:

    * the equity-gap verdict (real),
    * any fresh P13 (real — operator can't simulate the broker being
      quiet if it isn't actually quiet),

    and the simulator NEVER overrides ``EDGE_GATE_ENABLED`` /
    ``ALLOW_BROKER_PAPER`` / live flags.
    """
    blockers: list[str] = []
    if equity_gap_verdict and equity_gap_verdict != "EQUITY_GAP_OK":
        blockers.append(f"equity_gap_verdict={equity_gap_verdict}")
        return V_BLOCKED_FRESH_INCIDENT, blockers
    if fresh_p13 > 0:
        blockers.append(f"fresh_p13_count={fresh_p13}")
        return V_BLOCKED_FRESH_INCIDENT, blockers
    # All clear → READY_FOR_ALLOCATOR (the allocator gate would now
    # return ALLOCATOR_ALLOWED). Shadow mode is always permitted on
    # ALLOCATOR_ALLOWED.
    return V_READY_ALLOCATOR, blockers


def simulate() -> ActivationSimulation:
    """Run the full simulation and return the structured result."""
    brr_entries = _read_broker_repair_state()
    blocked_symbols = sorted(brr_entries.keys())

    markers = _read_operator_markers()
    with_marker, without_marker = _classify_marker_coverage(blocked_symbols, markers)

    sm_verdict = _read_safe_mode_consistency_verdict()
    sm_runtime = _read_runtime_safe_mode_active()
    equity_verdict = _read_equity_gap_verdict()
    fresh_p13 = _fresh_p13_count()

    current_verdict, current_blockers = _current_state_blockers(
        blocked_symbols=blocked_symbols,
        symbols_without_marker=without_marker,
        sm_consistency_verdict=sm_verdict,
        sm_runtime_active=sm_runtime,
        equity_gap_verdict=equity_verdict,
        fresh_p13=fresh_p13,
    )

    sim_verdict, sim_blockers = _simulated_state_blockers(
        equity_gap_verdict=equity_verdict,
        fresh_p13=fresh_p13,
    )

    return ActivationSimulation(
        schema_version="v3.31",
        evaluated_at_iso=_now_iso(),
        current_verdict=current_verdict,
        simulated_verdict=sim_verdict,
        blocked_symbols=blocked_symbols,
        symbols_with_marker=with_marker,
        symbols_without_marker=without_marker,
        safe_mode_consistency_verdict=sm_verdict,
        runtime_safe_mode_active=sm_runtime,
        equity_gap_verdict=equity_verdict,
        fresh_p13_count=fresh_p13,
        execution_note=EXECUTION_NOTE,
        blockers_current=current_blockers,
        blockers_simulated=sim_blockers,
        standing_markers=_standing_markers(),
    )


# ── Writers ───────────────────────────────────────────────────────────────────

def write_json(sim: ActivationSimulation) -> Path:
    path = _out_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = sim.to_dict()
    # Always surface the architectural execution gate.
    body["execution_layer"] = {
        "broker_execution_enabled": False,
        "allow_broker_paper":       False,
        "edge_gate_enabled":        False,
        "live_trading_unsupported": True,
        "no_order_placement":       True,
        "note": (
            "Even if simulated_verdict == READY_FOR_ALLOCATOR, the execution "
            "layer remains DISABLED by architectural design until a separate "
            "audited PR enables it. Operator clearance is necessary but not "
            "sufficient for execution."
        ),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=2, sort_keys=True)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)
    return path


def write_markdown(sim: ActivationSimulation) -> Path:
    path = _out_md_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Post-repair activation path — {sim.evaluated_at_iso}",
        "",
        "Read-only simulation. Tells the operator what the activation gate ",
        "would return after they finish recording markers, applying the ",
        "safe-mode reconciliation proposal, and applying the broker-repair ",
        "clearance proposal.",
        "",
        "## Current state",
        "",
        f"- verdict: **{sim.current_verdict}**",
        f"- blocked_symbols: {sim.blocked_symbols or 'none'}",
        f"- symbols_with_marker: {sim.symbols_with_marker or 'none'}",
        f"- symbols_without_marker: {sim.symbols_without_marker or 'none'}",
        f"- safe_mode_consistency_verdict: {sim.safe_mode_consistency_verdict or '(empty)'}",
        f"- runtime_safe_mode_active: {sim.runtime_safe_mode_active}",
        f"- equity_gap_verdict: {sim.equity_gap_verdict or '(empty)'}",
        f"- fresh_p13_count_last_{FRESH_P13_LOOKBACK_HOURS}h: {sim.fresh_p13_count}",
        "",
        "Current blockers:",
        "",
    ]
    for b in sim.blockers_current or ["(none)"]:
        lines.append(f"- {b}")
    lines.extend([
        "",
        "## Simulated state (operator finished all 3 steps)",
        "",
        f"- verdict: **{sim.simulated_verdict}**",
        "",
        "Remaining blockers (real, NOT simulated away):",
        "",
    ])
    for b in sim.blockers_simulated or ["(none)"]:
        lines.append(f"- {b}")
    lines.extend([
        "",
        "## Execution layer",
        "",
        f"**{EXECUTION_NOTE}**",
        "",
        "Even if `simulated_verdict == READY_FOR_ALLOCATOR_AFTER_OPERATOR_CLEARANCE`,",
        "the broker execution layer stays DISABLED by architectural design:",
        "",
        "- `broker_execution_enabled = false`",
        "- `allow_broker_paper = false`",
        "- `edge_gate_enabled = false`",
        "- `live_trading_unsupported = true`",
        "- `no_order_placement = true`",
        "",
        "Operator clearance is necessary but **not sufficient** for execution. ",
        "Execution requires a separate audited PR to enable the broker layer.",
        "",
        "## LLM advisory status",
        "",
        f"- {sim.llm_advisory_status}",
        "",
        "LLM availability NEVER changes readiness or unblocks any gate. ",
        "Advisory output is informational only.",
        "",
        "## Standing markers",
        "",
        *(f"- `{m}`" for m in sim.standing_markers),
        "",
    ])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


# ── CLI ───────────────────────────────────────────────────────────────────────

def _str_to_bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "on"}


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="check_post_repair_activation_path.py",
        description=(
            "Read-only simulator for the post-repair activation path. "
            "Writes a markdown + JSON report. NEVER mutates system state."
        ),
    )
    p.add_argument("--dry-run", default="false",
                   help="When 'true' print result without writing report files.")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    sim = simulate()

    print(f"check_post_repair_activation_path: current={sim.current_verdict}  "
          f"simulated={sim.simulated_verdict}")
    print(f"  blocked_symbols={sim.blocked_symbols}")
    print(f"  symbols_without_marker={sim.symbols_without_marker}")
    print(f"  safe_mode_consistency_verdict={sim.safe_mode_consistency_verdict}")
    print(f"  fresh_p13_count={sim.fresh_p13_count}")
    print(f"  EXECUTION NOTE: {EXECUTION_NOTE}")

    if not _str_to_bool(args.dry_run):
        json_path = write_json(sim)
        md_path = write_markdown(sim)
        print(f"  json: {json_path}")
        print(f"  md:   {md_path}")

    for m in _standing_markers():
        print(f"  marker: {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "V_BLOCKED_MARKERS",
    "V_BLOCKED_SAFE_MODE_RECONCILIATION",
    "V_BLOCKED_BROKER_REPAIR",
    "V_BLOCKED_FRESH_INCIDENT",
    "V_READY_SHADOW",
    "V_READY_ALLOCATOR",
    "EXECUTION_NOTE",
    "ActivationSimulation",
    "simulate",
    "write_json",
    "write_markdown",
    "main",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
    "EDGE_GATE_ENABLED",
    "ALLOW_BROKER_PAPER",
]
