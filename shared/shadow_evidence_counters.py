"""v3.26.0 (2026-06-09) — signal/shadow evidence counters.

Persists counts that the v3.25 ``trading_unlock_readiness`` module
consumes to evaluate whether broker-paper canary readiness can be
reached. Counts live under
``learning-loop/shadow_evidence/evidence_counters_latest.json``.

CONTRACT
--------
- READ + WRITE module (writes ONLY the counters file under
  ``learning-loop/shadow_evidence/``).
- Does NOT submit orders.
- Does NOT modify any other state file.
- Counts are monotonic non-decreasing per metric; never reset
  silently.

INVARIANTS (test-asserted)
--------------------------
- NEVER_SUBMITS_ORDERS = True
- NEVER_PROMOTES_BROKER_PAPER = True
- COUNTERS_ARE_MONOTONIC = True
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ─── Metric names ────────────────────────────────────────────────────────────
#
# Every metric a v3.26 collector may touch. Adding new metrics is
# allowed but they must be appended here; tests pin the list.

METRIC_NORMAL_NON_HALT_OPPORTUNITIES       = "normal_non_halt_opportunities_count"
METRIC_COMPLETED_SHADOW_OUTCOMES           = "completed_shadow_outcomes_count"
METRIC_HALT_PATH_OPPORTUNITIES             = "halt_path_opportunities_count"
METRIC_WOULD_BLOCK_BY_CRYPTO_EXPOSURE      = "would_block_by_crypto_exposure_count"
METRIC_WOULD_BLOCK_BY_DRAWDOWN_GUARD       = "would_block_by_drawdown_guard_count"
METRIC_WOULD_BLOCK_BY_RECENT_LOSS_COOLDOWN = "would_block_by_recent_loss_cooldown_count"
METRIC_EXPOSURE_CAP_BREACH                 = "exposure_cap_breach_count"
METRIC_REPEATED_BUY_VIOLATION              = "repeated_buy_violation_count"
METRIC_AUDIT_BYPASS_FINDINGS               = "audit_bypass_findings_count"
METRIC_UNEXPLAINED_BROKER_STATE_CONFLICTS  = (
    "unexplained_broker_state_conflicts_count")
# v3.26.1 (2026-06-09) — distinguish real evidence from scaffold smoke
# from halt-path skip-only. The v3.25 trading_unlock_readiness gate
# consumes ``real_market_opportunities_count`` directly. The legacy
# ``normal_non_halt_opportunities_count`` is preserved and ONLY
# incremented when ``evidence_quality == REAL_MARKET_DATA``.
METRIC_REAL_MARKET_OPPORTUNITIES           = "real_market_opportunities_count"
METRIC_SCAFFOLD_NO_MARKET_DATA_RECORDS     = "scaffold_no_market_data_records_count"
METRIC_HALT_PATH_RECORDS                   = "halt_path_records_count"

ALL_METRICS: tuple[str, ...] = (
    METRIC_NORMAL_NON_HALT_OPPORTUNITIES,
    METRIC_COMPLETED_SHADOW_OUTCOMES,
    METRIC_HALT_PATH_OPPORTUNITIES,
    METRIC_WOULD_BLOCK_BY_CRYPTO_EXPOSURE,
    METRIC_WOULD_BLOCK_BY_DRAWDOWN_GUARD,
    METRIC_WOULD_BLOCK_BY_RECENT_LOSS_COOLDOWN,
    METRIC_EXPOSURE_CAP_BREACH,
    METRIC_REPEATED_BUY_VIOLATION,
    METRIC_AUDIT_BYPASS_FINDINGS,
    METRIC_UNEXPLAINED_BROKER_STATE_CONFLICTS,
    METRIC_REAL_MARKET_OPPORTUNITIES,
    METRIC_SCAFFOLD_NO_MARKET_DATA_RECORDS,
    METRIC_HALT_PATH_RECORDS,
)

# Evidence quality enum (matches the JSON Schema).
EVIDENCE_QUALITY_REAL_MARKET_DATA        = "REAL_MARKET_DATA"
EVIDENCE_QUALITY_SCAFFOLD_NO_MARKET_DATA = "SCAFFOLD_NO_MARKET_DATA"
EVIDENCE_QUALITY_HALT_PATH_ONLY          = "HALT_PATH_ONLY"

ALL_EVIDENCE_QUALITIES: tuple[str, ...] = (
    EVIDENCE_QUALITY_REAL_MARKET_DATA,
    EVIDENCE_QUALITY_SCAFFOLD_NO_MARKET_DATA,
    EVIDENCE_QUALITY_HALT_PATH_ONLY,
)

# Thresholds for the unlock-readiness handoff. We mirror the v3.25
# values so callers can quickly check progress without importing the
# unlock module.
THRESHOLD_NORMAL_OPPORTUNITIES = 50
THRESHOLD_SHADOW_OUTCOMES      = 20

# Invariants.
NEVER_SUBMITS_ORDERS         = True
NEVER_PROMOTES_BROKER_PAPER  = True
COUNTERS_ARE_MONOTONIC       = True

# Path layout.
EVIDENCE_DIR = Path("learning-loop") / "shadow_evidence"
COUNTERS_FILENAME = "evidence_counters_latest.json"


# ─── Data class ──────────────────────────────────────────────────────────────

@dataclass
class EvidenceCounters:
    version: str = "v3.26.1"
    generated_at_iso: str = "2026-06-09T00:00:00+00:00"
    normal_non_halt_opportunities_count: int = 0
    completed_shadow_outcomes_count: int = 0
    halt_path_opportunities_count: int = 0
    would_block_by_crypto_exposure_count: int = 0
    would_block_by_drawdown_guard_count: int = 0
    would_block_by_recent_loss_cooldown_count: int = 0
    exposure_cap_breach_count: int = 0
    repeated_buy_violation_count: int = 0
    audit_bypass_findings_count: int = 0
    unexplained_broker_state_conflicts_count: int = 0
    # v3.26.1 — evidence quality split.
    real_market_opportunities_count: int = 0
    scaffold_no_market_data_records_count: int = 0
    halt_path_records_count: int = 0
    thresholds: dict[str, int] = field(default_factory=lambda: {
        "normal_opportunities": THRESHOLD_NORMAL_OPPORTUNITIES,
        "completed_shadow_outcomes": THRESHOLD_SHADOW_OUTCOMES,
        "real_market_opportunities": THRESHOLD_NORMAL_OPPORTUNITIES,
    })
    safety_invariants: dict[str, bool] = field(default_factory=lambda: {
        "broker_order_submitted_ever": False,
        "live_trading_enabled": False,
        "broker_paper_enabled": False,
        "edge_gate_enabled": False,
        "baseline_reset": False,
        "drawdown_guard_lowered": False,
    })

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─── Internal helpers ────────────────────────────────────────────────────────

def _counters_path(repo_root: Path) -> Path:
    return repo_root / EVIDENCE_DIR / COUNTERS_FILENAME


# ─── Public API ──────────────────────────────────────────────────────────────

def load_counters(repo_root: Path | None = None) -> EvidenceCounters:
    """Load counters from disk; return defaults if file missing.

    Never raises on a missing file — returns a fresh
    ``EvidenceCounters()`` so callers can chain ``increment_*`` calls.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent
    path = _counters_path(repo_root)
    if not path.exists():
        return EvidenceCounters()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return EvidenceCounters()
    out = EvidenceCounters()
    for name in ALL_METRICS:
        if isinstance(raw.get(name), int):
            setattr(out, name, raw[name])
    # Carry thresholds / safety_invariants if present.
    if isinstance(raw.get("thresholds"), dict):
        out.thresholds.update(
            {k: v for k, v in raw["thresholds"].items()
             if isinstance(v, int)},
        )
    if isinstance(raw.get("safety_invariants"), dict):
        out.safety_invariants.update(
            {k: bool(v) for k, v in raw["safety_invariants"].items()},
        )
    if isinstance(raw.get("version"), str):
        out.version = raw["version"]
    if isinstance(raw.get("generated_at_iso"), str):
        out.generated_at_iso = raw["generated_at_iso"]
    return out


