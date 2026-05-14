"""
IntradayProfitGovernor — defends intraday P&L peaks deterministically.

Problem this solves (2026-05-12 disaster + recurring pattern):
  System reaches +$5,000 intraday, gives it all back and ends -$2,000.
  v3.3 peak_tracker added WARN (30% retrace) / PROFIT_LOCK (50% retrace),
  but (a) only fired email alerts + harvested options winners, (b) state
  was written to learning-loop/state.json which 5-min monitors are no
  longer allowed to commit (rule C). Net effect in production: peak was
  re-initialised to current every cron tick, retrace was always ~0, and
  the cascade never armed.

What this module changes:
  1. Storage moves to learning-loop/runtime_state.json (a separate file
     custodied by exit-monitor with `contents: write`). State now survives
     across cron ticks.
  2. FSM extended from 3 states (NORMAL/WARN/PROFIT_LOCK) to 7:
        FLAT  → GREEN  → STRONG_GREEN
                  ↓         ↓
              GIVEBACK_WARN (retrace ≥ 25% of peak ≥ $1k)
                  ↓
              PROFIT_LOCK (retrace ≥ 35%)
                  ↓
              DEFEND_DAY (retrace ≥ 50%)
                  ↓
              RED_DAY_AFTER_GREEN (current ≤ 0 after peak ≥ min_to_arm)
     Once entered, advanced states never downgrade within the same UTC day.
  3. Each state maps to a deterministic action bundle:
       max_gross_exposure target, options-first reduction, entry block,
       harvest threshold, profit floor.
  4. Profit floor: dynamic $ floor proportional to peak (tier-based).
  5. Audit events written to journal/autonomy/YYYY-MM-DD.jsonl for every
     transition and every gate decision.

Public API:
    update(account_status) -> IntradaySnapshot
        Called by exit-monitor once per cron. Pulls equity, updates peak,
        computes state transition, persists snapshot.
    get_snapshot() -> IntradaySnapshot
        Read-only accessor for entry monitors and options-exit-monitor.
    block_new_entries(symbol=None, score=None) -> (bool, reason)
        Pre-trade gate. False means "allow"; True means "block, with reason".
    max_gross_exposure_target() -> float
        Dynamic gross-exposure ceiling driven by FSM state.
    should_close_options_first() -> bool
        True in PROFIT_LOCK/DEFEND_DAY/RED_DAY_AFTER_GREEN.
    profit_floor_usd() -> float | None
        Minimum acceptable end-of-day PnL given current peak.
    position_mfe_action(position) -> dict
        Position-level MFE/retrace verdict.

Config-driven defaults live in config/aggressive_profile.json under
`intraday_profit_protection` (Phase 14 of the spec).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from runtime_state import read_section, write_section, merge_section
except ImportError:                                                          # pragma: no cover
    from shared.runtime_state import read_section, write_section, merge_section  # type: ignore

try:
    from runtime_config import _bool                                         # private but reused
except ImportError:                                                          # pragma: no cover
    from shared.runtime_config import _bool  # type: ignore


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROFILE_PATH = os.path.join(_REPO_ROOT, "config", "aggressive_profile.json")


# ─── FSM states ──────────────────────────────────────────────────────────────

STATE_NEW_DAY            = "NEW_DAY"
STATE_FLAT               = "FLAT"
STATE_GREEN              = "GREEN"
STATE_STRONG_GREEN       = "STRONG_GREEN"
STATE_GIVEBACK_WARN      = "GIVEBACK_WARN"
STATE_PROFIT_LOCK        = "PROFIT_LOCK"
STATE_DEFEND_DAY         = "DEFEND_DAY"
STATE_RED_DAY_AFTER_GREEN = "RED_DAY_AFTER_GREEN"

# Once we land in one of these, we stay there for the rest of the UTC day.
TERMINAL_STATES = frozenset({
    STATE_PROFIT_LOCK,
    STATE_DEFEND_DAY,
    STATE_RED_DAY_AFTER_GREEN,
})

# Ordering used to enforce one-way ratchet.
STATE_ORDER = (
    STATE_NEW_DAY, STATE_FLAT, STATE_GREEN, STATE_STRONG_GREEN,
    STATE_GIVEBACK_WARN, STATE_PROFIT_LOCK, STATE_DEFEND_DAY,
    STATE_RED_DAY_AFTER_GREEN,
)
_STATE_RANK = {s: i for i, s in enumerate(STATE_ORDER)}


# ─── Defaults (overridden by aggressive_profile.json) ────────────────────────

_DEFAULTS: dict[str, Any] = {
    "enabled":                     True,
    "min_profit_to_arm_usd":       1000.0,
    "min_profit_to_arm_pct":       0.01,
    "strong_profit_usd":           3000.0,
    "strong_profit_pct":           0.03,
    "major_profit_usd":            5000.0,
    "major_profit_pct":            0.05,
    "giveback_warn_pct_of_peak":   0.25,
    "profit_lock_pct_of_peak":     0.35,
    "defend_day_pct_of_peak":      0.50,
    "red_after_green_pct_of_peak": 0.60,
    "block_new_entries_on_defend_day":     True,
    "block_new_entries_on_red_after_green": True,
    "reduce_options_first":        True,
    "reduce_weak_positions_first": True,
    "allow_hedges_during_defend_day": True,
    # Per-state gross-exposure caps (gross/equity ratio).
    "normal_max_gross":            1.50,
    "giveback_warn_max_gross":     1.25,
    "profit_lock_max_gross":       1.00,
    "defend_day_max_gross":        0.50,
    "red_after_green_max_gross":   0.25,
    # Profit-floor tiers.
    "tier_1_peak_usd":             1000.0,
    "tier_1_lock_ratio":           0.25,
    "tier_2_peak_usd":             3000.0,
    "tier_2_lock_ratio":           0.40,
    "tier_3_peak_usd":             5000.0,
    "tier_3_lock_ratio":           0.50,
    # Allow high-score signals through PROFIT_LOCK gate.
    "profit_lock_min_score_override": 0.65,
    # Position-level MFE harvest rules.
    "mfe_tier1_peak_pct":          0.08,
    "mfe_tier1_retrace_pct":       0.40,
    "mfe_tier1_reduce_pct":        0.50,
    "mfe_tier2_peak_pct":          0.12,
    "mfe_tier2_retrace_pct":       0.35,
    "mfe_tier2_reduce_pct":        0.75,
    "mfe_tier3_peak_pct":          0.20,
    "mfe_tier3_retrace_pct":       0.25,
    "mfe_tier3_reduce_pct":        1.00,
}


def _load_config() -> dict[str, Any]:
    """Merge intraday_profit_protection from aggressive_profile.json onto defaults."""
    try:
        with open(_PROFILE_PATH, encoding="utf-8") as f:
            profile = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULTS)
    cfg = dict(_DEFAULTS)
    section = profile.get("intraday_profit_protection") or {}
    for k, v in section.items():
        if not k.startswith("_") and k in _DEFAULTS:
            cfg[k] = v
    floor = profile.get("profit_floor") or {}
    for k in ("tier_1_peak_usd", "tier_1_lock_ratio",
              "tier_2_peak_usd", "tier_2_lock_ratio",
              "tier_3_peak_usd", "tier_3_lock_ratio"):
        if k in floor:
            cfg[k] = floor[k]
    exposure = profile.get("intraday_exposure_reduction") or {}
    for src, dst in (
        ("normal_max_gross",          "normal_max_gross"),
        ("giveback_warn_max_gross",   "giveback_warn_max_gross"),
        ("profit_lock_max_gross",     "profit_lock_max_gross"),
        ("defend_day_max_gross",      "defend_day_max_gross"),
        ("red_after_green_max_gross", "red_after_green_max_gross"),
    ):
        if src in exposure:
            cfg[dst] = exposure[src]
    return cfg


# ─── Snapshot dataclass (serialised to runtime_state.json) ────────────────────

@dataclass
class IntradaySnapshot:
    """Frozen view of the governor's state for one cron tick."""

    date: str                  = ""
    session_start_equity: float = 0.0   # = account.last_equity (Alpaca's close-of-prev-day)
    current_equity: float      = 0.0
    intraday_peak_equity: float = 0.0
    intraday_peak_pnl: float   = 0.0
    intraday_peak_pnl_pct: float = 0.0
    peak_at: str               = ""
    current_intraday_pnl: float = 0.0
    current_intraday_pnl_pct: float = 0.0
    giveback_usd: float        = 0.0
    giveback_pct_of_peak: float = 0.0
    pnl_state: str             = STATE_NEW_DAY
    state_entered_at: str      = ""
    profit_floor_usd: float    = 0.0
    max_gross_target: float    = 1.50
    block_new_entries: bool    = False
    options_first_reduction: bool = False
    alerts_sent: dict          = field(default_factory=dict)
    last_update_at: str        = ""
    last_action: str           = ""
    # Diagnostic: positions that contributed most to giveback (filled when
    # exit-monitor passes them in; lightweight string list of symbols).
    top_giveback_symbols: list = field(default_factory=list)
    # Was account-data missing this tick? (Caller is then required to
    # block new entries — see spec §G "Fail behavior".)
    account_unavailable: bool  = False

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _max_state(a: str, b: str) -> str:
    """Return the more advanced of two states (ratchet)."""
    return a if _STATE_RANK.get(a, 0) >= _STATE_RANK.get(b, 0) else b


