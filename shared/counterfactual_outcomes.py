"""v3.20.0 (2026-06-04) — ETAP 3 — Counterfactual Outcome Engine.

WHY
---
The audit board flagged that the system rejects (or marks observe-only)
many candidate signals every day, but never learns whether those
rejections were actually correct. We log the rejection reason in
``learning-loop/opportunity_ledger/<date>.jsonl`` but we do not look
back later to ask: "if we had taken the trade, would it have made or
lost money over the next 24-48 hours?". Without that feedback the gate
calibration is blind — there is no way to know whether a guard is
saving money (correct rejections) or burning edge (false rejections).

This module reads the opportunity ledger after a deterministic horizon
has elapsed (24h / 48h) and computes, per signal:

  * ``hypothetical_pnl_after_costs`` — what the trade would have made
    or lost, with slippage and commission baked in.
  * ``MFE`` — maximum favourable excursion during the holding window.
  * ``MAE`` — maximum adverse excursion during the holding window.
  * ``was_rejection_correct`` — boolean evaluation of the gate decision.
  * ``missed_opportunity_cost`` — magnitude of profit we did not take
    (only positive when the rejection was wrong).

CRITICAL CONTRACTS
------------------
* Counterfactual outcomes NEVER count as paper trades. They are stamped
  with ``evidence_source = "COUNTERFACTUAL"`` (a plain string constant,
  not added to :class:`shared.evidence_source.EvidenceSource`, to avoid
  merge conflicts with other v3.20 etaps). Downstream callers must keep
  treating these records as triage-only.
* No real orders are placed. No paid APIs are called. If bar data is
  missing the outcome is reported as ``"UNKNOWN"`` and never invented.
* Risk-gate rejections are still labelled distinctly downstream — see
  :mod:`shared.gate_calibration` for the safety vs missed-opportunity
  separation rule.
* All write paths go through ``shared.audit.write_audit_event`` so the
  audit log records every computation.

FREE OPERATION
--------------
Pure stdlib + the existing ``shared.market_data`` helper. No new paid
dependencies. Fail-soft when bar data is unavailable.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

# ─── Constants ────────────────────────────────────────────────────────────────

EVIDENCE_SOURCE_COUNTERFACTUAL: str = "COUNTERFACTUAL"
"""Local string constant. We intentionally do NOT extend
``shared.evidence_source.EvidenceSource`` to keep this etap merge-safe.
"""

DEFAULT_HORIZONS_HOURS: tuple[int, ...] = (24, 48)
"""Deterministic look-forward windows used for counterfactual scoring."""

DEFAULT_SLIPPAGE_BPS: float = 5.0   # 5 bps per side
DEFAULT_COMMISSION_BPS: float = 0.0  # Alpaca paper has no commission
DEFAULT_LEDGER_DIR = "learning-loop/opportunity_ledger"


_REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── Outcome enums (string-only for JSON friendliness) ───────────────────────

OUTCOME_UNKNOWN = "UNKNOWN"        # data missing — never guess
OUTCOME_PROFITABLE = "PROFITABLE"  # would have made money
OUTCOME_LOSING = "LOSING"          # would have lost money
OUTCOME_FLAT = "FLAT"              # within slippage of zero


# ─── Data classes ────────────────────────────────────────────────────────────


@dataclass
class CounterfactualResult:
    """Result for a single signal at a single horizon."""

    signal_id: str
    symbol: str
    side: str                   # "long" | "short"
    horizon_hours: int
    decision: str               # "REJECTED" | "OBSERVE_ONLY"
    gate: str                   # name of the gate that rejected (or "")
    entry_ts: str               # ISO timestamp recorded at signal time
    entry_price: float
    horizon_price: float | None
    hypothetical_pnl_pct: float
    hypothetical_pnl_after_costs_pct: float
    mfe_pct: float
    mae_pct: float
    outcome: str
    was_rejection_correct: bool | None
    missed_opportunity_cost_pct: float
    evidence_source: str = EVIDENCE_SOURCE_COUNTERFACTUAL
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateAggregate:
    """Aggregated counts for one gate."""

    gate: str
    horizon_hours: int
    n_rejections: int = 0
    n_false_rejections: int = 0
    n_correct_rejections: int = 0
    n_bad_acceptances: int = 0
    n_unknown: int = 0
    cumulative_missed_pnl_pct: float = 0.0
    cumulative_avoided_loss_pct: float = 0.0
    horizons: list[int] = field(default_factory=list)

    @property
    def false_rejection_rate(self) -> float:
        denom = max(1, self.n_rejections)
        return self.n_false_rejections / denom

    @property
    def bad_acceptance_rate(self) -> float:
        denom = max(1, self.n_rejections + self.n_bad_acceptances)
        return self.n_bad_acceptances / denom

    def to_dict(self) -> dict:
        d = asdict(self)
        d["false_rejection_rate"] = self.false_rejection_rate
        d["bad_acceptance_rate"] = self.bad_acceptance_rate
        return d


# ─── I/O helpers ──────────────────────────────────────────────────────────────


def _ledger_dir() -> Path:
    return Path(os.environ.get("OPPORTUNITY_LEDGER_DIR")
                or _REPO_ROOT / DEFAULT_LEDGER_DIR)


def read_ledger(date_iso: str | None = None,
                base_dir: Path | None = None) -> list[dict]:
    """Read one day's opportunity ledger entries.

    Returns ``[]`` if the file does not exist. Malformed JSON lines are
    silently dropped (fail-soft).
    """
    base = base_dir if base_dir is not None else _ledger_dir()
    if date_iso is None:
        date_iso = datetime.now(timezone.utc).date().isoformat()
    path = base / f"{date_iso}.jsonl"
    if not path.exists():
        return []
    entries: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries


# ─── Bar-data adapter ────────────────────────────────────────────────────────


def _fetch_bars_for_horizon(symbol: str,
                            entry_ts_iso: str,
                            horizon_hours: int,
                            *,
                            bars_fetcher=None) -> list[dict] | None:
    """Return the list of bar dicts covering ``[entry, entry+horizon]``.

    ``bars_fetcher`` is an injectable callable for tests — must take
    ``(symbol, days)`` and return a dict with key ``"bars"`` whose value
    is a list of ``{"t": iso, "o": float, "h": float, "l": float,
    "c": float, "v": float}`` entries (mirror of
    :func:`shared.market_data.get_daily_bars`).

    If ``bars_fetcher`` is ``None`` we try to import ``market_data``.
    If even that fails we return ``None`` (caller produces UNKNOWN).
    """
    if bars_fetcher is None:
        try:
            from market_data import get_daily_bars as _gd  # type: ignore
        except ImportError:
            try:
                from shared.market_data import get_daily_bars as _gd  # type: ignore
            except ImportError:
                return None
        bars_fetcher = _gd

    days = max(2, (horizon_hours // 24) + 2)
    try:
        payload = bars_fetcher(symbol, days)
    except Exception:
        return None
    if not payload:
        return None
    bars = payload.get("bars") if isinstance(payload, dict) else None
    if not bars:
        return None

    try:
        entry_ts = _parse_iso(entry_ts_iso)
    except Exception:
        return None
    horizon_end = entry_ts + timedelta(hours=horizon_hours)

    window: list[dict] = []
    for bar in bars:
        try:
            t = _parse_iso(bar.get("t"))
        except Exception:
            continue
        if entry_ts <= t <= horizon_end:
            window.append(bar)
    return window or None


def _parse_iso(value: str | None) -> datetime:
    if not value:
        raise ValueError("empty timestamp")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


# ─── Core computation ────────────────────────────────────────────────────────


def _direction_multiplier(side: str) -> int:
    return -1 if side.lower() in ("short", "sell", "sell_short") else 1


def _classify_outcome(pnl_after_costs_pct: float, *, flat_band_pct: float = 0.05) -> str:
    if pnl_after_costs_pct > flat_band_pct:
        return OUTCOME_PROFITABLE
    if pnl_after_costs_pct < -flat_band_pct:
        return OUTCOME_LOSING
    return OUTCOME_FLAT


def compute_counterfactual_for_signal(signal: dict,
                                      horizon_hours: int,
                                      *,
                                      slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
                                      commission_bps: float = DEFAULT_COMMISSION_BPS,
                                      bars_fetcher=None) -> CounterfactualResult:
    """Score a single rejected / observe-only signal against bar data.

    The ``signal`` dict is the same shape we already write to the
    opportunity ledger: ``signal_id``, ``symbol``, ``side``,
    ``entry_price``, ``entry_ts``, ``decision`` (``"REJECTED"`` or
    ``"OBSERVE_ONLY"``), ``gate`` (the rejecting gate name).

    Missing bar data → ``outcome = UNKNOWN`` and
    ``was_rejection_correct = None``.
    """
    symbol = str(signal.get("symbol", "")).upper()
    side = str(signal.get("side", "long"))
    decision = str(signal.get("decision", "REJECTED")).upper()
    gate = str(signal.get("gate", ""))
    entry_ts = str(signal.get("entry_ts") or signal.get("ts") or "")
    try:
        entry_price = float(signal.get("entry_price", 0.0))
    except (TypeError, ValueError):
        entry_price = 0.0

    sig_id = str(signal.get("signal_id")
                 or signal.get("id")
                 or f"{symbol}-{entry_ts}")

    base = CounterfactualResult(
        signal_id=sig_id,
        symbol=symbol,
        side=side,
        horizon_hours=horizon_hours,
        decision=decision,
        gate=gate,
        entry_ts=entry_ts,
        entry_price=entry_price,
        horizon_price=None,
        hypothetical_pnl_pct=0.0,
        hypothetical_pnl_after_costs_pct=0.0,
        mfe_pct=0.0,
        mae_pct=0.0,
        outcome=OUTCOME_UNKNOWN,
        was_rejection_correct=None,
        missed_opportunity_cost_pct=0.0,
    )

    if entry_price <= 0 or not entry_ts or not symbol:
        base.notes = "missing entry_price/symbol/entry_ts"
        return base

    bars = _fetch_bars_for_horizon(symbol, entry_ts, horizon_hours,
                                   bars_fetcher=bars_fetcher)
    if not bars:
        base.notes = "bar data unavailable"
        return base

    direction = _direction_multiplier(side)
    highs = [float(b.get("h", b.get("c", 0.0))) for b in bars]
    lows = [float(b.get("l", b.get("c", 0.0))) for b in bars]
    closes = [float(b.get("c", 0.0)) for b in bars]

    horizon_price = closes[-1] if closes else None
    if not horizon_price:
        base.notes = "horizon close missing"
        return base

    base.horizon_price = horizon_price

    raw_pct = ((horizon_price - entry_price) / entry_price) * 100.0 * direction
    cost_pct = (slippage_bps + commission_bps) / 100.0 * 2.0  # round trip
    pnl_after_costs = raw_pct - cost_pct
    base.hypothetical_pnl_pct = raw_pct
    base.hypothetical_pnl_after_costs_pct = pnl_after_costs

    # MFE / MAE in pct, direction-aware.
    if direction > 0:
        mfe_price = max(highs) if highs else entry_price
        mae_price = min(lows) if lows else entry_price
    else:
        mfe_price = min(lows) if lows else entry_price
        mae_price = max(highs) if highs else entry_price
    base.mfe_pct = ((mfe_price - entry_price) / entry_price) * 100.0 * direction
    base.mae_pct = ((mae_price - entry_price) / entry_price) * 100.0 * direction

    base.outcome = _classify_outcome(pnl_after_costs)

    # A rejection is "correct" if the trade would have lost money or
    # been flat. A rejection is "incorrect" (false rejection) if the
    # trade would have been profitable after costs.
    if decision in ("REJECTED", "OBSERVE_ONLY"):
        if base.outcome == OUTCOME_PROFITABLE:
            base.was_rejection_correct = False
            base.missed_opportunity_cost_pct = pnl_after_costs
        elif base.outcome in (OUTCOME_LOSING, OUTCOME_FLAT):
            base.was_rejection_correct = True
            base.missed_opportunity_cost_pct = 0.0
        else:
            base.was_rejection_correct = None
            base.missed_opportunity_cost_pct = 0.0
    return base


def compute_counterfactuals(signals: Iterable[dict],
                            *,
                            horizons_hours: Sequence[int] = DEFAULT_HORIZONS_HOURS,
                            slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
                            commission_bps: float = DEFAULT_COMMISSION_BPS,
                            bars_fetcher=None,
                            emit_audit: bool = True) -> list[CounterfactualResult]:
    """Score every signal across all horizons.

    Each ``signal × horizon`` produces one :class:`CounterfactualResult`.
    Returned records ALWAYS carry ``evidence_source = "COUNTERFACTUAL"``
    — they MUST NOT be merged into the paper ledger.
    """
    results: list[CounterfactualResult] = []
    for signal in signals:
        for h in horizons_hours:
            res = compute_counterfactual_for_signal(
                signal, h,
                slippage_bps=slippage_bps,
                commission_bps=commission_bps,
                bars_fetcher=bars_fetcher,
            )
            results.append(res)
            if emit_audit:
                _emit_counterfactual_audit(res)
    return results


def aggregate_by_gate(results: Sequence[CounterfactualResult],
                      *,
                      horizon_hours: int | None = None) -> list[GateAggregate]:
    """Group counterfactual results by gate name.

    When ``horizon_hours`` is provided we filter; otherwise we keep all
    horizons in a single aggregate but expose the list of horizons seen.
    """
    grouped: dict[tuple[str, int], GateAggregate] = {}
    for r in results:
        if horizon_hours is not None and r.horizon_hours != horizon_hours:
            continue
        key = (r.gate or "unknown", r.horizon_hours)
        agg = grouped.get(key)
        if agg is None:
            agg = GateAggregate(gate=key[0], horizon_hours=key[1])
            grouped[key] = agg
        if r.horizon_hours not in agg.horizons:
            agg.horizons.append(r.horizon_hours)
        if r.decision in ("REJECTED", "OBSERVE_ONLY"):
            agg.n_rejections += 1
            if r.was_rejection_correct is True:
                agg.n_correct_rejections += 1
                agg.cumulative_avoided_loss_pct += abs(
                    min(0.0, r.hypothetical_pnl_after_costs_pct))
            elif r.was_rejection_correct is False:
                agg.n_false_rejections += 1
                agg.cumulative_missed_pnl_pct += max(
                    0.0, r.missed_opportunity_cost_pct)
            else:
                agg.n_unknown += 1
        else:
            if r.outcome == OUTCOME_LOSING:
                agg.n_bad_acceptances += 1
    return list(grouped.values())


# ─── Audit emission ──────────────────────────────────────────────────────────


def _emit_counterfactual_audit(result: CounterfactualResult) -> None:
    """Write one COUNTERFACTUAL_COMPUTED line to the audit log.

    Best-effort: never raises. The decision_type tag is the
    constraint-mandated ``V320_COUNTERFACTUAL_COMPUTED``.
    """
    try:
        try:
            from audit import write_audit_event  # type: ignore
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "decision": "V320_COUNTERFACTUAL_COMPUTED",
            "actor": "counterfactual_outcomes",
            "evidence_source": EVIDENCE_SOURCE_COUNTERFACTUAL,
            "signal_id": result.signal_id,
            "symbol": result.symbol,
            "side": result.side,
            "horizon_hours": result.horizon_hours,
            "gate": result.gate,
            "outcome": result.outcome,
            "hypothetical_pnl_after_costs_pct":
                result.hypothetical_pnl_after_costs_pct,
            "mfe_pct": result.mfe_pct,
            "mae_pct": result.mae_pct,
            "was_rejection_correct": result.was_rejection_correct,
            "missed_opportunity_cost_pct": result.missed_opportunity_cost_pct,
        }
        write_audit_event(payload, kind="trading")
    except Exception:
        return


# ─── Convenience: full run from a ledger date ────────────────────────────────


def run_for_date(date_iso: str,
                 *,
                 horizons_hours: Sequence[int] = DEFAULT_HORIZONS_HOURS,
                 bars_fetcher=None,
                 emit_audit: bool = True) -> dict:
    """Read ledger for date, compute counterfactuals, return summary."""
    signals = read_ledger(date_iso)
    results = compute_counterfactuals(
        signals,
        horizons_hours=horizons_hours,
        bars_fetcher=bars_fetcher,
        emit_audit=emit_audit,
    )
    aggregates = aggregate_by_gate(results)
    return {
        "date": date_iso,
        "evidence_source": EVIDENCE_SOURCE_COUNTERFACTUAL,
        "n_signals": len(signals),
        "n_results": len(results),
        "results": [r.to_dict() for r in results],
        "by_gate": [a.to_dict() for a in aggregates],
    }


__all__ = [
    "EVIDENCE_SOURCE_COUNTERFACTUAL",
    "DEFAULT_HORIZONS_HOURS",
    "OUTCOME_UNKNOWN",
    "OUTCOME_PROFITABLE",
    "OUTCOME_LOSING",
    "OUTCOME_FLAT",
    "CounterfactualResult",
    "GateAggregate",
    "read_ledger",
    "compute_counterfactual_for_signal",
    "compute_counterfactuals",
    "aggregate_by_gate",
    "run_for_date",
]
