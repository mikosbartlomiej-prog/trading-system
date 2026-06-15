#!/usr/bin/env python3
"""scripts/incident_pattern_detector.py — Layer 1 deterministic incident watcher.

v3.9.10 (2026-05-27): standalone real-time monitor that scans recent system
state for KNOWN INCIDENT PATTERNS observed over 6-day incident history
(2026-05-22 RECREATE_EXIT_PLAN, 2026-05-26 duplicate_exits, 2026-05-27 NOW SHORT).

Runs every 5 min via .github/workflows/incident-pattern-detector.yml.
Zero LLM calls. Pure pattern matching. Conservative auto-actions only.

OUTPUTS:
  - stdout summary (always)
  - learning-loop/incidents/<date>.md (append-only when findings)
  - [INCIDENT-WARN] / [INCIDENT-CRITICAL] email
  - audit JSONL event per finding
  - optional auto-action (config flag flip — operator-reversible only)

PATTERNS DETECTED (severity in parens):

 P01 (CRITICAL) duplicate_allocator_execution
 P02 (CRITICAL) naked_short_on_long_only_whitelist  ← today's NOW SHORT
 P03 (CRITICAL) emergency_close_cascade  (>2 in 1h)
 P04 (WARN)     stale_plan_executed  (order placed for symbol not in positions)
 P05 (WARN)     unknown_position_origin  (client_order_id not in KNOWN_PREFIXES)
 P06 (WARN)     bracket_sl_no_recreation  (position SL-closed, no replacement)
 P07 (WARN)     audit_jsonl_gap  (position-affecting actions but <2 audit events/h)
 P08 (WARN)     routine_budget_exhausted_pre_noon
 P09 (WARN)     blackhole_hour  (>3 monitors STALE simultaneously)
 P10 (WARN)     plan_position_drift  (any symbol qty drift >20% plan vs live)
 P11 (WARN)     pdt_jump  (daytrade_count jumped >1 in 30 min)
 P12 (CRITICAL) concentration_violation  (single ticker >50% equity)
 P13 (CRITICAL) bracket_interlock_blocked_close  v3.11.3 (2026-05-30)
                  3+ CLOSE_POSITION FAILED events in 30 min with Alpaca 403
                  "insufficient qty" / "held_for_orders" → governor or
                  allocator trying to close but bracket OCO holds the qty.
                  (Should be impossible with v3.11.3 cancel_brackets_first.)
 P14 (WARN)     pdt_block_cascade  v3.13.3 (2026-06-02)
                  6+ PDT_BLOCK events in last 60 min for SAME symbol+rec.
                  Means exit-monitor (or other) is retrying every cron tick
                  without backoff. Should be impossible with v3.13.3
                  PDT_BLOCK_COOLDOWN_S = 3600. Indicates cooldown not honored
                  or operator forced override.

Exit code:
  0 — no CRITICAL findings (workflow stays green)
  2 — at least one CRITICAL finding (workflow shows red, escalation visible)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Union

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))

import requests  # noqa: E402

ALPACA_BASE = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")


def alpaca_headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }


# Known client_order_id prefixes — copied from forensic_position_origin.py
# v3.11.1 (2026-05-29): added geo-defense-/geo-energy-/geo-gold-/geo-xom-
# after observing 4 false-positive P05 alerts per detector run × cron */5
# = ~100 false alerts/day. These are LEGITIMATE automation prefixes used
# by geo-monitor (see shared/alpaca_orders.execute_stock_signal with
# strategy="geo-defense" etc.). Also added news-* (twitter-monitor patterns
# A-E) and reddit-sentiment- for completeness.
KNOWN_COID_PREFIXES = (
    "stock-", "crypto-", "options-momentum-", "alloc-exit-", "alloc-reduce-",
    "allocator-rebalance-", "exit-emergency-", "exit-tp-", "exit-sl-",
    "exit-trail-", "exit-regime-", "exit-governor-", "exit-profit-lock-",
    "recreate-exit-", "panic-close-", "op-correction-", "operational-correction-",
    # v3.11.1 additions — observed in production 2026-05-28/29
    "geo-defense-", "geo-energy-", "geo-gold-", "geo-xom-",
    "defense-news-", "reddit-sentiment-",
    "twitter-A-", "twitter-B-", "twitter-C-", "twitter-D-",
    "politician-djt-", "politician-stockact-",
    # v3.11.3 part 2 (2026-05-30) — new oversold-bounce path in crypto-monitor
    "crypto-momentum-", "crypto-breakdown-", "crypto-oversold-bounce-",
)

# Tickers that should NEVER be short (long-only whitelist by strategy design)
# Extracted from .claude/rules/tickers-whitelist.md sections marked long-only.
# Conservative default: ALL whitelist symbols are long-only EXCEPT a few that
# have explicit short strategy support.
EXPLICIT_SHORT_OK = {
    # Inverse leveraged ETFs (designed for short exposure via long position)
    "SQQQ", "SPXS", "SPXU", "SOXS", "FAZ", "TZA",
    # No others — overbought-short is disabled (state.json)
}


# Severity levels
INFO, WARN, CRITICAL = "INFO", "WARN", "CRITICAL"


def _load_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _fetch_alpaca_positions() -> list[dict]:
    if not alpaca_headers()["APCA-API-KEY-ID"]:
        return []
    try:
        r = requests.get(f"{ALPACA_BASE}/v2/positions",
                         headers=alpaca_headers(), timeout=10)
        if r.status_code == 200:
            return r.json() or []
    except Exception:
        pass
    return []


def _fetch_alpaca_account() -> dict | None:
    if not alpaca_headers()["APCA-API-KEY-ID"]:
        return None
    try:
        r = requests.get(f"{ALPACA_BASE}/v2/account",
                         headers=alpaca_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today_iso() -> str:
    return _now_utc().date().isoformat()


# ─── Pattern detectors ──────────────────────────────────────────────────────

def p01_duplicate_allocator_execution(execution_log: Path) -> list[dict]:
    """Check execution.json for multiple execute_orders runs same day."""
    if not execution_log.exists():
        return []
    data = _load_json(execution_log)
    if not isinstance(data, dict):
        return []
    # The execution.json stores ONE execution per day. But if executed_at field
    # exists AND log file shows multiple "execute_orders() — auto-execute path"
    # headers, we have duplicates.
    log_path = execution_log.with_suffix(".log")
    if not log_path.exists():
        return []
    try:
        log_text = log_path.read_text(encoding="utf-8")
    except OSError:
        return []
    exec_headers = log_text.count("execute_orders() — auto-execute path")
    if exec_headers >= 2:
        return [{
            "pattern": "P01_duplicate_allocator_execution",
            "severity": CRITICAL,
            "detail": (
                f"morning-allocator executed {exec_headers}× today. "
                f"v3.8.8 + v3.9.9 EXEC_TTL_MIN=360 should prevent this. "
                f"v3.9.10 _exec_buy position pre-check should prevent duplicate fills."
            ),
            "evidence": str(log_path.relative_to(_REPO_ROOT)),
        }]
    return []


def p02_naked_short_on_long_only(positions: list[dict]) -> list[dict]:
    findings = []
    for p in positions:
        sym = (p.get("symbol") or "").upper()
        side = (p.get("side") or "").lower()
        if side == "short" and sym not in EXPLICIT_SHORT_OK:
            try:
                mv = abs(float(p.get("market_value") or 0))
                qty = abs(float(p.get("qty") or 0))
            except (ValueError, TypeError):
                mv, qty = 0, 0
            findings.append({
                "pattern": "P02_naked_short_on_long_only",
                "severity": CRITICAL,
                "detail": (
                    f"{sym} SHORT qty={qty} mv=${mv:,.0f} — not in EXPLICIT_SHORT_OK "
                    f"set. Likely created by stale-plan EXIT MARKET on closed "
                    f"position (2026-05-27 NOW SHORT pattern)."
                ),
                "evidence": f"alpaca position {sym} side=short",
                "symbol": sym,
            })
    return findings


def p03_emergency_close_cascade(audit_events: list[dict]) -> list[dict]:
    """Count EMERGENCY_CLOSE events in last 60 min."""
    cutoff = _now_utc() - timedelta(hours=1)
    count = 0
    symbols = []
    for ev in audit_events:
        if ev.get("decision_type") != "EMERGENCY_CLOSE":
            continue
        try:
            ts = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if ts >= cutoff:
            count += 1
            symbols.extend(ev.get("affected_symbols", []))
    if count > 2:
        return [{
            "pattern": "P03_emergency_close_cascade",
            "severity": CRITICAL,
            "detail": (
                f"{count} EMERGENCY_CLOSE events in last 60min, "
                f"symbols={list(set(symbols))[:5]}. v3.9.9 invariant removed "
                f"no_exit_plan/duplicate_exits/stale_exit_order — only legitimate "
                f"emergencies remain. {count}>2 suggests systemic issue."
            ),
            "evidence": "journal/autonomy/<today>.jsonl",
        }]
    return []


def p04_stale_plan_executed(execution_log: Path, positions: list[dict]) -> list[dict]:
    """Order placed for symbol that doesn't exist in current positions
    (EXIT actions on missing positions = stale-plan symptom).
    Note: v3.9.10 plan revalidation should DROP these pre-exec. If detector
    catches one, revalidation either didn't run or has a bug."""
    if not execution_log.exists():
        return []
    data = _load_json(execution_log)
    if not isinstance(data, dict):
        return []
    pos_syms = {(p.get("symbol") or "").upper() for p in positions}
    findings = []
    for r in (data.get("results") or []):
        if r.get("status") != "placed":
            continue
        action = (r.get("action") or "").upper()
        sym = (r.get("symbol") or "").upper()
        if action in ("EXIT", "REDUCE") and sym not in pos_syms:
            findings.append({
                "pattern": "P04_stale_plan_executed",
                "severity": WARN,
                "detail": (
                    f"{action} {sym} was PLACED but symbol not in current positions. "
                    f"v3.9.10 _revalidate_plan_against_live should drop these — "
                    f"either revalidation skipped OR symbol disappeared after exec."
                ),
                "evidence": f"{execution_log.name}",
                "symbol": sym,
            })
    return findings