def _compute_state(snapshot: IntradaySnapshot, cfg: dict, prev_state: str) -> str:
    """
    Deterministic state machine. Inputs:
      - snapshot (just-computed peak/current/giveback)
      - cfg      (thresholds)
      - prev_state (so we honor the ratchet)
    """
    peak_usd = snapshot.intraday_peak_pnl
    peak_pct = snapshot.intraday_peak_pnl_pct
    cur_usd  = snapshot.current_intraday_pnl
    giveback = snapshot.giveback_pct_of_peak

    # Threshold: peak must arm protection before we even start ratcheting.
    armed = (peak_usd >= cfg["min_profit_to_arm_usd"]
             or peak_pct >= cfg["min_profit_to_arm_pct"])

    if not armed:
        # Still in pre-arm zone — track whether we're flat or just green.
        if cur_usd >= cfg["min_profit_to_arm_usd"] * 0.5:
            new_state = STATE_GREEN
        elif cur_usd > 0:
            new_state = STATE_GREEN if prev_state != STATE_NEW_DAY else STATE_FLAT
        else:
            new_state = STATE_FLAT if prev_state == STATE_NEW_DAY else prev_state
        return _max_state(prev_state, new_state) if prev_state in TERMINAL_STATES else new_state

    # Green-to-red short-circuit (spec §8) — peak armed but current ≤ 0
    # OR (peak ≥ major_profit_usd AND current ≤ 2000)  → RED_DAY_AFTER_GREEN.
    is_green_to_red = (cur_usd <= 0.0) or (
        peak_usd >= cfg["major_profit_usd"] and cur_usd <= 2000.0
        and giveback >= cfg["red_after_green_pct_of_peak"]
    )
    if is_green_to_red:
        return STATE_RED_DAY_AFTER_GREEN

    # Cascade by retrace percent.
    if giveback >= cfg["red_after_green_pct_of_peak"]:
        new_state = STATE_RED_DAY_AFTER_GREEN
    elif giveback >= cfg["defend_day_pct_of_peak"]:
        new_state = STATE_DEFEND_DAY
    elif giveback >= cfg["profit_lock_pct_of_peak"]:
        new_state = STATE_PROFIT_LOCK
    elif giveback >= cfg["giveback_warn_pct_of_peak"]:
        new_state = STATE_GIVEBACK_WARN
    elif peak_usd >= cfg["strong_profit_usd"] or peak_pct >= cfg["strong_profit_pct"]:
        new_state = STATE_STRONG_GREEN
    else:
        new_state = STATE_GREEN

    # Once in a terminal state today, never downgrade.
    return _max_state(prev_state, new_state)


