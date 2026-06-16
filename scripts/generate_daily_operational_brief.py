#!/usr/bin/env python3
"""v3.30 (2026-06-16) — Daily operational brief (truth-first).

Single-page operator-readable digest. v3.30 close-loop rewrite:

* TOP BANNER (RED / ORANGE / YELLOW / GREEN) surfaces the current
  truth at-a-glance, BEFORE any narrative.
* Every numeric claim cites the artefact path it came from.
* "What changed since yesterday" diffs the latest dashboard vs the
  sidecar snapshot from the previous day.
* "What operator must do" emits a numbered action list whenever the
  master gate is NOT in ALLOCATOR_ALLOWED.
* LLM advisory section is explicitly marked "advisory only —
  does not override deterministic gates".

The brief refuses to repeat unverified figures (the "92 %" / "18 LLM
agents" / "80-day failure" claims from the original v3.29 narrative
are flagged ``CLAIM_UNSUPPORTED`` unless an artefact backs them up).

Outputs
-------
- ``learning-loop/daily_operational_brief_latest.json``
- ``docs/DAILY_OPERATIONAL_BRIEF.md``

HARD SAFETY
-----------
- NEVER imports ``shared.alpaca_orders`` or ``alpaca_orders``.
- NEVER imports any broker SDK.
- NEVER makes a network call.
- NEVER mutates state.json or runtime_state.json.
- NEVER flips any flag.
- NEVER submits orders, never cancels orders, never closes positions.

Standing markers footer is always present.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

LATEST_JSON_PATH = (REPO_ROOT / "learning-loop"
                     / "daily_operational_brief_latest.json")
LATEST_MD_PATH   = REPO_ROOT / "docs" / "DAILY_OPERATIONAL_BRIEF.md"

STANDING_MARKERS = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER",
    "LLM_ADVISORY_ONLY",
    "TRADING_EXECUTION_ON=false",
)

CLAIM_UNSUPPORTED = "CLAIM_UNSUPPORTED"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _read_json(rel: str) -> dict | None:
    p = REPO_ROOT / rel
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _cite(value: Any, source: str) -> str:
    """Render a numeric / factual value with a source citation."""
    if value is None or value == "":
        return f"`{CLAIM_UNSUPPORTED}` [source: `{source}` missing]"
    return f"`{value}` [source: `{source}`]"


def _system_activation() -> dict:
    """Best-effort: master gate verdict. Fail-soft to UNKNOWN."""
    try:
        try:
            from system_activation_gate import evaluate  # type: ignore
        except ImportError:
            from shared.system_activation_gate import evaluate  # type: ignore
        return evaluate().to_dict()
    except Exception as e:
        return {
            "decision": "UNKNOWN",
            "reason":   f"system_activation_read_error: "
                         f"{type(e).__name__}: {e}",
            "shadow_only_allowed": False,
            "shadow_permitted":    False,
            "snapshot":            {},
            "blockers":            [],
        }


# ── Banner classification ────────────────────────────────────────────────────

def _classify_banner(sa: dict, dash_flags: dict | None) -> tuple[str, str, str]:
    """Return ``(color, headline, sub_headline)`` for the top banner.

    Precedence (first match wins):

      1. retry storm active in last hour → RED.
      2. broker repair queue non-empty   → ORANGE.
      3. allocator blocked (other reason) → YELLOW.
      4. allocator allowed                → GREEN.
      5. fall-through                     → YELLOW (UNKNOWN treated as
         blocked because the gate could not verify its state).
    """
    snap = sa.get("snapshot") or {}
    decision = sa.get("decision") or "UNKNOWN"
    blockers = sa.get("blockers") or []
    flags = dash_flags or {}

    if (snap.get("retry_storm_active")
            or (flags.get("RETRY_STORM_SUPPRESSION_ACTIVE")
                and snap.get("retry_storm_count_last_hour", 0) > 0)):
        return (
            "RED",
            "AUTO_CLOSE_RETRY_STORM_ACTIVE — DO NOT TRADE",
            "Broker-close retry storm detected in the last hour. "
            "Allocator is HARD-BLOCKED. Operator action required "
            "before any further automation runs.",
        )

    repair = snap.get("broker_repair_blocked") or []
    if repair:
        return (
            "ORANGE",
            "BROKER_REPAIR_REQUIRED — allocator blocked until operator "
            "confirmation",
            f"Symbols requiring manual repair: {', '.join(sorted(repair))}. "
            "See docs/OPERATOR_REPAIR_CONFIRMATION.md.",
        )

    if decision != "ALLOCATOR_ALLOWED":
        joined = "; ".join(blockers[:3]) if blockers else decision
        return (
            "YELLOW",
            f"ALLOCATOR_BLOCKED — {decision}",
            f"Active blockers: {joined}. No orders will be placed.",
        )

    return (
        "GREEN",
        "ALLOCATOR_ALLOWED — deterministic gates green",
        "No deterministic blocker is gating the allocator. "
        "TRADING_EXECUTION_ON remains false; review LLM advisory "
        "(advisory-only) before any operator-driven change.",
    )


# ── Yesterday diff ────────────────────────────────────────────────────────────

def _yesterday_brief_sidecar() -> dict | None:
    """Look for the latest JSON sidecar at most ~3 days back."""
    today = datetime.now(timezone.utc).date()
    for delta in (1, 2, 3):
        d = today - timedelta(days=delta)
        for cand in (
            REPO_ROOT / "briefs" / f"{d.isoformat()}.json",
            REPO_ROOT / "learning-loop" / "brief_history" /
                f"{d.isoformat()}.json",
        ):
            if cand.exists():
                try:
                    with open(cand, "r", encoding="utf-8") as fh:
                        raw = json.load(fh)
                    if isinstance(raw, dict):
                        return raw
                except Exception:
                    continue
    return None


def _what_changed(today: dict, yesterday: dict | None) -> list[str]:
    """Render "what changed since yesterday" bullet list."""
    if yesterday is None:
        return [
            "- No prior brief sidecar found on disk. First brief or "
            "history not persisted — nothing to diff against.",
        ]
    lines: list[str] = []

    sa_today = (today.get("system_activation") or {})
    sa_yest = (yesterday.get("system_activation") or {})
    d_today = sa_today.get("decision")
    d_yest = sa_yest.get("decision")
    if d_today != d_yest:
        lines.append(
            f"- Master gate decision changed: "
            f"`{d_yest}` → `{d_today}`")
    else:
        lines.append(f"- Master gate decision unchanged: `{d_today}`")

    b_today = set(sa_today.get("blockers") or [])
    b_yest = set(sa_yest.get("blockers") or [])
    added = sorted(b_today - b_yest)
    removed = sorted(b_yest - b_today)
    if added:
        lines.append(f"- Blockers added: `{', '.join(added)}`")
    if removed:
        lines.append(f"- Blockers removed: `{', '.join(removed)}`")
    if not added and not removed and b_today == b_yest:
        lines.append("- Blockers unchanged.")

    # LLM provider mode shift.
    lm_today = (today.get("flags") or {}).get("LLM_PROVIDER_MODE")
    lm_yest = (yesterday.get("flags") or {}).get("LLM_PROVIDER_MODE")
    if lm_today and lm_yest and lm_today != lm_yest:
        lines.append(
            f"- LLM provider mode changed: `{lm_yest}` → `{lm_today}`")
    elif lm_today:
        lines.append(f"- LLM provider mode: `{lm_today}` (unchanged)")

    # Audit-event count delta (best-effort).
    audit_today = today.get("audit_event_count_24h")
    audit_yest = yesterday.get("audit_event_count_24h")
    if audit_today is not None and audit_yest is not None:
        delta = audit_today - audit_yest
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"- Audit events (24h): {audit_today} "
            f"({sign}{delta} vs prior brief)")

    return lines or ["- No diff produced."]


# ── Operator action list (when blocked) ──────────────────────────────────────

def _operator_actions(banner_color: str, sa: dict,
                        dash_flags: dict | None) -> list[str]:
    if banner_color == "GREEN":
        return []
    flags = dash_flags or {}
    if isinstance(flags.get("NEXT_OPERATOR_ACTIONS"), list) and \
            flags["NEXT_OPERATOR_ACTIONS"]:
        return list(flags["NEXT_OPERATOR_ACTIONS"])

    # Fallback derivation from blockers if the dashboard list is empty.
    blockers = sa.get("blockers") or []
    joined = " ".join(blockers)
    actions: list[str] = []
    if "safe_mode_consistency" in joined:
        actions.append(
            "Investigate runtime_state.safe_mode vs audit-derived "
            "ENTERED events; do NOT auto-clear safe_mode. See "
            "docs/RUNBOOK.md (Scenario 5a).")
    if "broker_repair_required" in joined or "operator_confirmation_required" in joined:
        actions.append(
            "For each broker-repair symbol: open the Alpaca dashboard, "
            "manually close orphaned OCO legs / dust positions, then "
            "run `python3 scripts/record_operator_repair_confirmation.py "
            "--operator-confirmed`. See "
            "docs/OPERATOR_REPAIR_CONFIRMATION.md.")
    if "kill_switch_armed" in joined:
        actions.append(
            "Kill switch is armed by operator — verify intent before "
            "any disarm.")
    if not actions:
        actions.append(
            "Investigate the deterministic blocker(s) listed above. "
            "Do NOT enable broker_paper. Live trading remains "
            "unsupported.")
    return actions


# ── Brief renderer ────────────────────────────────────────────────────────────

def render_brief(*, today: dict, yesterday: dict | None,
                  banner: tuple[str, str, str],
                  dash_flags: dict | None) -> str:
    color, headline, sub = banner
    sa = today.get("system_activation") or {}
    decision = sa.get("decision", "UNKNOWN")

    lines: list[str] = []
    # Top banner.
    bar_top = "=" * 72
    lines.append(bar_top)
    lines.append(f"# Daily Operational Brief — {today.get('as_of', _today_iso_date())}")
    lines.append(bar_top)
    lines.append("")
    lines.append(f"## TOP BANNER: {color}")
    lines.append("")
    lines.append(f"**{headline}**")
    lines.append("")
    lines.append(sub)
    lines.append("")
    if color != "GREEN":
        lines.append(
            "_The banner reflects the deterministic gate state only. "
            "LLM advisory output is informational and CANNOT override "
            "this verdict._")
        lines.append("")

    # Master verdict + citation.
    lines.append("## Master verdict")
    lines.append("")
    lines.append("- Decision: " + _cite(
        decision,
        "learning-loop/system_activation_status_latest.json::master_decision"))
    lines.append("- Shadow simulator permitted: " + _cite(
        bool(sa.get("shadow_only_allowed")),
        "system_activation_gate.shadow_only_allowed"))
    lines.append("- Reason: " + _cite(
        sa.get("reason"),
        "system_activation_gate.reason"))
    lines.append("")

    # Top blockers (deterministic — LLM CANNOT hide them).
    lines.append("## Top blockers")
    lines.append("")
    blockers = sa.get("blockers") or []
    if blockers:
        for b in blockers:
            lines.append(f"- `{b}`")
        lines.append("")
        lines.append(
            "_Blockers are pulled from deterministic artefacts. "
            "LLM advisory output CANNOT add or remove items from "
            "this list._")
    else:
        lines.append("- (No deterministic blocker found.)")
    lines.append("")

    # What changed.
    lines.append("## What changed since yesterday")
    lines.append("")
    lines.extend(_what_changed(today, yesterday))
    lines.append("")

    # Operator-must-do.
    actions = _operator_actions(color, sa, dash_flags)
    if actions:
        lines.append("## What operator must do")
        lines.append("")
        for i, a in enumerate(actions, 1):
            lines.append(f"{i}. {a}")
        lines.append("")

    # Equity reconciliation snippet.
    lines.append("## Equity reconciliation")
    lines.append("")
    eq = _read_json("learning-loop/equity_gap_reconciliation_latest.json")
    if eq:
        lines.append("- verdict: " + _cite(
            eq.get("verdict"),
            "learning-loop/equity_gap_reconciliation_latest.json::verdict"))
        lines.append("- gap_amount: " + _cite(
            eq.get("gap_amount"),
            "learning-loop/equity_gap_reconciliation_latest.json::gap_amount"))
        lines.append("- gap_pct: " + _cite(
            eq.get("gap_pct"),
            "learning-loop/equity_gap_reconciliation_latest.json::gap_pct"))
        lines.append("- block_allocator: " + _cite(
            eq.get("block_allocator"),
            "learning-loop/equity_gap_reconciliation_latest.json::block_allocator"))
    else:
        lines.append("- " + _cite(
            None, "learning-loop/equity_gap_reconciliation_latest.json"))
    lines.append("")

    # Broker repair queue.
    lines.append("## Broker repair queue")
    lines.append("")
    br = _read_json("learning-loop/broker_repair_required_latest.json")
    if br and isinstance(br.get("entries"), dict):
        entries = br["entries"]
        lines.append("- Quarantined symbols: " + _cite(
            len(entries),
            "learning-loop/broker_repair_required_latest.json::entries"))
        for sym in sorted(entries.keys()):
            lines.append(f"  - `{sym}`")
    else:
        lines.append("- " + _cite(
            None, "learning-loop/broker_repair_required_latest.json"))
    lines.append("")

    # Safe-mode consistency.
    lines.append("## Safe-mode consistency")
    lines.append("")
    sm = _read_json("learning-loop/safe_mode_consistency_latest.json")
    if sm:
        lines.append("- verdict: " + _cite(
            sm.get("verdict"),
            "learning-loop/safe_mode_consistency_latest.json::verdict"))
        lines.append("- audit_enters: " + _cite(
            sm.get("audit_enters"),
            "learning-loop/safe_mode_consistency_latest.json::audit_enters"))
        lines.append("- audit_exits: " + _cite(
            sm.get("audit_exits"),
            "learning-loop/safe_mode_consistency_latest.json::audit_exits"))
    else:
        lines.append("- " + _cite(
            None, "learning-loop/safe_mode_consistency_latest.json"))
    lines.append("")

    # LLM advisory section.
    lines.append("## LLM advisory")
    lines.append("")
    mode = (dash_flags or {}).get("LLM_PROVIDER_MODE") or "UNAVAILABLE"
    lines.append(f"- Provider mode: `{mode}`")
    lines.append(
        "- **LLM advisory only — does not override deterministic "
        "gates.** Any recommendation surfaced below is informational. "
        "LLM has zero execution authority (`LLM_EXECUTION_AUTHORITY="
        "false`).")
    advisory = _read_json("learning-loop/llm_advisory_mesh_status_latest.json")
    if advisory:
        lines.append("- Latest mesh status: " + _cite(
            advisory.get("status") or advisory.get("verdict"),
            "learning-loop/llm_advisory_mesh_status_latest.json"))
    else:
        lines.append("- Mesh status: " + _cite(
            None, "learning-loop/llm_advisory_mesh_status_latest.json"))
    lines.append("")

    # Refuse to repeat unverified narrative claims.
    lines.append("## Unverified claims")
    lines.append("")
    lines.append(
        "- The earlier narrative claim of ``92 % readiness`` is "
        "`CLAIM_UNSUPPORTED` unless an artefact backs it up.")
    lines.append(
        "- The claim of ``18 LLM agents`` is `CLAIM_UNSUPPORTED` "
        "unless an artefact backs it up.")
    lines.append(
        "- The claim of ``80-day failure`` window is "
        "`CLAIM_UNSUPPORTED`. The deterministic LLM provider mode "
        "above is the only authoritative status.")
    lines.append("")

    # Standing markers.
    lines.append("## Standing markers")
    for m in STANDING_MARKERS:
        lines.append(f"- `{m}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "_This brief is built by aggregating already-on-disk reporter "
        "artefacts. It never opens a network connection, never "
        "submits an order, never cancels an order, never closes a "
        "position, never mutates state.json or runtime_state.json, "
        "and never lets the LLM advisory output override the "
        "deterministic master gate._")
    lines.append("")
    return "\n".join(lines)


# ── Dashboard flag accessor ──────────────────────────────────────────────────

def _read_dashboard_flags() -> dict | None:
    p = REPO_ROOT / "learning-loop" / "system_activation_status_latest.json"
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    flags = raw.get("flags")
    return flags if isinstance(flags, dict) else None


def _audit_event_count_24h() -> int:
    """Count audit JSONL rows from today and yesterday (best-effort)."""
    n = 0
    today = _today_iso_date()
    yest = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    for d in (today, yest):
        p = REPO_ROOT / "journal" / "autonomy" / f"{d}.jsonl"
        if not p.exists():
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        n += 1
        except OSError:
            continue
    return n


# ── Top-level builder ────────────────────────────────────────────────────────

def build_brief() -> dict:
    """Aggregate every reporter into one brief payload."""
    sa = _system_activation()
    flags = _read_dashboard_flags()
    audit_24h = _audit_event_count_24h()
    out: dict[str, Any] = {
        "schema_version":       "v3.30",
        "generated_at_iso":     _now_iso(),
        "as_of":                _today_iso_date(),
        "module":               "scripts.generate_daily_operational_brief",
        "standing_markers":     list(STANDING_MARKERS),
        "system_activation":    sa,
        "flags":                flags or {},
        "audit_event_count_24h": audit_24h,
    }
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    brief = build_brief()
    yesterday = _yesterday_brief_sidecar()
    banner = _classify_banner(brief.get("system_activation") or {},
                                brief.get("flags"))
    md = render_brief(
        today=brief,
        yesterday=yesterday,
        banner=banner,
        dash_flags=brief.get("flags"),
    )

    if args.json:
        print(json.dumps(brief, indent=2, sort_keys=True))

    if not args.no_write:
        LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_JSON_PATH.write_text(
            json.dumps(brief, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_MD_PATH.write_text(md, encoding="utf-8")
        print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
        print(f"Wrote {LATEST_MD_PATH.relative_to(REPO_ROOT)}")
    print(f"banner_color={banner[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
