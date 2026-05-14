"""
PDTGuard — proactive Pattern-Day-Trader protection.

Problem this solves (2026-05-14 incident + recurring):
  Account in PDT lockout (daytrade_count=4 vs limit 3, buying_power=$0).
  Every 5-min monitor still tries to fire BUYs / EXITs; broker rejects 403
  with "insufficient buying power"; allocator keeps emitting plans the
  account literally cannot execute. Pre-existing guard in risk_officer
  catches the LOCKED state (BP < size_usd) but not the approaching-limit
  states. We want to DEFER non-emergency same-day closes BEFORE the 4th
  day-trade lands us in DTMC.

PDT rules (sub-$25k account):
  - 4+ day-trades in 5 rolling business days = Day Trading Margin Call.
  - A "day trade" = open + close same position same trading day.
  - Alpaca exposes `daytrade_count` (rolling 5-day window).

What this module changes:
  1. Defines 4 modes — OK / CAUTION / RESTRICTED / LOCKED — derived
     deterministically from (daytrade_count, pattern_day_trader, equity,
     buying_power, size_usd).
  2. Provides `evaluate_order()` — single gate point that returns
     ALLOW / DEFER / BLOCK with explicit reason. Wired into all 5 order
     entry/exit paths (alpaca_orders × 3, allocator, two exit monitors).
  3. Detects "potential day trade" by querying Alpaca for same-day filled
     orders on the symbol (authoritative — no local state required).
  4. Emits audit events to journal/autonomy/YYYY-MM-DD.jsonl for every
     non-ALLOW verdict.

Public API:
    get_pdt_status(account=None, size_usd=0.0) -> PDTSnapshot
        Reads Alpaca account, classifies mode, returns snapshot.
    is_potential_day_trade(symbol) -> bool
        True if there's a filled OPEN order for `symbol` today.
    evaluate_order(action, symbol, side, size_usd, is_emergency=False) -> dict
        Returns {decision, reason, mode, dt_remaining}.
    record_decision(snapshot, decision, reason, **ctx) -> None
        Emits audit event.

Fail-soft contract: Alpaca unreachable / malformed account → mode='OK',
allow everything. Defensive design: PDT protection is preventive, not
load-bearing. If we can't classify, we trust risk_officer downstream to
catch the absolute case (BP < size_usd).
"""

from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import requests
except ImportError:                                                            # pragma: no cover
    requests = None  # type: ignore

try:
    from runtime_state import read_section, merge_section
except ImportError:                                                            # pragma: no cover
    from shared.runtime_state import read_section, merge_section  # type: ignore


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ALPACA_BASE_URL = (
    os.environ.get("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets"
).rstrip("/")

# Configurable thresholds (override via config/aggressive_profile.json
# section "pdt_protection" — loaded lazily so tests can monkeypatch).
DEFAULT_DT_LIMIT          = 3      # Regulator hard cap. 4th DT = DTMC.
DEFAULT_DT_CAUTION_AT     = 2      # 2 DTs used → CAUTION mode
DEFAULT_DT_RESTRICTED_AT  = 3      # 3 DTs used → RESTRICTED (1 more = lockout)
DEFAULT_BP_FLOOR_PCT      = 0.05   # BP/equity below 5% → CAUTION even if DT OK
DEFAULT_BP_HARD_FLOOR_USD = 100.0  # Absolute floor (broker rejects tiny BP)


# ─── Snapshot dataclass ──────────────────────────────────────────────────────


@dataclass
class PDTSnapshot:
    """Read-only PDT classification."""
    equity:              float
    buying_power:        float
    daytrade_count:      int
    pattern_day_trader:  bool
    dt_limit:            int                  # default 3 for sub-$25k
    dt_remaining:        int                  # max(0, limit - used)
    bp_pct_equity:       float                # 0-100
    mode:                str                  # OK / CAUTION / RESTRICTED / LOCKED / UNKNOWN
    classified_at:       str                  # ISO UTC timestamp
    reason:              str = ""             # human explanation

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Config loader ───────────────────────────────────────────────────────────


def _load_pdt_config() -> dict:
    """Read pdt_protection from aggressive_profile.json with sane defaults."""
    path = os.path.join(_REPO_ROOT, "config", "aggressive_profile.json")
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f).get("pdt_protection") or {}
            if not isinstance(cfg, dict):
                cfg = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        cfg = {}
    return {
        "dt_limit":           int(cfg.get("dt_limit",           DEFAULT_DT_LIMIT)),
        "dt_caution_at":      int(cfg.get("dt_caution_at",      DEFAULT_DT_CAUTION_AT)),
        "dt_restricted_at":   int(cfg.get("dt_restricted_at",   DEFAULT_DT_RESTRICTED_AT)),
        "bp_floor_pct":       float(cfg.get("bp_floor_pct",     DEFAULT_BP_FLOOR_PCT)),
        "bp_hard_floor_usd":  float(cfg.get("bp_hard_floor_usd", DEFAULT_BP_HARD_FLOOR_USD)),
        "enabled":            bool(cfg.get("enabled", True)),
    }


