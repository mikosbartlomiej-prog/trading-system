"""doj-monitor — SEC 8-K + DOJ press release scanner (FB-008, v3.16).

Two emit-only lanes:

  Lane A — SEC 8-K filings (Atom feed)
    Material items 1.01 / 1.02 / 1.03 / 5.02 / 8.01 surfaced via free
    SEC EDGAR endpoints + CIK→ticker map (company_tickers.json).
    Each event tagged as Tier 1 primary.

  Lane B — DOJ press releases (RSS)
    Indictments / settlements / investigations parsed from the
    official DOJ news RSS. Best-effort ticker extraction from headline
    + summary. Each event tagged Tier 1 primary.

Default behavior:
  - EMIT-ONLY. Every fetched + non-duplicate event becomes a
    `[DOJ-FILING]` email. NO auto-execute, NO Curator, NO trade
    placement. Operator reads the email and decides manually.
  - `AUTO_EXECUTE_DOJ=true` env flag exists as a documented future
    hook but is intentionally NOT wired — when implemented it must
    pass through `shared/risk_officer` + `news_signal_gate` like the
    other monitors.

Implements EventMonitorInterface from shared/event_monitor_interface.

NEVER live. Paper-only invariant honored upstream.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

MONITOR_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(MONITOR_DIR, ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared"))
sys.path.insert(0, MONITOR_DIR)

# Local lane modules
from sec_8k_client import (
    fetch_recent_8k,
    fetch_company_tickers,
    build_candidates as build_8k_candidates,
)
from doj_press_client import (
    fetch_doj_press,
    build_candidates as build_doj_candidates,
    _build_name_to_ticker_index,
)


# Shared interface + tier
try:
    from event_monitor_interface import (
        EventMonitorInterface,
        EventCandidate,
        EVT_SEC_8K_FILING,
        EVT_DOJ_PRESS_RELEASE,
    )
    from source_quality import TIER_1
except Exception:
    EventMonitorInterface = object  # type: ignore[assignment,misc]
    EventCandidate = None  # type: ignore[assignment]
    EVT_SEC_8K_FILING = "sec_8k_filing"
    EVT_DOJ_PRESS_RELEASE = "doj_press_release"
    TIER_1 = "tier_1_primary"


# ─── Config ───────────────────────────────────────────────────────────────────

AUTO_EXECUTE_DOJ = os.environ.get("AUTO_EXECUTE_DOJ", "false").lower() == "true"
MAX_ALERTS_PER_RUN = int(os.environ.get("MAX_ALERTS_PER_RUN", "3"))
USE_CURATOR = os.environ.get("USE_DOJ_CURATOR", "false").lower() == "true"

STATE_PATH = os.path.join(MONITOR_DIR, "state.json")
STATE_VERSION = "3.16.0"
SEEN_CAP = 1000  # FIFO cap


# ─── State (dedup cache) ──────────────────────────────────────────────────────

def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_state() -> dict[str, Any]:
    return {
        "seen_event_ids": [],
        "last_run_iso":   None,
        "version":        STATE_VERSION,
    }


def _load_state(path: str = STATE_PATH) -> dict[str, Any]:
    if not os.path.exists(path):
        return _empty_state()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    data.setdefault("seen_event_ids", [])
    data.setdefault("last_run_iso",   None)
    data.setdefault("version",        STATE_VERSION)
    return data


def _save_state(state: dict[str, Any], path: str = STATE_PATH) -> None:
    """Persist state with FIFO cap on seen_event_ids."""
    seen = list(state.get("seen_event_ids") or [])[-SEEN_CAP:]
    out = {
        "seen_event_ids": seen,
        "last_run_iso":   _utcnow(),
        "version":        STATE_VERSION,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
    except OSError as e:
        print(f"  WARN: could not write state.json: {e}")


# ─── Monitor implementation ──────────────────────────────────────────────────

class DOJMonitor(EventMonitorInterface):
    """SEC 8-K + DOJ press monitor implementing EventMonitorInterface.

    `fetch_events` pulls both lanes and returns the union. Source tier
    is always TIER_1 (primary sources). Day-trade eligibility defers to
    the base-class rule (Tier 1 + immediate catalyst), which matches our
    spec: bankruptcy / indictments go through as day-trade candidates;
    investigations / officer changes do not.
    """

    event_type = EVT_SEC_8K_FILING  # marker; lane-specific events carry their own
    source_tier = TIER_1
    rate_limit_per_run = MAX_ALERTS_PER_RUN

    def __init__(self,
                 *,
                 fetch_8k=None,
                 fetch_doj=None,
                 fetch_tickers=None):
        super().__init__()
        # Bind via module-globals lookup (resolved at call-time, not def-time)
        # so tests that patch `monitor.fetch_recent_8k` take effect.
        self._fetch_8k = fetch_8k
        self._fetch_doj = fetch_doj
        self._fetch_tickers = fetch_tickers
        self._raw_tickers_for_doj: Optional[dict] = None

    # -- public ---------------------------------------------------------------

    def fetch_events(self, now_iso: str) -> Iterable[Any]:
        """Single tick fetch: SEC 8-K + DOJ press. Fail-soft per lane."""
        out: list[Any] = []

        # Resolve fetchers at call-time via module globals so tests can
        # monkey-patch `monitor.fetch_recent_8k` etc. between construction
        # and run_scan.
        _g = globals()
        fetch_8k = self._fetch_8k or _g.get("fetch_recent_8k")
        fetch_doj = self._fetch_doj or _g.get("fetch_doj_press")
        fetch_tickers = self._fetch_tickers or _g.get("fetch_company_tickers")

        # Lane A — SEC 8-K
        try:
            filings = fetch_8k() or []
        except Exception as e:
            print(f"  Lane A (SEC 8-K) error: {type(e).__name__}: {e}")
            filings = []
        try:
            ticker_map = fetch_tickers() or {}
        except Exception as e:
            print(f"  Ticker map fetch error: {type(e).__name__}: {e}")
            ticker_map = {}
        try:
            cand_a = build_8k_candidates(filings, ticker_map, now_iso=now_iso)
        except Exception as e:
            print(f"  Lane A build error: {type(e).__name__}: {e}")
            cand_a = []
        print(f"  Lane A: {len(filings)} filings -> {len(cand_a)} candidates")

        # Lane B — DOJ press
        try:
            press_items = fetch_doj() or []
        except Exception as e:
            print(f"  Lane B (DOJ press) error: {type(e).__name__}: {e}")
            press_items = []
        # Reuse SEC company_tickers raw map for name -> ticker if available
        name_index = _build_name_to_ticker_index(self._raw_tickers_for_doj or {})
        try:
            cand_b = build_doj_candidates(press_items, name_index, now_iso=now_iso)
        except Exception as e:
            print(f"  Lane B build error: {type(e).__name__}: {e}")
            cand_b = []
        print(f"  Lane B: {len(press_items)} press -> {len(cand_b)} candidates")

        out.extend(cand_a)
        out.extend(cand_b)
        return out


# ─── Email emission ───────────────────────────────────────────────────────────

def _format_event_email(event: Any, decision: Any | None) -> tuple[str, str]:
    """Render `[DOJ-FILING]` subject + body."""
    e = event
    headline = getattr(e, "headline", None) or (e.get("headline") if isinstance(e, dict) else "")
    tickers  = getattr(e, "tickers", None) or (e.get("tickers", ()) if isinstance(e, dict) else ())
    url      = getattr(e, "source_url", None) or (e.get("source_url", "") if isinstance(e, dict) else "")
    summary  = getattr(e, "summary", None) or (e.get("summary", "") if isinstance(e, dict) else "")
    severity = getattr(e, "severity", None) or (e.get("severity", "") if isinstance(e, dict) else "")
    timing   = getattr(e, "catalyst_timing", None) or (e.get("catalyst_timing", "") if isinstance(e, dict) else "")
    etype    = getattr(e, "event_type", None) or (e.get("event_type", "") if isinstance(e, dict) else "")
    eid      = getattr(e, "event_id", None) or (e.get("event_id", "") if isinstance(e, dict) else "")

    tickers_str = ",".join(tickers) if tickers else "(no ticker)"
    subject = f"[DOJ-FILING] {tickers_str} {(headline or '')[:80]}"

    rationale = getattr(decision, "rationale", "") if decision is not None else ""
    eligible = getattr(decision, "day_trade_eligible", False) if decision is not None else False

    body_lines = [
        "DOJ-MONITOR — emit-only event (no auto-execute)",
        "",
        f"  Event ID:       {eid}",
        f"  Type:           {etype}",
        f"  Tickers:        {tickers_str}",
        f"  Severity:       {severity}",
        f"  Catalyst:       {timing}",
        f"  Day-trade eligible: {eligible}",
        "",
        f"  Headline:       {headline}",
        "",
        f"  Summary: {(summary or '')[:500]}",
        "",
        f"  Source URL:     {url}",
        "",
        f"  Rationale:      {rationale}",
        "",
        "  This event is EMIT-ONLY — no Alpaca order placed.",
        "  Operator review required before manual entry.",
        "",
        "  Source tier:    Tier 1 primary (SEC/DOJ filing).",
    ]
    body = "\n".join(body_lines)
    return subject, body


def emit_event(event: Any, decision: Any | None = None) -> bool:
    """Send `[DOJ-FILING]` email for a single event. Fail-soft.

    Returns True if email send was attempted successfully (or digested
    by NotificationPolicy), False on hard failure.
    """
    try:
        from notify import send_email
    except Exception as e:
        print(f"  notify import failed ({type(e).__name__}: {e}) — skip email")
        return False
    try:
        subject, body = _format_event_email(event, decision)
        return bool(send_email(subject, body))
    except Exception as e:
        print(f"  emit_event exception: {type(e).__name__}: {e}")
        return False


# ─── Main scan ────────────────────────────────────────────────────────────────

def run_scan(state_path: str = STATE_PATH) -> dict[str, Any]:
    """Single cron tick. Returns summary dict."""
    print(f"=== doj-monitor scan — {_utcnow()} ===")
    print(f"  AUTO_EXECUTE_DOJ={AUTO_EXECUTE_DOJ}  MAX_ALERTS_PER_RUN={MAX_ALERTS_PER_RUN}")

    # Account-level guards (fail-open). We do NOT execute trades, but we
    # still skip during HALT to avoid noise spam during stress events.
    try:
        from risk_guards import daily_drawdown_guard, vix_guard
        dd_status, dd_reason = daily_drawdown_guard()
        if dd_status == "HALT":
            print(f"  HALT: {dd_reason} — skipping emission this run")
            return {"skipped": "drawdown", "reason": dd_reason, "emitted": 0}
        vix_status, _ = vix_guard()
        if vix_status == "HALT":
            print("  HALT: VIX > 60 — skipping emission this run")
            return {"skipped": "vix", "emitted": 0}
    except Exception as e:
        print(f"  guards unavailable ({e}) — fail-open, proceeding")

    state = _load_state(state_path)
    seen: set[str] = set(state.get("seen_event_ids") or [])
    print(f"  state: {len(seen)} event_ids in dedup cache")

    monitor = DOJMonitor()
    now_iso = _utcnow()
    raw_events = list(monitor.fetch_events(now_iso))
    print(f"  fetched {len(raw_events)} candidate events (both lanes combined)")

    emitted: list[dict[str, Any]] = []
    fresh_count = 0
    for ev in raw_events:
        eid = getattr(ev, "event_id", None) or (ev.get("event_id") if isinstance(ev, dict) else "")
        if not eid:
            continue
        if eid in seen:
            continue
        fresh_count += 1
        if len(emitted) >= MAX_ALERTS_PER_RUN:
            # Still mark as seen so we don't re-attempt next tick.
            seen.add(eid)
            continue

        # Use base-class policy: dedupe + decide + confidence adj.
        decision = monitor.decide(ev)
        if not decision.emit:
            seen.add(eid)
            continue

        ok = emit_event(ev, decision)
        emitted.append({
            "event_id":       eid,
            "tickers":        list(getattr(ev, "tickers", ())
                                    if not isinstance(ev, dict)
                                    else ev.get("tickers", ())),
            "headline":       getattr(ev, "headline", None) or (ev.get("headline") if isinstance(ev, dict) else ""),
            "severity":       getattr(ev, "severity", None) or (ev.get("severity") if isinstance(ev, dict) else ""),
            "catalyst_timing": getattr(ev, "catalyst_timing", None) or (ev.get("catalyst_timing") if isinstance(ev, dict) else ""),
            "delivered":      bool(ok),
        })
        seen.add(eid)

    state["seen_event_ids"] = list(seen)
    _save_state(state, state_path)
    print(f"=== doj-monitor done: emitted={len(emitted)} fresh={fresh_count} ===")
    return {
        "emitted":      len(emitted),
        "fresh":        fresh_count,
        "candidates":   len(raw_events),
        "events":       emitted,
        "auto_execute": AUTO_EXECUTE_DOJ,
    }


# ─── Routine-budget hook (future; consume only if USE_CURATOR is enabled) ─────

def _maybe_consume_routine_budget() -> bool:
    """Reserve a P2_optional slot when DOJ Curator is enabled.

    Currently `USE_DOJ_CURATOR=false` (no Curator implemented). Hook
    kept so future iteration can plug in seamlessly via the same
    `shared/routine_budget` semantics as other monitors.
    """
    if not USE_CURATOR:
        return True
    try:
        from routine_budget import check_and_record
    except Exception as e:
        print(f"  routine_budget unavailable ({e}) — fail-open")
        return True
    try:
        ok, reason = check_and_record("doj-curator", "P2_optional")
        if not ok:
            print(f"  routine budget BLOCK: {reason}")
        return bool(ok)
    except Exception as e:
        print(f"  routine_budget error ({e}) — fail-open")
        return True


# ─── __main__ ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    summary = run_scan()

    # Summary email only when something fired (keeps inbox quiet).
    try:
        emitted = summary.get("emitted", 0)
        if emitted > 0:
            from notify import notify_summary
            notify_summary(
                monitor="doj-monitor",
                signals_found=summary.get("candidates", 0),
                alerts_sent=emitted,
            )
    except Exception as e:
        print(f"  summary email exception: {e}")

    # v3.14.0 — heartbeat ping (closes ARCH-001/RUNTIME-002/CONF-003).
    try:
        from heartbeat import ping as _hb_ping
        _hb_ping(
            "doj-monitor",
            status="ok",
            message=f"emitted={summary.get('emitted', 0)}",
        )
    except Exception as _hb_e:
        print(f"  heartbeat ping failed (non-fatal): {type(_hb_e).__name__}: {_hb_e}")
