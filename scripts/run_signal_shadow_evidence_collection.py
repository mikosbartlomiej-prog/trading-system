#!/usr/bin/env python3
"""v3.26.0 (2026-06-09) — signal/shadow evidence collection entry-point.

DRY-RUN ONLY. This script:

- runs the v3.26 preflight via ``shared/signal_shadow_preflight.py``,
- refuses to proceed if broker execution / broker paper / live
  trading / EDGE_GATE_ENABLED is set,
- collects/generates shadow decisions (no broker calls),
- records them under ``learning-loop/shadow_evidence/`` per the
  shadow decision schema,
- never imports or calls any order-submitting function (verified by
  test ``tests/test_signal_shadow_collection_no_broker_execution_v3260.py``),
- gracefully records ``SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA`` if
  market data is unavailable.

Usage:

    python3 scripts/run_signal_shadow_evidence_collection.py

Options:

    --max-records N    cap the number of records to emit (default: 10).
    --dry-run-only     refuse to proceed even if the preflight passes
                       (extra paranoia layer; default ON in this sprint).

HARD SAFETY RULES (cannot be opted out of)
------------------------------------------
- NEVER submits orders.
- NEVER closes or modifies positions.
- NEVER calls live broker endpoints.
- NEVER imports ``shared/alpaca_orders.py`` order-placing helpers.
- NEVER mutates ``state.json`` or ``runtime_state.json``.
- Every emitted record carries ``broker_order_submitted=false`` and
  ``broker_execution_enabled=false``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# Forbidden-imports guard: this script must NEVER load order submission
# modules. We add the shared/ path but explicitly avoid alpaca_orders.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))

import signal_shadow_preflight as preflight  # type: ignore  # noqa: E402
import shadow_evidence_counters as counters_mod  # type: ignore  # noqa: E402


# Status / verdict tokens emitted by this collector.
SHADOW_COLLECTION_PROCEEDING                    = "SHADOW_COLLECTION_PROCEEDING"
SHADOW_COLLECTION_REFUSED_BROKER_EXECUTION_ENABLED = (
    "SHADOW_COLLECTION_REFUSED_BROKER_EXECUTION_ENABLED")
SHADOW_COLLECTION_REFUSED_PREFLIGHT_FAILED      = (
    "SHADOW_COLLECTION_REFUSED_PREFLIGHT_FAILED")
SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA        = (
    "SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA")


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "false").strip().lower()
    return v in ("true", "1", "yes", "on")


def _evidence_dir(repo_root: Path) -> Path:
    return repo_root / "learning-loop" / "shadow_evidence"


def _records_path(repo_root: Path, ts: str) -> Path:
    # Emit one JSONL file per day so accumulation is append-only.
    day = ts[:10]  # YYYY-MM-DD
    return _evidence_dir(repo_root) / f"records_{day}.jsonl"


def build_record(
    *,
    symbol: str,
    asset_class: str,
    strategy: str,
    decision_type: str,
    side: str,
    would_trade: bool,
    would_block: bool,
    block_reasons: list[str],
    sizing_preview: dict[str, Any],
    exposure_policy_result: dict[str, Any],
    drawdown_guard_state: dict[str, Any],
    timestamp_iso: str,
    audit_trace_id: str,
    evidence_quality: str = counters_mod.EVIDENCE_QUALITY_SCAFFOLD_NO_MARKET_DATA,
    exit_policy_result: dict[str, Any] | None = None,
    outcome_tracking_status: str = "PENDING",
) -> dict[str, Any]:
    """Construct a shadow decision record.

    v3.26.1: ``evidence_quality`` is REQUIRED. Default is
    ``SCAFFOLD_NO_MARKET_DATA`` so a caller that forgets to set it
    is treated as scaffold-only — it will NOT count toward
    broker-paper canary readiness.

    ``broker_order_submitted`` and ``broker_execution_enabled`` are
    hard-coded to ``false`` so the record schema is honored even if a
    caller forgets to pass them.
    """
    if evidence_quality not in counters_mod.ALL_EVIDENCE_QUALITIES:
        raise ValueError(
            f"evidence_quality must be one of "
            f"{counters_mod.ALL_EVIDENCE_QUALITIES}; got "
            f"{evidence_quality!r}",
        )
    rec: dict[str, Any] = {
        "version": "v3.26.1",
        "timestamp": timestamp_iso,
        "symbol": symbol,
        "asset_class": asset_class,
        "strategy": strategy,
        "decision_type": decision_type,
        "side": side,
        "would_trade": would_trade,
        "would_block": would_block,
        "block_reasons": list(block_reasons),
        "sizing_preview": sizing_preview,
        "exposure_policy_result": exposure_policy_result,
        "drawdown_guard_state": drawdown_guard_state,
        "broker_execution_enabled": False,
        "broker_order_submitted": False,
        "outcome_tracking_status": outcome_tracking_status,
        "audit_trace_id": audit_trace_id,
        "evidence_quality": evidence_quality,
    }
    if exit_policy_result is not None:
        rec["exit_policy_result"] = exit_policy_result
    return rec


def append_record(repo_root: Path, record: dict[str, Any]) -> Path:
    target = _records_path(repo_root, record["timestamp"])
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    return target


def _preflight_or_refuse(refuse_if_failed: bool = True) -> dict[str, Any]:
    report = preflight.run_preflight()
    out: dict[str, Any] = {
        "verdict": report.verdict,
        "confirmations": report.confirmations,
        "blockers": report.blockers,
        "notes": report.notes,
    }
    if refuse_if_failed and report.verdict != preflight.SIGNAL_SHADOW_PREFLIGHT_PASS:
        out["status"] = SHADOW_COLLECTION_REFUSED_PREFLIGHT_FAILED
    return out


def _refuse_if_broker_execution_enabled() -> str | None:
    """Hard-refuse layer independent of preflight. Returns a refusal
    status token if execution should be refused; None otherwise."""
    if _env_truthy("ALLOW_BROKER_PAPER"):
        return SHADOW_COLLECTION_REFUSED_BROKER_EXECUTION_ENABLED
    if _env_truthy("EDGE_GATE_ENABLED"):
        return SHADOW_COLLECTION_REFUSED_BROKER_EXECUTION_ENABLED
    if _env_truthy("BROKER_EXECUTION_ENABLED"):
        return SHADOW_COLLECTION_REFUSED_BROKER_EXECUTION_ENABLED
    if (_env_truthy("LIVE_TRADING")
            or _env_truthy("LIVE_ENABLED")
            or _env_truthy("GO_LIVE")
            or _env_truthy("LIVE_TRADING_ENABLED")):
        return SHADOW_COLLECTION_REFUSED_BROKER_EXECUTION_ENABLED
    return None


def collect(
    *,
    max_records: int = 10,
    repo_root: Path | None = None,
    market_data_available: bool = False,
    timestamp_iso: str | None = None,
    refuse_if_preflight_failed: bool = True,
) -> dict[str, Any]:
    """Run a single dry-run collection pass.

    Behavior:
    - First refuse-layer: any broker-execution env var truthy → REFUSED.
    - Preflight: any blocker → REFUSED.
    - No market data → SKIPPED_NO_MARKET_DATA (records counters update
      but no shadow records are emitted).
    - Otherwise: PROCEEDING (in v3.26 the actual record generation is
      delegated to a future hook; this scaffolding writes counter
      updates and an audit-trace skeleton record).

    Returns a structured summary dict.
    """
    if repo_root is None:
        repo_root = REPO_ROOT
    if timestamp_iso is None:
        timestamp_iso = "2026-06-09T01:00:00+00:00"

    summary: dict[str, Any] = {
        "version": "v3.26.0",
        "timestamp": timestamp_iso,
        "max_records": int(max_records),
        "records_written": 0,
        "records_path": None,
    }

    # Refuse layer 1.
    refuse_token = _refuse_if_broker_execution_enabled()
    if refuse_token is not None:
        summary["status"] = refuse_token
        summary["broker_execution_enabled_refusal"] = True
        return summary

    # Refuse layer 2 (preflight).
    pre = _preflight_or_refuse(refuse_if_failed=refuse_if_preflight_failed)
    summary["preflight"] = pre
    if pre.get("status") == SHADOW_COLLECTION_REFUSED_PREFLIGHT_FAILED:
        summary["status"] = SHADOW_COLLECTION_REFUSED_PREFLIGHT_FAILED
        return summary

    # Counter load.
    cnt = counters_mod.load_counters(repo_root)

    # Without market data we cannot generate meaningful shadow
    # decisions. We still update the halt-path counters (so the
    # operator sees runs are happening) and return the skip token.
    # v3.26.1: halt-path runs do NOT increment the real-market counter.
    if not market_data_available:
        counters_mod.increment(
            cnt, counters_mod.METRIC_HALT_PATH_OPPORTUNITIES, by=1,
        )
        counters_mod.increment(
            cnt, counters_mod.METRIC_HALT_PATH_RECORDS, by=1,
        )
        counters_mod.save_counters(cnt, repo_root=repo_root,
                                     generated_at_iso=timestamp_iso)
        summary["status"] = SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA
        summary["evidence_quality"] = (
            counters_mod.EVIDENCE_QUALITY_HALT_PATH_ONLY)
        return summary

    # v3.27.0 — when market data is available, fetch real snapshots,
    # run pure strategy functions via shared/shadow_opportunity_generator.py,
    # and emit REAL_MARKET_DATA records. If no real records can be
    # generated (no signals fired, no bars), the run is treated as a
    # halt-path so scaffolded SCAFFOLD records do NOT inflate counters.
    summary["status"] = SHADOW_COLLECTION_PROCEEDING
    written = 0
    real_written = 0
    scaffold_written = 0
    try:
        import market_data_provider as mdp  # type: ignore
        import shadow_opportunity_generator as sog  # type: ignore
    except ImportError:
        mdp = None
        sog = None
    # v3.27.1 — per-symbol diagnostic aggregation. Each symbol gets
    # one status_token explaining why a record was or was not emitted.
    per_symbol_diag: list[dict] = []
    # v3.23 — aggregate DIAG_* token counts from
    # ``fetch_universe_snapshots_with_diagnostics``. Falls back to {}
    # when the diagnostic API is unavailable (legacy code path).
    diagnostic_token_counts: dict[str, int] = {}
    symbols_skipped_stale: list[str] = []
    symbols_skipped_provider_error: list[str] = []
    if mdp is not None and sog is not None:
        # v3.23 — prefer the diagnostic API so per-cycle health snapshots
        # contain a populated ``diagnostic_token_counts`` dict. Fail-soft
        # to the legacy path if the diagnostic helper is not exported.
        try:
            _fetch_with_diag = getattr(
                mdp, "fetch_universe_snapshots_with_diagnostics", None)
        except Exception:
            _fetch_with_diag = None
        if _fetch_with_diag is not None:
            try:
                _diag_result = _fetch_with_diag()
                snapshots = list(_diag_result.snapshots)
                diagnostic_token_counts = dict(
                    _diag_result.diagnostic_token_counts or {})
                symbols_skipped_stale = list(
                    _diag_result.symbols_skipped_stale or [])
                symbols_skipped_provider_error = list(
                    _diag_result.symbols_skipped_provider_error or [])
            except Exception:
                # Belt-and-braces — fall through to legacy fetch.
                snapshots = mdp.fetch_universe_snapshots()
        else:
            snapshots = mdp.fetch_universe_snapshots()
        # Pre-fetch daily bars per equity symbol; preserve per-symbol
        # bar-fetch diagnostic so the collector can surface
        # MARKET_CLOSED_OR_NO_BARS vs INSUFFICIENT_BARS_FOR_SIGNAL vs
        # MARKET_DATA_PROVIDER_ERROR distinctly.
        bars_by_symbol: dict[str, list] = {}
        bars_token_by_symbol: dict[str, str] = {}
        # v3.27.2 — operator-tunable lookback. Default 40 (well above
        # the 22-bar ATR floor). Cannot be reduced below 22 — that
        # safety floor is enforced server-side by
        # ``shared/market_data_provider.py::fetch_daily_bars_diagnostic``
        # which returns INSUFFICIENT_BARS_FOR_SIGNAL when bars<22.
        try:
            lookback_days = max(
                22,
                int(os.environ.get(
                    "SHADOW_MARKET_DATA_LOOKBACK_DAYS", "40") or 40))
        except (TypeError, ValueError):
            lookback_days = 40
        for snap in snapshots:
            if snap.asset_class == "us_equity":
                bars, bars_token = mdp.fetch_daily_bars_diagnostic(
                    snap.symbol, days=lookback_days,
                )
                bars_token_by_symbol[snap.symbol] = bars_token
                if bars and len(bars) >= 22:
                    bars_by_symbol[snap.symbol] = bars
        opps = sog.generate_for_universe(
            snapshots, bars_by_symbol=bars_by_symbol,
        )
        emitted_symbols: set[str] = set()
        for opp in opps[:int(max_records)]:
            record = sog.to_shadow_record(
                opp, timestamp_iso=timestamp_iso,
            )
            path = append_record(repo_root, record)
            summary["records_path"] = str(path.relative_to(repo_root))
            real_written += 1
            written += 1
            emitted_symbols.add(opp.symbol)
        # Aggregate per-symbol diagnostic.
        for snap in snapshots:
            sym = snap.symbol
            if sym in emitted_symbols:
                token = mdp.REAL_MARKET_SIGNAL_RECORDS_EMITTED
            elif snap.asset_class == "us_equity":
                # Use the bar-fetch token if it indicates a problem,
                # else fall back to the snapshot's own token.
                bars_token = bars_token_by_symbol.get(sym)
                if bars_token and bars_token != mdp.REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL:
                    token = bars_token
                else:
                    token = (snap.status_token
                              or mdp.REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL)
            else:
                token = (snap.status_token
                          or mdp.REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL)
            per_symbol_diag.append({
                "symbol":       sym,
                "asset_class":  snap.asset_class,
                "data_quality": snap.data_quality,
                "status_token": token,
            })
            # v3.30 — emit observation record when real market data is
            # available but no opportunity fired. Observation records
            # are diagnostic only — they NEVER count toward the
            # 50-opportunity unlock gate and NEVER flip
            # first_real_market_record_seen.
            if (sym not in emitted_symbols
                    and snap.data_quality == mdp.REAL_MARKET_DATA):
                try:
                    try:
                        import observation_records as _obs  # type: ignore
                    except ImportError:
                        from shared import observation_records as _obs  # type: ignore
                    # Map status_token to observation_reason enum.
                    reason_map = {
                        mdp.REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL:
                            "REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL",
                        mdp.INSUFFICIENT_BARS_FOR_SIGNAL:
                            "INSUFFICIENT_BARS_FOR_SIGNAL",
                        mdp.MARKET_CLOSED_OR_NO_BARS:
                            "MARKET_CLOSED_OR_NO_BARS",
                        mdp.MARKET_DATA_STALE:
                            "MARKET_DATA_STALE",
                        mdp.MARKET_DATA_PROVIDER_ERROR:
                            "PROVIDER_ERROR",
                        mdp.MARKET_DATA_AUTH_FAILED:
                            "AUTH_FAILED",
                    }
                    reason = reason_map.get(
                        token, "NO_TRADE_SIGNAL_NOT_TRIGGERED")
                    _obs.emit(
                        symbol=sym,
                        asset_class=snap.asset_class,
                        reason=reason,
                        strategy_name=None,
                        diagnostic_token=token,
                        evidence_values={
                            "data_quality": snap.data_quality,
                            "status_token": token,
                        },
                    )
                    counters_mod.increment(
                        cnt,
                        counters_mod.METRIC_OBSERVATION_RECORDS, by=1)
                    if (token == mdp.REAL_MARKET_DATA_AVAILABLE_BUT_NO_SIGNAL
                            and snap.asset_class == "us_equity"):
                        counters_mod.increment(
                            cnt,
                            counters_mod.METRIC_REAL_MARKET_NO_SIGNAL_OBSERVATIONS,
                            by=1)
                except Exception:
                    pass
    summary["per_symbol_diagnostics"] = per_symbol_diag
    # v3.23 — surface the v3.22 diagnostic API aggregate counter so the
    # workflow can pipe it into workflow_health_latest.json via
    # ``evaluate_automated_shadow_progress.py --collector-summary-path``.
    summary["diagnostic_token_counts"] = diagnostic_token_counts
    summary["symbols_skipped_stale"] = symbols_skipped_stale
    summary["symbols_skipped_provider_error"] = (
        symbols_skipped_provider_error)
    # v3.27.1 — bump granular "would_block_*" counters when a real
    # signal fired but was blocked by exposure / drawdown.
    if mdp is not None and sog is not None:
        for opp in opps[:int(max_records)] if opps else []:
            if not opp.would_block:
                continue
            reasons = " ".join(opp.block_reasons or [])
            if "DRAWDOWN_GUARD" in reasons:
                counters_mod.increment(
                    cnt,
                    counters_mod.METRIC_WOULD_BLOCK_BY_DRAWDOWN_GUARD,
                    by=1,
                )
            if "SYMBOL_EXPOSURE" in reasons or "AGGREGATE_EXPOSURE" in reasons:
                counters_mod.increment(
                    cnt,
                    counters_mod.METRIC_WOULD_BLOCK_BY_CRYPTO_EXPOSURE,
                    by=1,
                )
            if "RECENT_REALIZED_LOSS" in reasons:
                counters_mod.increment(
                    cnt,
                    counters_mod.METRIC_WOULD_BLOCK_BY_RECENT_LOSS_COOLDOWN,
                    by=1,
                )
    if real_written > 0:
        summary["evidence_quality"] = (
            counters_mod.EVIDENCE_QUALITY_REAL_MARKET_DATA)
        counters_mod.increment(
            cnt, counters_mod.METRIC_REAL_MARKET_OPPORTUNITIES,
            by=real_written,
        )
        # Keep the legacy counter advancing 1:1 for back-compat readers.
        counters_mod.increment(
            cnt, counters_mod.METRIC_NORMAL_NON_HALT_OPPORTUNITIES,
            by=real_written,
        )
    else:
        # No real opportunities generated. The v3.27 contract: do NOT
        # silently fall back to SCAFFOLD when market_data_available
        # was claimed but no real signals materialised. Treat as a
        # halt-path entry instead.
        summary["evidence_quality"] = (
            counters_mod.EVIDENCE_QUALITY_HALT_PATH_ONLY)
        counters_mod.increment(
            cnt, counters_mod.METRIC_HALT_PATH_OPPORTUNITIES, by=1,
        )
        counters_mod.increment(
            cnt, counters_mod.METRIC_HALT_PATH_RECORDS, by=1,
        )
        summary["status"] = SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA
    summary["records_written"] = written
    summary["real_records_written"] = real_written
    summary["scaffold_records_written"] = scaffold_written
    counters_mod.save_counters(cnt, repo_root=repo_root,
                                 generated_at_iso=timestamp_iso)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run v3.26 signal/shadow evidence collection "
                    "(dry-run only).",
    )
    parser.add_argument("--max-records", type=int, default=10)
    parser.add_argument(
        "--allow-without-market-data", action="store_true",
        help="v3.26 legacy flag. v3.27+ semantics: claim that the "
             "calling environment HAS market data and attempt to "
             "fetch real REAL_MARKET_DATA records via "
             "shared/shadow_opportunity_generator.py. Falls through "
             "to halt-path if real data cannot be fetched.",
    )
    parser.add_argument(
        "--with-market-data", action="store_true",
        help="v3.27 alias for --allow-without-market-data with "
             "clearer semantic: request a real-market-data "
             "collection pass.",
    )
    parser.add_argument(
        "--no-refuse-on-preflight", action="store_true",
        help="Report preflight blockers but continue. Intended for "
             "smoke-tests of the scaffold only.",
    )
    args = parser.parse_args(argv)

    summary = collect(
        max_records=args.max_records,
        market_data_available=bool(args.allow_without_market_data
                                     or args.with_market_data),
        refuse_if_preflight_failed=not args.no_refuse_on_preflight,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("status") in (
        SHADOW_COLLECTION_PROCEEDING,
        SHADOW_COLLECTION_SKIPPED_NO_MARKET_DATA,
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
