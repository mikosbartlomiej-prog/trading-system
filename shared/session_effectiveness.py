"""v3.15.0 (2026-06-04) — SessionEffectivenessMonitor.

Closes audit-board feedback FB-013 (real-time effectiveness verification).

WHY
---
Trader feedback: the system should do things whose effectiveness can be
verified in real time. We have `scripts/session_report.py` which is
post-session. Missing: in-session metric stream that can trigger safe_mode
when effectiveness degrades.

CONTRACT
--------
Append-only JSONL log of in-session events:
  - signal_emitted
  - signal_rejected_by_confidence
  - signal_rejected_by_risk_engine
  - signal_rejected_by_liquidity_guard
  - position_opened
  - position_closed_winner
  - position_closed_loser
  - confidence_calibration_sample

Aggregator reads the JSONL and computes:
  - signals/hour
  - rejection rate per gate
  - hit rate (closed winners / closed total)
  - average MAE / MFE
  - confidence-to-outcome correlation
  - calibration drift

Output: SessionEffectivenessReport — feeds `safe_mode.maybe_enter()` when
effectiveness drops below threshold.

CONSERVATIVE
------------
- NEVER raises confidence
- NEVER opens trades
- NEVER changes strategy
- CAN trigger safe_mode (which BLOCKS new entries)
- CAN demand more conservative confidence threshold

LOCAL & FREE
------------
JSONL files under `learning-loop/session_metrics/<date>.jsonl`. No DB.
"""

from __future__ import annotations

import json
import os
import statistics
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Iterable, Optional

# ─── Event type tokens ────────────────────────────────────────────────────────

EVT_SIGNAL_EMITTED                   = "signal_emitted"
EVT_REJECTED_CONFIDENCE              = "signal_rejected_by_confidence"
EVT_REJECTED_RISK_ENGINE             = "signal_rejected_by_risk_engine"
EVT_REJECTED_LIQUIDITY               = "signal_rejected_by_liquidity_guard"
EVT_REJECTED_SOURCE_TIER             = "signal_rejected_by_source_tier"
EVT_POSITION_OPENED                  = "position_opened"
EVT_POSITION_CLOSED_WINNER           = "position_closed_winner"
EVT_POSITION_CLOSED_LOSER            = "position_closed_loser"
EVT_CALIBRATION_SAMPLE               = "confidence_calibration_sample"

VALID_EVENT_TYPES = (
    EVT_SIGNAL_EMITTED, EVT_REJECTED_CONFIDENCE, EVT_REJECTED_RISK_ENGINE,
    EVT_REJECTED_LIQUIDITY, EVT_REJECTED_SOURCE_TIER, EVT_POSITION_OPENED,
    EVT_POSITION_CLOSED_WINNER, EVT_POSITION_CLOSED_LOSER,
    EVT_CALIBRATION_SAMPLE,
)


# ─── Tunables (degradation thresholds) ────────────────────────────────────────

DEGRADATION_MIN_SAMPLES        = 10
DEGRADATION_HIT_RATE_THRESHOLD = 0.30   # below 30% closed winners → degrade
DEGRADATION_MAE_THRESHOLD      = 0.05   # > 5% average adverse excursion → degrade
DEGRADATION_REJECT_RATE_CAP    = 0.95   # > 95% rejections → entire pipeline broken
ENTER_SAFE_MODE_SIGNALS_NEEDED = 2      # two degradation signals → safe_mode


SESSION_DIR_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "learning-loop", "session_metrics",
)


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SessionEvent:
    iso:         str
    event_type:  str
    symbol:      str
    payload:     dict

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SessionEffectivenessReport:
    date:                       str
    sample_size:                int
    signals_emitted:            int
    rejection_breakdown:        dict
    positions_opened:           int
    positions_closed_total:     int
    positions_closed_winners:   int
    positions_closed_losers:    int
    hit_rate:                   float | None
    avg_mae_pct:                float | None
    avg_mfe_pct:                float | None
    confidence_calibration:     dict
    degradation_signals:        tuple
    recommend_safe_mode:        bool
    rationale:                  str

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_path(session_dir: str | None = None) -> str:
    base = session_dir or SESSION_DIR_DEFAULT
    today = datetime.now(timezone.utc).date().isoformat()
    return os.path.join(base, f"{today}.jsonl")