def _profit_floor(peak_usd: float, cfg: dict) -> float:
    """
    Locked profit = peak × tier-dependent lock_ratio.

    Tiers (matches spec §9):
      peak ≥ tier_3_peak_usd  → tier_3_lock_ratio  (default 0.50)
      peak ≥ tier_2_peak_usd  → tier_2_lock_ratio  (0.40)
      peak ≥ tier_1_peak_usd  → tier_1_lock_ratio  (0.25)
      peak <  tier_1_peak_usd → 0  (no floor yet)
    """
    if peak_usd >= cfg["tier_3_peak_usd"]:
        return peak_usd * cfg["tier_3_lock_ratio"]
    if peak_usd >= cfg["tier_2_peak_usd"]:
        return peak_usd * cfg["tier_2_lock_ratio"]
    if peak_usd >= cfg["tier_1_peak_usd"]:
        return peak_usd * cfg["tier_1_lock_ratio"]
    return 0.0


def _max_gross_for_state(state: str, cfg: dict) -> float:
    return {
        STATE_NEW_DAY:             cfg["normal_max_gross"],
        STATE_FLAT:                cfg["normal_max_gross"],
        STATE_GREEN:               cfg["normal_max_gross"],
        STATE_STRONG_GREEN:        cfg["normal_max_gross"],
        STATE_GIVEBACK_WARN:       cfg["giveback_warn_max_gross"],
        STATE_PROFIT_LOCK:         cfg["profit_lock_max_gross"],
        STATE_DEFEND_DAY:          cfg["defend_day_max_gross"],
        STATE_RED_DAY_AFTER_GREEN: cfg["red_after_green_max_gross"],
    }.get(state, cfg["normal_max_gross"])


