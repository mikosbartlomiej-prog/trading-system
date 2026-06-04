"""v3.20.0 (2026-06-04) — ETAP 2 — Signal Opportunity Ledger.

WHY
---
Today the only signals we keep durable evidence on are the ones that
*reach* the broker (or the shadow simulator). Every BLOCKED, DEFERRED,
or downsized signal is logged to stderr and effectively lost. That
breaks the post-trade audit story (per audit board P1 ``CONF-003`` +
``DATA-002``) and prevents the learning loop from reasoning about
*why* we did not take a trade.

This module records EVERY signal — accepted, rejected, deferred — to a
single daily JSONL under
``learning-loop/opportunity_ledger/<date>.jsonl``. Each entry captures
the per-gate decisions so a future replay can answer "if we removed
gate X for strategy Y, how many extra trades would we have placed?".

CONTRACT
--------
- Pure record-keeping. ``record_opportunity(...)`` NEVER places trades,
  NEVER touches the broker, NEVER bypasses risk engines. The signal
  has already been evaluated upstream; this layer only WRITES.
- Six gate types are recognised (see ``GATE_TYPES``): confidence, risk,
  universe, regime, spread_slippage, quality. Unknown gate names are
  retained but flagged in the audit payload as ``unknown_gate``.
- Determinism. Records are timestamped to microsecond UTC and sorted
  JSON so diffs are stable across replays.
- Free operation. Local filesystem only. No paid APIs. Audit emit goes
  through the existing ``shared.audit.write_audit_event`` helper.
- Offline-safe. No network calls; safe to import under the e2e
  ``conftest.py`` network guard.
- Audit emit per record: ``V320_OPPORTUNITY_RECORDED``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


_REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── Schema ───────────────────────────────────────────────────────────────────


# Closed enum of recognised gate types. Spec §ETAP 2.
GATE_TYPES: frozenset[str] = frozenset({
    "confidence",
    "risk",
    "universe",
    "regime",
    "spread_slippage",
    "quality",
})


@dataclass
class GateDecision:
    """One per-gate decision attached to an opportunity record."""

    gate: str
    decision: str               # PASS | BLOCK | DEFER | DOWNSIZE | ALERT_ONLY
    reason: str = ""
    score: float | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "gate":      self.gate,
            "decision":  self.decision,
            "reason":    self.reason,
            "score":     self.score,
            "extra":     dict(self.extra),
        }


# ─── Storage helpers ──────────────────────────────────────────────────────────


def _ledger_dir() -> Path:
    return Path(
        os.environ.get("OPPORTUNITY_LEDGER_DIR")
        or _REPO_ROOT / "learning-loop" / "opportunity_ledger"
    )


def _utc_now_iso_us() -> str:
    # Microsecond precision so close-together opportunities don't
    # collide on signal_id when called in tight loops.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _safe_str(x: Any, default: str = "") -> str:
    try:
        return str(x) if x is not None else default
    except Exception:
        return default


def _safe_float(x: Any, default: float | None = None) -> float | None:
    if x is None:
        return default
    try:
        v = float(x)
        if v != v:  # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


# ─── Audit emission ───────────────────────────────────────────────────────────


def _emit_audit_event(event_type: str, payload: dict) -> None:
    """Best-effort audit emission. Never raises. Spec §ETAP 2."""
    try:
        try:
            from audit import write_audit_event
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
    except Exception:
        return
    try:
        record = {
            "ts":           _utc_now_iso_us(),
            "decision":     event_type,
            "event_type":   event_type,
            "actor":        "signal_opportunity_ledger",
            "payload":      payload,
        }
        write_audit_event(record, kind="trading")
    except Exception:
        pass


# ─── Normalisation ────────────────────────────────────────────────────────────


def _normalise_gates(gate_decisions: Iterable[dict | GateDecision] | None
                     ) -> list[dict]:
    out: list[dict] = []
    if not gate_decisions:
        return out
    for g in gate_decisions:
        if isinstance(g, GateDecision):
            out.append(g.to_dict())
            continue
        if not isinstance(g, dict):
            continue
        gate_name = _safe_str(g.get("gate")).lower() or "unknown"
        out.append({
            "gate":      gate_name,
            "decision":  _safe_str(g.get("decision"), "UNKNOWN").upper(),
            "reason":    _safe_str(g.get("reason"), ""),
            "score":     _safe_float(g.get("score")),
            "extra":     dict(g.get("extra") or {}),
        })
    return out


def _collect_rejection_reasons(gates: list[dict]) -> list[str]:
    """Collect reasons for any gate that did not PASS."""
    blockers = {"BLOCK", "DEFER", "DOWNSIZE", "REJECT", "ALERT_ONLY"}
    out: list[str] = []
    for g in gates:
        if g.get("decision", "").upper() in blockers:
            reason = g.get("reason") or g.get("decision")
            out.append(f"{g.get('gate', 'unknown')}: {reason}")
    return out


# ─── Public API ───────────────────────────────────────────────────────────────


def record_opportunity(
    *,
    signal_id: str,
    strategy: str,
    symbol: str,
    raw_signal: dict | None = None,
    confidence_score: float | None = None,
    confidence_components: dict | None = None,
    risk_decision: str | None = None,
    gate_decisions: Iterable[dict | GateDecision] | None = None,
    rejection_reasons: Iterable[str] | None = None,
    market_regime: str | None = None,
    universe_status: str | None = None,
    paper_action: str | None = None,
    shadow_action: str | None = None,
    audit_link: str | None = None,
    timestamp: str | None = None,
) -> dict:
    """Append one opportunity record to today's ledger.

    Returns the record (already on disk) so callers can attach the
    ledger path / signal_id to their own logs.
    """
    gates = _normalise_gates(gate_decisions)
    auto_reasons = _collect_rejection_reasons(gates)
    explicit_reasons = [str(r) for r in (rejection_reasons or []) if r]

    # Flag any gate names we don't recognise — they are still recorded
    # but downstream consumers will know to treat them carefully.
    unknown_gates = [g["gate"] for g in gates if g.get("gate") not in GATE_TYPES]

    record = {
        "signal_id":             _safe_str(signal_id, default="?"),
        "strategy":              _safe_str(strategy, default="unknown"),
        "symbol":                _safe_str(symbol, default="?"),
        "timestamp":             _safe_str(timestamp, default="") or _utc_now_iso_us(),
        "raw_signal":            dict(raw_signal or {}),
        "confidence_score":      _safe_float(confidence_score),
        "confidence_components": dict(confidence_components or {}),
        "risk_decision":         _safe_str(risk_decision, default="UNKNOWN"),
        "gate_decisions":        gates,
        "rejection_reasons":     explicit_reasons + auto_reasons,
        "market_regime":         market_regime,
        "universe_status":       universe_status,
        "paper_action":          paper_action,
        "shadow_action":         shadow_action,
        "audit_link":            audit_link,
        "schema_version":        "v3.20.0",
    }
    if unknown_gates:
        record["unknown_gates"] = unknown_gates

    ledger_path = _ledger_dir() / f"{_utc_today_iso()}.jsonl"
    try:
        _ensure_dir(ledger_path.parent)
        with open(ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str, sort_keys=True) + "\n")
    except OSError:
        # Fail-soft, but caller still gets the record so it can be
        # forwarded to email / stderr / etc.
        pass

    _emit_audit_event("V320_OPPORTUNITY_RECORDED", {
        "signal_id":         record["signal_id"],
        "strategy":          record["strategy"],
        "symbol":            record["symbol"],
        "risk_decision":     record["risk_decision"],
        "rejection_reasons": record["rejection_reasons"],
        "audit_link":        record["audit_link"],
        "unknown_gates":     unknown_gates or [],
    })

    return record


# ─── Read helpers (for the learning loop) ─────────────────────────────────────


def read_today() -> list[dict]:
    """Return all opportunities recorded today, in append order."""
    path = _ledger_dir() / f"{_utc_today_iso()}.jsonl"
    out: list[dict] = []
    if not path.exists():
        return out
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


__all__ = [
    "GATE_TYPES",
    "GateDecision",
    "record_opportunity",
    "read_today",
]
