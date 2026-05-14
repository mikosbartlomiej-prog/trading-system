"""
PDTGuard v3.8 — intent-aware Pattern-Day-Trader protection.

Design overhaul (2026-05-14 evening, v3.8):

v3.7 problem: LOCKED mode blocked ALL new entries, including overnight-
intended opens that wouldn't have caused a day-trade. The result was the
system refusing to open positions even when the only PDT-relevant
constraint was the impending CLOSE of a same-day position.

Core insight:
  A day-trade is opening AND closing the SAME SYMBOL in the SAME SESSION.
  Opens alone never increment daytrade_count. Closes of overnight
  positions never increment it. Crypto is exempt entirely. Therefore:

    OPEN any asset                  → never PDT-blocking (BP gate only)
    OPEN with intent=intraday       → DEFER in RESTRICTED/LOCKED (would
                                       force a same-day close that burns
                                       the saved budget)
    CLOSE crypto                    → always ALLOW
    CLOSE stock, overnight position → always ALLOW (not a day-trade)
    CLOSE stock, same-day position  → budget-aware:
        OK / CAUTION  → ALLOW
        RESTRICTED    → DEFER unless emergency (save last slot)
        LOCKED        → BLOCK unless emergency
    Emergency CLOSE (SL / governor / PROFIT_LOCK / NEARDTH / REGIME)
                                    → always ALLOW regardless of mode

Mode classification (corrected thresholds, v3.8):
  OK         — daytrade_count = 0  (full budget)
  CAUTION    — daytrade_count = 1  (heads up; favour overnight holds)
  RESTRICTED — daytrade_count = 2  (save the last slot for emergency)
  LOCKED     — daytrade_count ≥ 3  (Alpaca paper bug zeros BP; broker rejects)

Intent enum (callers may pass to influence the decision):
  swing       — caller intends to hold ≥1 session (default — most signals)
  intraday    — caller is doing a same-day flip (price-monitor pre-EOD
                 entries, allocator REDUCE/EXIT during the session)
  emergency   — SL hit, governor force-close, PROFIT_LOCK harvest, NEARDTH,
                 REGIME mismatch, hard-loss EOD — always bypass DEFER

Asset awareness:
  Crypto symbols (slash in name like BTC/USD) are always ALLOWed — PDT
  rule does not apply to crypto trades regardless of cadence.
  Stocks + options share the same daytrade_count pool.

Public API (mostly unchanged from v3.7; intent parameter added):
    get_pdt_status(account=None, size_usd=0.0) -> PDTSnapshot
    is_potential_day_trade(symbol) -> bool
    evaluate_order(action, symbol, side, size_usd,
                   intent='swing', is_emergency=False,
                   snapshot=None, skip_intraday_check=False) -> dict
    record_decision(verdict, action, symbol, extra=None) -> None
    persist_snapshot(snapshot, actor='intraday-monitor') -> bool

Fail-soft contract: Alpaca unreachable / malformed account → mode='UNKNOWN',
allow everything. Defensive design — PDT protection is preventive, not
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

# Default thresholds — overridable via config/aggressive_profile.json
# section "pdt_protection" (loaded lazily so tests can monkeypatch).
DEFAULT_DT_LIMIT          = 3      # Regulator hard cap. 4th DT = DTMC.
DEFAULT_DT_CAUTION_AT     = 1      # 1 DT used → CAUTION (informational)
DEFAULT_DT_RESTRICTED_AT  = 2      # 2 DTs used → RESTRICTED (save 1 slot)
DEFAULT_BP_FLOOR_PCT      = 0.05   # BP/equity below 5% → CAUTION when otherwise OK
DEFAULT_BP_HARD_FLOOR_USD = 100.0  # Absolute floor (broker rejects tiny BP)


# Intent enum — captures caller's expectation of how the position will be
# held. Influences whether OPEN gets DEFER'd (intraday flip would burn the
# saved DT budget when closed) and how CLOSE decisions are classified.
INTENT_SWING       = "swing"        # default — held ≥1 session
INTENT_INTRADAY    = "intraday"     # planned same-day flip
INTENT_EMERGENCY   = "emergency"    # SL, governor force, PROFIT_LOCK, etc.


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
        # New v3.8: maximum portion of equity in a single SWING-only entry
        # (default 0.20 = 20%). Caller may consult to bias toward fewer,
        # larger swing trades when DT budget is tight.
        "swing_max_pct_equity": float(cfg.get("swing_max_pct_equity", 0.20)),
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


def _is_crypto(symbol: str) -> bool:
    """Crypto symbols are PDT-exempt (24/7 market)."""
    return bool(symbol) and "/" in symbol


# ─── Mode classification ─────────────────────────────────────────────────────


def _classify_mode(daytrade_count: int, is_pdt: bool, bp: float, equity: float,
                   size_usd: float, cfg: dict) -> tuple[str, str, int]:
    """
    Return (mode, reason, dt_remaining).

    Thresholds (v3.8 corrected):
      OK         — dt_used = 0  (full budget)
      CAUTION    — dt_used = 1  (favour overnight holds)
      RESTRICTED — dt_used = 2  (save last slot for emergency)
      LOCKED     — dt_used ≥ 3  (DT limit hit OR BP exhausted)
    """
    dt_limit   = max(1, cfg["dt_limit"])
    dt_used    = max(0, daytrade_count)
    dt_remain  = max(0, dt_limit - dt_used)
    bp_pct     = (bp / equity * 100.0) if equity > 0 else 0.0

    # LOCKED first (most restrictive).
    # NB: BP < size_usd is reported but no longer blocks at PDT layer —
    # risk_officer catches absolute BP-insufficient case downstream. Here
    # we still mark mode=LOCKED when DT count at-or-above limit (paper
    # account at dt=4 historically zeros BP) so callers can adapt.
    if dt_used >= dt_limit:
        return ("LOCKED", f"daytrade_count {dt_used} >= limit {dt_limit} (DTMC active)", dt_remain)
    if bp < cfg["bp_hard_floor_usd"]:
        return ("LOCKED", f"buying_power ${bp:,.0f} below hard floor ${cfg['bp_hard_floor_usd']:,.0f}", dt_remain)

    # RESTRICTED — save the last slot.
    if dt_used >= cfg["dt_restricted_at"]:
        return ("RESTRICTED", f"daytrade_count {dt_used} at limit-1 (save last slot for emergency)", dt_remain)

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
    if _is_crypto(symbol):
        return False   # crypto is exempt from PDT
    return bool(_fetch_today_filled_orders(symbol))


def _dt_impact(action: str, symbol: str, intent: str,
                same_day_open: bool) -> int:
    """
    Day-trade impact of this order: 0 means no daytrade_count consumed,
    1 means closing same-day position would increment count.

    Logic:
      crypto                          → 0
      OPEN                            → 0 (opens never consume — the close
                                          might, but that's a future event)
      OPEN intraday-intent in RESTRICTED+
                                      → caller side-decides (see eval_order)
      CLOSE crypto                    → 0
      CLOSE stock overnight           → 0
      CLOSE stock same-day            → 1
      CLOSE emergency (any)           → 1 but bypassed in eval_order
    """
    if _is_crypto(symbol):
        return 0
    if action == "OPEN":
        return 0
    if action == "CLOSE" and same_day_open:
        return 1
    return 0


def evaluate_order(action: str, symbol: str, side: str, size_usd: float,
                   intent: str = INTENT_SWING,
                   is_emergency: bool = False,
                   snapshot: PDTSnapshot | None = None,
                   skip_intraday_check: bool = False) -> dict:
    """
    Single gate point used by all order paths.

    Parameters:
      action:       "OPEN" (new entry/BUY/SELL_SHORT) or "CLOSE" (sell-to-close)
      symbol:       e.g. "AAPL", "BTC/USD", "AAPL260520P00295000"
      side:         alpaca side ("buy", "sell", "sell_short")
      size_usd:     dollar value of the order
      intent:       INTENT_SWING (default) | INTENT_INTRADAY | INTENT_EMERGENCY
                     Caller's expectation of holding period. Affects whether
                     an OPEN in RESTRICTED+ gets DEFER'd (intraday flip would
                     burn the saved budget when closed same-day).
      is_emergency: True for SL hits, governor force-close, PROFIT_LOCK,
                     NEARDTH, REGIME mismatch, hard-loss EOD — always
                     bypasses DEFER and only honours BP-floor LOCKED.
      snapshot:     pre-fetched PDTSnapshot (saves a /v2/account roundtrip)
      skip_intraday_check:
                     True ⇒ treat as "potential day trade" without
                     querying Alpaca (used in tests and crypto paths).

    Returns:
      {
        "decision":     "ALLOW" | "DEFER" | "BLOCK",
        "reason":       human-readable string,
        "mode":         PDT mode from snapshot,
        "dt_remaining": int,
        "dt_impact":    0 or 1,
        "intent":       echoed intent (for audit clarity),
        "snapshot":     snapshot.to_dict()
      }
    """
    cfg = _load_pdt_config()
    if not cfg["enabled"]:
        snap = snapshot or get_pdt_status(size_usd=size_usd)
        return _verdict("ALLOW", "pdt_guard disabled in config", snap,
                        dt_impact=0, intent=intent)

    snap = snapshot or get_pdt_status(size_usd=size_usd)
    action = (action or "").upper()
    intent = (intent or INTENT_SWING).lower()
    crypto = _is_crypto(symbol)

    # ── Mode UNKNOWN: trust risk_officer downstream. ──
    if snap.mode == "UNKNOWN":
        return _verdict("ALLOW", f"pdt_guard unknown state: {snap.reason}",
                        snap, dt_impact=0, intent=intent)

    # ── Crypto is fully PDT-exempt. ──
    if crypto:
        return _verdict("ALLOW", f"crypto exempt from PDT (mode={snap.mode})",
                        snap, dt_impact=0, intent=intent)

    # ── Determine same-day-open state for stocks/options. ──
    # OPENs never query (no impact); CLOSEs need to know whether the
    # position being closed was opened today.
    same_day = False
    if action == "CLOSE":
        same_day = skip_intraday_check or is_potential_day_trade(symbol)

    impact = _dt_impact(action, symbol, intent, same_day)

    # ── OPEN actions ──
    # Opens never consume daytrade_count themselves. Only blocked when:
    #   (a) BP < size_usd  — broker would reject; handled by risk_officer
    #       downstream, but we surface it here too for clean BLOCK.
    #   (b) intent=INTRADAY in RESTRICTED+ — the planned same-day close
    #       would burn the saved budget; ask caller to flip intent to
    #       SWING (overnight hold) or wait.
    if action == "OPEN":
        if snap.buying_power < size_usd and size_usd > 0:
            return _verdict("BLOCK",
                            f"BP ${snap.buying_power:,.0f} < required ${size_usd:,.0f}",
                            snap, dt_impact=0, intent=intent)
        if intent == INTENT_INTRADAY and snap.mode in ("RESTRICTED", "LOCKED"):
            return _verdict("DEFER",
                            f"OPEN intraday-intent blocked in {snap.mode} "
                            f"(would force a budgeted close); flip to "
                            f"intent=swing to hold overnight",
                            snap, dt_impact=0, intent=intent)
        return _verdict("ALLOW",
                        f"OPEN allowed in {snap.mode} (intent={intent}, "
                        f"BP=${snap.buying_power:,.0f} ≥ ${size_usd:,.0f})",
                        snap, dt_impact=0, intent=intent)

    # ── CLOSE actions ──
    if action == "CLOSE":
        # Overnight positions or non-crypto with no same-day open: free.
        if not same_day:
            return _verdict("ALLOW",
                            f"CLOSE overnight position (no day-trade impact, "
                            f"mode={snap.mode})",
                            snap, dt_impact=0, intent=intent)

        # Same-day close. Emergency always allowed regardless of mode.
        if is_emergency:
            return _verdict("ALLOW",
                            f"CLOSE emergency honored in {snap.mode} "
                            f"(saved DT budget intentionally spent)",
                            snap, dt_impact=1, intent=intent)

        # Same-day discretionary close — budget-aware decision.
        if snap.mode == "LOCKED":
            return _verdict("BLOCK",
                            f"CLOSE discretionary blocked in LOCKED "
                            f"(daytrade_count {snap.daytrade_count} ≥ "
                            f"{snap.dt_limit}); emergency would proceed",
                            snap, dt_impact=1, intent=intent)
        if snap.mode == "RESTRICTED":
            return _verdict("DEFER",
                            f"CLOSE discretionary DEFER in RESTRICTED "
                            f"(save last DT slot for emergency; "
                            f"daytrade_count {snap.daytrade_count}/{snap.dt_limit})",
                            snap, dt_impact=1, intent=intent)
        if snap.mode == "CAUTION":
            return _verdict("ALLOW",
                            f"CLOSE discretionary in CAUTION — "
                            f"after-this {snap.daytrade_count+1}/{snap.dt_limit}",
                            snap, dt_impact=1, intent=intent)
        # OK mode
        return _verdict("ALLOW",
                        f"CLOSE same-day in OK ({snap.daytrade_count+1}/{snap.dt_limit} "
                        f"after this DT)",
                        snap, dt_impact=1, intent=intent)

    # Unknown action — fail-soft.
    return _verdict("ALLOW", f"unknown action '{action}' — fail-soft permissive",
                    snap, dt_impact=0, intent=intent)


def _verdict(decision: str, reason: str, snap: PDTSnapshot,
              dt_impact: int = 0, intent: str = INTENT_SWING) -> dict:
    """Internal: build the verdict dict consistently."""
    return {
        "decision":     decision,
        "reason":       reason,
        "mode":         snap.mode,
        "dt_remaining": snap.dt_remaining,
        "dt_impact":    dt_impact,
        "intent":       intent,
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
        "dt_impact":    verdict.get("dt_impact"),
        "intent":       verdict.get("intent"),
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
