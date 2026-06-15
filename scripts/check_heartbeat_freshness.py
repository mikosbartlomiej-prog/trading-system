#!/usr/bin/env python3
"""scripts/check_heartbeat_freshness.py — v3.22 ETAP 10 (2026-06-15).

Operational-safety check: read the per-component heartbeats persisted in
``learning-loop/runtime_state.json::heartbeat`` and assert that every
EXPECTED_COMPONENT pinged recently enough to count as alive.

Thresholds:
  - market_session_stale_seconds = 7200   (2h during US market session)
  - non_market_stale_seconds     = 86400  (24h off-session / weekends)

Exit codes:
  0 — all components FRESH
  2 — at least one STALE (during the relevant window)
  3 — at least one MISSING (during US market session only — off-session
      we tolerate missing components because some monitors are session-only)

Artefacts:
  - learning-loop/heartbeat_freshness_latest.json
  - docs/HEARTBEAT_FRESHNESS_STATUS.md

NEVER places trades. NEVER imports ``shared.alpaca_orders`` (or
``alpaca_orders``).  Read-only over runtime_state.json + the configured
US-market-hours helper.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "shared"))

# Heartbeat module is mandatory for this script — fail-soft if absent.
try:
    import heartbeat  # type: ignore
except Exception as e:  # pragma: no cover — heartbeat ships with repo
    print(f"FATAL: cannot import shared/heartbeat.py: {e}")
    sys.exit(1)


MARKET_SESSION_STALE_SECONDS = 2 * 3600   # 7200
NON_MARKET_STALE_SECONDS     = 24 * 3600  # 86400


# ─── Status enum ────────────────────────────────────────────────────────────

STATUS_FRESH   = "FRESH"
STATUS_STALE   = "STALE"
STATUS_MISSING = "MISSING"


# ─── Market hours detection ─────────────────────────────────────────────────

def _is_us_market_open_safe(now: datetime | None = None) -> tuple[bool, str]:
    """Best-effort market hours check, fail-soft to "closed".

    Spec: use ``shared/instrument_windows.py`` if available; else assume
    non-market on weekend. We dispatch via the canonical
    ``shared.market_hours.is_us_market_open`` because instrument_windows
    itself delegates there.
    """
    now = now or datetime.now(timezone.utc)
    try:
        from market_hours import is_us_market_open as _impl  # type: ignore
        return _impl(now)
    except Exception:
        try:
            from shared.market_hours import is_us_market_open as _impl  # type: ignore
            return _impl(now)
        except Exception:
            # Fallback: weekend → closed; weekday 13:30-20:00 UTC → open
            if now.weekday() >= 5:
                return False, "weekend (fallback)"
            hhmm = now.hour * 60 + now.minute
            if 13 * 60 + 30 <= hhmm <= 20 * 60:
                return True, "weekday session window (fallback)"
            return False, "weekday outside session window (fallback)"


# ─── Core check ─────────────────────────────────────────────────────────────

def _component_age_seconds(component: str, entries: dict,
                            now: datetime) -> Optional[float]:
    entry = entries.get(component)
    if not entry:
        return None
    last_iso = entry.get("last_seen_iso") if isinstance(entry, dict) else None
    if not last_iso:
        return None
    try:
        last_dt = datetime.fromisoformat(str(last_iso).replace("Z", "+00:00"))
    except Exception:
        return None
    return (now - last_dt).total_seconds()


def evaluate(now: datetime | None = None,
              components: tuple | None = None,
              market_session_threshold: float = MARKET_SESSION_STALE_SECONDS,
              non_market_threshold: float = NON_MARKET_STALE_SECONDS) -> dict:
    """Pure evaluation — returns a structured report. No I/O side-effects.

    Caller decides how to act on the report (print / write JSON / write MD).
    """
    now = now or datetime.now(timezone.utc)
    comp_list = tuple(components) if components is not None else heartbeat.EXPECTED_COMPONENTS

    entries = heartbeat.read() or {}

    is_open, market_reason = _is_us_market_open_safe(now)
    threshold = market_session_threshold if is_open else non_market_threshold

    per_component: list[dict] = []
    counts = {STATUS_FRESH: 0, STATUS_STALE: 0, STATUS_MISSING: 0}

    for c in comp_list:
        age = _component_age_seconds(c, entries, now)
        if age is None:
            status = STATUS_MISSING
            per_component.append({
                "component":         c,
                "status":            status,
                "age_seconds":       None,
                "threshold_seconds": threshold,
                "last_seen_iso":     (entries.get(c) or {}).get("last_seen_iso") if isinstance(entries.get(c), dict) else None,
            })
        elif age > threshold:
            status = STATUS_STALE
            per_component.append({
                "component":         c,
                "status":            status,
                "age_seconds":       age,
                "threshold_seconds": threshold,
                "last_seen_iso":     entries[c].get("last_seen_iso"),
            })
        else:
            status = STATUS_FRESH
            per_component.append({
                "component":         c,
                "status":            status,
                "age_seconds":       age,
                "threshold_seconds": threshold,
                "last_seen_iso":     entries[c].get("last_seen_iso"),
            })
        counts[status] += 1

    # Exit code per spec:
    #   - any MISSING during market session → 3
    #   - else any STALE                    → 2
    #   - else                              → 0
    exit_code = 0
    if is_open and counts[STATUS_MISSING] > 0:
        exit_code = 3
    elif counts[STATUS_STALE] > 0:
        exit_code = 2

    return {
        "generated_at_iso": now.isoformat(),
        "market_open":      is_open,
        "market_reason":    market_reason,
        "threshold_seconds": threshold,
        "thresholds": {
            "market_session_stale_seconds": market_session_threshold,
            "non_market_stale_seconds":     non_market_threshold,
        },
        "summary": {
            "fresh":   counts[STATUS_FRESH],
            "stale":   counts[STATUS_STALE],
            "missing": counts[STATUS_MISSING],
            "total":   len(comp_list),
        },
        "components": per_component,
        "exit_code":  exit_code,
        "version":    "v3.22.0",
    }


# ─── Renderers ──────────────────────────────────────────────────────────────

def _render_markdown(report: dict) -> str:
    lines: list[str] = []
    lines.append("# Heartbeat Freshness Status")
    lines.append("")
    lines.append(f"- Generated at: `{report['generated_at_iso']}`")
    mo = "OPEN" if report["market_open"] else "CLOSED"
    lines.append(f"- US market session: **{mo}** ({report['market_reason']})")
    lines.append(f"- Stale threshold in effect: `{int(report['threshold_seconds'])}s`")
    lines.append(f"- Exit code: `{report['exit_code']}`")
    lines.append("")
    s = report["summary"]
    lines.append(
        f"- Summary: FRESH={s['fresh']}, STALE={s['stale']}, "
        f"MISSING={s['missing']}, TOTAL={s['total']}"
    )
    lines.append("")
    lines.append("| Component | Status | Age (s) | Last seen |")
    lines.append("|---|---|---|---|")
    for c in report["components"]:
        age = c.get("age_seconds")
        age_s = "n/a" if age is None else f"{age:.0f}"
        last_seen = c.get("last_seen_iso") or "—"
        lines.append(f"| `{c['component']}` | {c['status']} | {age_s} | {last_seen} |")
    lines.append("")
    return "\n".join(lines) + "\n"


def _write_artefacts(report: dict) -> None:
    json_path = _REPO_ROOT / "learning-loop" / "heartbeat_freshness_latest.json"
    md_path   = _REPO_ROOT / "docs" / "HEARTBEAT_FRESHNESS_STATUS.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")


# ─── CLI ────────────────────────────────────────────────────────────────────

def _parse_as_of(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as e:
        raise SystemExit(f"--as-of parse failed: {e}")


def main() -> int:
    p = argparse.ArgumentParser(description="Heartbeat freshness check (v3.22 ETAP 10)")
    p.add_argument("--as-of", type=str, default=None,
                   help="Override 'now' (ISO-8601) for tests")
    p.add_argument("--json", action="store_true",
                   help="Print the report as JSON to stdout")
    p.add_argument("--no-write", action="store_true",
                   help="Skip writing artefact files (for tests)")
    args = p.parse_args()

    now = _parse_as_of(args.as_of)
    report = evaluate(now=now)

    if not args.no_write:
        try:
            _write_artefacts(report)
        except Exception as e:
            print(f"  artefact write failed (non-fatal): {e}")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_markdown(report))

    return int(report["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
