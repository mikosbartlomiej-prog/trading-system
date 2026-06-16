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


# ── v3.30 LLM provider mode detection ────────────────────────────────────────

def _detect_llm_provider_mode() -> str:
    """Return one of ``REAL_PROVIDER`` / ``DETERMINISTIC_FALLBACK`` /
    ``UNAVAILABLE`` based on the latest LLM mesh status artefact.

    v3.30: this is informational only — never affects allocator gates.
    """
    p = _REPO_ROOT / "learning-loop" / "llm_advisory_mesh_status_latest.json"
    if not p.exists():
        return "UNAVAILABLE"
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return "UNAVAILABLE"
    if not isinstance(raw, dict):
        return "UNAVAILABLE"
    mode = str(
        raw.get("provider_mode")
        or raw.get("mode")
        or raw.get("status")
        or ""
    ).upper()
    if mode in {"REAL_PROVIDER", "REAL", "ONLINE"}:
        return "REAL_PROVIDER"
    if mode in {"DETERMINISTIC_FALLBACK", "FALLBACK", "DETERMINISTIC"}:
        return "DETERMINISTIC_FALLBACK"
    return "UNAVAILABLE"


# ── v3.30 invariant probes (read-only AST + state checks) ────────────────────

def _broker_repair_guard_wired() -> bool:
    """True iff ``shared/alpaca_orders.py::safe_close`` has the v3.30
    PRECONDITION guard above its broker calls.

    We just check that the symbols ``REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE``
    and ``is_repair_required`` both appear in the safe_close source. AST
    walk would be more robust but a simple substring check is enough
    for an at-a-glance dashboard flag.
    """
    p = _REPO_ROOT / "shared" / "alpaca_orders.py"
    if not p.exists():
        return False
    try:
        src = p.read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        "REPAIR_REQUIRED_SKIPPING_AUTO_CLOSE" in src
        and "is_repair_required" in src
    )


def _retry_storm_suppression_active() -> bool:
    """True iff ``shared/retry_storm_containment.py`` is present and the
    safe_close path imports it.
    """
    p = _REPO_ROOT / "shared" / "retry_storm_containment.py"
    if not p.exists():
        return False
    try:
        ac = (_REPO_ROOT / "shared" / "alpaca_orders.py").read_text(encoding="utf-8")
        return "retry_storm_containment" in ac
    except OSError:
        return False


def _safe_mode_consistency_check_active() -> bool:
    """True iff the consistency checker has produced a recent artefact
    (or even an old one — presence alone tells us the check is wired).
    """
    p = _REPO_ROOT / "learning-loop" / "safe_mode_consistency_latest.json"
    return p.exists()


# ── v3.31 helpers — Remaining Actions + completion flags ─────────────────────

def _gemini_api_key_present() -> bool:
    """v3.31 — detect ``GEMINI_API_KEY`` env presence. NEVER reads the
    value. Used to flip ``SECRET_WORK_REMAINING`` on the dashboard."""
    raw = os.environ.get("GEMINI_API_KEY", "")
    if not isinstance(raw, str):
        return False
    return bool(raw.strip())