# ─── Public API ──────────────────────────────────────────────────────────────

def update(account: Optional[dict] = None,
           top_giveback_symbols: Optional[list[str]] = None) -> IntradaySnapshot:
    """
    Recompute snapshot from current account state, persist, return snapshot.

    `account` is a dict in the get_account_status() shape:
        {"equity": float, "last_equity": float, ...}
    If None, governor marks `account_unavailable=True` and the snapshot's
    block_new_entries=True (spec §G fail-closed for new entries).

    Caller (exit-monitor) is expected to invoke this once per cron run, then
    consult the returned snapshot's `last_action` to decide whether to emit
    an alert, harvest winners, etc.
    """
    cfg = _load_config()
    if not cfg["enabled"]:
        snap = IntradaySnapshot(date=_today(), pnl_state=STATE_FLAT,
                                max_gross_target=cfg["normal_max_gross"])
        snap.last_update_at = _utcnow_iso()
        write_section("intraday_governor", snap.to_dict())
        return snap

    prev_raw = read_section("intraday_governor")
    today = _today()
    new_day = (prev_raw.get("date") != today)
    prev_state = STATE_NEW_DAY if new_day else (prev_raw.get("pnl_state") or STATE_NEW_DAY)
    prev_peak_pnl = 0.0 if new_day else float(prev_raw.get("intraday_peak_pnl") or 0.0)
    prev_peak_equity = 0.0 if new_day else float(prev_raw.get("intraday_peak_equity") or 0.0)
    prev_peak_at = "" if new_day else (prev_raw.get("peak_at") or "")
    prev_alerts = {} if new_day else (prev_raw.get("alerts_sent") or {})
    prev_state_entered_at = "" if new_day else (prev_raw.get("state_entered_at") or "")

    # Account state missing → fail-closed for new entries, but keep prior peak.
    if account is None or not isinstance(account, dict):
        snap = IntradaySnapshot(
            date=today,
            pnl_state=prev_state,
            intraday_peak_pnl=prev_peak_pnl,
            intraday_peak_equity=prev_peak_equity,
            peak_at=prev_peak_at,
            account_unavailable=True,
            block_new_entries=True,
            alerts_sent=prev_alerts,
            state_entered_at=prev_state_entered_at,
            last_update_at=_utcnow_iso(),
            last_action="account_unavailable_block_new_entries",
            max_gross_target=_max_gross_for_state(prev_state, cfg),
            options_first_reduction=(prev_state in TERMINAL_STATES),
        )
        write_section("intraday_governor", snap.to_dict())
        return snap

    equity      = float(account.get("equity") or 0.0)
    last_equity = float(account.get("last_equity") or 0.0)
    if last_equity <= 0:
        # Brand-new account or Alpaca returned 0 — treat like unavailable.
        snap = IntradaySnapshot(
            date=today, pnl_state=prev_state, account_unavailable=True,
            block_new_entries=True, last_update_at=_utcnow_iso(),
            max_gross_target=_max_gross_for_state(prev_state, cfg),
            last_action="missing_last_equity_block_new_entries",
        )
        write_section("intraday_governor", snap.to_dict())
        return snap

    daily_pl     = equity - last_equity
    daily_pl_pct = daily_pl / last_equity if last_equity > 0 else 0.0
    now_iso      = _utcnow_iso()

    # Peak ratchet (positive PnL only — sub-zero starts don't set a peak).
    peak_pnl    = max(prev_peak_pnl, daily_pl, 0.0)
    peak_equity = max(prev_peak_equity, equity, last_equity)
    peak_at     = now_iso if (daily_pl > prev_peak_pnl and daily_pl > 0) else (prev_peak_at or now_iso)
    peak_pnl_pct = peak_pnl / last_equity if last_equity > 0 else 0.0

    giveback_usd = max(0.0, peak_pnl - daily_pl)
    giveback_pct = (giveback_usd / peak_pnl) if peak_pnl > 0 else 0.0

    snap = IntradaySnapshot(
        date                   = today,
        session_start_equity   = last_equity,
        current_equity         = equity,
        intraday_peak_equity   = peak_equity,
        intraday_peak_pnl      = peak_pnl,
        intraday_peak_pnl_pct  = peak_pnl_pct,
        peak_at                = peak_at,
        current_intraday_pnl   = daily_pl,
        current_intraday_pnl_pct = daily_pl_pct,
        giveback_usd           = giveback_usd,
        giveback_pct_of_peak   = giveback_pct,
        alerts_sent            = dict(prev_alerts),
        last_update_at         = now_iso,
        top_giveback_symbols   = list(top_giveback_symbols or []),
    )
    new_state = _compute_state(snap, cfg, prev_state)
    snap.pnl_state              = new_state
    snap.profit_floor_usd       = _profit_floor(peak_pnl, cfg)
    snap.max_gross_target       = _max_gross_for_state(new_state, cfg)
    snap.options_first_reduction = (
        cfg["reduce_options_first"] and new_state in (
            STATE_PROFIT_LOCK, STATE_DEFEND_DAY, STATE_RED_DAY_AFTER_GREEN,
        )
    )
    snap.block_new_entries = _state_blocks_entries(new_state, cfg)
    snap.state_entered_at  = now_iso if new_state != prev_state else prev_state_entered_at
    snap.last_action       = _action_for_transition(prev_state, new_state)

    # Persist.
    write_section("intraday_governor", snap.to_dict())

    # Side-effect: emit audit events for transitions (idempotent — one per
    # transition per session). Done here so every caller doesn't have to
    # remember to.
    if new_state != prev_state:
        _emit_transition_audit(prev_state, new_state, snap)

    return snap