# ─── Public API: emission ─────────────────────────────────────────────────────

def record_event(event_type: str, *, symbol: str = "",
                   payload: dict | None = None,
                   session_dir: str | None = None,
                   now_iso: str | None = None) -> None:
    """Append a JSONL event. Fail-soft: any error → silent."""
    if event_type not in VALID_EVENT_TYPES:
        return
    try:
        base = session_dir or SESSION_DIR_DEFAULT
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, f"{datetime.now(timezone.utc).date().isoformat()}.jsonl")
        evt = SessionEvent(
            iso=now_iso or _now_iso(),
            event_type=event_type,
            symbol=symbol or "",
            payload=payload or {},
        )
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(evt.to_dict(), separators=(",", ":")) + "\n")
    except Exception:
        pass


# ─── Public API: aggregation ──────────────────────────────────────────────────

def load_events(date_iso: str | None = None,
                 session_dir: str | None = None,
                 ) -> list[SessionEvent]:
    """Load today's events (or specific date). Fail-soft → []."""
    try:
        base = session_dir or SESSION_DIR_DEFAULT
        d = date_iso or datetime.now(timezone.utc).date().isoformat()
        path = os.path.join(base, f"{d}.jsonl")
        if not os.path.exists(path):
            return []
        out = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    out.append(SessionEvent(
                        iso=obj.get("iso", ""),
                        event_type=obj.get("event_type", ""),
                        symbol=obj.get("symbol", ""),
                        payload=obj.get("payload", {}) or {},
                    ))
                except Exception:
                    continue
        return out
    except Exception:
        return []


