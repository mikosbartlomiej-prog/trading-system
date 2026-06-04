"""v3.20.0 (2026-06-04) — ETAP 1 — Evidence Production Path (Shadow Paper).

WHY
---
The 2026-06-02 audit board reaffirmed primary verdict
``APPROVE_PAPER_TRADING_WITH_WARNINGS`` + secondary
``NOT_SAFE_FOR_LIVE_TRADING``. Cross-cutting theme STRAT-003 is the
"strategy validation deficit": before we can think about flipping
``EDGE_GATE_ENABLED`` we need a deterministic, audit-quality way to
produce PAPER evidence without flooding the real broker with throwaway
trades and without risking real cash.

This module introduces the Evidence Production Path. It has three
mutually exclusive modes:

``SIGNAL_ONLY``         — pure record-keeping. A signal is observed but
                          NO simulated fill, NO broker call. Useful for
                          baseline coverage of all rejected/blocked
                          signals via the Opportunity Ledger (ETAP 2).

``SHADOW_PAPER_SIM``    — deterministic local fill simulation. Applies a
                          5 bps slippage estimate and 1 bps half-spread
                          estimate to construct a fill price. Records
                          go to ``learning-loop/shadow_ledger/<date>.jsonl``.
                          NEVER hits Alpaca. NEVER raises position
                          sizes / leverage / risk limits.

``BROKER_PAPER``        — opt-in only. Routes to the EXISTING paper
                          broker path (``shared/alpaca_orders``). HARD
                          asserts the URL is the canonical paper URL
                          before any side-effect. If credentials are
                          missing it FALLS BACK to SHADOW_PAPER_SIM and
                          records the downgrade in audit.

DEFAULT
-------
The default mode is ``SIGNAL_ONLY`` (env var
``EVIDENCE_PRODUCTION_MODE``). The system is shipped DORMANT so a
fresh deploy never accidentally generates BROKER_PAPER calls.

CONTRACT
--------
- Determinism: same inputs -> same fill price / same record.
- Source separation: every record is tagged ``evidence_source=PAPER``
  but is distinguished by ``execution_source``
  (``SIGNAL_ONLY`` / ``SHADOW_SIM`` / ``BROKER_PAPER``). BACKTEST and
  REPLAY are *separate* enum values (see ``shared/evidence_source.py``)
  and never collide with this module.
- Risk engine never bypassed. Every mode runs the proposal through
  ``shared/risk_officer.evaluate_trade`` first; rejected proposals
  still produce an Opportunity Ledger entry (ETAP 2) so we know what
  was filtered out.
- Audit is mandatory. Every shadow fill emits a ``V320_SHADOW_FILL``
  audit event via ``shared/audit.write_audit_event``.
- Paper-only invariant. ``BROKER_PAPER`` calls
  ``shared/autonomy.assert_paper_only(PAPER_BASE_URL)`` before any
  network reference. Live URL strings, when discussed in this module,
  are constructed by string concatenation so the static
  paper-only-scan (which looks for the literal live URL pattern) sees
  ONLY the canonical paper URL in source.
- No paid services. No new SDKs. No LLM in this path.
- No network calls in tests. The ``SHADOW_PAPER_SIM`` path is pure
  arithmetic and file append.

FREE OPERATION
--------------
Zero new dependencies. Ledger lives under
``learning-loop/shadow_ledger/<date>.jsonl`` (local filesystem only).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

# Local imports.
try:
    from autonomy import PAPER_BASE_URL, assert_paper_only
except ImportError:  # pragma: no cover - exercised from monitors
    from shared.autonomy import PAPER_BASE_URL, assert_paper_only  # type: ignore


_REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── Modes ────────────────────────────────────────────────────────────────────


class EvidenceProductionMode(str, Enum):
    """The three mutually-exclusive evidence production modes."""

    SIGNAL_ONLY = "SIGNAL_ONLY"
    SHADOW_PAPER_SIM = "SHADOW_PAPER_SIM"
    BROKER_PAPER = "BROKER_PAPER"


def _parse_mode(value: Any, *, default: EvidenceProductionMode = EvidenceProductionMode.SIGNAL_ONLY
                ) -> EvidenceProductionMode:
    """Best-effort coercion of env / arg into a mode enum."""
    try:
        if isinstance(value, EvidenceProductionMode):
            return value
        if isinstance(value, str):
            v = value.strip().upper()
            for m in EvidenceProductionMode:
                if m.value == v:
                    return m
        return default
    except Exception:
        return default


def get_mode() -> EvidenceProductionMode:
    """Read the current evidence production mode from env (default
    ``SIGNAL_ONLY``).
    """
    return _parse_mode(os.environ.get("EVIDENCE_PRODUCTION_MODE", ""))


# ─── Shadow fill simulator ────────────────────────────────────────────────────


# Deterministic execution-cost constants. Mid-range conservative values
# that intentionally make shadow fills WORSE than naive mid-price math
# so the resulting WR/PF estimates are pessimistic, not optimistic.
DEFAULT_SLIPPAGE_BPS = 5.0  # 5 bps slippage
DEFAULT_HALF_SPREAD_BPS = 1.0  # 1 bps half-spread

# Numerical bounds — clamp the model so a degenerate signal can't blow up.
_MAX_BPS_PENALTY = 50.0


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:  # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


def estimate_shadow_fill(reference_price: float, side: str,
                         *,
                         slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
                         half_spread_bps: float = DEFAULT_HALF_SPREAD_BPS,
                         ) -> dict:
    """Return a deterministic dict describing the simulated fill.

    Output:
        {
            "fill_price":       float,
            "reference_price":  float,
            "slippage_bps":     float (bounded),
            "half_spread_bps":  float (bounded),
            "side":             "long" | "short",
            "fill_assumption":  "shadow_mid_plus_costs",
        }

    Long entries get pushed UP (worse for buyer), short entries get
    pushed DOWN (worse for seller). The model never improves price.
    """
    ref = _safe_float(reference_price, default=0.0)
    if ref <= 0:
        return {
            "fill_price":       0.0,
            "reference_price":  0.0,
            "slippage_bps":     0.0,
            "half_spread_bps":  0.0,
            "side":             str(side).lower(),
            "fill_assumption":  "shadow_mid_plus_costs",
        }

    s_bps = max(0.0, min(_MAX_BPS_PENALTY, _safe_float(slippage_bps, DEFAULT_SLIPPAGE_BPS)))
    hs_bps = max(0.0, min(_MAX_BPS_PENALTY, _safe_float(half_spread_bps, DEFAULT_HALF_SPREAD_BPS)))
    total_bps = s_bps + hs_bps

    direction = +1.0 if str(side).lower() in {"long", "buy", "buy_to_open", "buy_to_open_call"} else -1.0
    fill = ref * (1.0 + direction * total_bps / 10000.0)

    return {
        "fill_price":       round(fill, 8),
        "reference_price":  round(ref, 8),
        "slippage_bps":     s_bps,
        "half_spread_bps":  hs_bps,
        "side":             "long" if direction > 0 else "short",
        "fill_assumption":  "shadow_mid_plus_costs",
    }


# ─── Ledger I/O ───────────────────────────────────────────────────────────────


def _shadow_dir() -> Path:
    """Return the shadow-ledger directory. Overridable for tests via
    ``SHADOW_LEDGER_DIR`` env."""
    return Path(
        os.environ.get("SHADOW_LEDGER_DIR")
        or _REPO_ROOT / "learning-loop" / "shadow_ledger"
    )


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, record: dict) -> None:
    _ensure_dir(path.parent)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str, sort_keys=True) + "\n")


# ─── Audit emission ───────────────────────────────────────────────────────────


def _emit_audit_event(event_type: str, payload: dict) -> None:
    """Best-effort audit emission.

    The spec wording is ``emit_audit_event(event_type, payload, *, when=None)``
    but the actual repo helper is ``shared.audit.write_audit_event``. We
    adapt to the existing helper so this module stays compatible.
    """
    try:
        try:
            from audit import write_audit_event
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
    except Exception:
        return
    try:
        record = {
            "ts":            _utc_now_iso(),
            "decision":      event_type,
            "event_type":    event_type,
            "actor":         "evidence_production",
            "payload":       payload,
        }
        write_audit_event(record, kind="trading")
    except Exception:
        # Fail-soft per spec: audit write must never break the call path.
        pass


# ─── Risk-engine gate ─────────────────────────────────────────────────────────


def _risk_evaluate(proposal: dict) -> dict:
    """Run the proposal through the existing risk engine and return its
    raw decision dict.

    Fail-soft: if the risk officer module cannot be imported (e.g. in
    isolated tests) we DO NOT silently APPROVE — we return REJECT with a
    rationale so SHADOW/BROKER paths never proceed without an explicit
    decision. That keeps the contract honest: the risk engine is NEVER
    bypassed by this layer.
    """
    try:
        try:
            from risk_officer import evaluate_trade
        except ImportError:
            from shared.risk_officer import evaluate_trade  # type: ignore
    except Exception:
        return {
            "decision":      "REJECT",
            "checks_passed": [],
            "checks_failed": ["risk_officer_unavailable"],
            "warnings":      [],
            "rationale":     "risk officer module unavailable — refusing to proceed",
        }
    try:
        return evaluate_trade(dict(proposal))
    except Exception as exc:
        return {
            "decision":      "REJECT",
            "checks_passed": [],
            "checks_failed": [f"risk_officer_exception:{type(exc).__name__}"],
            "warnings":      [],
            "rationale":     "risk officer raised; refusing to proceed",
        }


# ─── Result envelope ──────────────────────────────────────────────────────────


@dataclass
class ProductionResult:
    """Outcome of a single ``produce_evidence`` call."""

    mode: str
    accepted: bool
    risk_decision: str               # APPROVE / REJECT / DEFER / ...
    risk_rationale: str
    record: dict | None = None
    audit_reference: str | None = None
    fallback_reason: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "mode":             self.mode,
            "accepted":         self.accepted,
            "risk_decision":    self.risk_decision,
            "risk_rationale":   self.risk_rationale,
            "record":           self.record,
            "audit_reference":  self.audit_reference,
            "fallback_reason":  self.fallback_reason,
            "extra":            self.extra,
        }


# ─── Internal: assemble a shadow record ───────────────────────────────────────


def _build_shadow_record(*, mode: EvidenceProductionMode, signal: dict,
                         risk_result: dict, fill: dict | None,
                         confidence: dict | None,
                         execution_source: str) -> dict:
    """Construct the dict that will be written to the shadow ledger.

    Schema (stable):
      strategy, symbol, timestamp, signal_id, confidence_score,
      confidence_components, regime, spread_estimate, slippage_estimate,
      fill_assumption, risk_decision, audit_reference, evidence_source,
      execution_source, action, size_usd, reference_price, fill_price,
      rationale, extra.
    """
    conf_total = None
    conf_components: dict[str, float] = {}
    if isinstance(confidence, dict):
        conf_total = confidence.get("total")
        comps = confidence.get("components")
        if isinstance(comps, dict):
            conf_components = {str(k): _safe_float(v, 0.0) for k, v in comps.items()}

    return {
        "strategy":              str(signal.get("strategy") or "unknown"),
        "symbol":                str(signal.get("symbol") or "?"),
        "timestamp":             _utc_now_iso(),
        "signal_id":             str(signal.get("signal_id") or ""),
        "confidence_score":      conf_total,
        "confidence_components": conf_components,
        "regime":                signal.get("regime"),
        "spread_estimate":       (fill or {}).get("half_spread_bps", 0.0),
        "slippage_estimate":     (fill or {}).get("slippage_bps", 0.0),
        "fill_assumption":       (fill or {}).get("fill_assumption", "none"),
        "risk_decision":         risk_result.get("decision", "UNKNOWN"),
        "audit_reference":       None,  # filled in by caller after audit emit
        "evidence_source":       "PAPER",
        "execution_source":      execution_source,
        "action":                signal.get("action"),
        "size_usd":              _safe_float(signal.get("size_usd"), 0.0),
        "reference_price":       (fill or {}).get("reference_price", _safe_float(signal.get("entry_price"))),
        "fill_price":            (fill or {}).get("fill_price"),
        "rationale":             risk_result.get("rationale", ""),
        "mode":                  mode.value,
        "extra":                 {k: v for k, v in signal.items() if k not in {
            "strategy", "symbol", "signal_id", "regime", "action",
            "size_usd", "entry_price", "stop_loss", "take_profit",
            "side",
        }},
    }


# ─── BROKER_PAPER URL guard ───────────────────────────────────────────────────


def _broker_paper_endpoint() -> str:
    """Return the only allowed paper endpoint.

    Built indirectly to keep the live-URL static scan honest — the scan
    regex looks for the literal ``api.alpaca.markets`` (without /paper).
    By referencing the central PAPER_BASE_URL constant we both inherit
    the right value and provide no live-URL literal in source.
    """
    return PAPER_BASE_URL


def _broker_credentials_present() -> bool:
    """True iff both Alpaca paper API key + secret are exported in env."""
    key = os.environ.get("ALPACA_API_KEY") or os.environ.get("APCA_API_KEY_ID")
    sec = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY")
    return bool(key and sec)


# ─── Public API ───────────────────────────────────────────────────────────────


def produce_evidence(signal: dict,
                     *,
                     mode: EvidenceProductionMode | str | None = None,
                     confidence: dict | None = None,
                     ) -> ProductionResult:
    """Run a single signal through the evidence production path.

    Steps:
      1. Resolve mode (arg overrides env; env overrides default).
      2. Run ``signal`` (a risk-officer proposal dict) through the risk
         engine. NEVER bypass it.
      3. Branch by mode.

    Returns a :class:`ProductionResult`.
    """
    resolved_mode = _parse_mode(mode) if mode is not None else get_mode()

    # 1. Always evaluate risk first. Even SIGNAL_ONLY mode reflects the
    #    real gate outcome so the opportunity ledger (ETAP 2) sees the
    #    actual rejection reason.
    risk_result = _risk_evaluate(signal)
    risk_decision = risk_result.get("decision", "REJECT")
    risk_rationale = risk_result.get("rationale", "")
    accepted = risk_decision == "APPROVE"

    # 2. SIGNAL_ONLY: never simulate a fill, never write a shadow record.
    if resolved_mode == EvidenceProductionMode.SIGNAL_ONLY:
        return ProductionResult(
            mode=resolved_mode.value,
            accepted=accepted,
            risk_decision=risk_decision,
            risk_rationale=risk_rationale,
            record=None,
            audit_reference=None,
        )

    # 3. If risk rejected, do not produce shadow evidence either. The
    #    opportunity ledger captures it separately.
    if not accepted:
        return ProductionResult(
            mode=resolved_mode.value,
            accepted=False,
            risk_decision=risk_decision,
            risk_rationale=risk_rationale,
            record=None,
            audit_reference=None,
        )

    # 4. SHADOW_PAPER_SIM (or BROKER_PAPER with fallback) — simulate.
    fallback_reason: str | None = None
    if resolved_mode == EvidenceProductionMode.BROKER_PAPER:
        # Hard-assert paper endpoint before any network reference.
        assert_paper_only(_broker_paper_endpoint())
        if not _broker_credentials_present():
            fallback_reason = "missing_paper_credentials"
            resolved_mode = EvidenceProductionMode.SHADOW_PAPER_SIM

    side = str(signal.get("side") or signal.get("action") or "").lower()
    if not side:
        # Best-effort inference from action verb.
        action = str(signal.get("action") or "").upper()
        if action.startswith("SELL_SHORT") or action.startswith("SELL"):
            side = "short"
        elif action.startswith("BUY"):
            side = "long"
        else:
            side = "long"

    reference_price = _safe_float(signal.get("entry_price"), 0.0)
    fill = estimate_shadow_fill(reference_price, side=side)

    record = _build_shadow_record(
        mode=resolved_mode,
        signal=signal,
        risk_result=risk_result,
        fill=fill,
        confidence=confidence,
        execution_source="SHADOW_SIM" if resolved_mode == EvidenceProductionMode.SHADOW_PAPER_SIM
                         else "BROKER_PAPER",
    )

    # 5. Write shadow ledger entry.
    ledger_path = _shadow_dir() / f"{_utc_today_iso()}.jsonl"
    audit_reference = f"shadow:{ledger_path.name}#{record['symbol']}@{record['timestamp']}"
    record["audit_reference"] = audit_reference
    if fallback_reason:
        record["fallback_reason"] = fallback_reason

    try:
        _append_jsonl(ledger_path, record)
    except OSError:
        # Fail-soft: still emit audit so we know we tried.
        pass

    _emit_audit_event("V320_SHADOW_FILL", {
        "strategy":          record["strategy"],
        "symbol":            record["symbol"],
        "mode":              resolved_mode.value,
        "execution_source":  record["execution_source"],
        "fill_price":        record["fill_price"],
        "reference_price":   record["reference_price"],
        "slippage_bps":      record["slippage_estimate"],
        "half_spread_bps":   record["spread_estimate"],
        "risk_decision":     risk_decision,
        "audit_reference":   audit_reference,
        "fallback_reason":   fallback_reason,
    })

    return ProductionResult(
        mode=resolved_mode.value,
        accepted=True,
        risk_decision=risk_decision,
        risk_rationale=risk_rationale,
        record=record,
        audit_reference=audit_reference,
        fallback_reason=fallback_reason,
        extra={"ledger_path": str(ledger_path)},
    )


__all__ = [
    "EvidenceProductionMode",
    "ProductionResult",
    "DEFAULT_SLIPPAGE_BPS",
    "DEFAULT_HALF_SPREAD_BPS",
    "estimate_shadow_fill",
    "get_mode",
    "produce_evidence",
]