# ─── Alpaca helpers (testable) ───────────────────────────────────────────────


def _headers() -> dict[str, str]:
    """Alpaca REST headers from env."""
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
        "Accept":              "application/json",
    }


def _fetch_account() -> dict | None:
    """GET /v2/account. Returns None on any failure (caller will fail-soft)."""
    if requests is None:
        return None
    headers = _headers()
    if not headers["APCA-API-KEY-ID"]:
        return None
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/account",
                         headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _fetch_today_filled_orders(symbol: str) -> list[dict]:
    """
    Return list of filled BUY/SELL_SHORT orders for `symbol` since today's
    UTC midnight. Empty list on any failure (treated as "no day trade
    risk" — defensive fail-open since this is a preventive check).
    """
    if requests is None:
        return []
    headers = _headers()
    if not headers["APCA-API-KEY-ID"]:
        return []
    after = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    params = {
        "status":  "closed",       # filled orders move to closed status
        "symbols": symbol,
        "after":   after,
        "limit":   "50",
    }
    qs = urllib.parse.urlencode(params)
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/v2/orders?{qs}",
                         headers=headers, timeout=10)
        if r.status_code != 200:
            return []
        orders = r.json() or []
        if not isinstance(orders, list):
            return []
        # Filter to OPEN-side fills only (we want to know "did we open
        # a position in this symbol today?").
        opens = [
            o for o in orders
            if o.get("status") == "filled"
            and o.get("side") in ("buy", "sell_short")
            and float(o.get("filled_qty") or 0) > 0
        ]
        return opens
    except Exception:
        return []


# ─── Mode classification ─────────────────────────────────────────────────────


def _classify_mode(daytrade_count: int, is_pdt: bool, bp: float, equity: float,
                   size_usd: float, cfg: dict) -> tuple[str, str, int]:
    """
    Return (mode, reason, dt_remaining).

    Modes:
      OK         — normal operations; intraday closes welcome
      CAUTION    — daytrade_count or BP getting tight; favour overnight holds
      RESTRICTED — one DT away from DTMC; defer non-emergency closes
      LOCKED     — BP exhausted OR DTs at limit; block new entries
    """
    dt_limit   = max(1, cfg["dt_limit"])
    dt_used    = max(0, daytrade_count)
    dt_remain  = max(0, dt_limit - dt_used)
    bp_pct     = (bp / equity * 100.0) if equity > 0 else 0.0

    # LOCKED first (most restrictive).
    if size_usd > 0 and bp < size_usd:
        return ("LOCKED", f"buying_power ${bp:,.0f} < required ${size_usd:,.0f}", dt_remain)
    if bp < cfg["bp_hard_floor_usd"]:
        return ("LOCKED", f"buying_power ${bp:,.0f} below hard floor ${cfg['bp_hard_floor_usd']:,.0f}", dt_remain)
    if dt_used >= dt_limit:
        return ("LOCKED", f"daytrade_count {dt_used} >= limit {dt_limit} (DTMC active)", dt_remain)

    # RESTRICTED — at the brink.
    if dt_used >= cfg["dt_restricted_at"]:
        return ("RESTRICTED", f"daytrade_count {dt_used} at limit-1 (next intraday close = DTMC)", dt_remain)

    # CAUTION — heading toward the brink.
    if dt_used >= cfg["dt_caution_at"]:
        return ("CAUTION", f"daytrade_count {dt_used} approaching limit {dt_limit}", dt_remain)
    if bp_pct < cfg["bp_floor_pct"] * 100.0:
        return ("CAUTION", f"buying_power {bp_pct:.1f}% of equity (under {cfg['bp_floor_pct']*100:.0f}% floor)", dt_remain)

    return ("OK", f"daytrade_count {dt_used}/{dt_limit}, BP {bp_pct:.0f}% equity", dt_remain)


# ─── Public API ───────────────────────────────────────────────────────────────