def p05_unknown_position_origin(positions: list[dict]) -> list[dict]:
    """v3.10.1 (2026-05-27): position has no recent order with known coid
    prefix in last 7d. Implementation queries GET /v2/orders?symbols=X
    for each position symbol (one call per position, batched).

    Skips check if Alpaca creds missing (fail-soft → empty findings)."""
    if not alpaca_headers()["APCA-API-KEY-ID"]:
        return []
    if not positions:
        return []

    findings = []
    cutoff = (_now_utc() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    for p in positions:
        sym = (p.get("symbol") or "").upper()
        if not sym:
            continue
        try:
            r = requests.get(
                f"{ALPACA_BASE}/v2/orders",
                headers=alpaca_headers(),
                params={"status": "closed", "symbols": sym,
                        "after": cutoff, "limit": 50, "direction": "desc"},
                timeout=8,
            )
            if r.status_code != 200:
                continue
            orders = r.json() or []
            # Look at filled orders only — that's how position originated
            filled = [o for o in orders if o.get("status") == "filled"]
            if not filled:
                # Position exists but no fills in 7d — old position, not anomaly
                continue
            # Check if ANY filled order has a known coid prefix
            has_known = False
            for o in filled:
                coid = (o.get("client_order_id") or "")
                if any(coid.startswith(p_) for p_ in KNOWN_COID_PREFIXES):
                    has_known = True
                    break
            if not has_known:
                # Most recent fill — report its coid for forensic visibility
                most_recent = filled[0]
                findings.append({
                    "pattern": "P05_unknown_position_origin",
                    "severity": WARN,
                    "detail": (
                        f"{sym}: position exists but no recent fill has a known "
                        f"client_order_id prefix. Most recent coid="
                        f"{(most_recent.get('client_order_id') or '<missing>')[:50]}. "
                        f"Possible sources: manual Alpaca dashboard order, external "
                        f"session, or deprecated automation prefix."
                    ),
                    "evidence": f"alpaca orders for {sym}, status=filled, 7d window",
                    "symbol": sym,
                })
        except Exception:
            continue

    return findings[:5]  # cap to avoid spam if many unknowns


def p06_bracket_sl_no_recreation(audit_events: list[dict], positions: list[dict]) -> list[dict]:
    """Position closed by SL in last 4h but no RECREATE_EXIT_PLAN action.
    Detects scenario: bracket OCO child filled, position gone, but no
    indication remediation ran or LLM noticed."""
    cutoff = _now_utc() - timedelta(hours=4)
    recreate_syms = set()
    sl_close_syms = set()
    for ev in audit_events:
        try:
            ts = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if ts < cutoff:
            continue
        if ev.get("decision_type") == "RECREATE_EXIT_PLAN":
            recreate_syms.update(ev.get("affected_symbols", []))
        reason = (ev.get("reason") or "").lower()
        if "stop_loss" in reason or "sl_hit" in reason or "exit-sl" in reason:
            sl_close_syms.update(ev.get("affected_symbols", []))
    # If sl_close happened but no recreate AND no current position → silent loss
    pos_syms = {(p.get("symbol") or "").upper() for p in positions}
    silent = (sl_close_syms - recreate_syms) - pos_syms
    if silent:
        return [{
            "pattern": "P06_bracket_sl_no_recreation",
            "severity": WARN,
            "detail": (
                f"{len(silent)} symbol(s) SL-closed in last 4h without RECREATE_EXIT_PLAN "
                f"and not in current positions: {sorted(silent)[:5]}. "
                f"Likely fine (allocator may re-buy next session) but worth verifying."
            ),
            "evidence": "audit JSONL + positions diff",
        }]
    return []


def p07_audit_jsonl_gap(audit_events: list[dict], execution_log: Path) -> list[dict]:
    """Allocator placed orders but no corresponding audit events.
    v3.9.6 promise: audit captures all position-affecting decisions.
    v3.9.10 safe_close emits CLOSE_POSITION events. Anything else is gap."""
    if not execution_log.exists():
        return []
    data = _load_json(execution_log)
    if not isinstance(data, dict):
        return []
    placed_count = sum(1 for r in (data.get("results") or []) if r.get("status") == "placed")
    if placed_count == 0:
        return []
    # Count CLOSE_POSITION + EMERGENCY_CLOSE + safe_close audit events today
    cutoff = _now_utc() - timedelta(hours=12)
    audit_close_count = 0
    for ev in audit_events:
        try:
            ts = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if ts < cutoff:
            continue
        if ev.get("decision_type") in ("CLOSE_POSITION", "EMERGENCY_CLOSE"):
            audit_close_count += 1
        if (ev.get("actor") or "").startswith("safe_close"):
            audit_close_count += 1
    # If allocator placed N close orders but <N/2 audit events → suspicious
    placed_close = sum(
        1 for r in (data.get("results") or [])
        if r.get("status") == "placed" and (r.get("action") or "").upper() in ("EXIT", "REDUCE")
    )
    if placed_close >= 2 and audit_close_count < (placed_close // 2):
        return [{
            "pattern": "P07_audit_jsonl_gap",
            "severity": WARN,
            "detail": (
                f"Allocator placed {placed_close} EXIT/REDUCE orders but only "
                f"{audit_close_count} CLOSE_POSITION audit events today. "
                f"v3.9.10 safe_close should emit 1 audit event per call."
            ),
            "evidence": "execution.json vs audit JSONL",
        }]
    return []


def p08_routine_budget_exhausted_pre_noon(runtime_state: dict) -> list[dict]:
    """P0 tier exceeded its cap before noon UTC = anomaly."""
    rb = (runtime_state or {}).get("routine_budget") or {}
    by_tier = rb.get("by_tier") or {}
    p0_used = int(by_tier.get("P0_essential") or 0)
    P0_CAP = 4  # from config/routine_budget.json
    now = _now_utc()
    if now.hour < 12 and p0_used >= P0_CAP:
        return [{
            "pattern": "P08_routine_budget_exhausted_pre_noon",
            "severity": WARN,
            "detail": (
                f"P0_essential budget {p0_used}/{P0_CAP} used before {now.hour}:00 UTC. "
                f"daily-learning normally uses 3 (Senior PM + Challenger + Revise). "
                f"4+ pre-noon = likely retry loop or watchdog re-fire."
            ),
            "evidence": "runtime_state.json::routine_budget",
        }]
    return []


def p09_blackhole_hour(health_data: dict) -> list[dict]:
    """>3 monitors STALE simultaneously (GitHub Actions cron-skip cascade)."""
    if not isinstance(health_data, dict):
        return []
    workflows = (health_data.get("workflows") or [])
    stale = [w for w in workflows
             if w.get("verdict") in ("STALE", "MISSING")]
    if len(stale) > 3:
        return [{
            "pattern": "P09_blackhole_hour",
            "severity": WARN,
            "detail": (
                f"{len(stale)} workflows STALE simultaneously: "
                f"{[w.get('name','?')[:30] for w in stale[:5]]}. "
                f"GitHub Actions cron-skip cascade — entry-monitors-watchdog "
                f"should retrigger but may itself be stale."
            ),
            "evidence": "learning-loop/health/latest.json",
        }]
    return []


def p10_plan_position_drift(execution_log: Path, positions: list[dict]) -> list[dict]:
    """Plan qty differs from live qty by >20% for any actionable symbol."""
    if not execution_log.exists():
        return []
    plan_path = execution_log.with_name(execution_log.stem.replace(".execution", "") + ".json")
    if not plan_path.exists():
        return []
    plan = _load_json(plan_path)
    if not isinstance(plan, dict):
        return []
    pos_map = {(p.get("symbol") or "").upper(): abs(float(p.get("qty") or 0))
               for p in positions}
    findings = []
    for order in (plan.get("rebalance_orders") or []):
        action = (order.get("action") or "").upper()
        if action not in ("EXIT", "REDUCE", "HOLD"):
            continue
        sym = (order.get("symbol") or "").upper()
        if sym not in pos_map:
            continue
        plan_qty = abs(float(order.get("current_qty") or 0))
        live_qty = pos_map[sym]
        if plan_qty <= 0:
            continue
        drift = abs(live_qty - plan_qty) / plan_qty
        if drift > 0.20:
            findings.append({
                "pattern": "P10_plan_position_drift",
                "severity": WARN,
                "detail": (
                    f"{sym}: plan_qty={plan_qty} live_qty={live_qty} "
                    f"drift={drift:.0%} (action={action}). v3.9.10 safe_close "
                    f"will clamp to live but indicates stale plan."
                ),
                "evidence": plan_path.name,
                "symbol": sym,
            })
    return findings[:3]  # cap to avoid spam


def p11_pdt_jump(runtime_state: dict) -> list[dict]:
    """v3.10.1 (2026-05-27): daytrade_count jumped >1 in last detector tick.
    History persisted via runtime_state.json::incident_detector_history
    (self-managed — detector writes its own baseline each run)."""
    if not runtime_state:
        return []
    pdt_status = runtime_state.get("pdt_status") or {}
    pdt_now = pdt_status.get("daytrade_count")
    if pdt_now is None:
        return []

    # Read previous baseline (set by detector itself last run)
    hist = (runtime_state.get("incident_detector_history") or {})
    pdt_prev = hist.get("pdt_count_prev")
    pdt_prev_ts = hist.get("pdt_prev_ts")

    findings = []
    # Only fire if prev exists AND jumped >1 (skip first detector run)
    if pdt_prev is not None and (pdt_now - pdt_prev) > 1:
        findings.append({
            "pattern": "P11_pdt_jump",
            "severity": WARN,
            "detail": (
                f"daytrade_count {pdt_prev} → {pdt_now} (jump +{pdt_now-pdt_prev}) "
                f"since last detector tick ({pdt_prev_ts}). Multiple intraday "
                f"close/reopen = potential PDT lockout risk (lockout at 3 in 5d)."
            ),
            "evidence": "runtime_state.json::pdt_status.daytrade_count",
            "delta": pdt_now - pdt_prev,
        })

    # Persist current pdt_count for next-tick comparison
    # (file write is best-effort; failure doesn't block findings)
    try:
        import json as _json
        from pathlib import Path as _Path
        path = _REPO_ROOT / "learning-loop" / "runtime_state.json"
        if path.exists():
            data = _json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("incident_detector_history", {})
            data["incident_detector_history"]["pdt_count_prev"] = pdt_now
            data["incident_detector_history"]["pdt_prev_ts"] = _now_utc().isoformat()
            path.write_text(_json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass

    return findings


def p13_bracket_interlock_blocked_close(audit_events: list[dict]) -> list[dict]:
    """v3.11.3 (2026-05-30): detect bracket interlock cascade.

    Background: 2026-05-29 14:11-14:21 UTC, intraday-governor tried to
    force-close 5 positions during DEFEND_DAY / RED_DAY_AFTER_GREEN.
    All 5 failed with Alpaca 403 "insufficient qty available" because
    bracket OCO children were holding the entire qty (`held_for_orders=N`).
    Governor's protective mechanism was armed but could not fire.

    v3.11.3 fix: safe_close now cancels open orders for the symbol BEFORE
    placing the protective close. If THIS detector fires post-v3.11.3 →
    the cancel step itself is failing → systemic Alpaca issue or new
    bug. Treat as CRITICAL.

    Trigger: ≥3 CLOSE_POSITION / EMERGENCY_CLOSE events with
    decision="FAILED" in last 30 min whose reason contains "403" AND
    one of: "insufficient", "held_for_orders".
    """
    cutoff = _now_utc() - timedelta(minutes=30)
    matches: list[dict] = []
    for ev in audit_events:
        try:
            ts = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if ts < cutoff:
            continue
        dt = (ev.get("decision_type") or "").upper()
        dec = (ev.get("decision") or "").upper()
        if dt not in ("CLOSE_POSITION", "EMERGENCY_CLOSE"):
            continue
        if dec != "FAILED":
            continue
        reason = (ev.get("reason") or "").lower()
        if "403" not in reason:
            continue
        if not any(k in reason for k in ("insufficient", "held_for_orders")):
            continue
        matches.append(ev)
    if len(matches) < 3:
        return []
    symbols = list({s for ev in matches for s in (ev.get("affected_symbols") or [])})[:5]
    return [{
        "pattern": "P13_bracket_interlock_blocked_close",
        "severity": CRITICAL,
        "detail": (
            f"{len(matches)} CLOSE_POSITION events FAILED in last 30min with "
            f"Alpaca 403 (insufficient qty / held_for_orders). symbols={symbols}. "
            f"v3.11.3 cancel_brackets_first should prevent this — if firing post "
            f"v3.11.3 deploy, the cancel step itself is failing (broker outage, "
            f"DELETE permission revoked, or new bug). Operator action: check "
            f"Alpaca status + recent commits to shared/alpaca_orders.py."
        ),
        "evidence": "journal/autonomy/<today>.jsonl",
    }]


def p14_pdt_block_cascade(audit_events: list[dict]) -> list[dict]:
    """v3.13.3 (2026-06-02): detect PDT_BLOCK retry cascade.

    Background: 2026-06-01 exit-monitor wanted CLOSE_FLAT on LMT/RTX
    every 5 min during PDT lockout. Result: 36 PDT_BLOCK events in single
    day (LMT×21, RTX×12). Pure noise — pdt_guard correctly blocked, but
    audit JSONL was spammed.

    v3.13.3 fix: PDT_BLOCK_COOLDOWN_S=3600 silences (symbol, rec)
    repeats for 60 min. If THIS detector fires post-v3.13.3 → cooldown
    not honored OR operator manually disabled it. Severity WARN
    (no money lost, just operational noise).

    Trigger: ≥6 PDT_BLOCK events in last 60 min for SAME (symbol, rec).
    """
    cutoff = _now_utc() - timedelta(minutes=60)
    by_key: dict = {}
    for ev in audit_events:
        try:
            ts_str = ev.get("ts") or ev.get("timestamp", "")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (KeyError, ValueError, AttributeError):
            continue
        if ts < cutoff:
            continue
        dec = (ev.get("decision") or "").upper()
        if dec != "PDT_BLOCK":
            continue
        symbol = ev.get("symbol") or "?"
        rec = (ev.get("context") or {}).get("recommendation", "?")
        key = (symbol, rec)
        by_key.setdefault(key, []).append(ev)
    findings = []
    for (sym, rec), evs in by_key.items():
        if len(evs) < 6:
            continue
        findings.append({
            "pattern": "P14_pdt_block_cascade",
            "severity": WARN,
            "detail": (
                f"{len(evs)} PDT_BLOCK events in last 60min for {sym} "
                f"recommendation={rec}. exit-monitor retrying without backoff. "
                f"v3.13.3 PDT_BLOCK_COOLDOWN_S=3600 should silence repeats. "
                f"If firing post-v3.13.3 deploy, cooldown not honored — "
                f"check exit-monitor _PDT_BLOCK_COOLDOWN dict resetting "
                f"between cron ticks (no persistent storage by design)."
            ),
            "evidence": "journal/autonomy/<today>.jsonl",
        })
    return findings[:3]   # cap output


def p12_concentration_violation(positions: list[dict], account: dict | None) -> list[dict]:
    if not account:
        return []
    try:
        equity = float(account.get("equity") or 0)
    except (ValueError, TypeError):
        return []
    if equity <= 0:
        return []
    findings = []
    for p in positions:
        try:
            mv = abs(float(p.get("market_value") or 0))
        except (ValueError, TypeError):
            continue
        pct = mv / equity * 100
        if pct > 50:
            sym = (p.get("symbol") or "?").upper()
            findings.append({
                "pattern": "P12_concentration_violation",
                "severity": CRITICAL,
                "detail": (
                    f"{sym} concentration {pct:.1f}% > 50% equity (${mv:,.0f} / "
                    f"${equity:,.0f}). STRATEGY.md cap is 40%; v3.9 default 18%/pos."
                ),
                "evidence": "alpaca positions",
                "symbol": sym,
            })
    return findings


# ─── Main ─────────────────────────────────────────────────────────────────

def run_all_checks() -> list[dict]:
    findings: list[dict] = []

    # Load data sources
    health = _load_json(_REPO_ROOT / "learning-loop" / "health" / "latest.json") or {}
    runtime = _load_json(_REPO_ROOT / "learning-loop" / "runtime_state.json") or {}
    today = _today_iso()
    audit_events = _load_jsonl(_REPO_ROOT / "journal" / "autonomy" / f"{today}.jsonl")
    execution_log = _REPO_ROOT / "learning-loop" / "allocations" / f"{today}.execution.json"
    positions = _fetch_alpaca_positions()
    account = _fetch_alpaca_account()

    # Run all 12 patterns
    findings.extend(p01_duplicate_allocator_execution(execution_log))
    findings.extend(p02_naked_short_on_long_only(positions))
    findings.extend(p03_emergency_close_cascade(audit_events))
    findings.extend(p04_stale_plan_executed(execution_log, positions))
    findings.extend(p05_unknown_position_origin(positions))
    findings.extend(p06_bracket_sl_no_recreation(audit_events, positions))
    findings.extend(p07_audit_jsonl_gap(audit_events, execution_log))
    findings.extend(p08_routine_budget_exhausted_pre_noon(runtime))
    findings.extend(p09_blackhole_hour(health))
    findings.extend(p10_plan_position_drift(execution_log, positions))
    findings.extend(p11_pdt_jump(runtime))  # v3.10.1: self-managed history in runtime_state
    findings.extend(p12_concentration_violation(positions, account))
    findings.extend(p13_bracket_interlock_blocked_close(audit_events))
    findings.extend(p14_pdt_block_cascade(audit_events))

    return findings


def write_incident_report(findings: list[dict]) -> str | None:
    """Append to learning-loop/incidents/<date>.md. Returns path or None."""
    if not findings:
        return None
    inc_dir = _REPO_ROOT / "learning-loop" / "incidents"
    inc_dir.mkdir(parents=True, exist_ok=True)
    path = inc_dir / f"{_today_iso()}.md"
    now = _now_utc().strftime("%H:%M:%S UTC")

    lines = [f"\n## Run {now}\n"]
    for f in findings:
        lines.append(f"### {f['severity']} {f['pattern']}\n")
        lines.append(f"- **Detail:** {f['detail']}")
        lines.append(f"- **Evidence:** `{f.get('evidence', 'n/a')}`")
        if "symbol" in f:
            lines.append(f"- **Symbol:** {f['symbol']}")
        lines.append("")

    if not path.exists():
        path.write_text(f"# Incident Pattern Detector — {_today_iso()}\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as fp:
        fp.write("\n".join(lines))
    return str(path.relative_to(_REPO_ROOT))


def emit_email(findings: list[dict]) -> None:
    """Send [INCIDENT-WARN] or [INCIDENT-CRITICAL] email per highest severity."""
    if not findings:
        return
    has_critical = any(f["severity"] == CRITICAL for f in findings)
    subject_prefix = "[INCIDENT-CRITICAL]" if has_critical else "[INCIDENT-WARN]"
    subject = f"{subject_prefix} {len(findings)} pattern hit(s) — {_today_iso()}"
    body_lines = [
        f"Incident Pattern Detector run @ {_now_utc().isoformat()}",
        f"",
        f"Total findings: {len(findings)} "
        f"(CRITICAL={sum(1 for f in findings if f['severity']==CRITICAL)}, "
        f"WARN={sum(1 for f in findings if f['severity']==WARN)})",
        f"",
    ]
    for f in findings:
        body_lines.append(f"[{f['severity']}] {f['pattern']}")
        body_lines.append(f"  detail: {f['detail']}")
        body_lines.append(f"  evidence: {f.get('evidence','n/a')}")
        body_lines.append("")
    body_lines.append("Full report: learning-loop/incidents/<today>.md (committed to repo).")
    body_lines.append("")
    body_lines.append("If CRITICAL: investigate immediately. Possible auto-actions taken — "
                       "check config/capital_deployment.json::auto_execute_rebalance.")
    try:
        from notify import send_email
        send_email(subject=subject, body="\n".join(body_lines))
    except Exception as e:
        print(f"  email emit failed (non-fatal): {e}")


def trigger_safe_mode_for_critical(findings: list[dict]) -> list[dict]:
    """v3.22 ETAP 9 (2026-06-15) — flip safe_mode on for P01/P02/P13.

    When the detector finds at least one CRITICAL finding matching one
    of {P01, P02, P13}, ensure ``safe_mode`` is ACTIVE for the matching
    trigger. Dedupe window = 60 min (so a stuck pattern does not
    re-emit SAFE_MODE_ENTERED every cron tick).

    Returns the list of safe_mode entries actually triggered (for
    reporting). Fail-soft: any error inside the safe_mode call is
    swallowed, the detector keeps reporting findings.
    """
    if not findings:
        return []
    try:
        sys.path.insert(0, str(_REPO_ROOT / "shared"))
        import safe_mode  # type: ignore
    except Exception as e:
        print(f"  safe_mode import failed (non-fatal): {e}")
        return []

    pattern_to_trigger = {
        "P01_duplicate_allocator_execution": safe_mode.TRIGGER_INCIDENT_P01_DUPLICATE_ALLOCATOR,
        "P02_naked_short_on_long_only":      safe_mode.TRIGGER_INCIDENT_P02_NAKED_SHORT,
        "P13_bracket_interlock_blocked_close": safe_mode.TRIGGER_INCIDENT_P13_BRACKET_INTERLOCK,
    }
    triggered: list[dict] = []
    seen_triggers: set[str] = set()
    for f in findings:
        if f.get("severity") != CRITICAL:
            continue
        pattern = f.get("pattern", "")
        trigger = pattern_to_trigger.get(pattern)
        if not trigger:
            continue
        if trigger in seen_triggers:
            continue   # same trigger from multiple findings → only attempt once
        seen_triggers.add(trigger)
        try:
            state_before = safe_mode.read_state()
            new_state = safe_mode.enter(
                trigger=trigger,
                reason=f"incident-pattern-detector {pattern}: {f.get('detail', '')[:300]}",
                actor="incident-pattern-detector",
                dedupe_seconds=safe_mode.INCIDENT_DEDUPE_WINDOW_SECONDS,
            )
            # Detect whether this call actually flipped/refreshed
            entered = bool(new_state.active) and (
                not state_before.active
                or state_before.trigger != trigger
                or state_before.entered_at != new_state.entered_at
            )
            triggered.append({
                "trigger":   trigger,
                "pattern":   pattern,
                "entered":   entered,
                "deduped":   not entered,
            })
        except Exception as e:
            print(f"  safe_mode.enter({trigger}) failed (non-fatal): {e}")
    return triggered


def emit_audit_events(findings: list[dict]) -> None:
    """One audit JSONL event per finding."""
    if not findings:
        return
    try:
        from autonomy import make_decision
        from audit import write_audit_event
    except ImportError:
        return
    for f in findings:
        try:
            d = make_decision(
                decision_type="CLEANUP_STALE_ORDERS",  # closest enum match
                decision="DETECTED",
                reason=f"{f['pattern']}: {f['detail'][:200]}",
                actor="incident_pattern_detector",
                affected_symbols=[f["symbol"]] if "symbol" in f else [],
                risk_metrics={"severity": f["severity"], "pattern": f["pattern"]},
                action_taken="pattern_match",
                result="reported",
                reversible=True,
            )
            write_audit_event(d, kind="trading")
        except Exception as e:
            print(f"  audit emit failed for {f['pattern']}: {e}")


def maybe_auto_disable(findings: list[dict]) -> str | None:
    """Conservative auto-action: flip auto_execute_rebalance=false ONLY on
    CRITICAL findings AND environment opt-in (INCIDENT_AUTO_DISABLE=true).
    Reversible by operator. Returns description of action taken or None."""
    if os.environ.get("INCIDENT_AUTO_DISABLE", "false").lower() != "true":
        return None
    has_critical = any(f["severity"] == CRITICAL for f in findings)
    if not has_critical:
        return None
    cfg_path = _REPO_ROOT / "config" / "capital_deployment.json"
    cfg = _load_json(cfg_path)
    if not isinstance(cfg, dict):
        return None
    cap = cfg.get("capital_deployment") or {}
    if not cap.get("auto_execute_rebalance", False):
        return None  # already disabled
    cap["auto_execute_rebalance"] = False
    cfg["capital_deployment"] = cap
    cfg["_incident_disabled_at"] = _now_utc().isoformat()
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return "auto_execute_rebalance flipped to false (incident-pattern-detector CRITICAL)"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Print findings only; no email/audit/disable")
    args = p.parse_args()

    print(f"=== Incident Pattern Detector — {_now_utc().isoformat()} ===")
    findings = run_all_checks()
    print(f"Patterns checked: 12  Findings: {len(findings)}")

    if not findings:
        print("✅ No incident patterns detected.")
        return 0

    for f in findings:
        print(f"  [{f['severity']}] {f['pattern']} — {f['detail'][:120]}")

    if args.dry_run:
        print("\n(dry-run: skipping email/audit/auto-disable)")
        return 0

    report_path = write_incident_report(findings)
    if report_path:
        print(f"Report written: {report_path}")

    emit_email(findings)
    emit_audit_events(findings)

    # v3.22 ETAP 9 (2026-06-15) — flip safe_mode ACTIVE for CRITICAL
    # P01/P02/P13 findings. Dedupe window keeps detector cron from
    # re-emitting SAFE_MODE_ENTERED every tick.
    sm_results = trigger_safe_mode_for_critical(findings)
    for r in sm_results:
        if r.get("entered"):
            print(f"  safe_mode ENTERED via {r['pattern']} → trigger={r['trigger']}")
        elif r.get("deduped"):
            print(f"  safe_mode already ACTIVE for {r['trigger']} (deduped)")

    action = maybe_auto_disable(findings)
    if action:
        print(f"AUTO-ACTION: {action}")

    # v3.13.3 — heartbeat ping (READINESS-1). Fail-soft.
    try:
        sys.path.insert(0, str(_REPO_ROOT / "shared"))
        from heartbeat import ping as _hb_ping
        _hb_ping("incident-pattern-detector", status="ok",
                 message=f"findings={len(findings)}")
    except Exception as _hb_e:
        print(f"  heartbeat ping failed (non-fatal): {type(_hb_e).__name__}")

    has_critical = any(f["severity"] == CRITICAL for f in findings)
    return 2 if has_critical else 0


if __name__ == "__main__":
    sys.exit(main())