def save_counters(counters: EvidenceCounters,
                   *, repo_root: Path | None = None,
                   generated_at_iso: str | None = None) -> Path:
    """Persist counters to disk. Refuses to write if any safety
    invariant is False (would indicate the operator/runtime has
    mutated the invariants away from their safe defaults)."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent
    # Refuse to persist if invariants were tampered.
    if counters.safety_invariants.get("broker_order_submitted_ever"):
        raise RuntimeError(
            "refuse to persist counters: "
            "broker_order_submitted_ever=True")
    if counters.safety_invariants.get("live_trading_enabled"):
        raise RuntimeError(
            "refuse to persist counters: live_trading_enabled=True")
    if counters.safety_invariants.get("broker_paper_enabled"):
        raise RuntimeError(
            "refuse to persist counters: broker_paper_enabled=True")
    if generated_at_iso:
        counters.generated_at_iso = generated_at_iso
    target = _counters_path(repo_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(counters.as_dict(), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return target


def increment(counters: EvidenceCounters, metric: str,
               by: int = 1) -> EvidenceCounters:
    """Monotonic non-decreasing increment for one metric.

    Negative or zero ``by`` values are clamped to a no-op. Unknown
    metric names raise ``KeyError`` — callers must reference the
    documented metric constants.
    """
    if metric not in ALL_METRICS:
        raise KeyError(
            f"unknown metric: {metric!r} "
            f"(allowed: {ALL_METRICS})")
    if by <= 0:
        return counters
    current = getattr(counters, metric)
    setattr(counters, metric, current + by)
    return counters


def progress_summary(counters: EvidenceCounters) -> dict[str, Any]:
    """Return a compact view of progress toward broker-paper canary
    readiness.

    v3.26.1: progress is measured against
    ``real_market_opportunities_count``, NOT
    ``normal_non_halt_opportunities_count`` (which v3.26.0 inflated
    with scaffold records). ``broker_paper_canary_ready`` is always
    ``False`` here — promotion still requires the v3.25
    trading_unlock_readiness gate plus explicit operator approval.
    """
    real_target = counters.thresholds.get(
        "real_market_opportunities", THRESHOLD_NORMAL_OPPORTUNITIES)
    outcome_target = counters.thresholds.get(
        "completed_shadow_outcomes", THRESHOLD_SHADOW_OUTCOMES)
    return {
        # v3.26.1 — the only counter that gates broker-paper readiness.
        "real_market_opportunities": (
            f"{counters.real_market_opportunities_count}/"
            f"{real_target}"),
        "completed_shadow_outcomes": (
            f"{counters.completed_shadow_outcomes_count}/"
            f"{outcome_target}"),
        "scaffold_no_market_data_records": (
            counters.scaffold_no_market_data_records_count),
        "halt_path_records": counters.halt_path_records_count,
        "broker_paper_canary_ready": False,
        "live_trading_supported": False,
        "audit_bypass_findings": counters.audit_bypass_findings_count,
        "exposure_cap_breaches": counters.exposure_cap_breach_count,
        "repeated_buy_violations": counters.repeated_buy_violation_count,
        # Legacy view (preserved for backward compatibility but should
        # NOT be used as the broker-paper gate input).
        "legacy_normal_non_halt_opportunities": (
            counters.normal_non_halt_opportunities_count),
    }


def policy_summary() -> dict[str, Any]:
    return {
        "version": "v3.26.0",
        "metrics": list(ALL_METRICS),
        "thresholds": {
            "normal_opportunities": THRESHOLD_NORMAL_OPPORTUNITIES,
            "completed_shadow_outcomes": THRESHOLD_SHADOW_OUTCOMES,
        },
        "invariants": {
            "NEVER_SUBMITS_ORDERS": NEVER_SUBMITS_ORDERS,
            "NEVER_PROMOTES_BROKER_PAPER": NEVER_PROMOTES_BROKER_PAPER,
            "COUNTERS_ARE_MONOTONIC": COUNTERS_ARE_MONOTONIC,
        },
    }


__all__ = [
    # Metrics
    "METRIC_NORMAL_NON_HALT_OPPORTUNITIES",
    "METRIC_COMPLETED_SHADOW_OUTCOMES",
    "METRIC_HALT_PATH_OPPORTUNITIES",
    "METRIC_WOULD_BLOCK_BY_CRYPTO_EXPOSURE",
    "METRIC_WOULD_BLOCK_BY_DRAWDOWN_GUARD",
    "METRIC_WOULD_BLOCK_BY_RECENT_LOSS_COOLDOWN",
    "METRIC_EXPOSURE_CAP_BREACH",
    "METRIC_REPEATED_BUY_VIOLATION",
    "METRIC_AUDIT_BYPASS_FINDINGS",
    "METRIC_UNEXPLAINED_BROKER_STATE_CONFLICTS",
    "METRIC_REAL_MARKET_OPPORTUNITIES",
    "METRIC_SCAFFOLD_NO_MARKET_DATA_RECORDS",
    "METRIC_HALT_PATH_RECORDS",
    "ALL_METRICS",
    # Evidence quality enum
    "EVIDENCE_QUALITY_REAL_MARKET_DATA",
    "EVIDENCE_QUALITY_SCAFFOLD_NO_MARKET_DATA",
    "EVIDENCE_QUALITY_HALT_PATH_ONLY",
    "ALL_EVIDENCE_QUALITIES",
    # Thresholds
    "THRESHOLD_NORMAL_OPPORTUNITIES",
    "THRESHOLD_SHADOW_OUTCOMES",
    # Invariants
    "NEVER_SUBMITS_ORDERS",
    "NEVER_PROMOTES_BROKER_PAPER",
    "COUNTERS_ARE_MONOTONIC",
    # Data class
    "EvidenceCounters",
    # API
    "load_counters", "save_counters", "increment",
    "progress_summary", "policy_summary",
    "EVIDENCE_DIR", "COUNTERS_FILENAME",
]