def get_pdt_status(account: dict | None = None, size_usd: float = 0.0) -> PDTSnapshot:
    """
    Fetch + classify PDT status. Pass `account` to use a pre-fetched dict
    (avoids redundant /v2/account calls). Fail-soft to mode='UNKNOWN' if
    Alpaca is unreachable — caller should treat as "no protection" and
    trust risk_officer downstream.
    """
    cfg = _load_pdt_config()
    if account is None:
        account = _fetch_account()

    if account is None:
        # Defensive: cannot read account → assume OK (no overlay) but log.
        return PDTSnapshot(
            equity=0.0, buying_power=0.0, daytrade_count=0,
            pattern_day_trader=False,
            dt_limit=cfg["dt_limit"], dt_remaining=cfg["dt_limit"],
            bp_pct_equity=0.0, mode="UNKNOWN",
            classified_at=datetime.now(timezone.utc).isoformat(),
            reason="account unreachable — PDT classification skipped",
        )

    try:
        equity   = float(account.get("equity") or 0.0)
        bp       = float(account.get("buying_power") or 0.0)
        dt_count = int(account.get("daytrade_count") or 0)
        is_pdt   = bool(account.get("pattern_day_trader"))
    except (TypeError, ValueError):
        return PDTSnapshot(
            equity=0.0, buying_power=0.0, daytrade_count=0,
            pattern_day_trader=False,
            dt_limit=cfg["dt_limit"], dt_remaining=cfg["dt_limit"],
            bp_pct_equity=0.0, mode="UNKNOWN",
            classified_at=datetime.now(timezone.utc).isoformat(),
            reason="account fields malformed — PDT classification skipped",
        )

    mode, reason, dt_remain = _classify_mode(
        dt_count, is_pdt, bp, equity, size_usd, cfg,
    )

    return PDTSnapshot(
        equity=equity, buying_power=bp, daytrade_count=dt_count,
        pattern_day_trader=is_pdt,
        dt_limit=cfg["dt_limit"], dt_remaining=dt_remain,
        bp_pct_equity=(bp / equity * 100.0) if equity > 0 else 0.0,
        mode=mode,
        classified_at=datetime.now(timezone.utc).isoformat(),
        reason=reason,
    )


def is_potential_day_trade(symbol: str) -> bool:
    """
    True iff there's a filled OPEN (buy/sell_short) order for `symbol`
    today — closing now would count as a day trade.
    """
    if not symbol:
        return False
    return bool(_fetch_today_filled_orders(symbol))


