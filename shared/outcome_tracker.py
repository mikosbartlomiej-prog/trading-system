"""v3.23 (2026-06-15) — Outcome scheduler for shadow fills (NO-BROKER).

Outcomes are NEVER paper trades. Every emitted record carries the
hard-coded fields ``record_type=SHADOW_OUTCOME_OBSERVATION`` and
``is_paper_trade=False`` so downstream consumers cannot inadvertently
count them as broker activity.

HARD SAFETY
-----------
- NEVER imports ``shared.alpaca_orders`` or ``alpaca_orders``.
- NEVER imports any broker SDK.
- NEVER calls ``submit_order`` / ``place_order`` / ``safe_close`` /
  any close / cancel helper.
- NEVER makes a network call. The ``snapshot_fetcher`` callable is
  supplied by the caller; this module never instantiates one itself.
- All file I/O is fail-soft; functions never raise.

WHAT THIS MODULE DOES
---------------------
Given a ``ShadowFill`` produced by ``shared.shadow_simulator``, it
schedules a small number of horizon-bound outcome observations
(30m / 1h / 4h / EOD / next_open). At resolution time, given a
caller-provided snapshot fetcher, it computes hypothetical PnL, MFE,
MAE, hit_stop_first, hit_target_first, time-to-favorable / adverse.

The output ledger (``learning-loop/shadow_outcomes/<date>.jsonl``) is
a stream of ``ResolvedOutcome`` rows. Pending outcomes that have not
yet matured stay in caller memory (or in a separate pending file the
caller manages). This module is intentionally stateless w.r.t.
disk: the only persisted artefact is the resolved-outcome JSONL.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent

# ─── Horizons ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class OutcomeHorizon:
    """A single observation horizon.

    ``seconds_or_marker`` is either an int (relative seconds from the
    shadow-fill timestamp) or one of the string markers
    ``"market_close_utc"`` / ``"next_market_open_utc"`` for
    calendar-aware horizons.
    """
    name:              str
    seconds_or_marker: int | str


OUTCOME_HORIZONS: tuple[OutcomeHorizon, ...] = (
    OutcomeHorizon("30m",       30 * 60),
    OutcomeHorizon("1h",        60 * 60),
    OutcomeHorizon("4h",   4 * 60 * 60),
    OutcomeHorizon("EOD",       "market_close_utc"),
    OutcomeHorizon("next_open", "next_market_open_utc"),
)


# US-equity-ish defaults (used only when the caller does not provide
# explicit close/open times). The outcome tracker is asset-class
# agnostic — for crypto the marker horizons collapse to 24h windows.
_MARKET_CLOSE_HOUR_UTC = 20  # 16:00 ET (DST-naive approximation)
_MARKET_OPEN_HOUR_UTC  = 13  # 09:00 ET


def _parse_iso_utc(ts: str) -> datetime | None:
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_iso() -> str:
    return _utc_now().strftime("%Y-%m-%d")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        out = float(v)
        if math.isnan(out) or math.isinf(out):
            return default
        return out
    except Exception:
        return default


def _resolve_horizon_to_utc(*,
                             entry_ts: datetime,
                             horizon: OutcomeHorizon,
                             ) -> datetime:
    """Convert a horizon spec to a concrete UTC datetime."""
    spec = horizon.seconds_or_marker
    if isinstance(spec, int):
        return entry_ts + timedelta(seconds=int(spec))
    s = str(spec or "")
    if s == "market_close_utc":
        close_today = entry_ts.replace(
            hour=_MARKET_CLOSE_HOUR_UTC, minute=0,
            second=0, microsecond=0)
        if close_today <= entry_ts:
            close_today = close_today + timedelta(days=1)
        return close_today
    if s == "next_market_open_utc":
        open_next = entry_ts.replace(
            hour=_MARKET_OPEN_HOUR_UTC, minute=30,
            second=0, microsecond=0)
        if open_next <= entry_ts:
            open_next = open_next + timedelta(days=1)
        return open_next
    # Unknown marker — collapse to 1h to fail-soft (caller can override)
    return entry_ts + timedelta(seconds=60 * 60)


# ─── Dataclasses ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ScheduledOutcome:
    """Pending outcome (in-memory representation).

    The caller is responsible for any persistence of pending outcomes.
    This module only persists RESOLVED outcomes (so the ledger stays
    append-only and append-only files don't grow on every reschedule).
    """
    signal_id:      str
    symbol:         str
    strategy:       str
    side:           str
    asset_class:    str
    entry_ts_iso:   str
    entry_price:    float
    qty:            float
    horizon_name:   str
    resolves_at_iso: str
    stop_price:     float | None = None
    target_price:   float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type":     "SHADOW_OUTCOME_PENDING",
            "signal_id":       self.signal_id,
            "symbol":          self.symbol,
            "strategy":        self.strategy,
            "side":            self.side,
            "asset_class":     self.asset_class,
            "entry_ts":        self.entry_ts_iso,
            "entry_price":     self.entry_price,
            "qty":             self.qty,
            "horizon":         self.horizon_name,
            "resolves_at":     self.resolves_at_iso,
            "stop_price":      self.stop_price,
            "target_price":    self.target_price,
            "is_paper_trade":  False,
        }


@dataclass(frozen=True)
class ResolvedOutcome:
    """Resolved outcome row written to JSONL ledger."""
    signal_id:                 str
    symbol:                    str
    strategy:                  str
    side:                      str
    asset_class:               str
    horizon_name:              str
    entry_ts_iso:              str
    resolved_at_iso:           str
    entry_price:               float
    exit_price:                float
    qty:                       float
    hypothetical_pnl:          float
    max_favorable_excursion:   float
    max_adverse_excursion:     float
    hit_stop_first:            bool
    hit_target_first:          bool
    time_to_favorable_move_seconds:  float | None
    time_to_adverse_move_seconds:    float | None
    record_type:               str  = "SHADOW_OUTCOME_OBSERVATION"
    is_paper_trade:            bool = False
    standing_markers:          tuple[str, ...] = field(default_factory=lambda: (
        "EDGE_GATE_ENABLED=false",
        "ALLOW_BROKER_PAPER=false",
        "LIVE_TRADING_UNSUPPORTED",
        "NO_ORDER_PLACEMENT",
        "SHADOW_ONLY",
    ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type":              self.record_type,
            "signal_id":                self.signal_id,
            "symbol":                   self.symbol,
            "strategy":                 self.strategy,
            "side":                     self.side,
            "asset_class":              self.asset_class,
            "horizon":                  self.horizon_name,
            "entry_ts":                 self.entry_ts_iso,
            "resolved_at":              self.resolved_at_iso,
            "entry_price":              self.entry_price,
            "exit_price":               self.exit_price,
            "qty":                      self.qty,
            "hypothetical_pnl":         self.hypothetical_pnl,
            "max_favorable_excursion":  self.max_favorable_excursion,
            "max_adverse_excursion":    self.max_adverse_excursion,
            "hit_stop_first":           self.hit_stop_first,
            "hit_target_first":         self.hit_target_first,
            "time_to_favorable_move_seconds":
                self.time_to_favorable_move_seconds,
            "time_to_adverse_move_seconds":
                self.time_to_adverse_move_seconds,
            "is_paper_trade":           self.is_paper_trade,
            "standing_markers":         list(self.standing_markers),
        }


# ─── Public API ────────────────────────────────────────────────────


def schedule_outcomes(shadow_fill: Any) -> list[ScheduledOutcome]:
    """Emit pending outcome records for a (FILLED) ShadowFill.

    A REJECTED_BY_GATE fill produces NO outcomes (returns ``[]``).
    A non-ShadowFill object also returns ``[]`` (fail-soft).
    """
    if shadow_fill is None:
        return []
    fill_status = getattr(shadow_fill, "fill_status", None)
    if fill_status != "FILLED":
        return []

    entry_ts = _parse_iso_utc(
        getattr(shadow_fill, "timestamp_iso", "")) or _utc_now()
    entry_price = _safe_float(
        getattr(shadow_fill, "fill_price", 0.0))
    qty = _safe_float(getattr(shadow_fill, "qty", 0.0))
    if entry_price <= 0 or qty <= 0:
        return []

    side = str(getattr(shadow_fill, "side", "long"))
    sym  = str(getattr(shadow_fill, "symbol", "?"))
    strat = str(getattr(shadow_fill, "strategy", "unknown"))
    ac   = str(getattr(shadow_fill, "asset_class", "us_equity"))
    sid  = str(getattr(shadow_fill, "signal_id", ""))

    out: list[ScheduledOutcome] = []
    for h in OUTCOME_HORIZONS:
        resolves_at = _resolve_horizon_to_utc(
            entry_ts=entry_ts, horizon=h)
        out.append(ScheduledOutcome(
            signal_id=     sid,
            symbol=        sym,
            strategy=      strat,
            side=          side,
            asset_class=   ac,
            entry_ts_iso=  entry_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            entry_price=   entry_price,
            qty=           qty,
            horizon_name=  h.name,
            resolves_at_iso=
                resolves_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            stop_price=    None,
            target_price=  None,
        ))
    return out


def _pnl(side: str, entry: float, exit_p: float, qty: float) -> float:
    if side == "long":
        return (exit_p - entry) * qty
    return (entry - exit_p) * qty


def evaluate_pending(
    pending: list[ScheduledOutcome],
    *,
    as_of: datetime,
    snapshot_fetcher: Callable[[str, datetime, datetime], Mapping[str, Any]],
) -> list[ResolvedOutcome]:
    """For each pending outcome whose ``resolves_at`` ≤ ``as_of``,
    compute the resolved outcome using ``snapshot_fetcher``.

    ``snapshot_fetcher(symbol, start_ts, end_ts)`` must return a dict
    with keys: ``high_max``, ``low_min``, ``close``, ``ts_high``,
    ``ts_low``. All keys optional; missing values are treated as
    "no observation" (the resolved row uses ``close`` and defaults
    MFE/MAE to 0).

    This function NEVER calls the network. It only invokes the
    supplied ``snapshot_fetcher``.
    """
    out: list[ResolvedOutcome] = []
    if not pending:
        return out
    for sch in pending:
        try:
            resolves_at = _parse_iso_utc(sch.resolves_at_iso)
            entry_ts    = _parse_iso_utc(sch.entry_ts_iso)
            if resolves_at is None or entry_ts is None:
                continue
            if resolves_at > as_of:
                continue
            snap = {}
            try:
                snap = dict(snapshot_fetcher(
                    sch.symbol, entry_ts, resolves_at)) or {}
            except Exception:
                snap = {}
            high_max = _safe_float(snap.get("high_max"), sch.entry_price)
            low_min  = _safe_float(snap.get("low_min"),  sch.entry_price)
            close    = _safe_float(snap.get("close"),    sch.entry_price)
            ts_high  = snap.get("ts_high")
            ts_low   = snap.get("ts_low")

            # PnL at horizon close (deterministic exit assumption).
            pnl = _pnl(sch.side, sch.entry_price, close, sch.qty)
            # MFE / MAE.
            if sch.side == "long":
                mfe = max(0.0, _pnl(
                    sch.side, sch.entry_price, high_max, sch.qty))
                mae = min(0.0, _pnl(
                    sch.side, sch.entry_price, low_min, sch.qty))
            else:
                mfe = max(0.0, _pnl(
                    sch.side, sch.entry_price, low_min, sch.qty))
                mae = min(0.0, _pnl(
                    sch.side, sch.entry_price, high_max, sch.qty))

            # Stop / target ordering.
            stop_p   = sch.stop_price
            target_p = sch.target_price
            hit_stop  = False
            hit_tgt   = False
            if stop_p is not None and target_p is not None:
                if sch.side == "long":
                    stop_hit_first = (low_min  <= stop_p) and (
                        not (high_max >= target_p) or _ts_lt(ts_low, ts_high))
                    target_hit_first = (high_max >= target_p) and (
                        not (low_min  <= stop_p) or _ts_lt(ts_high, ts_low))
                else:
                    stop_hit_first = (high_max >= stop_p) and (
                        not (low_min  <= target_p) or _ts_lt(ts_high, ts_low))
                    target_hit_first = (low_min  <= target_p) and (
                        not (high_max >= stop_p) or _ts_lt(ts_low, ts_high))
                hit_stop = bool(stop_hit_first and not target_hit_first)
                hit_tgt  = bool(target_hit_first and not stop_hit_first)

            # Time-to-move timings.
            t_fav = _seconds_between(entry_ts, ts_high if sch.side == "long" else ts_low)
            t_adv = _seconds_between(entry_ts, ts_low  if sch.side == "long" else ts_high)

            out.append(ResolvedOutcome(
                signal_id=                sch.signal_id,
                symbol=                   sch.symbol,
                strategy=                 sch.strategy,
                side=                     sch.side,
                asset_class=              sch.asset_class,
                horizon_name=             sch.horizon_name,
                entry_ts_iso=             sch.entry_ts_iso,
                resolved_at_iso=
                    resolves_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                entry_price=              sch.entry_price,
                exit_price=               close,
                qty=                      sch.qty,
                hypothetical_pnl=         pnl,
                max_favorable_excursion=  mfe,
                max_adverse_excursion=    mae,
                hit_stop_first=           hit_stop,
                hit_target_first=         hit_tgt,
                time_to_favorable_move_seconds=  t_fav,
                time_to_adverse_move_seconds=    t_adv,
            ))
        except Exception:
            # fail-soft per element
            continue
    return out


def _ts_lt(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    da = _parse_iso_utc(str(a)) if not isinstance(a, datetime) else a
    db = _parse_iso_utc(str(b)) if not isinstance(b, datetime) else b
    if da is None or db is None:
        return False
    return da < db


def _seconds_between(entry_ts: datetime, ts: Any) -> float | None:
    if ts is None:
        return None
    dt = _parse_iso_utc(str(ts)) if not isinstance(ts, datetime) else ts
    if dt is None:
        return None
    return max(0.0, (dt - entry_ts).total_seconds())


def append_outcome_ledger(outcome: ResolvedOutcome,
                           *,
                           path: Path | str | None = None
                           ) -> Path | None:
    """Append one ResolvedOutcome to today's outcome ledger.

    Fail-soft; returns ``None`` on I/O error.
    Default destination: ``learning-loop/shadow_outcomes/<YYYY-MM-DD>.jsonl``.
    """
    if not isinstance(outcome, ResolvedOutcome):
        return None
    try:
        if path is None:
            ledger_dir = REPO_ROOT / "learning-loop" / "shadow_outcomes"
            ledger_dir.mkdir(parents=True, exist_ok=True)
            p = ledger_dir / f"{_today_iso()}.jsonl"
        else:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(outcome.to_dict(), sort_keys=True, default=str)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return p
    except Exception:
        return None


__all__ = [
    "OutcomeHorizon",
    "OUTCOME_HORIZONS",
    "ScheduledOutcome",
    "ResolvedOutcome",
    "schedule_outcomes",
    "evaluate_pending",
    "append_outcome_ledger",
]