def _state_blocks_entries(state: str, cfg: dict) -> bool:
    if state == STATE_RED_DAY_AFTER_GREEN and cfg["block_new_entries_on_red_after_green"]:
        return True
    if state == STATE_DEFEND_DAY and cfg["block_new_entries_on_defend_day"]:
        return True
    # PROFIT_LOCK does NOT auto-block — caller checks score override.
    return False


def _action_for_transition(prev: str, new: str) -> str:
    if prev == new:
        return "noop"
    if new == STATE_GIVEBACK_WARN:
        return "warn_tighten_stops"
    if new == STATE_PROFIT_LOCK:
        return "profit_lock_harvest_winners_options_first"
    if new == STATE_DEFEND_DAY:
        return "defend_day_flatten_weak_block_new"
    if new == STATE_RED_DAY_AFTER_GREEN:
        return "red_after_green_close_intraday_block_until_next_session"
    return f"transition_{prev}_to_{new}"


def get_snapshot() -> IntradaySnapshot:
    """Read-only access; does not touch Alpaca. Returns last persisted snapshot."""
    raw = read_section("intraday_governor")
    if not raw or raw.get("date") != _today():
        return IntradaySnapshot(date=_today(), pnl_state=STATE_NEW_DAY)
    # Restore known fields; ignore extras.
    known = {f for f in IntradaySnapshot.__dataclass_fields__}
    return IntradaySnapshot(**{k: v for k, v in raw.items() if k in known})


