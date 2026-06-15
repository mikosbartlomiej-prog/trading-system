"""v3.27.0 (2026-06-15) — ETAP 8 — Watchlist-aware monitor diagnostics.

WHY
---
v3.27 ETAP 7 produces ``learning-loop/trigger_watchlist_latest.json`` —
a curated Top-N list of (strategy, symbol) pairs the operator should
watch in real time. v3.24 ETAP 9 added a deterministic diagnostic JSONL
("did the monitor run? did it find a signal?"). This module is the
bridge: when a monitor scans a symbol, it asks this module
"is this symbol on the watchlist?" and the module emits one of four
watchlist-aware diagnostic tokens.

Tokens emitted (v3.27 additions to monitor_runtime_diag TOKEN_SET):
  * ``WATCHLIST_SYMBOL_SCANNED``   — the symbol IS on the watchlist
                                     and the monitor is about to scan it
  * ``WATCHLIST_NO_TRIGGER``       — scan finished, no candidate, no
                                     near-miss
  * ``WATCHLIST_NEAR_MISS``        — scan finished, no signal, but the
                                     distance is within the operator's
                                     near-miss band (default 15%)
  * ``WATCHLIST_TRIGGER_CROSSED``  — scan produced a signal candidate

CONTRACT
--------
- This module NEVER places orders.
- This module NEVER imports ``alpaca_orders``.
- This module NEVER makes network calls.
- This module NEVER mutates the trigger watchlist or any state.
- Every error is silently swallowed — the diagnostic writer must never
  break a monitor scan.

USAGE
-----
    from watchlist_diag import (
        load_watchlist_cache_for_scan,
        diag_watchlist_scan_started,
        diag_watchlist_scan_finished,
    )

    cache = load_watchlist_cache_for_scan()
    for symbol in symbols_to_scan:
        diag_watchlist_scan_started("price-monitor", symbol, cache)
        signal = detect_signal(symbol)
        diag_watchlist_scan_finished(
            "price-monitor", symbol, cache,
            signal_detected=bool(signal),
            distance=...,           # optional; if provided enables NEAR_MISS classification
            signal_id=...,          # optional; tagged on TRIGGER_CROSSED
        )
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

# Re-export the token constants under a friendlier alias for monitors.
try:
    from monitor_runtime_diag import (  # type: ignore
        record_diag,
        DIAG_WATCHLIST_SYMBOL_SCANNED,
        DIAG_WATCHLIST_NO_TRIGGER,
        DIAG_WATCHLIST_NEAR_MISS,
        DIAG_WATCHLIST_TRIGGER_CROSSED,
    )
except Exception:
    try:
        from shared.monitor_runtime_diag import (  # type: ignore
            record_diag,
            DIAG_WATCHLIST_SYMBOL_SCANNED,
            DIAG_WATCHLIST_NO_TRIGGER,
            DIAG_WATCHLIST_NEAR_MISS,
            DIAG_WATCHLIST_TRIGGER_CROSSED,
        )
    except Exception:
        # Final fallback: define no-op record_diag and string constants
        # so the helper's API never breaks the calling monitor.
        def record_diag(*_a: Any, **_kw: Any) -> bool:  # type: ignore
            return False
        DIAG_WATCHLIST_SYMBOL_SCANNED = "WATCHLIST_SYMBOL_SCANNED"
        DIAG_WATCHLIST_NO_TRIGGER = "WATCHLIST_NO_TRIGGER"
        DIAG_WATCHLIST_NEAR_MISS = "WATCHLIST_NEAR_MISS"
        DIAG_WATCHLIST_TRIGGER_CROSSED = "WATCHLIST_TRIGGER_CROSSED"


# Default near-miss band in distance-to-trigger units. If
# ``distance <= NEAR_MISS_BAND`` after a no-signal scan, we emit
# WATCHLIST_NEAR_MISS rather than WATCHLIST_NO_TRIGGER. Configurable via
# env var so operator tuning never needs a code change.
NEAR_MISS_BAND = float(
    os.environ.get("WATCHLIST_NEAR_MISS_BAND", "0.15")
)


def _watchlist_path() -> Path:
    """Resolve the trigger-watchlist JSON path.

    Honours env override ``TRIGGER_WATCHLIST_PATH`` (used by tests),
    falls back to ``learning-loop/trigger_watchlist_latest.json`` at the
    repo root.
    """
    env_override = os.environ.get("TRIGGER_WATCHLIST_PATH")
    if env_override:
        return Path(env_override)
    here = Path(__file__).resolve()
    return here.parent.parent / "learning-loop" / "trigger_watchlist_latest.json"


def load_watchlist_cache_for_scan(
    path: Optional[Path] = None,
) -> dict[str, dict[str, Any]]:
    """Read the watchlist JSON once and return a (symbol → row) map.

    Fail-soft: missing/malformed file returns an empty cache. Monitors
    should call this once at the top of a scan and pass the result to
    the diag helpers so we don't re-read disk per symbol.

    Returns a dict keyed by symbol — if the watchlist contains the same
    symbol under multiple strategies, the highest-priority row wins
    (P1 > P2 > P3 > BLOCKED).
    """
    target = path or _watchlist_path()
    out: dict[str, dict[str, Any]] = {}
    try:
        if not target.exists():
            return out
        raw = target.read_text(encoding="utf-8")
        d = json.loads(raw)
        rows = (d or {}).get("rows") or []
        if not isinstance(rows, list):
            return out
        priority_rank = {"P1": 1, "P2": 2, "P3": 3, "BLOCKED": 4}
        for r in rows:
            if not isinstance(r, dict):
                continue
            sym = r.get("symbol")
            if not sym:
                continue
            existing = out.get(sym)
            rp = priority_rank.get(r.get("priority", "BLOCKED"), 9)
            ep = (
                priority_rank.get(existing.get("priority", "BLOCKED"), 9)
                if existing else 9
            )
            if existing is None or rp < ep:
                out[sym] = r
    except Exception:
        return {}
    return out


def is_symbol_on_watchlist(
    cache: dict[str, dict[str, Any]] | None,
    symbol: str,
) -> bool:
    """Return True iff the symbol is currently on the watchlist."""
    if not cache or not symbol:
        return False
    return symbol in cache


def diag_watchlist_scan_started(
    monitor_name: str,
    symbol: str,
    cache: dict[str, dict[str, Any]] | None,
) -> bool:
    """Emit WATCHLIST_SYMBOL_SCANNED iff the symbol is on the watchlist.

    Returns True iff the token was emitted (i.e. the symbol IS on the
    watchlist), False otherwise. Fail-soft.
    """
    try:
        if not is_symbol_on_watchlist(cache, symbol):
            return False
        row = (cache or {}).get(symbol) or {}
        return bool(record_diag(
            monitor_name,
            DIAG_WATCHLIST_SYMBOL_SCANNED,
            {
                "symbol":             symbol,
                "watchlist_priority": row.get("priority"),
                "strategy_id":        row.get("strategy_id") or row.get("strategy"),
            },
        ))
    except Exception:
        return False


def diag_watchlist_scan_finished(
    monitor_name: str,
    symbol: str,
    cache: dict[str, dict[str, Any]] | None,
    *,
    signal_detected: bool,
    distance: Optional[float] = None,
    near_miss_band: Optional[float] = None,
    signal_id: Optional[str] = None,
    strategy_id_override: Optional[str] = None,
) -> Optional[str]:
    """Emit one of WATCHLIST_TRIGGER_CROSSED / WATCHLIST_NEAR_MISS /
    WATCHLIST_NO_TRIGGER based on scan outcome.

    No-op (returns None) if the symbol is NOT on the watchlist.

    Returns the emitted token string, or None when nothing was emitted.
    """
    try:
        if not is_symbol_on_watchlist(cache, symbol):
            return None
        row = (cache or {}).get(symbol) or {}
        strategy_id = (
            strategy_id_override
            or row.get("strategy_id")
            or row.get("strategy")
        )

        if signal_detected:
            record_diag(
                monitor_name,
                DIAG_WATCHLIST_TRIGGER_CROSSED,
                {
                    "symbol":      symbol,
                    "strategy":    strategy_id,
                    "signal_id":   signal_id,
                },
            )
            return DIAG_WATCHLIST_TRIGGER_CROSSED

        band = float(
            near_miss_band if near_miss_band is not None else NEAR_MISS_BAND
        )

        is_near_miss = False
        if isinstance(distance, (int, float)) and 0.0 <= float(distance) <= band:
            is_near_miss = True

        if is_near_miss:
            record_diag(
                monitor_name,
                DIAG_WATCHLIST_NEAR_MISS,
                {
                    "symbol":   symbol,
                    "distance": round(float(distance), 6) if distance is not None else None,
                    "band":     band,
                    "strategy": strategy_id,
                },
            )
            return DIAG_WATCHLIST_NEAR_MISS

        record_diag(
            monitor_name,
            DIAG_WATCHLIST_NO_TRIGGER,
            {
                "symbol":   symbol,
                "current_distance": (
                    round(float(distance), 6)
                    if isinstance(distance, (int, float)) else None
                ),
                "strategy": strategy_id,
            },
        )
        return DIAG_WATCHLIST_NO_TRIGGER
    except Exception:
        return None


__all__ = [
    "NEAR_MISS_BAND",
    "load_watchlist_cache_for_scan",
    "is_symbol_on_watchlist",
    "diag_watchlist_scan_started",
    "diag_watchlist_scan_finished",
]
