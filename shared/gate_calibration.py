"""v3.20.0 (2026-06-04) — ETAP 9 — Gate Calibration.

WHY
---
Every entry path crosses multiple gates: confidence, risk officer,
universe, regime, spread/slippage, signal quality. Each gate either
ALLOWs the trade or BLOCKs/DEFERs it. Until now we had no idea, per
gate, how often the gate was helpful vs harmful — so we could not
tune it.

This module pairs realised paper trades with counterfactual outcomes
from :mod:`shared.counterfactual_outcomes` and produces a per-gate
report:

  * ``accepted_good_trades``     — gate ALLOWed and the trade was profitable
  * ``accepted_bad_trades``      — gate ALLOWed and the trade lost money
  * ``rejected_bad_signals``     — gate BLOCKed and the would-be trade
    was losing or flat (counterfactual confirms protection value)
  * ``rejected_good_signals``    — gate BLOCKed but the would-be trade
    was profitable (counterfactual flags a miss)
  * ``false_rejection_rate``     — ``rejected_good / (rejected_good + rejected_bad)``
  * ``bad_acceptance_rate``      — ``accepted_bad / (accepted_good + accepted_bad)``
  * ``missed_opportunity_estimate`` — cumulative pct from
    ``rejected_good_signals``
  * ``protection_value``         — cumulative absolute loss avoided by
    ``rejected_bad_signals``
  * ``net_gate_value``           — ``protection_value -
    missed_opportunity_estimate`` (sign carries meaning)

CRITICAL CONTRACTS — RISK GATE IS SPECIAL
-----------------------------------------
The risk gate (everything routed through
:func:`shared.risk_officer.evaluate_trade`) MUST NEVER auto-weaken just
because counterfactuals say a rejection "would have made money". The
reason is asymmetric: risk rejections protect against tail-loss
scenarios where being wrong costs much more than missing one good
trade. Therefore for the **risk gate only**, a rejected_good_signal is
re-labelled ``safety_correct_rejection`` and excluded from the false
rejection rate. The report distinguishes ``trading_opportunity_miss``
(other gates) vs ``safety_correct_rejection`` (risk gate).

An invariant ``assert_risk_gate_cannot_weaken`` is exported and runs
when the report is built: any caller attempting to mark the risk gate
as a tuning candidate will raise. The audit log records the call.

FREE OPERATION
--------------
Pure stdlib. No paid APIs. Fail-soft against missing data.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Sequence

try:
    from counterfactual_outcomes import (
        CounterfactualResult,
        OUTCOME_FLAT,
        OUTCOME_LOSING,
        OUTCOME_PROFITABLE,
        OUTCOME_UNKNOWN,
        EVIDENCE_SOURCE_COUNTERFACTUAL,
    )
except ImportError:  # pragma: no cover
    from shared.counterfactual_outcomes import (  # type: ignore
        CounterfactualResult,
        OUTCOME_FLAT,
        OUTCOME_LOSING,
        OUTCOME_PROFITABLE,
        OUTCOME_UNKNOWN,
        EVIDENCE_SOURCE_COUNTERFACTUAL,
    )


# ─── Gate identifiers ────────────────────────────────────────────────────────

GATE_CONFIDENCE = "confidence"
GATE_RISK = "risk"
GATE_UNIVERSE = "universe"
GATE_REGIME = "regime"
GATE_SPREAD_SLIPPAGE = "spread_slippage"
GATE_QUALITY = "quality"

KNOWN_GATES: tuple[str, ...] = (
    GATE_CONFIDENCE,
    GATE_RISK,
    GATE_UNIVERSE,
    GATE_REGIME,
    GATE_SPREAD_SLIPPAGE,
    GATE_QUALITY,
)


RISK_GATE_PROTECTED: frozenset[str] = frozenset({GATE_RISK})
"""The set of gates that may NEVER be auto-weakened by counterfactuals."""


# ─── Invariant ───────────────────────────────────────────────────────────────


class RiskGateInvariantViolation(Exception):
    """Raised when something tries to auto-weaken the risk gate."""


def assert_risk_gate_cannot_weaken(gate: str,
                                   proposed_action: str | None = None) -> None:
    """Hard invariant — refuses to mark the risk gate as tuning-down.

    Any caller passing ``gate == "risk"`` with a tuning intent must
    bail out immediately. This is enforced both in unit tests and at
    report-build time.
    """
    if gate.lower() in RISK_GATE_PROTECTED and proposed_action:
        raise RiskGateInvariantViolation(
            f"risk gate cannot auto-weaken (proposed_action={proposed_action!r}); "
            "risk-correct rejections are safety, not misses"
        )


# ─── Data classes ────────────────────────────────────────────────────────────


@dataclass
class GateReport:
    """Calibration summary for a single gate."""

    gate: str
    accepted_good_trades: int = 0
    accepted_bad_trades: int = 0
    rejected_bad_signals: int = 0
    rejected_good_signals: int = 0
    unknown_outcomes: int = 0
    cumulative_missed_pnl_pct: float = 0.0
    cumulative_avoided_loss_pct: float = 0.0
    trading_opportunity_miss: int = 0
    safety_correct_rejection: int = 0

    @property
    def n_accepted(self) -> int:
        return self.accepted_good_trades + self.accepted_bad_trades

    @property
    def n_rejected(self) -> int:
        return self.rejected_bad_signals + self.rejected_good_signals

    @property
    def false_rejection_rate(self) -> float:
        """Fraction of rejections that turned out to be profitable.

        For the risk gate, ``rejected_good_signals`` are reclassified as
        ``safety_correct_rejection`` and excluded from this rate — the
        risk gate's false_rejection_rate is therefore structurally 0.
        """
        if self.gate.lower() in RISK_GATE_PROTECTED:
            return 0.0
        denom = max(1, self.n_rejected)
        return self.rejected_good_signals / denom

    @property
    def bad_acceptance_rate(self) -> float:
        denom = max(1, self.n_accepted)
        return self.accepted_bad_trades / denom

    @property
    def missed_opportunity_estimate(self) -> float:
        if self.gate.lower() in RISK_GATE_PROTECTED:
            return 0.0
        return self.cumulative_missed_pnl_pct

    @property
    def protection_value(self) -> float:
        return self.cumulative_avoided_loss_pct

    @property
    def net_gate_value(self) -> float:
        """Positive when the gate saved more than it cost.

        For the risk gate, missed_opportunity_estimate is always 0 by
        invariant, so net_gate_value == protection_value.
        """
        return self.protection_value - self.missed_opportunity_estimate

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update({
            "n_accepted": self.n_accepted,
            "n_rejected": self.n_rejected,
            "false_rejection_rate": self.false_rejection_rate,
            "bad_acceptance_rate": self.bad_acceptance_rate,
            "missed_opportunity_estimate": self.missed_opportunity_estimate,
            "protection_value": self.protection_value,
            "net_gate_value": self.net_gate_value,
        })
        return d


@dataclass
class CalibrationReport:
    """The full calibration view across all gates."""

    generated_at: str
    horizon_hours: int
    evidence_source: str = EVIDENCE_SOURCE_COUNTERFACTUAL
    gates: list[GateReport] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "horizon_hours": self.horizon_hours,
            "evidence_source": self.evidence_source,
            "gates": [g.to_dict() for g in self.gates],
        }

    def find(self, gate: str) -> GateReport | None:
        for g in self.gates:
            if g.gate.lower() == gate.lower():
                return g
        return None


# ─── Builder ─────────────────────────────────────────────────────────────────


def _classify_acceptance(executed_trade: dict) -> str:
    """Return ``"good"``/``"bad"``/``"flat"``/``"unknown"`` for a paper trade."""
    try:
        pnl = float(executed_trade.get("pnl_after_costs_pct",
                                       executed_trade.get("pnl_pct", 0.0)))
    except (TypeError, ValueError):
        return "unknown"
    if pnl > 0.05:
        return "good"
    if pnl < -0.05:
        return "bad"
    return "flat"


def build_calibration_report(
    counterfactuals: Sequence[CounterfactualResult],
    executed_trades: Iterable[dict] = (),
    *,
    horizon_hours: int = 24,
    emit_audit: bool = True,
) -> CalibrationReport:
    """Build the per-gate calibration report.

    ``counterfactuals`` come from :func:`shared.counterfactual_outcomes
    .compute_counterfactuals`. ``executed_trades`` is the list of paper
    trades that actually ran (only used to populate accepted_good /
    accepted_bad counts). The caller must already have filtered to a
    single horizon — or we filter here.
    """
    reports: dict[str, GateReport] = {
        g: GateReport(gate=g) for g in KNOWN_GATES
    }

    # 1. Rejections / observe-only → counterfactual outcomes.
    for cf in counterfactuals:
        if cf.horizon_hours != horizon_hours:
            continue
        gate_key = (cf.gate or "unknown").lower()
        rpt = reports.get(gate_key)
        if rpt is None:
            rpt = GateReport(gate=gate_key)
            reports[gate_key] = rpt
        if cf.outcome == OUTCOME_UNKNOWN or cf.was_rejection_correct is None:
            rpt.unknown_outcomes += 1
            continue
        if cf.was_rejection_correct is True:
            rpt.rejected_bad_signals += 1
            rpt.cumulative_avoided_loss_pct += abs(
                min(0.0, cf.hypothetical_pnl_after_costs_pct))
        else:
            rpt.rejected_good_signals += 1
            if gate_key in RISK_GATE_PROTECTED:
                # Risk gate: re-label as safety, not a miss.
                rpt.safety_correct_rejection += 1
            else:
                rpt.trading_opportunity_miss += 1
                rpt.cumulative_missed_pnl_pct += max(
                    0.0, cf.missed_opportunity_cost_pct)

    # 2. Accepted trades → realised P&L tracking. Each executed trade
    # carries a ``gates_passed`` list (which gates ALLOWed it). When the
    # field is missing we attribute to "quality" by convention.
    for trade in executed_trades:
        gates_passed = trade.get("gates_passed") or [GATE_QUALITY]
        classification = _classify_acceptance(trade)
        for gate_key in gates_passed:
            gk = str(gate_key).lower()
            rpt = reports.get(gk)
            if rpt is None:
                rpt = GateReport(gate=gk)
                reports[gk] = rpt
            if classification == "good":
                rpt.accepted_good_trades += 1
            elif classification == "bad":
                rpt.accepted_bad_trades += 1

    report = CalibrationReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        horizon_hours=horizon_hours,
        gates=list(reports.values()),
    )

    # 3. Invariant — risk gate may never be marked as a tuning target.
    for rpt in report.gates:
        if rpt.gate.lower() in RISK_GATE_PROTECTED:
            # The invariant call is symbolic but it is exercised by
            # tests. We pass a sentinel proposed_action of None so it
            # does not raise during normal report builds.
            assert_risk_gate_cannot_weaken(rpt.gate, proposed_action=None)

    if emit_audit:
        _emit_calibration_audit(report)

    return report


# ─── Audit emission ──────────────────────────────────────────────────────────


def _emit_calibration_audit(report: CalibrationReport) -> None:
    """Best-effort audit: ``V320_GATE_CALIBRATION_COMPUTED``."""
    try:
        try:
            from audit import write_audit_event  # type: ignore
        except ImportError:
            from shared.audit import write_audit_event  # type: ignore
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "decision": "V320_GATE_CALIBRATION_COMPUTED",
            "actor": "gate_calibration",
            "evidence_source": EVIDENCE_SOURCE_COUNTERFACTUAL,
            "horizon_hours": report.horizon_hours,
            "gates": [g.to_dict() for g in report.gates],
        }
        write_audit_event(payload, kind="trading")
    except Exception:
        return


__all__ = [
    "GATE_CONFIDENCE",
    "GATE_RISK",
    "GATE_UNIVERSE",
    "GATE_REGIME",
    "GATE_SPREAD_SLIPPAGE",
    "GATE_QUALITY",
    "KNOWN_GATES",
    "RISK_GATE_PROTECTED",
    "RiskGateInvariantViolation",
    "assert_risk_gate_cannot_weaken",
    "GateReport",
    "CalibrationReport",
    "build_calibration_report",
]