def block_new_entries(symbol: str | None = None,
                      score: float | None = None) -> tuple[bool, str]:
    """
    Pre-trade gate for entry monitors. Returns (block, reason).

    Logic (deterministic):
      account_unavailable      → block ("intraday governor: account unavailable")
      RED_DAY_AFTER_GREEN      → block (config gate)
      DEFEND_DAY               → block (config gate)
      PROFIT_LOCK + low score  → block (allows top-scored override)
      else                     → allow
    """
    cfg = _load_config()
    if not cfg["enabled"]:
        return False, "intraday_protection_disabled"
    snap = get_snapshot()
    if snap.account_unavailable:
        return True, "intraday_governor:account_unavailable"
    if snap.pnl_state == STATE_RED_DAY_AFTER_GREEN and cfg["block_new_entries_on_red_after_green"]:
        return True, f"intraday_governor:RED_DAY_AFTER_GREEN (peak ${snap.intraday_peak_pnl:+.0f} → current ${snap.current_intraday_pnl:+.0f})"
    if snap.pnl_state == STATE_DEFEND_DAY and cfg["block_new_entries_on_defend_day"]:
        return True, f"intraday_governor:DEFEND_DAY (giveback {snap.giveback_pct_of_peak:.0%} from peak ${snap.intraday_peak_pnl:+.0f})"
    if snap.pnl_state == STATE_PROFIT_LOCK:
        thresh = cfg["profit_lock_min_score_override"]
        if score is None or score < thresh:
            return True, f"intraday_governor:PROFIT_LOCK (need score>={thresh}, got {score})"
    return False, "ok"


def max_gross_exposure_target() -> float:
    """Dynamic gross-exposure cap. Portfolio-risk gate should clamp to this."""
    return get_snapshot().max_gross_target


def should_close_options_first() -> bool:
    """True when options should be reduced before stocks/ETFs in any close pass."""
    return get_snapshot().options_first_reduction


def profit_floor_usd() -> Optional[float]:
    """Locked profit floor; None if no floor armed yet."""
    snap = get_snapshot()
    return snap.profit_floor_usd if snap.profit_floor_usd > 0 else None


# ─── Position-level MFE tracker ──────────────────────────────────────────────