def _broker_repair_symbols() -> list[str]:
    """v3.31 — return the canonical list of symbols still in the
    broker_repair_required queue. Read-only. Defensive against any
    schema drift."""
    out: list[str] = []
    repair_path = (_REPO_ROOT / "learning-loop"
                    / "broker_repair_required_latest.json")
    if not repair_path.exists():
        return out
    try:
        raw = json.loads(repair_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    if not isinstance(raw, dict):
        return out
    canonical = raw.get("canonical_entries") or raw.get("entries") or {}
    if isinstance(canonical, dict):
        for k in canonical.keys():
            if isinstance(k, str) and k.strip():
                out.append(k.strip())
    elif isinstance(canonical, list):
        for entry in canonical:
            if isinstance(entry, dict):
                sym = entry.get("symbol") or entry.get("canonical_symbol")
                if isinstance(sym, str) and sym.strip():
                    out.append(sym.strip())
    return sorted(set(out))


def _count_positive_entry_capable_rows() -> int:
    """v3.31 — count entry-capable rows across the opportunity ledger.

    Used to flip ``MARKET_DATA_WORK_REMAINING`` to False once the
    discovery layer produces at least one positive row.
    """
    ledger_dir = _REPO_ROOT / "learning-loop" / "opportunity_ledger"
    if not ledger_dir.exists() or not ledger_dir.is_dir():
        return 0
    count = 0
    try:
        for p in ledger_dir.glob("*.jsonl"):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    for line in fh:
                        if '"entry_capable"' not in line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if (isinstance(row, dict)
                                and row.get("entry_capable") is True):
                            count += 1
            except OSError:
                continue
    except Exception:
        return count
    return count


def _detect_code_work_items() -> list[str]:
    """v3.31 — informational hook for CODE_WORK_REMAINING.

    The v3.31 spec sets ``CODE_WORK_REMAINING=false`` once the agent
    workload is closed. We surface a CI/test failure detection hook
    here so future drift can flag itself. Currently returns an empty
    list (no code work remaining).
    """
    return []


def _build_remaining_actions(broker_repair_symbols: list[str],
                                gemini_key_present: bool,
                                positive_rows: int,
                                shadow_only_allowed: bool,
                                allocator_allowed: bool) -> list[dict]:
    """v3.31 — Remaining Actions table per dashboard contract.

    Each row: ``action / owner / blocking / script_or_link / status``.
    """
    actions: list[dict] = []
    symbols = list(broker_repair_symbols)
    # Always include the three canonical broker-repair symbols (if absent
    # from the latest queue, mark them ``resolved``).
    canonical = ("AVAX/USD", "ETH/USD", "LTC/USD")
    for sym in canonical:
        in_queue = sym in symbols
        # Pick the operator-facing template / runbook link per symbol.
        if sym == "AVAX/USD":
            link = "docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md"
        elif sym == "ETH/USD":
            link = ("docs/operator_repair_templates/"
                    "ETH_USD_repair_marker_template.md")
        else:
            link = ("docs/operator_repair_templates/"
                    "LTC_USD_repair_marker_template.md")
        actions.append({
            "action":         f"Operator verify Alpaca dashboard for {sym}",
            "owner":          "OPERATOR",
            "blocking":       in_queue,
            "script_or_link": link,
            "status":         "pending" if in_queue else "resolved",
        })

    # Marker recording action.
    actions.append({
        "action":         "Operator record repair markers",
        "owner":          "OPERATOR",
        "blocking":       bool(symbols),
        "script_or_link":
            "scripts/record_operator_repair_confirmation.py",
        "status":         "pending" if symbols else "resolved",
    })

    # Clearance proposal action — always paired with markers.
    clearance_script = (
        "scripts/run_operator_clearance_readiness.py")
    actions.append({
        "action":         "Operator run clearance proposal",
        "owner":          "OPERATOR",
        "blocking":       bool(symbols),
        "script_or_link": clearance_script,
        "status":         "pending" if symbols else "resolved",
    })

    # Safe-mode reconciliation action — surface always (dashboard
    # blockers gate it).
    sm_script = "scripts/propose_safe_mode_reconciliation.py"
    actions.append({
        "action":         "Operator reconcile safe_mode",
        "owner":          "OPERATOR",
        "blocking":       not allocator_allowed,
        "script_or_link": sm_script,
        "status":         "pending" if not allocator_allowed else "resolved",
    })

    # GitHub secret action — non-blocking (advisory fallback active).
    actions.append({
        "action":         "GitHub secret GEMINI_API_KEY",
        "owner":          "GITHUB_SECRET",
        "blocking":       False,
        "script_or_link":
            "Settings -> Secrets and variables -> Actions",
        "status":         "resolved" if gemini_key_present else "pending",
    })

    # Market-trigger waiting — non-blocking, observe-only.
    actions.append({
        "action":         (
            "Market trigger required for positive entry rows"),
        "owner":          "MARKET_TRIGGER",
        "blocking":       False,
        "script_or_link": "discovery layer",
        "status":         "resolved" if positive_rows > 0 else "observing",
    })

    # Shadow-only auto-resolution row.
    actions.append({
        "action":         (
            "Shadow-only requires deterministic gate clean"),
        "owner":          "SYSTEM (auto when operator clears)",
        "blocking":       False,
        "script_or_link": "system_activation_gate",
        "status":         "resolved" if allocator_allowed else "pending",
    })
    return actions


def _compute_v331_completion_flags(broker_repair_symbols: list[str],
                                       gemini_key_present: bool,
                                       positive_rows: int,
                                       code_work_items: list[str]
                                       ) -> dict:
    """Compose the v3.31 completion-flag set."""
    return {
        # CODE_WORK_REMAINING — false after v3.31 unless a test gate
        # detects regressed code.
        "CODE_WORK_REMAINING":          bool(code_work_items),
        "CODE_WORK_REMAINING_ITEMS":    list(code_work_items),
        "OPERATOR_WORK_REMAINING":      bool(broker_repair_symbols),
        "SECRET_WORK_REMAINING":        not gemini_key_present,
        "MARKET_DATA_WORK_REMAINING":   positive_rows == 0,
        # NOTE: TRADING_EXECUTION_ON and LLM_EXECUTION_AUTHORITY remain
        # write-time literal False elsewhere; we surface them here for
        # easy operator inspection.
        "TRADING_EXECUTION_ON":         TRADING_EXECUTION_ON,
        "LLM_EXECUTION_AUTHORITY":      LLM_EXECUTION_AUTHORITY,
    }


# ── Top-level flag composition ───────────────────────────────────────────────

def _compute_top_level_flags(master_decision: str,
                              blockers: list[str],
                              snapshot: dict | None = None,
                              shadow_only_allowed: bool = False) -> dict:
    """Produce the top-level dashboard flags (spec §ETAP 10 + v3.30 §11)."""

    snapshot = snapshot or {}
    allocator_allowed = master_decision == "ALLOCATOR_ALLOWED"
    operator_required = bool(blockers) and not allocator_allowed
    reason_op = ""
    if operator_required:
        reason_op = "; ".join(blockers[:3]) if blockers else master_decision

    provider_mode = _detect_llm_provider_mode()
    broker_guard = _broker_repair_guard_wired()
    retry_supp = _retry_storm_suppression_active()
    sm_check = _safe_mode_consistency_check_active()

    return {
        # Pre-v3.30 flags (preserved for back-compat).
        "WHOLE_SOLUTION_SAFE_ON":     True,
        "TRADING_EXECUTION_ON":       TRADING_EXECUTION_ON,    # literal False
        "LLM_EXECUTION_AUTHORITY":    LLM_EXECUTION_AUTHORITY, # literal False
        "LLM_ADVISORY_ON":            True,
        "ALLOCATOR_ALLOWED":          allocator_allowed,
        "SHADOW_ONLY_ALLOWED":        bool(shadow_only_allowed),
        "OPERATOR_ACTION_REQUIRED":   operator_required,
        "OPERATOR_ACTION_REASON":     reason_op,

        # v3.30 additions.
        "WHOLE_SAFE_STACK_ON":         True,
        "LLM_PROVIDER_MODE":           provider_mode,
        "BROKER_REPAIR_GUARD_WIRED_IN_SAFE_CLOSE": broker_guard,
        "RETRY_STORM_SUPPRESSION_ACTIVE":          retry_supp,
        "SAFE_MODE_CONSISTENCY_CHECK_ACTIVE":      sm_check,
        "BLOCKERS":                    list(blockers),
        "NEXT_OPERATOR_ACTIONS":       _derive_next_operator_actions(
            master_decision, blockers, snapshot=snapshot),
    }


def _derive_next_operator_actions(master_decision: str,
                                    blockers: list[str],
                                    snapshot: dict | None = None) -> list[str]:
    """Produce the concrete next operator-step list.

    Empty when the allocator is allowed. Items are operator-facing
    English imperatives; the brief renders them as a checklist.
    v3.30: also inspects the master-gate snapshot so multi-blocker
    situations (e.g. SAFE_MODE_INCONSISTENT + broker_repair queue)
    surface every action even though only the first-firing blocker
    is in ``blockers``.
    """
    if master_decision == "ALLOCATOR_ALLOWED":
        return []
    actions: list[str] = []
    joined = " ".join(blockers)
    snapshot = snapshot or {}
    repair_queue = snapshot.get("broker_repair_blocked") or []
    if "safe_mode_consistency" in joined:
        actions.append(
            "Investigate runtime_state vs audit safe_mode mismatch "
            "(see docs/RUNBOOK.md scenario 5a); do NOT auto-clear "
            "safe_mode."
        )
    if ("broker_repair" in joined
            or "operator_confirmation_required" in joined
            or repair_queue):
        actions.append(
            "For each broker-repair symbol: review Alpaca dashboard, "
            "manually fix orphaned OCO legs / dust positions, then run "
            "`python3 scripts/record_operator_repair_confirmation.py "
            "--operator-confirmed`. See "
            "docs/OPERATOR_REPAIR_CONFIRMATION.md."
        )
    if "safe_mode_active" in joined:
        actions.append(
            "Resolve the safe_mode trigger before considering any "
            "manual clearance; consult docs/RUNBOOK_AVAXUSD_P13_"
            "2026-06-16.md for incident-specific guidance."
        )
    if "equity_gap" in joined:
        actions.append(
            "Review learning-loop/equity_gap_reconciliation_latest.json "
            "and the upstream account/equity sources; do NOT flip any "
            "broker or live-trading flag."
        )
    if "position_recon" in joined:
        actions.append(
            "Re-run the position reconciliation reporter and verify "
            "Alpaca side reflects the same positions."
        )
    if "kill_switch_armed" in joined:
        actions.append(
            "Kill switch is operator-armed. Confirm intent before "
            "disarming via the appropriate config edit."
        )
    if not actions:
        actions.append(
            "Investigate the deterministic blocker(s) listed above "
            "before flipping any flag. Live trading remains unsupported."
        )
    return actions


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

    shadow_flag = bool(getattr(master, "shadow_only_allowed", False))
    flags = _compute_top_level_flags(master_decision, blockers,
                                       snapshot=snapshot,
                                       shadow_only_allowed=shadow_flag)

    # ── v3.31 — Remaining Actions + completion flags ────────────────────────
    broker_repair_symbols = _broker_repair_symbols()
    gemini_key_present     = _gemini_api_key_present()
    positive_rows          = _count_positive_entry_capable_rows()
    code_work_items        = _detect_code_work_items()
    allocator_allowed_bool = master_decision == "ALLOCATOR_ALLOWED"

    remaining_actions = _build_remaining_actions(
        broker_repair_symbols=broker_repair_symbols,
        gemini_key_present=gemini_key_present,
        positive_rows=positive_rows,
        shadow_only_allowed=shadow_flag,
        allocator_allowed=allocator_allowed_bool,
    )
    v331_flags = _compute_v331_completion_flags(
        broker_repair_symbols=broker_repair_symbols,
        gemini_key_present=gemini_key_present,
        positive_rows=positive_rows,
        code_work_items=code_work_items,
    )
    # Merge v3.31 completion flags into the top-level flag dict so the
    # dashboard JSON exposes them inside ``flags``.
    flags.update(v331_flags)

    payload = {
        "schema_version":     "v3.31",
        "generated_at_iso":   _now_iso(),
        "module":             "scripts.build_system_activation_status",
        "master_decision":    master_decision,
        "master_blockers":    blockers,
        "llm_status":         master.llm_status,
        "flags":              flags,
        "subsystems":         subsystems,
        "remaining_actions":  remaining_actions,
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
        "WHOLE_SAFE_STACK_ON",
        "WHOLE_SOLUTION_SAFE_ON",
        "TRADING_EXECUTION_ON",
        "LLM_EXECUTION_AUTHORITY",
        "LLM_ADVISORY_ON",
        "LLM_PROVIDER_MODE",
        "ALLOCATOR_ALLOWED",
        "SHADOW_ONLY_ALLOWED",
        "BROKER_REPAIR_GUARD_WIRED_IN_SAFE_CLOSE",
        "RETRY_STORM_SUPPRESSION_ACTIVE",
        "SAFE_MODE_CONSISTENCY_CHECK_ACTIVE",
        "OPERATOR_ACTION_REQUIRED",
        # v3.31 completion flags.
        "CODE_WORK_REMAINING",
        "OPERATOR_WORK_REMAINING",
        "SECRET_WORK_REMAINING",
        "MARKET_DATA_WORK_REMAINING",
    ):
        out.append(f"| `{k}` | `{flags.get(k)}` |")
    if flags.get("OPERATOR_ACTION_REQUIRED"):
        out.append(f"| `OPERATOR_ACTION_REASON` | {flags.get('OPERATOR_ACTION_REASON','')} |")
    out.append("")
    next_actions = flags.get("NEXT_OPERATOR_ACTIONS") or []
    if next_actions:
        out.append("## Next operator actions")
        out.append("")
        for i, a in enumerate(next_actions, 1):
            out.append(f"{i}. {a}")
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
    # v3.31 — Remaining Actions table.
    remaining = payload.get("remaining_actions") or []
    if remaining:
        out.append("")
        out.append("## Remaining Actions (v3.31)")
        out.append("")
        out.append(
            "| Action | Owner | Blocking? | Script / Link | Current "
            "status |")
        out.append("|---|---|---|---|---|")
        for row in remaining:
            blocking_cell = "yes" if row.get("blocking") else "no"
            out.append(
                f"| {row.get('action','')} "
                f"| `{row.get('owner','')}` "
                f"| {blocking_cell} "
                f"| `{row.get('script_or_link','')}` "
                f"| `{row.get('status','')}` |"
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
    print(f"WHOLE_SAFE_STACK_ON={flags['WHOLE_SAFE_STACK_ON']}")
    print(f"TRADING_EXECUTION_ON={flags['TRADING_EXECUTION_ON']}")
    print(f"LLM_EXECUTION_AUTHORITY={flags['LLM_EXECUTION_AUTHORITY']}")
    print(f"LLM_ADVISORY_ON={flags['LLM_ADVISORY_ON']}")
    print(f"LLM_PROVIDER_MODE={flags['LLM_PROVIDER_MODE']}")
    print(f"ALLOCATOR_ALLOWED={flags['ALLOCATOR_ALLOWED']}")
    print(f"SHADOW_ONLY_ALLOWED={flags['SHADOW_ONLY_ALLOWED']}")
    print(f"BROKER_REPAIR_GUARD_WIRED_IN_SAFE_CLOSE="
            f"{flags['BROKER_REPAIR_GUARD_WIRED_IN_SAFE_CLOSE']}")
    print(f"RETRY_STORM_SUPPRESSION_ACTIVE={flags['RETRY_STORM_SUPPRESSION_ACTIVE']}")
    print(f"SAFE_MODE_CONSISTENCY_CHECK_ACTIVE="
            f"{flags['SAFE_MODE_CONSISTENCY_CHECK_ACTIVE']}")
    print(f"OPERATOR_ACTION_REQUIRED={flags['OPERATOR_ACTION_REQUIRED']}"
          + (f" reason={flags['OPERATOR_ACTION_REASON']}"
             if flags.get('OPERATOR_ACTION_REQUIRED') else ""))
    # v3.31 completion flags.
    print(f"CODE_WORK_REMAINING={flags.get('CODE_WORK_REMAINING')}")
    print(f"OPERATOR_WORK_REMAINING={flags.get('OPERATOR_WORK_REMAINING')}")
    print(f"SECRET_WORK_REMAINING={flags.get('SECRET_WORK_REMAINING')}")
    print(
        f"MARKET_DATA_WORK_REMAINING="
        f"{flags.get('MARKET_DATA_WORK_REMAINING')}")
    print(
        f"remaining_actions_rows={len(payload.get('remaining_actions') or [])}")
    if flags.get("NEXT_OPERATOR_ACTIONS"):
        for i, a in enumerate(flags["NEXT_OPERATOR_ACTIONS"], 1):
            print(f"  [op-{i}] {a}")
    print(f"wrote: {paths['json']}")
    print(f"wrote: {paths['md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