def evaluate_order(action: str, symbol: str, side: str, size_usd: float,
                   is_emergency: bool = False,
                   snapshot: PDTSnapshot | None = None,
                   skip_intraday_check: bool = False) -> dict:
    """
    Single gate point used by all order paths.

    action:        "OPEN" (new entry/BUY/SELL_SHORT) or "CLOSE" (sell-to-close)
    symbol:        e.g. "AAPL", "BTC/USD", "AAPL260520P00295000"
    side:          alpaca side ("buy", "sell", "sell_short")
    size_usd:      dollar value of the order (used for BP check)
    is_emergency:  True for SL hits, governor force-close, hard-loss exits
                   — bypasses DEFER and only honours LOCKED
    snapshot:      pre-fetched PDTSnapshot (saves a /v2/account roundtrip)
    skip_intraday_check: True for crypto (no PDT; 24/7 market) and options
                   (options ARE subject to PDT but check tracks differently)

    Returns:
      {
        "decision": "ALLOW" | "DEFER" | "BLOCK",
        "reason":   human-readable string,
        "mode":     PDT mode from snapshot,
        "dt_remaining": int,
        "snapshot": snapshot.to_dict()
      }
    """
    cfg = _load_pdt_config()
    if not cfg["enabled"]:
        snap = snapshot or get_pdt_status(size_usd=size_usd)
        return {
            "decision":     "ALLOW", "reason": "pdt_guard disabled in config",
            "mode":         snap.mode, "dt_remaining": snap.dt_remaining,
            "snapshot":     snap.to_dict(),
        }

    snap = snapshot or get_pdt_status(size_usd=size_usd)
    action = (action or "").upper()

    # Crypto is exempt (24/7 market, not subject to PDT rule). Options are
    # subject but Alpaca's daytrade_count already counts options legs, so
    # the standard flow handles them.
    asset_is_crypto = "/" in symbol

    # Mode-based decisions ─────────────────────────────────────────────────
    if snap.mode == "UNKNOWN":
        # Defensive fail-open: trust risk_officer downstream.
        return {
            "decision":     "ALLOW", "reason": f"pdt_guard unknown state: {snap.reason}",
            "mode":         "UNKNOWN", "dt_remaining": snap.dt_remaining,
            "snapshot":     snap.to_dict(),
        }

    if snap.mode == "LOCKED":
        # Hard block — broker will reject anyway. Emergency closes are an
        # exception: we still want to attempt them (the position needs to
        # die regardless of BP).
        if action == "CLOSE" and is_emergency:
            return {
                "decision":     "ALLOW",
                "reason":       f"LOCKED but emergency close honored: {snap.reason}",
                "mode":         snap.mode, "dt_remaining": snap.dt_remaining,
                "snapshot":     snap.to_dict(),
            }
        return {
            "decision":     "BLOCK",
            "reason":       f"PDT LOCKED — {snap.reason}",
            "mode":         snap.mode, "dt_remaining": snap.dt_remaining,
            "snapshot":     snap.to_dict(),
        }

    if snap.mode == "RESTRICTED":
        if asset_is_crypto:
            return {
                "decision":     "ALLOW",
                "reason":       f"crypto exempt from PDT (mode {snap.mode})",
                "mode":         snap.mode, "dt_remaining": snap.dt_remaining,
                "snapshot":     snap.to_dict(),
            }
        if action == "CLOSE":
            if is_emergency:
                return {
                    "decision":     "ALLOW",
                    "reason":       f"RESTRICTED but emergency close honored ({snap.reason})",
                    "mode":         snap.mode, "dt_remaining": snap.dt_remaining,
                    "snapshot":     snap.to_dict(),
                }
            # Non-emergency close: defer if it would be a day trade.
            if skip_intraday_check or is_potential_day_trade(symbol):
                return {
                    "decision":     "DEFER",
                    "reason":       (f"RESTRICTED: non-emergency intraday close would "
                                     f"trigger DTMC (daytrade_count {snap.daytrade_count}/{snap.dt_limit})"),
                    "mode":         snap.mode, "dt_remaining": snap.dt_remaining,
                    "snapshot":     snap.to_dict(),
                }
            # Position opened on a previous day → not a day trade → allow.
            return {
                "decision":     "ALLOW",
                "reason":       f"RESTRICTED but overnight position (not a day trade)",
                "mode":         snap.mode, "dt_remaining": snap.dt_remaining,
                "snapshot":     snap.to_dict(),
            }
        # OPEN action — allow but expect overnight hold required.
        return {
            "decision":     "ALLOW",
            "reason":       f"RESTRICTED: opening allowed; MUST hold overnight ({snap.reason})",
            "mode":         snap.mode, "dt_remaining": snap.dt_remaining,
            "snapshot":     snap.to_dict(),
        }

    if snap.mode == "CAUTION":
        # CAUTION still allows everything, just flags it.
        return {
            "decision":     "ALLOW",
            "reason":       f"CAUTION mode (allowed with warning): {snap.reason}",
            "mode":         snap.mode, "dt_remaining": snap.dt_remaining,
            "snapshot":     snap.to_dict(),
        }

    # OK mode
    return {
        "decision":     "ALLOW",
        "reason":       f"OK ({snap.reason})",
        "mode":         snap.mode, "dt_remaining": snap.dt_remaining,
        "snapshot":     snap.to_dict(),
    }


# ─── Audit emission ──────────────────────────────────────────────────────────


def record_decision(verdict: dict, action: str, symbol: str,
                    extra: dict | None = None) -> None:
    """
    Emit non-ALLOW decisions to today's autonomy JSONL. Best-effort —
    audit write must never break the order path.
    """
    decision = verdict.get("decision", "")
    if decision == "ALLOW":
        return
    try:
        from audit import write_audit_event
    except ImportError:
        try:
            from shared.audit import write_audit_event  # type: ignore
        except ImportError:
            return

    payload = {
        "ts":           datetime.now(timezone.utc).isoformat(),
        "decision":     f"PDT_{decision}",
        "actor":        "pdt_guard",
        "action":       action,
        "symbol":       symbol,
        "mode":         verdict.get("mode"),
        "dt_remaining": verdict.get("dt_remaining"),
        "reason":       verdict.get("reason"),
    }
    if extra:
        payload["context"] = extra

    try:
        write_audit_event(payload, kind="trading")
    except Exception:
        pass


# ─── Snapshot persistence (read-only by default) ─────────────────────────────


def persist_snapshot(snapshot: PDTSnapshot, actor: str = "intraday-monitor") -> bool:
    """
    Best-effort persist of latest snapshot to runtime_state.json::pdt_status.
    Other monitors can read this to avoid hitting Alpaca again within
    the same cron window. Fail-soft: returns False if not allowed.
    """
    try:
        merge_section("pdt_status", snapshot.to_dict(), actor=actor)
        return True
    except Exception:
        return False


def read_snapshot_from_runtime() -> dict:
    """Read last persisted snapshot. Empty dict if absent."""
    return read_section("pdt_status")