def position_mfe_action(position: dict) -> dict:
    """
    Track per-position Max Favorable Excursion and decide if a partial close
    is warranted. State is persisted under runtime_state.position_mfe.

    Returns dict:
        {"action": "HOLD"|"REDUCE"|"HARVEST",
         "reduce_pct": float (0..1),  # only meaningful for REDUCE
         "reason":   "...",
         "mfe_peak": float (decimal, e.g. 0.12 = 12%),
         "mfe_retrace": float}

    Rules (defaults; tunable via aggressive_profile.json):
      - peak ≥ 20% AND retrace ≥ 25% → HARVEST (close 100%)
      - peak ≥ 12% AND retrace ≥ 35% → REDUCE (close 75%)
      - peak ≥  8% AND retrace ≥ 40% → REDUCE (close 50%)
      - else                          → HOLD
    """
    cfg = _load_config()
    sym = position.get("symbol") or ""
    if not sym:
        return {"action": "HOLD", "reduce_pct": 0.0, "reason": "no_symbol",
                "mfe_peak": 0.0, "mfe_retrace": 0.0}
    try:
        plpc = float(position.get("unrealized_plpc") or position.get("plpc") or 0.0)
    except (TypeError, ValueError):
        plpc = 0.0
    # Alpaca returns plpc as a decimal (e.g. "0.085" for +8.5%). Accept both.
    if abs(plpc) > 5:
        plpc = plpc / 100.0

    all_mfe = read_section("position_mfe")
    rec = dict(all_mfe.get(sym) or {})
    peak = max(float(rec.get("peak_pct") or 0.0), plpc)
    retrace = (peak - plpc) / peak if peak > 0 else 0.0
    rec["peak_pct"] = peak
    rec["last_pct"] = plpc
    rec["last_seen_at"] = _utcnow_iso()
    if "first_seen_at" not in rec:
        rec["first_seen_at"] = rec["last_seen_at"]
    all_mfe[sym] = rec
    write_section("position_mfe", all_mfe)

    if peak >= cfg["mfe_tier3_peak_pct"] and retrace >= cfg["mfe_tier3_retrace_pct"]:
        return {"action": "HARVEST", "reduce_pct": cfg["mfe_tier3_reduce_pct"],
                "reason": f"MFE tier3: peak {peak:.0%} retrace {retrace:.0%}",
                "mfe_peak": peak, "mfe_retrace": retrace}
    if peak >= cfg["mfe_tier2_peak_pct"] and retrace >= cfg["mfe_tier2_retrace_pct"]:
        return {"action": "REDUCE", "reduce_pct": cfg["mfe_tier2_reduce_pct"],
                "reason": f"MFE tier2: peak {peak:.0%} retrace {retrace:.0%}",
                "mfe_peak": peak, "mfe_retrace": retrace}
    if peak >= cfg["mfe_tier1_peak_pct"] and retrace >= cfg["mfe_tier1_retrace_pct"]:
        return {"action": "REDUCE", "reduce_pct": cfg["mfe_tier1_reduce_pct"],
                "reason": f"MFE tier1: peak {peak:.0%} retrace {retrace:.0%}",
                "mfe_peak": peak, "mfe_retrace": retrace}
    return {"action": "HOLD", "reduce_pct": 0.0,
            "reason": "MFE within tolerance",
            "mfe_peak": peak, "mfe_retrace": retrace}


def reset_position_mfe(symbol: str) -> None:
    """Drop a position from the MFE tracker once it's closed."""
    all_mfe = read_section("position_mfe")
    if symbol in all_mfe:
        del all_mfe[symbol]
        write_section("position_mfe", all_mfe)


# ─── Audit ───────────────────────────────────────────────────────────────────

# Audit type codes (kept here so callers don't have to import autonomy
# DECISION_TYPES — this is a higher-level event log; one decision per cron
# may map to several state-machine events).
EVENT_UPDATE_INTRADAY_PEAK         = "UPDATE_INTRADAY_PEAK"
EVENT_GIVEBACK_WARN                = "GIVEBACK_WARN"
EVENT_PROFIT_LOCK_TRIGGERED        = "PROFIT_LOCK_TRIGGERED"
EVENT_DEFEND_DAY_TRIGGERED         = "DEFEND_DAY_TRIGGERED"
EVENT_RED_DAY_AFTER_GREEN          = "RED_DAY_AFTER_GREEN_PROTECTION"
EVENT_BLOCK_NEW_ENTRIES_INTRADAY   = "BLOCK_NEW_ENTRIES_INTRADAY"
EVENT_TIGHTEN_STOPS_INTRADAY       = "TIGHTEN_STOPS_INTRADAY"
EVENT_REDUCE_GROSS_EXPOSURE        = "REDUCE_GROSS_EXPOSURE_INTRADAY"
EVENT_POSITION_MFE_TRAIL_REDUCE    = "POSITION_MFE_TRAIL_REDUCE"
EVENT_POSITION_MFE_TRAIL_EXIT      = "POSITION_MFE_TRAIL_EXIT"
EVENT_INTRADAY_TREND_REVERSAL_EXIT = "INTRADAY_TREND_REVERSAL_EXIT"


