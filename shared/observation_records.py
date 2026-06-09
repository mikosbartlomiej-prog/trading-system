"""v3.30 (2026-06-09) — real-market observation records (diagnostic only).

Observation records are emitted by the v3.30 shadow collector when
real market data is available BUT no deterministic opportunity fires.
They are append-only, schema-shaped, and serve only as operator + LLM
visibility into "what did the system see and choose to skip".

HARD SAFETY
-----------
- Observation records NEVER increment ``real_market_opportunities_count``.
- Observation records NEVER count toward the 50-opportunity unlock gate.
- Observation records NEVER flip ``first_real_market_record_seen``.
- Observation records NEVER count as completed outcomes.
- Observation records NEVER unlock broker paper.
- ``record_type=NO_TRADE_OBSERVATION`` and
  ``evidence_quality=REAL_MARKET_DATA_OBSERVATION`` are forced by this
  module — callers cannot set arbitrary values.
- The append helper NEVER imports the broker-orders module.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def _observations_dir() -> Path:
    override = os.environ.get("OBSERVATION_RECORDS_DIR")
    if override:
        return Path(override)
    return REPO_ROOT / "learning-loop" / "shadow_evidence" / "observations"


def _observations_path(date_iso: str | None = None) -> Path:
    d = date_iso or datetime.now(timezone.utc).date().isoformat()
    return _observations_dir() / f"{d}.jsonl"


def build_observation_record(
    *,
    symbol: str,
    asset_class: str,
    reason: str,
    strategy_name: str | None = None,
    diagnostic_token: str | None = None,
    evidence_values: dict | None = None,
    extra: dict | None = None,
) -> dict:
    """Build a schema-shaped observation record.

    The safety-critical fields are hard-coded:
    - ``record_type=NO_TRADE_OBSERVATION``
    - ``evidence_quality=REAL_MARKET_DATA_OBSERVATION``
    - ``broker_order_submitted=False``
    - ``broker_execution_enabled=False``
    - ``affects_readiness_gate=False``
    """
    try:
        from shadow_evidence_counters import (  # type: ignore
            EVIDENCE_QUALITY_REAL_MARKET_DATA_OBSERVATION,
            RECORD_TYPE_NO_TRADE_OBSERVATION,
            ALL_OBSERVATION_REASONS,
        )
    except ImportError:
        from shared.shadow_evidence_counters import (  # type: ignore
            EVIDENCE_QUALITY_REAL_MARKET_DATA_OBSERVATION,
            RECORD_TYPE_NO_TRADE_OBSERVATION,
            ALL_OBSERVATION_REASONS,
        )
    if reason not in ALL_OBSERVATION_REASONS:
        # Fail-soft: store the actual reason but tag it OTHER if not
        # in the enum.
        reason = "OTHER_DIAGNOSTIC"
    row = {
        "timestamp_iso":           datetime.now(timezone.utc).isoformat(),
        "record_type":             RECORD_TYPE_NO_TRADE_OBSERVATION,
        "evidence_quality":        (
            EVIDENCE_QUALITY_REAL_MARKET_DATA_OBSERVATION),
        "symbol":                  str(symbol),
        "asset_class":             str(asset_class),
        "observation_reason":      reason,
        "strategy_name":           strategy_name,
        "diagnostic_token":        diagnostic_token,
        "evidence_values":         dict(evidence_values or {}),
        # Hard-coded safety contract.
        "broker_order_submitted":   False,
        "broker_execution_enabled": False,
        "affects_readiness_gate":   False,
        "counts_toward_unlock_gate": False,
    }
    if extra:
        for k, v in extra.items():
            if k in row:
                continue
            row[k] = v
    return row


def append_observation_record(row: dict,
                                 *,
                                 path: Path | None = None) -> Path:
    """Append-only writer. NEVER raises. Returns the path written."""
    p = path or _observations_path()
    # Re-assert safety-critical fields BEFORE writing in case the
    # caller mutated them.
    row["record_type"]              = "NO_TRADE_OBSERVATION"
    row["evidence_quality"]         = "REAL_MARKET_DATA_OBSERVATION"
    row["broker_order_submitted"]   = False
    row["broker_execution_enabled"] = False
    row["affects_readiness_gate"]   = False
    row["counts_toward_unlock_gate"] = False
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception as e:
        print(f"  [observations] append failed: {e}")
    return p


def emit(
    *,
    symbol: str,
    asset_class: str,
    reason: str,
    strategy_name: str | None = None,
    diagnostic_token: str | None = None,
    evidence_values: dict | None = None,
    extra: dict | None = None,
    path: Path | None = None,
) -> Path:
    """Convenience: build + append."""
    row = build_observation_record(
        symbol=symbol, asset_class=asset_class, reason=reason,
        strategy_name=strategy_name,
        diagnostic_token=diagnostic_token,
        evidence_values=evidence_values, extra=extra)
    return append_observation_record(row, path=path)


__all__ = [
    "build_observation_record",
    "append_observation_record",
    "emit",
]