def compute_report(events: Iterable[SessionEvent],
                    date_iso: str | None = None,
                    ) -> SessionEffectivenessReport:
    """Aggregate events → SessionEffectivenessReport. Pure function."""
    events = list(events)
    n = len(events)
    today = date_iso or datetime.now(timezone.utc).date().isoformat()

    signals = sum(1 for e in events if e.event_type == EVT_SIGNAL_EMITTED)
    rejected_conf = sum(1 for e in events if e.event_type == EVT_REJECTED_CONFIDENCE)
    rejected_risk = sum(1 for e in events if e.event_type == EVT_REJECTED_RISK_ENGINE)
    rejected_liq  = sum(1 for e in events if e.event_type == EVT_REJECTED_LIQUIDITY)
    rejected_src  = sum(1 for e in events if e.event_type == EVT_REJECTED_SOURCE_TIER)

    rejection_breakdown = {
        "confidence":    rejected_conf,
        "risk_engine":   rejected_risk,
        "liquidity":     rejected_liq,
        "source_tier":   rejected_src,
        "total":         rejected_conf + rejected_risk + rejected_liq + rejected_src,
    }

    opens   = [e for e in events if e.event_type == EVT_POSITION_OPENED]
    winners = [e for e in events if e.event_type == EVT_POSITION_CLOSED_WINNER]
    losers  = [e for e in events if e.event_type == EVT_POSITION_CLOSED_LOSER]
    closed = len(winners) + len(losers)
    hit_rate = (len(winners) / closed) if closed > 0 else None

    mae_samples = []
    mfe_samples = []
    for e in winners + losers:
        m = e.payload.get("mae_pct")
        if isinstance(m, (int, float)):
            mae_samples.append(abs(float(m)))
        f = e.payload.get("mfe_pct")
        if isinstance(f, (int, float)):
            mfe_samples.append(float(f))
    avg_mae = (sum(mae_samples) / len(mae_samples)) if mae_samples else None
    avg_mfe = (sum(mfe_samples) / len(mfe_samples)) if mfe_samples else None

    # Confidence calibration — buckets of (confidence_at_entry → outcome)
    calib_bins: dict = {"low": [], "mid": [], "high": []}
    for e in events:
        if e.event_type == EVT_CALIBRATION_SAMPLE:
            conf = e.payload.get("confidence", 0.5)
            outcome = 1 if e.payload.get("outcome") == "win" else 0
            try:
                c = float(conf)
            except Exception:
                c = 0.5
            if c < 0.45:
                calib_bins["low"].append(outcome)
            elif c < 0.65:
                calib_bins["mid"].append(outcome)
            else:
                calib_bins["high"].append(outcome)
    calib = {k: (sum(v) / len(v)) if v else None for k, v in calib_bins.items()}
    calib["counts"] = {k: len(v) for k, v in calib_bins.items()}

    # Degradation signals
    degradation_signals = []
    if closed >= DEGRADATION_MIN_SAMPLES and hit_rate is not None \
            and hit_rate < DEGRADATION_HIT_RATE_THRESHOLD:
        degradation_signals.append("low_hit_rate")
    if avg_mae is not None and avg_mae > DEGRADATION_MAE_THRESHOLD \
            and (avg_mae / max(avg_mfe or 1e-6, 1e-6)) > 1.5:
        degradation_signals.append("adverse_excursion_dominant")
    total_decisions = signals + rejection_breakdown["total"]
    if total_decisions >= DEGRADATION_MIN_SAMPLES \
            and (rejection_breakdown["total"] / total_decisions) > DEGRADATION_REJECT_RATE_CAP:
        degradation_signals.append("pipeline_choked")
    # Confidence calibration inversion: high-conf does worse than low-conf
    high_win = calib.get("high")
    low_win = calib.get("low")
    if (high_win is not None and low_win is not None
            and high_win < low_win - 0.20
            and calib["counts"]["high"] >= 5):
        degradation_signals.append("confidence_calibration_inverted")

    recommend = len(degradation_signals) >= ENTER_SAFE_MODE_SIGNALS_NEEDED

    rationale = (
        f"signals={signals} rej={rejection_breakdown['total']} "
        f"closed={closed} hit_rate={hit_rate} avg_mae={avg_mae} "
        f"degradation={degradation_signals} recommend_safe_mode={recommend}"
    )

    return SessionEffectivenessReport(
        date=today,
        sample_size=n,
        signals_emitted=signals,
        rejection_breakdown=rejection_breakdown,
        positions_opened=len(opens),
        positions_closed_total=closed,
        positions_closed_winners=len(winners),
        positions_closed_losers=len(losers),
        hit_rate=hit_rate,
        avg_mae_pct=avg_mae,
        avg_mfe_pct=avg_mfe,
        confidence_calibration=calib,
        degradation_signals=tuple(degradation_signals),
        recommend_safe_mode=recommend,
        rationale=rationale,
    )


def report_today(session_dir: str | None = None) -> SessionEffectivenessReport:
    events = load_events(session_dir=session_dir)
    return compute_report(events)


__all__ = [
    "VALID_EVENT_TYPES",
    "EVT_SIGNAL_EMITTED", "EVT_REJECTED_CONFIDENCE", "EVT_REJECTED_RISK_ENGINE",
    "EVT_REJECTED_LIQUIDITY", "EVT_REJECTED_SOURCE_TIER",
    "EVT_POSITION_OPENED", "EVT_POSITION_CLOSED_WINNER", "EVT_POSITION_CLOSED_LOSER",
    "EVT_CALIBRATION_SAMPLE",
    "SessionEvent", "SessionEffectivenessReport",
    "record_event", "load_events", "compute_report", "report_today",
    "DEGRADATION_HIT_RATE_THRESHOLD", "DEGRADATION_MAE_THRESHOLD",
    "DEGRADATION_REJECT_RATE_CAP", "DEGRADATION_MIN_SAMPLES",
    "ENTER_SAFE_MODE_SIGNALS_NEEDED",
    "SESSION_DIR_DEFAULT",
]
