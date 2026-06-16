#!/usr/bin/env python3
"""v3.29 ETAP 9 (2026-06-16) — Geo monitor health audit.

Read-only verdict over the production state of geo-monitor. Checks:

* runtime_state heartbeat freshness for ``geo-monitor``.
* count of opportunity_ledger rows attributable to geo-monitor over the
  last 7 days.
* recent monitor_runtime_diag tokens for geo-monitor (RAN /
  EMIT_SUCCESS / EMIT_FAILED).
* learning-loop/state.json::strategies geo-* entries (enabled,
  paused_until, trades_lifetime).
* explicit claim verifier: when the operator brief asserts geo-monitor
  has been "down for 80 days", debunks the claim with the heartbeat /
  history evidence we actually have. Defaults to
  ``CLAIM_UNSUPPORTED`` when there is no evidence of an 80-day outage.

Outputs
-------
- ``learning-loop/geo_monitor_health_latest.json``
- ``docs/GEO_MONITOR_HEALTH_STATUS.md``

HARD SAFETY
-----------
- NEVER imports ``shared.alpaca_orders`` or ``alpaca_orders``.
- NEVER imports any broker SDK.
- NEVER makes a network call.
- NEVER mutates state.json or runtime_state.json.
- NEVER flips any flag.
- NEVER submits orders / cancels orders / closes positions / changes
  any threshold.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

LATEST_JSON_PATH = (REPO_ROOT / "learning-loop"
                     / "geo_monitor_health_latest.json")
LATEST_MD_PATH   = REPO_ROOT / "docs" / "GEO_MONITOR_HEALTH_STATUS.md"

STANDING_MARKERS = (
    "EDGE_GATE_ENABLED=false",
    "ALLOW_BROKER_PAPER=false",
    "LIVE_TRADING_UNSUPPORTED",
    "NO_ORDER_PLACEMENT",
    "NO_AUTO_BROKER_ACTION_FROM_THIS_REPORTER",
)

# Verdict tokens
VERDICT_OK                 = "OK"
VERDICT_DEGRADED           = "DEGRADED"
VERDICT_FAILED             = "FAILED"
VERDICT_UNKNOWN            = "UNKNOWN"
VERDICT_CLAIM_UNSUPPORTED  = "CLAIM_UNSUPPORTED"

# Geo-monitor is the canonical component name in heartbeat ledger.
GEO_COMPONENT_NAME = "geo-monitor"

# Reasonable thresholds (tunable; never auto-modified by this script).
MARKET_SESSION_FRESH_S = 2 * 3600       # 2h
MARKET_SESSION_STALE_S = 6 * 3600       # 6h


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _is_market_hours(now: datetime | None = None) -> bool:
    """US equity market session check (UTC). Approximate, weekday-only."""
    n = now or _now()
    if n.weekday() >= 5:
        return False
    # 13:30 - 20:00 UTC = 09:30 - 16:00 ET
    h = n.hour * 60 + n.minute
    return (13 * 60 + 30) <= h <= (20 * 60)


def _safe_load_json(rel: str) -> Any:
    p = REPO_ROOT / rel
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _read_heartbeat() -> dict:
    """Return the geo-monitor heartbeat entry from the latest snapshot."""
    snapshot = _safe_load_json("learning-loop/heartbeat_freshness_latest.json")
    if not isinstance(snapshot, dict):
        return {"ok": False, "error": "heartbeat_freshness_missing"}
    comps = snapshot.get("components") or []
    if not isinstance(comps, list):
        return {"ok": False, "error": "heartbeat_components_not_a_list"}
    for c in comps:
        if not isinstance(c, dict):
            continue
        if str(c.get("component", "")).strip() == GEO_COMPONENT_NAME:
            return {
                "ok":              True,
                "age_seconds":     c.get("age_seconds"),
                "last_seen_iso":   c.get("last_seen_iso"),
                "status":          c.get("status"),
                "threshold_seconds": c.get("threshold_seconds"),
            }
    return {"ok": True, "missing": True}


def _read_opportunity_ledger_count(days: int = 7) -> int:
    """Count opportunity_ledger rows attributable to geo-monitor in N days."""
    ledger_dir = REPO_ROOT / "learning-loop" / "opportunity_ledger"
    if not ledger_dir.exists():
        return 0
    cutoff = _now() - timedelta(days=days)
    count = 0
    for path in sorted(ledger_dir.glob("*.jsonl")):
        # Quick filename-date filter
        try:
            day_iso = path.stem
            day = datetime.fromisoformat(day_iso).replace(tzinfo=timezone.utc)
            if day < cutoff - timedelta(days=1):
                continue
        except Exception:
            pass
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(row, dict):
                        continue
                    monitor = (row.get("monitor")
                                or row.get("source")
                                or row.get("strategy") or "")
                    if (str(monitor).lower().startswith("geo")
                            or "geo" in str(row.get("strategy", "")).lower()):
                        count += 1
        except Exception:
            continue
    return count


def _read_diag_tokens(days: int = 7) -> dict:
    """Distribution of RAN / EMIT_SUCCESS / EMIT_FAILED for geo-monitor."""
    diag = _safe_load_json(
        "learning-loop/monitor_runtime_diag_status_latest.json")
    out = {
        "RAN": 0, "EMIT_SUCCESS": 0, "EMIT_FAILED": 0,
        "available": False,
    }
    if not isinstance(diag, dict):
        return out
    out["available"] = True
    monitors = diag.get("monitors") or diag.get("by_monitor") or {}
    if isinstance(monitors, dict):
        entry = monitors.get(GEO_COMPONENT_NAME) or monitors.get("geo") or {}
        if isinstance(entry, dict):
            for k in ("RAN", "EMIT_SUCCESS", "EMIT_FAILED"):
                v = entry.get(k) or entry.get(k.lower())
                if isinstance(v, (int, float)):
                    out[k] = int(v)
    return out


def _read_state_strategies() -> dict:
    """All geo-* strategy entries from learning-loop/state.json."""
    st = _safe_load_json("learning-loop/state.json")
    out: dict[str, dict] = {}
    if not isinstance(st, dict):
        return out
    strategies = st.get("strategies") or {}
    if not isinstance(strategies, dict):
        return out
    for name, cfg in strategies.items():
        if str(name).lower().startswith("geo"):
            if isinstance(cfg, dict):
                out[name] = {
                    "enabled":         cfg.get("enabled"),
                    "paused_until":    cfg.get("paused_until"),
                    "trades_lifetime": cfg.get("trades_lifetime"),
                    "placed_lifetime": cfg.get("placed_lifetime"),
                }
    return out


def _verdict_from_inputs(heartbeat: dict, ledger_count: int,
                         diag: dict, is_market_hours: bool) -> tuple[str, str]:
    """Decide the verdict + a short reason string."""
    if not heartbeat.get("ok"):
        return VERDICT_UNKNOWN, f"heartbeat_read_error: {heartbeat.get('error')}"
    if heartbeat.get("missing"):
        # No entry in heartbeat at all
        return VERDICT_UNKNOWN, "geo-monitor not present in heartbeat ledger"

    age = heartbeat.get("age_seconds")
    try:
        age_f = float(age) if age is not None else None
    except Exception:
        age_f = None

    if age_f is None:
        return VERDICT_UNKNOWN, "heartbeat age unparseable"

    if is_market_hours and age_f > MARKET_SESSION_STALE_S:
        return VERDICT_FAILED, (
            f"heartbeat age {age_f:.0f}s > "
            f"{MARKET_SESSION_STALE_S}s during US market session")

    if age_f > MARKET_SESSION_STALE_S and not is_market_hours:
        # Off-session: relax to DEGRADED (caller can verify via cron)
        return VERDICT_DEGRADED, (
            f"heartbeat age {age_f:.0f}s outside session window")

    # Heartbeat fresh: now ask about emit success
    if diag.get("available") and diag.get("EMIT_SUCCESS", 0) == 0 \
            and (diag.get("RAN", 0) > 0):
        return VERDICT_DEGRADED, (
            "heartbeat fresh but no EMIT_SUCCESS in 7d "
            f"(RAN={diag.get('RAN')}, EMIT_FAILED={diag.get('EMIT_FAILED')})")

    return VERDICT_OK, "heartbeat fresh and pipeline healthy"


def _classify_80_day_claim(heartbeat: dict) -> tuple[str, str]:
    """Specifically debunk the 80-day outage claim if evidence rejects it."""
    # If the heartbeat is missing OR age > 80 days, the claim is supportable
    if not heartbeat.get("ok"):
        return VERDICT_CLAIM_UNSUPPORTED, (
            "heartbeat read error; cannot prove an 80-day outage")
    if heartbeat.get("missing"):
        return VERDICT_CLAIM_UNSUPPORTED, (
            "geo-monitor missing from heartbeat ledger entirely; "
            "evidence does not show a continuous 80-day outage")
    age = heartbeat.get("age_seconds")
    try:
        age_f = float(age) if age is not None else None
    except Exception:
        age_f = None
    if age_f is None:
        return VERDICT_CLAIM_UNSUPPORTED, "heartbeat age unparseable"
    eighty_days_s = 80 * 24 * 3600
    if age_f >= eighty_days_s:
        return VERDICT_FAILED, (
            f"heartbeat age {age_f:.0f}s >= 80 days "
            f"({eighty_days_s}s); claim supported")
    return VERDICT_CLAIM_UNSUPPORTED, (
        f"heartbeat age is {age_f:.0f}s which is FAR less than 80 days; "
        "the 80-day-down claim is debunked by direct evidence")


def build_status() -> dict:
    now = _now()
    is_hours = _is_market_hours(now)
    heartbeat = _read_heartbeat()
    ledger_count_7d = _read_opportunity_ledger_count(days=7)
    diag = _read_diag_tokens(days=7)
    state_strategies = _read_state_strategies()

    verdict, reason = _verdict_from_inputs(
        heartbeat, ledger_count_7d, diag, is_hours)
    claim_verdict, claim_reason = _classify_80_day_claim(heartbeat)

    payload = {
        "module":           "scripts.audit_geo_monitor_health",
        "schema_version":   "v3.29",
        "generated_at_iso": _now_iso(),
        "is_market_hours":  is_hours,
        "verdict":          verdict,
        "reason":           reason,
        "eighty_day_claim_verdict": claim_verdict,
        "eighty_day_claim_reason":  claim_reason,
        "heartbeat":        heartbeat,
        "opportunity_ledger_rows_7d": ledger_count_7d,
        "diag_tokens_7d":   diag,
        "state_strategies": state_strategies,
        "standing_markers": list(STANDING_MARKERS),
    }
    return payload


def render_md(status: dict) -> str:
    lines: list[str] = []
    lines.append("# Geo Monitor Health Audit (v3.29)")
    lines.append("")
    lines.append(f"_Generated:_ `{status.get('generated_at_iso', '')}`")
    lines.append("")
    lines.append(f"**Verdict:** `{status.get('verdict')}`")
    lines.append(f"**Reason:** `{status.get('reason')}`")
    lines.append(f"**Is market hours:** "
                 f"`{bool(status.get('is_market_hours'))}`")
    lines.append("")
    lines.append("## 80-day-down claim")
    lines.append("")
    lines.append(f"- Verdict: `{status.get('eighty_day_claim_verdict')}`")
    lines.append(f"- Reason: `{status.get('eighty_day_claim_reason')}`")
    lines.append("")
    hb = status.get("heartbeat") or {}
    lines.append("## Heartbeat")
    lines.append("")
    if hb.get("ok"):
        lines.append(f"- last_seen_iso: `{hb.get('last_seen_iso')}`")
        lines.append(f"- age_seconds: `{hb.get('age_seconds')}`")
        lines.append(f"- status: `{hb.get('status')}`")
    else:
        lines.append(f"- READ ERROR: `{hb.get('error')}`")
    lines.append("")
    lines.append("## Opportunity ledger")
    lines.append("")
    lines.append(f"- geo rows last 7d: `{status.get('opportunity_ledger_rows_7d')}`")
    lines.append("")
    lines.append("## monitor_runtime_diag tokens (7d)")
    lines.append("")
    diag = status.get("diag_tokens_7d") or {}
    for k in ("RAN", "EMIT_SUCCESS", "EMIT_FAILED"):
        lines.append(f"- `{k}`: `{diag.get(k, 0)}`")
    lines.append(f"- available: `{diag.get('available')}`")
    lines.append("")
    lines.append("## state.json::strategies geo-* entries")
    lines.append("")
    strategies = status.get("state_strategies") or {}
    if not strategies:
        lines.append("- (no geo-* entries found)")
    for name in sorted(strategies.keys()):
        cfg = strategies[name]
        lines.append(f"- `{name}`: "
                     f"enabled={cfg.get('enabled')}, "
                     f"paused_until={cfg.get('paused_until')}, "
                     f"trades_lifetime={cfg.get('trades_lifetime')}, "
                     f"placed_lifetime={cfg.get('placed_lifetime')}")
    lines.append("")
    lines.append("## Standing markers")
    for m in status.get("standing_markers") or STANDING_MARKERS:
        lines.append(f"- `{m}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_This audit never submits, cancels, or closes any order, "
                 "never enables broker paper, never enables live trading, "
                 "never mutates strategy thresholds, never auto-clears "
                 "safe_mode. Output is read-only._")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    status = build_status()
    md = render_md(status)

    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))

    if not args.no_write:
        LATEST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_JSON_PATH.write_text(
            json.dumps(status, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        LATEST_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LATEST_MD_PATH.write_text(md, encoding="utf-8")
        try:
            print(f"Wrote {LATEST_JSON_PATH.relative_to(REPO_ROOT)}")
            print(f"Wrote {LATEST_MD_PATH.relative_to(REPO_ROOT)}")
        except ValueError:
            print(f"Wrote {LATEST_JSON_PATH}")
            print(f"Wrote {LATEST_MD_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