def _emit_transition_audit(prev: str, new: str, snap: IntradaySnapshot) -> None:
    """Write a journal/autonomy/YYYY-MM-DD.jsonl line for a state transition."""
    event_type = {
        STATE_GIVEBACK_WARN:       EVENT_GIVEBACK_WARN,
        STATE_PROFIT_LOCK:         EVENT_PROFIT_LOCK_TRIGGERED,
        STATE_DEFEND_DAY:          EVENT_DEFEND_DAY_TRIGGERED,
        STATE_RED_DAY_AFTER_GREEN: EVENT_RED_DAY_AFTER_GREEN,
    }.get(new, EVENT_UPDATE_INTRADAY_PEAK)
    emit_audit(event_type, snap, state_before=prev, state_after=new,
               action=snap.last_action, reason=f"FSM transition {prev} -> {new}")


def emit_audit(event_type: str,
               snapshot: IntradaySnapshot | dict,
               *,
               state_before: str = "",
               state_after: str = "",
               action: str = "",
               reason: str = "",
               affected_symbols: list[str] | None = None) -> None:
    """
    Append one IntradayProfitGovernor audit event to journal/autonomy/.
    Format mirrors spec §15 (full diagnostic envelope).

    Fail-soft: any error is logged but doesn't propagate (we don't want a
    disk-write hiccup to kill an exit-monitor cron run).
    """
    snap = snapshot.to_dict() if isinstance(snapshot, IntradaySnapshot) else dict(snapshot or {})
    record = {
        "timestamp":               _utcnow_iso(),
        "event_type":              event_type,
        "actor":                   "intraday-governor",
        "session_start_equity":    snap.get("session_start_equity"),
        "current_equity":          snap.get("current_equity"),
        "intraday_peak_equity":    snap.get("intraday_peak_equity"),
        "intraday_peak_pnl":       snap.get("intraday_peak_pnl"),
        "current_intraday_pnl":    snap.get("current_intraday_pnl"),
        "giveback_usd":            snap.get("giveback_usd"),
        "giveback_pct_of_peak":    snap.get("giveback_pct_of_peak"),
        "profit_floor_usd":        snap.get("profit_floor_usd"),
        "max_gross_target":        snap.get("max_gross_target"),
        "state_before":            state_before or snap.get("pnl_state"),
        "state_after":             state_after  or snap.get("pnl_state"),
        "action":                  action,
        "reason":                  reason,
        "affected_symbols":        affected_symbols or snap.get("top_giveback_symbols") or [],
    }
    try:
        try:
            from audit import write_audit_event
        except ImportError:
            from shared.audit import write_audit_event       # type: ignore
        write_audit_event(record, kind="trading")
    except Exception as e:                                   # pragma: no cover
        print(f"  [intraday-governor] audit write failed ({type(e).__name__}: {e})")


def mark_alert_sent(level: str) -> None:
    """Record that an email at `level` was sent today (for dedup)."""
    snap_dict = read_section("intraday_governor")
    alerts = dict(snap_dict.get("alerts_sent") or {})
    alerts[level] = _utcnow_iso()
    snap_dict["alerts_sent"] = alerts
    write_section("intraday_governor", snap_dict)


def alert_already_sent(level: str) -> bool:
    return level in (read_section("intraday_governor").get("alerts_sent") or {})


# ─── Test helper ─────────────────────────────────────────────────────────────

def _reset_for_test() -> None:
    """Clear all governor + MFE state. Tests only; production must not call."""
    write_section("intraday_governor", {})
    write_section("position_mfe", {})


def summarize(snap: IntradaySnapshot | None = None) -> str:
    """One-line human summary for logs."""
    s = snap or get_snapshot()
    if not s.intraday_peak_pnl and s.pnl_state == STATE_NEW_DAY:
        return f"(intraday governor: NEW_DAY equity ${s.current_equity:,.0f})"
    return (
        f"intraday: peak ${s.intraday_peak_pnl:+,.0f} at {(s.peak_at or '?')[-9:-1]} "
        f"current ${s.current_intraday_pnl:+,.0f} giveback {s.giveback_pct_of_peak:.0%} "
        f"state={s.pnl_state} max_gross={s.max_gross_target:.2f}"
        + (f" floor=${s.profit_floor_usd:,.0f}" if s.profit_floor_usd > 0 else "")
        + (" BLOCK_ENTRIES" if s.block_new_entries else "")
    )
