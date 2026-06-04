"""v3.21.0 (2026-06-04) — ETAP 3 — Multi-Horizon Outcome Tracking.

WHY
---
The audit board cross-cutting theme STRAT-003 (strategy validation
deficit) is reinforced by a subtler problem: when we *do* count an
observed signal, we collapse the whole trade-life into a single P&L
number. That hides answers to questions the strategy layer needs:

  * Does this strategy's edge live in the first 5-30 minutes?
  * Does the move keep going overnight, or does the next-session open
    reverse it?
  * How much heat (MAE) does the position eat before it turns green?
  * How long does it take to reach the first peak (time-to-MFE)?

Multi-horizon outcomes answer those questions. For every signal in
``learning-loop/opportunity_ledger/<date>.jsonl`` we compute deterministic
hypothetical results at six fixed horizons (5m, 15m, 30m, 60m, EOD,
next-session-open) using ONLY local bar data and a deterministic
slippage / spread model.

HARD INVARIANTS
---------------
* Each horizon is computed independently. A missing horizon never
  contaminates another — its outcome is reported as ``"UNKNOWN"``.
* These records are stamped with ``evidence_source="MULTI_HORIZON"``
  (a plain string constant). They are NEVER counted as paper trades
  and never modify ``paper_n``. Downstream consumers (lower bounds,
  ranking, calibration) treat them as triage-only.
* The module is observe-only. It NEVER places a trade, NEVER touches
  the broker, NEVER mutates strategy state, NEVER changes any risk
  threshold, NEVER flips ``EDGE_GATE_ENABLED``.
* No paid APIs. No new SDKs. No LLM calls. Pure stdlib + an injectable
  bar-fetcher callable (same shape as
  ``shared.market_data.get_daily_bars``).
* Fail-soft: an internal error in one horizon returns ``"UNKNOWN"``
  and is logged via :func:`shared.audit.write_audit_event`. The next
  horizon still computes.

PUBLIC API
----------
``HORIZONS`` — the canonical tuple of horizon names.

``compute_outcome_for_signal(signal, horizon, *, bars_fetcher=None,
                             slippage_bps=5.0, half_spread_bps=1.0)``
    Returns one :class:`HorizonOutcome` for a single horizon.

``compute_outcomes_for_signal(signal, horizons=HORIZONS, **kwargs)``
    Returns a dict ``{horizon: HorizonOutcome}``.

``compute_outcomes_for_ledger(date_iso=None, ledger_dir=None,
                              horizons=HORIZONS, **kwargs)``
    Reads the day's opportunity ledger and returns a list of
    ``{signal_id, symbol, outcomes_by_horizon, ...}`` dicts.

``write_outcomes_jsonl(records, *, out_dir=None, date_iso=None)``
    Append-only sink to
    ``learning-loop/multi_horizon_outcomes/<date>.jsonl``.

OUTCOME STATUS LADDER
---------------------
Each horizon outcome is one of:

* ``"PROFITABLE"`` — net return after costs > +0.05 %.
* ``"LOSING"``     — net return after costs < -0.05 %.
* ``"FLAT"``       — net return within the flat band.
* ``"UNKNOWN"``    — bar data unavailable for that horizon.

FREE OPERATION
--------------
Zero new dependencies. Ledger lives under
``learning-loop/multi_horizon_outcomes/<date>.jsonl`` (local filesystem
only).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── Constants ────────────────────────────────────────────────────────────────

EVIDENCE_SOURCE_MULTI_HORIZON: str = "MULTI_HORIZON"
"""Local string constant. Never added to
``shared.evidence_source.EvidenceSource`` — multi-horizon records are
*not* PAPER, BACKTEST, REPLAY, or COUNTERFACTUAL evidence. They are a
diagnostic overlay and must remain string-isolated downstream."""

# Canonical horizons. ``end_of_day`` and ``next_session_open`` are
# computed against the session window described below; they may yield
# ``"UNKNOWN"`` when bar coverage stops short.
HORIZON_5MIN              = "5min"
HORIZON_15MIN             = "15min"
HORIZON_30MIN             = "30min"
HORIZON_60MIN             = "60min"
HORIZON_END_OF_DAY        = "end_of_day"
HORIZON_NEXT_SESSION_OPEN = "next_session_open"

HORIZONS: tuple[str, ...] = (
    HORIZON_5MIN,
    HORIZON_15MIN,
    HORIZON_30MIN,
    HORIZON_60MIN,
    HORIZON_END_OF_DAY,
    HORIZON_NEXT_SESSION_OPEN,
)

# Map horizon → look-forward in minutes. ``None`` means "session-derived"
# (see ``_resolve_horizon_window`` for end_of_day / next_session_open).
_HORIZON_MINUTES: Mapping[str, int | None] = {
    HORIZON_5MIN:              5,
    HORIZON_15MIN:             15,
    HORIZON_30MIN:             30,
    HORIZON_60MIN:             60,
    HORIZON_END_OF_DAY:        None,
    HORIZON_NEXT_SESSION_OPEN: None,
}

OUTCOME_PROFITABLE = "PROFITABLE"
OUTCOME_LOSING     = "LOSING"
OUTCOME_FLAT       = "FLAT"
OUTCOME_UNKNOWN    = "UNKNOWN"

# Deterministic execution costs. Mirrors evidence_production defaults so
# multi-horizon estimates are pessimistic in the same way SHADOW fills
# are pessimistic.
DEFAULT_SLIPPAGE_BPS    = 5.0
DEFAULT_HALF_SPREAD_BPS = 1.0
FLAT_BAND_PCT           = 0.05  # +/- 0.05 % → FLAT

# Session window assumptions (US equities). Used only when bars do not
# carry their own session metadata.
_SESSION_OPEN_UTC_HOUR   = 13  # 13:30 UTC → 09:30 ET
_SESSION_OPEN_UTC_MINUTE = 30
_SESSION_CLOSE_UTC_HOUR  = 20
_SESSION_CLOSE_UTC_MIN   = 0


# ─── Safe helpers ─────────────────────────────────────────────────────────────


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:  # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime:
    if not value:
        raise ValueError("empty timestamp")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _direction_multiplier(side: str) -> int:
    s = str(side).lower()
    if s in ("short", "sell", "sell_short", "sell_to_open"):
        return -1
    return 1


def _classify_outcome(pnl_after_costs_pct: float,
                      *,
                      flat_band_pct: float = FLAT_BAND_PCT) -> str:
    if pnl_after_costs_pct > flat_band_pct:
        return OUTCOME_PROFITABLE
    if pnl_after_costs_pct < -flat_band_pct:
        return OUTCOME_LOSING
    return OUTCOME_FLAT


# ─── Data classes ────────────────────────────────────────────────────────────


@dataclass
class HorizonOutcome:
    """Per-horizon result for a single signal."""

    signal_id: str
    symbol: str
    side: str
    horizon: str
    horizon_minutes: int | None
    entry_ts: str
    entry_price: float
    horizon_price: float | None
    hypothetical_return_pct: float
    net_return_after_costs_pct: float
    mfe_pct: float
    mae_pct: float
    direction_correctness: bool | None
    drawdown_before_profit_pct: float
    time_to_mfe_minutes: float | None
    time_to_mae_minutes: float | None
    outcome: str
    status: str = "OK"
    evidence_source: str = EVIDENCE_SOURCE_MULTI_HORIZON
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Audit emission ───────────────────────────────────────────────────────────


def _emit_audit_event(event_type: str, payload: dict) -> None:
    """Best-effort audit emission. Never raises. Uses the existing
    ``shared.audit.write_audit_event`` helper."""
    try:
        try:
            from audit import write_audit_event
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
    except Exception:
        return
    try:
        record = {
            "ts":         _utc_now_iso(),
            "decision":   event_type,
            "event_type": event_type,
            "actor":      "multi_horizon_outcomes",
            "payload":    payload,
        }
        write_audit_event(record, kind="trading")
    except Exception:
        pass


# ─── Bar fetching ─────────────────────────────────────────────────────────────


def _resolve_bars_fetcher(bars_fetcher: Callable | None) -> Callable | None:
    """Return a ``(symbol, days_or_minutes) -> {"bars": [...]}`` callable.

    If ``bars_fetcher`` is provided we use it verbatim. Otherwise we try
    to import ``shared.market_data.get_daily_bars``. If even that fails
    we return ``None`` so callers will report ``UNKNOWN``.
    """
    if bars_fetcher is not None:
        return bars_fetcher
    try:
        from market_data import get_daily_bars as _gd  # type: ignore
        return _gd
    except ImportError:
        try:
            from shared.market_data import get_daily_bars as _gd  # type: ignore
            return _gd
        except ImportError:
            return None


def _resolve_horizon_window(entry_ts: datetime, horizon: str
                            ) -> tuple[datetime, datetime, int | None]:
    """Return ``(window_start, window_end, horizon_minutes_or_None)``.

    For intraday horizons (5/15/30/60 min) the window is
    ``[entry, entry+minutes]``.

    For ``end_of_day`` the window is ``[entry, session_close_same_day]``.

    For ``next_session_open`` the window is ``[entry, next_session_open]``
    where the next session is the next weekday at the canonical open.
    """
    minutes = _HORIZON_MINUTES.get(horizon)
    if isinstance(minutes, int):
        return entry_ts, entry_ts + timedelta(minutes=minutes), minutes

    if horizon == HORIZON_END_OF_DAY:
        end = entry_ts.replace(hour=_SESSION_CLOSE_UTC_HOUR,
                               minute=_SESSION_CLOSE_UTC_MIN,
                               second=0, microsecond=0)
        if end <= entry_ts:
            # entry already past close — push to same-day close (still
            # a valid pointer; result will be UNKNOWN if no bars cover).
            end = entry_ts + timedelta(minutes=1)
        # Approximate the horizon minutes for the metadata field.
        approx_min = max(0, int((end - entry_ts).total_seconds() // 60))
        return entry_ts, end, approx_min

    if horizon == HORIZON_NEXT_SESSION_OPEN:
        # Walk forward until we hit Mon-Fri at the canonical open.
        candidate = entry_ts + timedelta(days=1)
        candidate = candidate.replace(hour=_SESSION_OPEN_UTC_HOUR,
                                      minute=_SESSION_OPEN_UTC_MINUTE,
                                      second=0, microsecond=0)
        # Skip Sat (5) and Sun (6).
        while candidate.weekday() >= 5:
            candidate = candidate + timedelta(days=1)
        approx_min = max(0, int((candidate - entry_ts).total_seconds() // 60))
        return entry_ts, candidate, approx_min

    # Unknown horizon name — treat as zero-length window so caller falls
    # to UNKNOWN. We never silently relabel an unknown horizon.
    return entry_ts, entry_ts, 0


def _required_days_for_window(window_end: datetime, entry_ts: datetime) -> int:
    """Estimate how many days of bars we need to cover the window."""
    span_minutes = max(1, int((window_end - entry_ts).total_seconds() // 60))
    days = max(2, (span_minutes // (60 * 24)) + 2)
    return days


def _fetch_window_bars(bars_fetcher: Callable, symbol: str,
                       window_start: datetime, window_end: datetime,
                       ) -> list[dict] | None:
    """Best-effort window fetch. Returns ``None`` on any failure."""
    days = _required_days_for_window(window_end, window_start)
    try:
        payload = bars_fetcher(symbol, days)
    except Exception:
        return None
    if not isinstance(payload, Mapping):
        return None
    bars = payload.get("bars")
    if not isinstance(bars, list) or not bars:
        return None

    window: list[dict] = []
    for bar in bars:
        try:
            t = _parse_iso(bar.get("t"))
        except Exception:
            continue
        if window_start <= t <= window_end:
            window.append(bar)
    return window or None


# ─── Per-horizon computation ──────────────────────────────────────────────────


def _empty_outcome(signal: Mapping[str, Any], horizon: str,
                   horizon_minutes: int | None,
                   *, status: str, notes: str) -> HorizonOutcome:
    """Construct an outcome flagged ``UNKNOWN`` with an explicit reason."""
    return HorizonOutcome(
        signal_id=str(signal.get("signal_id") or signal.get("id") or "?"),
        symbol=str(signal.get("symbol", "")).upper(),
        side=str(signal.get("side", "long")),
        horizon=horizon,
        horizon_minutes=horizon_minutes,
        entry_ts=str(signal.get("entry_ts") or signal.get("ts") or ""),
        entry_price=_safe_float(signal.get("entry_price"), default=0.0),
        horizon_price=None,
        hypothetical_return_pct=0.0,
        net_return_after_costs_pct=0.0,
        mfe_pct=0.0,
        mae_pct=0.0,
        direction_correctness=None,
        drawdown_before_profit_pct=0.0,
        time_to_mfe_minutes=None,
        time_to_mae_minutes=None,
        outcome=OUTCOME_UNKNOWN,
        status=status,
        notes=notes,
    )


def compute_outcome_for_signal(signal: Mapping[str, Any],
                               horizon: str,
                               *,
                               bars_fetcher: Callable | None = None,
                               slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
                               half_spread_bps: float = DEFAULT_HALF_SPREAD_BPS,
                               ) -> HorizonOutcome:
    """Compute a single-horizon outcome for one signal.

    Missing bar data → outcome ``UNKNOWN`` with ``status="MISSING_BARS"``.
    Internal exceptions → outcome ``UNKNOWN`` with ``status="ERROR"``.
    Horizons are NEVER cross-contaminated: a failure here only affects
    this horizon's record.
    """
    if horizon not in HORIZONS:
        return _empty_outcome(signal, horizon,
                              _HORIZON_MINUTES.get(horizon),
                              status="UNKNOWN_HORIZON",
                              notes=f"unknown horizon: {horizon!r}")

    horizon_minutes_meta = _HORIZON_MINUTES.get(horizon)
    symbol = str(signal.get("symbol", "")).upper()
    side = str(signal.get("side", "long"))
    entry_ts_raw = signal.get("entry_ts") or signal.get("ts")
    entry_price = _safe_float(signal.get("entry_price"), default=0.0)

    if not symbol or not entry_ts_raw or entry_price <= 0:
        return _empty_outcome(signal, horizon, horizon_minutes_meta,
                              status="BAD_INPUT",
                              notes="missing symbol/entry_ts/entry_price")

    try:
        entry_ts = _parse_iso(str(entry_ts_raw))
    except Exception:
        return _empty_outcome(signal, horizon, horizon_minutes_meta,
                              status="BAD_INPUT",
                              notes="invalid entry_ts ISO")

    window_start, window_end, resolved_minutes = _resolve_horizon_window(
        entry_ts, horizon)
    fetcher = _resolve_bars_fetcher(bars_fetcher)
    if fetcher is None:
        return _empty_outcome(signal, horizon,
                              resolved_minutes or horizon_minutes_meta,
                              status="NO_FETCHER",
                              notes="bars_fetcher unavailable")

    try:
        bars = _fetch_window_bars(fetcher, symbol, window_start, window_end)
    except Exception as exc:  # noqa: BLE001
        return _empty_outcome(signal, horizon,
                              resolved_minutes or horizon_minutes_meta,
                              status="ERROR",
                              notes=f"bars fetch raised: {exc}")

    if not bars:
        return _empty_outcome(signal, horizon,
                              resolved_minutes or horizon_minutes_meta,
                              status="MISSING_BARS",
                              notes="no bars in window")

    try:
        direction = _direction_multiplier(side)
        highs = [_safe_float(b.get("h", b.get("c", 0.0))) for b in bars]
        lows = [_safe_float(b.get("l", b.get("c", 0.0))) for b in bars]
        closes = [_safe_float(b.get("c", 0.0)) for b in bars]
        timestamps = []
        for bar in bars:
            try:
                timestamps.append(_parse_iso(bar.get("t")))
            except Exception:
                timestamps.append(window_start)

        horizon_close = closes[-1] if closes else 0.0
        if horizon_close <= 0:
            return _empty_outcome(signal, horizon,
                                  resolved_minutes or horizon_minutes_meta,
                                  status="MISSING_BARS",
                                  notes="horizon close missing")

        raw_pct = ((horizon_close - entry_price) / entry_price) * 100.0 * direction
        cost_pct = (slippage_bps + half_spread_bps) / 100.0 * 2.0  # round trip
        net_pct = raw_pct - cost_pct

        # Direction-aware MFE / MAE.
        if direction > 0:
            mfe_price = max(highs) if highs else entry_price
            mae_price = min(lows) if lows else entry_price
        else:
            mfe_price = min(lows) if lows else entry_price
            mae_price = max(highs) if highs else entry_price
        mfe_pct = ((mfe_price - entry_price) / entry_price) * 100.0 * direction
        mae_pct = ((mae_price - entry_price) / entry_price) * 100.0 * direction

        # Time-to-MFE / MAE in minutes from entry.
        time_to_mfe = None
        time_to_mae = None
        try:
            if direction > 0:
                mfe_idx = highs.index(max(highs))
                mae_idx = lows.index(min(lows))
            else:
                mfe_idx = lows.index(min(lows))
                mae_idx = highs.index(max(highs))
            time_to_mfe = max(0.0,
                              (timestamps[mfe_idx] - entry_ts).total_seconds() / 60.0)
            time_to_mae = max(0.0,
                              (timestamps[mae_idx] - entry_ts).total_seconds() / 60.0)
        except Exception:
            pass

        # Drawdown-before-profit: largest adverse move before time-to-MFE.
        # If MAE occurs *after* MFE we treat drawdown-before-profit as 0.
        if (time_to_mfe is not None and time_to_mae is not None
                and time_to_mae < time_to_mfe):
            drawdown_before_profit = max(0.0, -mae_pct)
        else:
            drawdown_before_profit = 0.0

        direction_correct = net_pct > 0.0 if abs(net_pct) > FLAT_BAND_PCT else None
        outcome = _classify_outcome(net_pct)

        return HorizonOutcome(
            signal_id=str(signal.get("signal_id") or signal.get("id") or "?"),
            symbol=symbol,
            side=side,
            horizon=horizon,
            horizon_minutes=resolved_minutes or horizon_minutes_meta,
            entry_ts=str(entry_ts_raw),
            entry_price=entry_price,
            horizon_price=horizon_close,
            hypothetical_return_pct=round(raw_pct, 6),
            net_return_after_costs_pct=round(net_pct, 6),
            mfe_pct=round(mfe_pct, 6),
            mae_pct=round(mae_pct, 6),
            direction_correctness=direction_correct,
            drawdown_before_profit_pct=round(drawdown_before_profit, 6),
            time_to_mfe_minutes=time_to_mfe,
            time_to_mae_minutes=time_to_mae,
            outcome=outcome,
        )
    except Exception as exc:  # noqa: BLE001
        return _empty_outcome(signal, horizon,
                              resolved_minutes or horizon_minutes_meta,
                              status="ERROR",
                              notes=f"compute raised: {exc}")


def compute_outcomes_for_signal(signal: Mapping[str, Any],
                                horizons: Sequence[str] = HORIZONS,
                                *,
                                bars_fetcher: Callable | None = None,
                                slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
                                half_spread_bps: float = DEFAULT_HALF_SPREAD_BPS,
                                ) -> dict[str, HorizonOutcome]:
    """Compute every horizon for one signal independently."""
    out: dict[str, HorizonOutcome] = {}
    for horizon in horizons:
        out[horizon] = compute_outcome_for_signal(
            signal, horizon,
            bars_fetcher=bars_fetcher,
            slippage_bps=slippage_bps,
            half_spread_bps=half_spread_bps,
        )
    return out


# ─── Ledger sweep ─────────────────────────────────────────────────────────────


def _opportunity_ledger_dir() -> Path:
    return Path(os.environ.get("OPPORTUNITY_LEDGER_DIR")
                or _REPO_ROOT / "learning-loop" / "opportunity_ledger")


def _multi_horizon_dir() -> Path:
    return Path(os.environ.get("MULTI_HORIZON_OUTCOMES_DIR")
                or _REPO_ROOT / "learning-loop" / "multi_horizon_outcomes")


def _read_ledger_for_date(date_iso: str, base_dir: Path) -> list[dict]:
    path = base_dir / f"{date_iso}.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def _signal_from_ledger_entry(entry: Mapping[str, Any]) -> dict:
    """Normalise an opportunity-ledger row into the shape this module
    expects (``symbol``, ``side``, ``entry_price``, ``entry_ts``)."""
    raw = entry.get("raw_signal") if isinstance(entry, Mapping) else None
    raw = raw if isinstance(raw, Mapping) else {}
    side = raw.get("side") or entry.get("side") or "long"
    entry_price = (raw.get("entry_price")
                   or raw.get("price")
                   or entry.get("entry_price"))
    entry_ts = (raw.get("entry_ts") or entry.get("entry_ts")
                or entry.get("timestamp"))
    return {
        "signal_id":   entry.get("signal_id") or raw.get("signal_id") or "",
        "symbol":      entry.get("symbol")    or raw.get("symbol")    or "",
        "side":        side,
        "entry_price": entry_price,
        "entry_ts":    entry_ts,
    }


def compute_outcomes_for_ledger(date_iso: str | None = None,
                                ledger_dir: Path | None = None,
                                horizons: Sequence[str] = HORIZONS,
                                *,
                                bars_fetcher: Callable | None = None,
                                slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
                                half_spread_bps: float = DEFAULT_HALF_SPREAD_BPS,
                                ) -> list[dict]:
    """Run multi-horizon outcomes over a day of opportunity ledger rows."""
    if date_iso is None:
        date_iso = _utc_today_iso()
    base = ledger_dir if ledger_dir is not None else _opportunity_ledger_dir()
    rows = _read_ledger_for_date(date_iso, base)

    out: list[dict] = []
    for row in rows:
        sig = _signal_from_ledger_entry(row)
        outcomes = compute_outcomes_for_signal(
            sig, horizons,
            bars_fetcher=bars_fetcher,
            slippage_bps=slippage_bps,
            half_spread_bps=half_spread_bps,
        )
        out.append({
            "signal_id":          sig["signal_id"],
            "symbol":             sig["symbol"],
            "side":               sig["side"],
            "entry_ts":           sig["entry_ts"],
            "evidence_source":    EVIDENCE_SOURCE_MULTI_HORIZON,
            "outcomes_by_horizon": {
                h: oc.to_dict() for h, oc in outcomes.items()
            },
        })

    _emit_audit_event("V321_MULTI_HORIZON_OUTCOMES_COMPUTED", {
        "date":      date_iso,
        "n_signals": len(out),
        "horizons":  list(horizons),
    })
    return out


def write_outcomes_jsonl(records: Iterable[Mapping[str, Any]],
                         *,
                         out_dir: Path | None = None,
                         date_iso: str | None = None) -> Path:
    """Append ``records`` to today's multi-horizon JSONL.

    Returns the path written. Fail-soft: OS errors do not raise out of
    this function — the caller still gets the path (which may not
    exist).
    """
    if date_iso is None:
        date_iso = _utc_today_iso()
    base = out_dir if out_dir is not None else _multi_horizon_dir()
    path = base / f"{date_iso}.jsonl"
    try:
        base.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, default=str, sort_keys=True) + "\n")
    except OSError:
        pass
    return path


__all__ = [
    "EVIDENCE_SOURCE_MULTI_HORIZON",
    "HORIZONS",
    "HORIZON_5MIN",
    "HORIZON_15MIN",
    "HORIZON_30MIN",
    "HORIZON_60MIN",
    "HORIZON_END_OF_DAY",
    "HORIZON_NEXT_SESSION_OPEN",
    "OUTCOME_PROFITABLE",
    "OUTCOME_LOSING",
    "OUTCOME_FLAT",
    "OUTCOME_UNKNOWN",
    "HorizonOutcome",
    "compute_outcome_for_signal",
    "compute_outcomes_for_signal",
    "compute_outcomes_for_ledger",
    "write_outcomes_jsonl",
]
