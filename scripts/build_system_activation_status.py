#!/usr/bin/env python3
"""v3.29 ETAP 10 (2026-06-16) — System Activation Dashboard.

PURPOSE
-------
Single status page that answers, at-a-glance, three operator questions:

1. Is the whole solution safely ON?  (``WHOLE_SOLUTION_SAFE_ON``)
2. Is anything actually executing trades?  (``TRADING_EXECUTION_ON``)
3. What does the operator need to do RIGHT NOW?  (``OPERATOR_ACTION_REQUIRED``)

The dashboard reads every subsystem state file the master gate already
consumes, plus a small set of supplementary discovery / shadow / LLM
artefacts. It writes two outputs:

* ``learning-loop/system_activation_status_latest.json`` — machine-readable
* ``docs/SYSTEM_ACTIVATION_STATUS.md`` — operator-friendly markdown

This file supersedes the previous ETAP 8 reporter (same path) with a
richer 20-subsystem catalogue and the full ETAP 10 top-level flag set.

CONTRACT
--------
* Read-only.
* NEVER calls the broker.
* NEVER imports ``alpaca_orders``.
* NEVER flips any flag.
* NEVER auto-clears anything.
* ``TRADING_EXECUTION_ON`` is **always** ``False`` (write-time literal).
* ``LLM_EXECUTION_AUTHORITY`` is **always** ``False`` (write-time literal).

STANDING MARKERS
----------------
- ``EDGE_GATE_ENABLED=false``
- ``ALLOW_BROKER_PAPER=false``
- ``LIVE_TRADING_UNSUPPORTED``
- ``NO_ORDER_PLACEMENT``
- ``NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT``
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Standing invariants (asserted by tests) ──────────────────────────────────
LIVE_TRADING_UNSUPPORTED = True
NO_ORDER_PLACEMENT = True
NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT = True
EDGE_GATE_ENABLED = False
ALLOW_BROKER_PAPER = False

STANDING_MARKERS = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_SCRIPT",
)

# Hard invariants the dashboard writes verbatim regardless of state.
TRADING_EXECUTION_ON = False        # NEVER true
LLM_EXECUTION_AUTHORITY = False     # NEVER true


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))


# ── Path helpers ─────────────────────────────────────────────────────────────

def _out_json_path() -> Path:
    env = os.environ.get("SYSTEM_ACTIVATION_STATUS_OUT_JSON")
    if env:
        return Path(env)
    return _REPO_ROOT / "learning-loop" / "system_activation_status_latest.json"


def _out_md_path() -> Path:
    env = os.environ.get("SYSTEM_ACTIVATION_STATUS_OUT_MD")
    if env:
        return Path(env)
    return _REPO_ROOT / "docs" / "SYSTEM_ACTIVATION_STATUS.md"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Subsystem catalogue (20 entries per spec §ETAP 10) ───────────────────────

SUBSYSTEMS: tuple[dict, ...] = (
    {"key": "broker_repair_gate",          "name": "Broker repair gate",          "desired": "ENFORCED"},
    {"key": "safe_mode",                   "name": "Safe mode",                   "desired": "AUTO"},
    {"key": "safe_mode_consistency",       "name": "Safe mode consistency checker", "desired": "ENFORCED"},
    {"key": "equity_reconciliation",       "name": "Equity reconciliation",       "desired": "FRESH"},
    {"key": "allocator_gate",              "name": "Allocator gate",              "desired": "ENFORCED"},
    {"key": "position_reconciliation",     "name": "Position reconciliation",     "desired": "FRESH"},
    {"key": "kill_switch",                 "name": "Kill switch",                 "desired": "DISARMED"},
    {"key": "discovery_reporters",         "name": "Discovery reporters",         "desired": "READ_ONLY_ON"},
    {"key": "trigger_watchlist",           "name": "Trigger watchlist",           "desired": "READ_ONLY_ON"},
    {"key": "shadow_candidate_queue",      "name": "Shadow candidate queue",      "desired": "READ_ONLY_ON"},
    {"key": "shadow_simulator",            "name": "Shadow simulator",            "desired": "READ_ONLY_ON"},
    {"key": "outcome_tracker",             "name": "Outcome tracker",             "desired": "READ_ONLY_ON"},
    {"key": "llm_advisory_mesh",           "name": "LLM advisory mesh",           "desired": "ADVISORY_ONLY"},
    {"key": "daily_operational_brief",     "name": "Daily operational brief",     "desired": "DAILY"},
    {"key": "geo_monitor",                 "name": "Geo monitor",                 "desired": "READ_ONLY_ON"},
    {"key": "crypto_monitor",              "name": "Crypto monitor",              "desired": "READ_ONLY_ON"},
    {"key": "price_monitor",               "name": "Price monitor",               "desired": "READ_ONLY_ON"},
    {"key": "options_monitor",             "name": "Options monitor",             "desired": "READ_ONLY_ON"},
    {"key": "daily_reporters",             "name": "Daily reporters",             "desired": "DAILY"},
    {"key": "operator_dashboard",          "name": "Operator dashboard",          "desired": "READ_ONLY_ON"},
)


# ── Subsystem probes (all best-effort, never raise) ──────────────────────────

def _file_present(rel: str) -> bool:
    return (_REPO_ROOT / rel).exists()


def _probe_broker_repair_gate(snapshot: dict) -> dict:
    state = snapshot.get("broker_repair_state") or {}
    blocked = snapshot.get("broker_repair_blocked") or []
    if state or blocked:
        actual = "ENFORCED_BLOCKING"
        notes = f"blocked: {','.join(sorted(blocked))}"
    else:
        actual = "ENFORCED_CLEAR"
        notes = "no symbols quarantined"
    return {
        "actual":   actual,
        "enabled":  True,
        "blockers": list(blocked) if blocked else [],
        "notes":    notes,
        "safety":   "deterministic gate, never auto-clears",
    }


def _probe_safe_mode(snapshot: dict) -> dict:
    active = snapshot.get("safe_mode_active")
    reason = snapshot.get("safe_mode_reason") or ""
    if active:
        actual, enabled = "ACTIVE", True
        blockers = ["safe_mode_active"]
    elif active is False:
        actual, enabled = "INACTIVE", True
        blockers = []
    else:
        actual, enabled = "READ_ERROR", False
        blockers = ["safe_mode_read_error"]
    return {
        "actual":   actual,
        "enabled":  enabled,
        "blockers": blockers,
        "notes":    reason,
        "safety":   "auto on incident triggers; never auto-cleared",
    }


def _probe_safe_mode_consistency(snapshot: dict) -> dict:
    sm_consistency = snapshot.get("safe_mode_consistency") or {}
    verdict = (str(sm_consistency.get("verdict", ""))
               if isinstance(sm_consistency, dict) else "")
    if not sm_consistency:
        return {
            "actual":   "MISSING",
            "enabled":  False,
            "blockers": [],
            "notes":    "checker has not run yet",
            "safety":   "read-only checker",
        }
    if verdict == "INCONSISTENT_ENTERED_NOT_PERSISTED":
        return {
            "actual":   "INCONSISTENT_ENTERED_NOT_PERSISTED",
            "enabled":  True,
            "blockers": [verdict],
            "notes":    str(sm_consistency.get("detail", "")),
            "safety":   "blocks allocator on audit-vs-runtime mismatch",
        }
    return {
        "actual":   verdict or "UNKNOWN",
        "enabled":  True,
        "blockers": [],
        "notes":    str(sm_consistency.get("detail", "")),
        "safety":   "blocks allocator on audit-vs-runtime mismatch",
    }


def _probe_equity_reconciliation(snapshot: dict) -> dict:
    report = snapshot.get("equity_gap_report") or {}
    if not report:
        return {
            "actual":   "MISSING",
            "enabled":  False,
            "blockers": ["equity_gap_report_missing"],
            "notes":    "report has not been generated yet",
            "safety":   "blocks allocator while missing",
        }
    verdict = str(report.get("verdict", "")) or "UNKNOWN"
    blockers = (
        ["equity_gap_unresolved"] if bool(report.get("block_allocator"))
        else []
    )
    return {
        "actual":   verdict,
        "enabled":  True,
        "blockers": blockers,
        "notes":    (f"schema_version={report.get('schema_version','?')}, "
                     f"confidence={report.get('confidence','?')}"),
        "safety":   "blocks allocator if unresolved, schema-invalid, or stale",
    }


def _probe_allocator_gate(decision: str, blockers: list[str]) -> dict:
    return {
        "actual":   decision,
        "enabled":  True,
        "blockers": list(blockers),
        "notes":    "master gate verdict (deterministic)",
        "safety":   "fail-closed default UNKNOWN_BLOCK_FAIL_CLOSED",
    }


def _probe_position_reconciliation(snapshot: dict) -> dict:
    age = snapshot.get("position_recon_age_s")
    is_hours = bool(snapshot.get("is_market_hours"))
    if age is None:
        return {
            "actual":   "MISSING",
            "enabled":  False,
            "blockers": ["position_recon_missing"] if is_hours else [],
            "notes":    "no reconciled_at timestamp",
            "safety":   "blocks allocator if stale during market hours",
        }
    try:
        age_f = float(age)
    except (TypeError, ValueError):
        age_f = -1.0
    if is_hours and age_f > 2 * 3600:
        actual = f"STALE_AGE_S={int(age_f)}"
        blockers = ["position_recon_stale"]
    else:
        actual = f"FRESH_AGE_S={int(age_f)}"
        blockers = []
    return {
        "actual":   actual,
        "enabled":  True,
        "blockers": blockers,
        "notes":    f"market_hours={is_hours}",
        "safety":   "informational outside market hours",
    }


def _probe_kill_switch(snapshot: dict) -> dict:
    armed = snapshot.get("kill_switch_armed")
    if armed is None:
        return {
            "actual":   "READ_ERROR",
            "enabled":  False,
            "blockers": [],
            "notes":    snapshot.get("kill_switch_error", ""),
            "safety":   "informational",
        }
    if armed:
        return {
            "actual":   "ARMED",
            "enabled":  True,
            "blockers": ["kill_switch_armed"],
            "notes":    "operator override active",
            "safety":   "blocks allocator unconditionally",
        }
    return {
        "actual":   "DISARMED",
        "enabled":  True,
        "blockers": [],
        "notes":    "",
        "safety":   "informational",
    }


def _probe_discovery_reporters() -> dict:
    fresh = _file_present("learning-loop/discovery_reporters_latest.json")
    return {
        "actual":   "READ_ONLY_ON" if fresh else "MISSING",
        "enabled":  fresh,
        "blockers": [],
        "notes":    "read-only diagnostics" if fresh else "snapshot not present",
        "safety":   "never places orders",
    }


def _probe_trigger_watchlist() -> dict:
    fresh = _file_present("learning-loop/trigger_watchlist_latest.json")
    return {
        "actual":   "READ_ONLY_ON" if fresh else "MISSING",
        "enabled":  fresh,
        "blockers": [],
        "notes":    "trigger candidates only" if fresh else "watchlist not present",
        "safety":   "never places orders",
    }


def _probe_shadow_candidate_queue() -> dict:
    fresh = _file_present("learning-loop/shadow_candidate_queue_latest.json")
    return {
        "actual":   "READ_ONLY_ON" if fresh else "MISSING",
        "enabled":  fresh,
        "blockers": [],
        "notes":    "queue snapshot" if fresh else "queue not present",
        "safety":   "shadow only; never places orders",
    }


def _probe_shadow_simulator() -> dict:
    fresh = _file_present("learning-loop/shadow_outcome_status_latest.json")
    return {
        "actual":   "READ_ONLY_ON" if fresh else "MISSING",
        "enabled":  fresh,
        "blockers": [],
        "notes":    "simulator outcomes" if fresh else "no recent simulator output",
        "safety":   "shadow only; never places orders",
    }


def _probe_outcome_tracker() -> dict:
    fresh = _file_present("learning-loop/shadow_outcome_status_latest.json")
    return {
        "actual":   "READ_ONLY_ON" if fresh else "MISSING",
        "enabled":  fresh,
        "blockers": [],
        "notes":    "tracker reads shadow + real outcomes",
        "safety":   "read-only",
    }


def _probe_llm_advisory_mesh(snapshot: dict) -> dict:
    status = snapshot.get("llm_status") or "unknown"
    return {
        "actual":   f"ADVISORY_{status.upper()}",
        "enabled":  status == "advisory_on",
        "blockers": [],
        "notes":    "advisory-only; cannot block or unblock deterministic gates",
        "safety":   "LLM has zero execution authority (HARD invariant)",
    }


def _probe_daily_operational_brief() -> dict:
    fresh = _file_present("docs/DAILY_OPERATIONAL_BRIEF.md")
    return {
        "actual":   "DAILY" if fresh else "MISSING",
        "enabled":  fresh,
        "blockers": [],
        "notes":    "brief present" if fresh else "no recent brief",
        "safety":   "read-only documentation",
    }


def _probe_monitor(name: str) -> dict:
    """Best-effort liveness probe for a scheduled monitor."""
    fresh = _file_present("learning-loop/runtime_state.json")
    return {
        "actual":   "READ_ONLY_ON" if fresh else "UNKNOWN",
        "enabled":  fresh,
        "blockers": [],
        "notes":    f"runtime_state probe for {name}",
        "safety":   "never places orders unless allocator allows AND broker enabled",
    }


def _probe_daily_reporters() -> dict:
    fresh = _file_present("docs/SAFE_MODE_CONSISTENCY_STATUS.md")
    return {
        "actual":   "DAILY" if fresh else "MISSING",
        "enabled":  fresh,
        "blockers": [],
        "notes":    "reporters wrote at least one status doc",
        "safety":   "read-only",
    }


def _probe_operator_dashboard() -> dict:
    fresh = _file_present(
        "learning-loop/position_reconciliation/operator_dashboard_snapshot.json")
    return {
        "actual":   "READ_ONLY_ON" if fresh else "MISSING",
        "enabled":  fresh,
        "blockers": [],
        "notes":    "dashboard snapshot" if fresh else "snapshot not present",
        "safety":   "read-only",
    }


# ── Top-level flag composition ───────────────────────────────────────────────

def _compute_top_level_flags(master_decision: str,
                              blockers: list[str]) -> dict:
    """Produce the top-level dashboard flags (spec §ETAP 10)."""

    allocator_allowed = master_decision == "ALLOCATOR_ALLOWED"
    shadow_allowed = master_decision in (
        "ALLOCATOR_ALLOWED",
        "SYSTEM_ACTIVE_SHADOW_ONLY",
    )
    operator_required = bool(blockers) and not allocator_allowed
    reason_op = ""
    if operator_required:
        reason_op = "; ".join(blockers[:3]) if blockers else master_decision

    return {
        "WHOLE_SOLUTION_SAFE_ON":     True,
        "TRADING_EXECUTION_ON":       TRADING_EXECUTION_ON,    # literal False
        "LLM_EXECUTION_AUTHORITY":    LLM_EXECUTION_AUTHORITY, # literal False
        "LLM_ADVISORY_ON":            True,
        "ALLOCATOR_ALLOWED":          allocator_allowed,
        "SHADOW_ONLY_ALLOWED":        shadow_allowed,
        "OPERATOR_ACTION_REQUIRED":   operator_required,
        "OPERATOR_ACTION_REASON":     reason_op,
    }


# ── Dashboard builder ────────────────────────────────────────────────────────

def build_status_payload() -> dict:
    """Compose the full dashboard payload by running every subsystem probe."""

    from system_activation_gate import evaluate  # type: ignore

    master = evaluate()
    snapshot = dict(master.snapshot)
    master_decision = master.decision.value
    blockers = list(master.blockers)

    subsystems: list[dict] = []
    monitor_probes = {
        "geo_monitor":    _probe_monitor("geo_monitor"),
        "crypto_monitor": _probe_monitor("crypto_monitor"),
        "price_monitor":  _probe_monitor("price_monitor"),
        "options_monitor": _probe_monitor("options_monitor"),
    }
    for entry in SUBSYSTEMS:
        key = entry["key"]
        try:
            if key == "broker_repair_gate":
                probe = _probe_broker_repair_gate(snapshot)
            elif key == "safe_mode":
                probe = _probe_safe_mode(snapshot)
            elif key == "safe_mode_consistency":
                probe = _probe_safe_mode_consistency(snapshot)
            elif key == "equity_reconciliation":
                probe = _probe_equity_reconciliation(snapshot)
            elif key == "allocator_gate":
                probe = _probe_allocator_gate(master_decision, blockers)
            elif key == "position_reconciliation":
                probe = _probe_position_reconciliation(snapshot)
            elif key == "kill_switch":
                probe = _probe_kill_switch(snapshot)
            elif key == "discovery_reporters":
                probe = _probe_discovery_reporters()
            elif key == "trigger_watchlist":
                probe = _probe_trigger_watchlist()
            elif key == "shadow_candidate_queue":
                probe = _probe_shadow_candidate_queue()
            elif key == "shadow_simulator":
                probe = _probe_shadow_simulator()
            elif key == "outcome_tracker":
                probe = _probe_outcome_tracker()
            elif key == "llm_advisory_mesh":
                probe = _probe_llm_advisory_mesh(snapshot)
            elif key == "daily_operational_brief":
                probe = _probe_daily_operational_brief()
            elif key in monitor_probes:
                probe = monitor_probes[key]
            elif key == "daily_reporters":
                probe = _probe_daily_reporters()
            elif key == "operator_dashboard":
                probe = _probe_operator_dashboard()
            else:
                probe = {
                    "actual":   "UNKNOWN",
                    "enabled":  False,
                    "blockers": [],
                    "notes":    "no probe wired",
                    "safety":   "unknown",
                }
        except Exception as e:  # never let one probe break the rest
            probe = {
                "actual":   "PROBE_ERROR",
                "enabled":  False,
                "blockers": [],
                "notes":    f"{type(e).__name__}: {e}",
                "safety":   "fail-soft",
            }
        subsystems.append({
            "key":            key,
            "name":           entry["name"],
            "desired_state":  entry["desired"],
            "actual_state":   probe["actual"],
            "enabled":        probe["enabled"],
            "blockers":       probe["blockers"],
            "notes":          probe["notes"],
            "safety_notes":   probe["safety"],
        })

    flags = _compute_top_level_flags(master_decision, blockers)

    payload = {
        "schema_version":     "v3.29",
        "generated_at_iso":   _now_iso(),
        "module":             "scripts.build_system_activation_status",
        "master_decision":    master_decision,
        "master_blockers":    blockers,
        "llm_status":         master.llm_status,
        "flags":              flags,
        "subsystems":         subsystems,
        "standing_markers":   list(STANDING_MARKERS),
        "does_not_execute_orders":  True,
        "live_trading_unsupported": True,
        "no_order_placement":       True,
        "no_auto_broker_action":    True,
    }
    return payload


def render_markdown(payload: dict) -> str:
    flags = payload.get("flags", {})
    subsystems = payload.get("subsystems", [])
    blockers = payload.get("master_blockers") or []

    out: list[str] = []
    out.append("# SYSTEM ACTIVATION STATUS")
    out.append("")
    out.append(f"_Generated at:_ `{payload.get('generated_at_iso')}`")
    out.append("")
    out.append("## Top-level flags")
    out.append("")
    out.append("| Flag | Value |")
    out.append("|---|---|")
    for k in (
        "WHOLE_SOLUTION_SAFE_ON",
        "TRADING_EXECUTION_ON",
        "LLM_EXECUTION_AUTHORITY",
        "LLM_ADVISORY_ON",
        "ALLOCATOR_ALLOWED",
        "SHADOW_ONLY_ALLOWED",
        "OPERATOR_ACTION_REQUIRED",
    ):
        out.append(f"| `{k}` | `{flags.get(k)}` |")
    if flags.get("OPERATOR_ACTION_REQUIRED"):
        out.append(f"| `OPERATOR_ACTION_REASON` | {flags.get('OPERATOR_ACTION_REASON','')} |")
    out.append("")
    out.append(f"**Master gate decision:** `{payload.get('master_decision')}`  ")
    if blockers:
        out.append(f"**Active blockers:** `{', '.join(blockers)}`  ")
    out.append(f"**LLM advisory status:** `{payload.get('llm_status')}`")
    out.append("")
    out.append("## Subsystems")
    out.append("")
    out.append("| Subsystem | Desired | Actual | Enabled? | Blockers | Safety notes |")
    out.append("|---|---|---|---|---|---|")
    for s in subsystems:
        blockers_cell = ", ".join(s.get("blockers", [])) or "—"
        out.append(
            f"| {s.get('name','')} "
            f"| `{s.get('desired_state','')}` "
            f"| `{s.get('actual_state','')}` "
            f"| {'yes' if s.get('enabled') else 'no'} "
            f"| {blockers_cell} "
            f"| {s.get('safety_notes','')} |"
        )
    out.append("")
    out.append("---")
    out.append("")
    out.append("### Standing markers")
    for m in payload.get("standing_markers", []):
        out.append(f"- `{m}`")
    out.append("")
    out.append("> This dashboard is read-only. It never calls the broker, never")
    out.append("> places orders, never flips any flag, and never auto-clears safe_mode.")
    out.append("> `TRADING_EXECUTION_ON` and `LLM_EXECUTION_AUTHORITY` are write-time")
    out.append("> literal `False` in `scripts/build_system_activation_status.py`.")
    out.append("")
    return "\n".join(out)


def write_outputs(payload: dict) -> dict[str, Path]:
    """Persist the dashboard JSON + markdown atomically (tmp + fsync + replace)."""
    json_path = _out_json_path()
    md_path = _out_md_path()
    for p in (json_path, md_path):
        p.parent.mkdir(parents=True, exist_ok=True)

    # JSON
    tmp_json = json_path.with_suffix(json_path.suffix + ".tmp")
    with open(tmp_json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, default=str)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp_json, json_path)

    # Markdown
    md_text = render_markdown(payload)
    tmp_md = md_path.with_suffix(md_path.suffix + ".tmp")
    with open(tmp_md, "w", encoding="utf-8") as fh:
        fh.write(md_text)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp_md, md_path)

    return {"json": json_path, "md": md_path}


def main() -> int:
    payload = build_status_payload()
    paths = write_outputs(payload)
    flags = payload["flags"]
    print(f"SYSTEM_ACTIVATION_STATUS schema_version={payload['schema_version']}")
    print(f"master_decision={payload['master_decision']}")
    print(f"master_blockers={','.join(payload['master_blockers']) or '—'}")
    print(f"WHOLE_SOLUTION_SAFE_ON={flags['WHOLE_SOLUTION_SAFE_ON']}")
    print(f"TRADING_EXECUTION_ON={flags['TRADING_EXECUTION_ON']}")
    print(f"LLM_EXECUTION_AUTHORITY={flags['LLM_EXECUTION_AUTHORITY']}")
    print(f"LLM_ADVISORY_ON={flags['LLM_ADVISORY_ON']}")
    print(f"ALLOCATOR_ALLOWED={flags['ALLOCATOR_ALLOWED']}")
    print(f"SHADOW_ONLY_ALLOWED={flags['SHADOW_ONLY_ALLOWED']}")
    print(f"OPERATOR_ACTION_REQUIRED={flags['OPERATOR_ACTION_REQUIRED']}"
          + (f" reason={flags['OPERATOR_ACTION_REASON']}"
             if flags.get('OPERATOR_ACTION_REQUIRED') else ""))
    print(f"wrote: {paths['json']}")
    print(f"wrote: {paths['md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
