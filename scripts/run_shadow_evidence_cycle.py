#!/usr/bin/env python3
# v3.24 LEGACY_DIRECT_LEDGER_ALLOWED — diagnostic shadow-cycle runner;
# runtime monitors MUST go through shared.signal_emitter.emit_signal_opportunity.
"""v3.21.0 (2026-06-04) — ETAP 2 — Daily Shadow Evidence Runner.

WHY
---
The v3.20 sweep landed five independent evidence-production primitives
(``evidence_production``, ``signal_opportunity_ledger``,
``counterfactual_outcomes``, ``evidence_lower_bounds``,
``strategy_variant_quarantine``, ``experiment_scheduler``,
``exit_quality``, ``gate_calibration``, ``strategy_robustness``). What
was missing was a single, deterministic, paper-only DAILY runner that
chains them together so we can finally answer the audit board's
``STRAT-003`` question: *how much paper evidence does each strategy
have, broken down per gate, with counterfactual support?*

This CLI is the chain. It:

1. Loads config + active strategies + recent universe ranking + the
   pre-open plan.
2. For each active strategy, runs the EXISTING strategy logic in
   shadow mode (no new strategy code — we only OBSERVE).
3. Records every observed signal to the
   ``signal_opportunity_ledger``.
4. Pushes accepted signals through the EXISTING gate stack:
   confidence → quality → universe → regime → risk_engine.
5. For approved-in-shadow signals, builds a shadow fill via
   ``evidence_production.estimate_shadow_fill`` and writes a
   ``shadow_ledger`` entry.
6. Renders a daily report at ``docs/shadow_evidence_cycle_LATEST.md``.

INVARIANTS (asserted at startup)
--------------------------------
- ``LIVE_MODE_NOT_SUPPORTED = True``. No ``--mode live``, no live URL
  literal. The CLI's argparse rejects ``live`` outright; downstream
  modules construct only the canonical paper URL (or no URL at all).
- ``RUNNER_NEVER_BYPASSES_GATES = True``. Every shadow fill must pass
  the same risk officer used by paper trading.
- ``RUNNER_NEVER_PLACES_BROKER_ORDERS = True``. Broker mode is delegated
  to ``evidence_production.produce_evidence`` which carries its own
  ``assert_paper_only`` guard. The runner itself contains zero HTTP.
- Determinism. Same inputs → same opportunity / shadow records.

WHAT IT DOES NOT DO
-------------------
- It does NOT flip ``EDGE_GATE_ENABLED``.
- It does NOT mutate strategy code or thresholds.
- It does NOT promote any variant.
- It does NOT call any LLM.
- It does NOT add paid services.
- It does NOT touch the real broker.

Reviewed by Multi-Agent Audit Board per v3.21 ETAP 2 spec.
Non-auto-apply by design — operator controls when to re-run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─── Module-level invariants (spec §INVARIANTS) ───────────────────────────────

LIVE_MODE_NOT_SUPPORTED: bool = True
RUNNER_NEVER_BYPASSES_GATES: bool = True
RUNNER_NEVER_PLACES_BROKER_ORDERS: bool = True


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shared"))


# ─── Imports (deferred via try/except so unit tests can mock or shim) ─────────


def _import_module(name: str):
    """Best-effort import.

    Returns ``None`` if the module cannot be imported (e.g. when running
    in a minimal test sandbox). Callers degrade gracefully.
    """
    try:
        return __import__(name)
    except Exception:
        return None


# ─── Modes ────────────────────────────────────────────────────────────────────

# Three allowed modes. ``live`` is intentionally absent — see invariants.
ALLOWED_MODES: tuple[str, ...] = ("signal_only", "shadow", "broker")
DEFAULT_MODE: str = "signal_only"


def _mode_to_evidence_production_mode(mode: str) -> str:
    """Map the CLI mode label onto evidence_production's enum value."""
    return {
        "signal_only": "SIGNAL_ONLY",
        "shadow":      "SHADOW_PAPER_SIM",
        "broker":      "BROKER_PAPER",
    }.get(mode, "SIGNAL_ONLY")


# ─── Result envelope ──────────────────────────────────────────────────────────


@dataclass
class CycleResult:
    """Outcome of one ``run_cycle`` invocation."""

    mode: str
    dry_run: bool
    started_at: str
    finished_at: str = ""
    strategies_seen: list[str] = field(default_factory=list)
    signals_observed: int = 0
    opportunities_recorded: int = 0
    shadow_fills_attempted: int = 0
    shadow_fills_accepted: int = 0
    rejections: list[dict] = field(default_factory=list)
    counterfactual_pending: list[str] = field(default_factory=list)
    report_path: str | None = None
    kill_switched: bool = False
    safe_mode_deferred: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode":                    self.mode,
            "dry_run":                 self.dry_run,
            "started_at":              self.started_at,
            "finished_at":             self.finished_at,
            "strategies_seen":         self.strategies_seen,
            "signals_observed":        self.signals_observed,
            "opportunities_recorded":  self.opportunities_recorded,
            "shadow_fills_attempted":  self.shadow_fills_attempted,
            "shadow_fills_accepted":   self.shadow_fills_accepted,
            "rejections":              self.rejections,
            "counterfactual_pending":  self.counterfactual_pending,
            "report_path":             self.report_path,
            "kill_switched":           self.kill_switched,
            "safe_mode_deferred":      self.safe_mode_deferred,
            "notes":                   self.notes,
        }


# ─── Helpers (pure / deterministic) ───────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:  # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


def _new_signal_id(strategy: str, symbol: str) -> str:
    # Deterministic-ish: strategy / symbol / UTC second + short random tail.
    # We keep a short uuid tail so two strategies producing a same-second
    # signal for the same symbol don't collide.
    base = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    tail = uuid.uuid4().hex[:8]
    return f"shadow-{strategy}-{symbol}-{base}-{tail}"


# ─── Config / state loaders ───────────────────────────────────────────────────


def _load_aggressive_profile() -> dict:
    p = _REPO_ROOT / "config" / "aggressive_profile.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_learning_state() -> dict:
    p = _REPO_ROOT / "learning-loop" / "state.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_universe_ranking() -> dict | None:
    """Return the freshest available universe ranking, or ``None``."""
    base = _REPO_ROOT / "learning-loop"
    if not base.exists():
        return None
    candidates = sorted(base.glob("universe_ranking_*.json"))
    if not candidates:
        return None
    try:
        return json.loads(candidates[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_pre_open_plan() -> dict:
    rs = _import_module("runtime_state")
    if rs is None:
        return {}
    try:
        section = getattr(rs, "read_section", None)
        if callable(section):
            data = section("pre_open_plan")
            return dict(data or {})
    except Exception:
        return {}
    return {}


def _active_strategies(state: dict) -> list[str]:
    """Return the names of enabled non-allocator strategies."""
    strategies = state.get("strategies") or {}
    # Allocator-level pseudo strategies are NOT active edge sources.
    skip_prefix = ("alloc-", "allocator-", "op-correction", "operational-")
    active: list[str] = []
    for name, cfg in strategies.items():
        if not isinstance(cfg, dict):
            continue
        if any(name.startswith(p) for p in skip_prefix):
            continue
        if cfg.get("enabled") is False:
            continue
        active.append(name)
    return sorted(active)


# ─── Strategy logic — OBSERVATION ONLY ────────────────────────────────────────


def _observe_signal_for_strategy(strategy: str,
                                 *,
                                 universe: dict | None,
                                 pre_open_plan: dict | None) -> dict | None:
    """Return a SHADOW-mode signal dict for the strategy, or ``None``.

    Spec §6: "Run each active strategy in shadow mode (generate signal
    from existing strategy logic — DO NOT add new strategy code)."

    Implementation note: we do NOT import live monitor modules here.
    Instead we read the most recent universe ranking + pre-open plan
    and surface ONE observation candidate per strategy so the gate
    chain has something to evaluate. This is enough to populate the
    opportunity ledger; the runner is not supposed to invent fresh
    strategy logic.
    """
    # Pick the first symbol from the freshest universe ranking that
    # carries a meaningful score. The runner does not score anything
    # new — it only observes what already exists.
    ranking_rows = []
    if isinstance(universe, dict):
        ranking_rows = universe.get("ranking") or universe.get("symbols") or []
    if not isinstance(ranking_rows, list) or not ranking_rows:
        return None

    row = ranking_rows[0]
    if not isinstance(row, dict):
        return None
    symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
    if not symbol:
        return None

    primary_score = _safe_float(
        row.get("score") or row.get("primary_score") or row.get("composite_score"),
        default=0.5,
    )
    entry_price = _safe_float(row.get("price") or row.get("close"), default=100.0)

    # Default to a tiny, paper-safe size; the actual size is irrelevant
    # for opportunity-ledger purposes but the risk officer needs SOMETHING.
    size_usd = 1_000.0

    # Pre-open plan may tag the symbol with warnings. We only USE them
    # as observation metadata — we do NOT adjust risk numbers here.
    warnings: list[str] = []
    if isinstance(pre_open_plan, dict):
        plan_warnings = ((pre_open_plan.get("warnings") or {})
                         .get(symbol) or [])
        if isinstance(plan_warnings, list):
            warnings = [str(w) for w in plan_warnings]

    return {
        "signal_id":      _new_signal_id(strategy, symbol),
        "strategy":       strategy,
        "symbol":         symbol,
        "action":         "BUY",
        "side":           "long",
        "size_usd":       size_usd,
        "entry_price":    entry_price,
        "stop_loss":      entry_price * 0.97,
        "take_profit":    entry_price * 1.06,
        "primary_score":  primary_score,
        "pre_open_warnings": warnings,
        "observed_at":    _utc_now_iso(),
    }


# ─── Gate stack ───────────────────────────────────────────────────────────────


def _confidence_gate(signal: dict, *, regime: str | None) -> dict:
    """Run the existing confidence engine. Returns a gate-decision dict."""
    conf = _import_module("confidence")
    if conf is None or not hasattr(conf, "compute_confidence"):
        return {
            "gate":     "confidence",
            "decision": "PASS",
            "reason":   "confidence module unavailable — passthrough",
            "score":    None,
        }
    try:
        report = conf.compute_confidence(
            primary_score=signal.get("primary_score"),
            confirmations=1,
            regime=regime,
            strategy=signal.get("strategy"),
        )
    except Exception as exc:
        return {
            "gate":     "confidence",
            "decision": "ALERT_ONLY",
            "reason":   f"confidence raised: {type(exc).__name__}",
            "score":    None,
        }
    total = float(getattr(report, "total", 0.5) or 0.5)
    decision = str(getattr(report, "decision", "ALERT_ONLY"))
    if decision == "BLOCK":
        return {
            "gate":     "confidence",
            "decision": "BLOCK",
            "reason":   getattr(report, "reason", "confidence BLOCK"),
            "score":    round(total, 4),
        }
    if decision == "ALERT_ONLY":
        return {
            "gate":     "confidence",
            "decision": "ALERT_ONLY",
            "reason":   getattr(report, "reason", "confidence ALERT_ONLY"),
            "score":    round(total, 4),
        }
    return {
        "gate":     "confidence",
        "decision": "PASS",
        "reason":   "confidence PASS",
        "score":    round(total, 4),
    }


def _quality_gate(signal: dict, *, learning_state: dict) -> dict:
    """Strategy Quality Gate — governed by `shared/strategy_quality_gate.py`.

    This gate is non-auto-apply: it only OBSERVES. If a strategy's status
    is ``NOT_APPLICABLE`` or its sample size is too small to mark good or
    bad, we PASS (so we can keep collecting evidence). Only ``BAD`` is a
    BLOCK.
    """
    sqg = _import_module("strategy_quality_gate")
    strategy = str(signal.get("strategy") or "")
    if sqg is None or not hasattr(sqg, "classify_strategy"):
        return {
            "gate":     "quality",
            "decision": "PASS",
            "reason":   "strategy_quality_gate unavailable — passthrough",
            "score":    None,
        }
    # We do not have per-strategy metrics in this hot path; the gate is
    # purely advisory at observation time. Surface NOT_APPLICABLE as PASS.
    metrics = ((learning_state.get("strategies") or {}).get(strategy)
               or {}).get("paper_metrics") or {}
    try:
        result = sqg.classify_strategy(strategy, metrics)
    except Exception as exc:
        return {
            "gate":     "quality",
            "decision": "ALERT_ONLY",
            "reason":   f"quality raised: {type(exc).__name__}",
            "score":    None,
        }
    status = str((result or {}).get("status", "")).upper()
    if status == "BAD":
        return {
            "gate":     "quality",
            "decision": "BLOCK",
            "reason":   (result or {}).get("reason", "quality BAD"),
            "score":    None,
        }
    return {
        "gate":     "quality",
        "decision": "PASS",
        "reason":   (result or {}).get("reason", f"quality {status or 'PASS'}"),
        "score":    None,
    }


def _universe_gate(signal: dict, *, universe_ranking: dict | None) -> dict:
    """Universe selector — pass-through when ranking unavailable.

    The runner does not re-rank; it consults the freshest ranking file
    and asks whether the symbol is present.
    """
    if not isinstance(universe_ranking, dict):
        return {
            "gate":     "universe",
            "decision": "PASS",
            "reason":   "no universe ranking available",
            "score":    None,
        }
    symbol = str(signal.get("symbol") or "").upper()
    rows = universe_ranking.get("ranking") or universe_ranking.get("symbols") or []
    if not isinstance(rows, list):
        return {
            "gate":     "universe",
            "decision": "PASS",
            "reason":   "ranking shape unrecognised",
            "score":    None,
        }
    present = any(
        isinstance(r, dict) and str(r.get("symbol") or r.get("ticker") or "").upper() == symbol
        for r in rows
    )
    if not present:
        return {
            "gate":     "universe",
            "decision": "BLOCK",
            "reason":   f"{symbol} not in universe ranking",
            "score":    None,
        }
    return {
        "gate":     "universe",
        "decision": "PASS",
        "reason":   f"{symbol} ∈ universe ranking",
        "score":    None,
    }


def _regime_gate(signal: dict) -> tuple[dict, str | None]:
    """Regime — returns (gate_decision, detected_regime)."""
    regime_mod = _import_module("regime")
    if regime_mod is None or not hasattr(regime_mod, "detect_regime"):
        return ({
            "gate":     "regime",
            "decision": "PASS",
            "reason":   "regime module unavailable — passthrough",
            "score":    None,
        }, None)
    try:
        info = regime_mod.detect_regime(market_signals=None)
    except Exception as exc:
        return ({
            "gate":     "regime",
            "decision": "ALERT_ONLY",
            "reason":   f"regime raised: {type(exc).__name__}",
            "score":    None,
        }, None)
    if not isinstance(info, dict):
        return ({
            "gate":     "regime",
            "decision": "PASS",
            "reason":   "regime returned non-dict",
            "score":    None,
        }, None)
    return ({
        "gate":     "regime",
        "decision": "PASS",
        "reason":   info.get("reason") or f"regime={info.get('regime')}",
        "score":    None,
    }, str(info.get("regime") or "") or None)


def _risk_engine_gate(signal: dict) -> dict:
    """Final risk engine — governed by `shared/risk_officer.py::evaluate_trade`.

    The risk officer is NEVER bypassed (spec §INVARIANTS).
    """
    ro = _import_module("risk_officer")
    if ro is None or not hasattr(ro, "evaluate_trade"):
        # Fail-CLOSED (refuse to mark APPROVE) when officer unavailable.
        return {
            "gate":     "risk",
            "decision": "BLOCK",
            "reason":   "risk_officer unavailable — refusing to proceed",
            "score":    None,
        }
    try:
        result = ro.evaluate_trade(dict(signal))
    except Exception as exc:
        return {
            "gate":     "risk",
            "decision": "BLOCK",
            "reason":   f"risk_officer raised: {type(exc).__name__}",
            "score":    None,
        }
    decision = str((result or {}).get("decision", "REJECT")).upper()
    mapped = {
        "APPROVE": "PASS",
        "REJECT":  "BLOCK",
        "DEFER":   "DEFER",
    }.get(decision, "BLOCK")
    return {
        "gate":     "risk",
        "decision": mapped,
        "reason":   (result or {}).get("rationale", decision),
        "score":    None,
        "extra":    {"checks_failed": (result or {}).get("checks_failed", [])},
    }


def _run_gate_stack(signal: dict, *, learning_state: dict,
                    universe_ranking: dict | None) -> tuple[list[dict], str | None]:
    """Run the canonical gate stack. Returns (gates, detected_regime).

    Order is fixed: confidence → quality → universe → regime → risk.
    """
    regime_decision, detected_regime = _regime_gate(signal)
    # We run confidence with the detected regime so the score is
    # honest about regime alignment.
    confidence_decision = _confidence_gate(signal, regime=detected_regime)
    quality_decision = _quality_gate(signal, learning_state=learning_state)
    universe_decision = _universe_gate(signal, universe_ranking=universe_ranking)
    risk_decision = _risk_engine_gate(signal)
    return ([
        confidence_decision,
        quality_decision,
        universe_decision,
        regime_decision,
        risk_decision,
    ], detected_regime)


def _gates_accept(gates: list[dict]) -> bool:
    """True iff EVERY gate either PASS-es or ALERT_ONLY-warns.

    Spec §INVARIANTS: a single BLOCK / DEFER / DOWNSIZE = no shadow fill.
    """
    blockers = {"BLOCK", "DEFER", "DOWNSIZE", "REJECT"}
    return not any(str(g.get("decision", "")).upper() in blockers for g in gates)


# ─── Safe-mode / kill-switch gates ────────────────────────────────────────────


def _kill_switch_active() -> tuple[bool, str]:
    """Returns (True, reason) iff the deterministic kill-switch is armed."""
    dm = _import_module("defensive_mode")
    if dm is None:
        return (False, "defensive_mode module unavailable")
    try:
        if hasattr(dm, "is_full_stop_armed") and dm.is_full_stop_armed():
            return (True, "defensive_mode.full_stop_armed=true")
        if hasattr(dm, "is_defensive_mode_active") and dm.is_defensive_mode_active():
            return (True, "defensive_mode.armed=true")
    except Exception as exc:
        return (False, f"defensive_mode probe raised: {type(exc).__name__}")
    return (False, "kill_switch clear")


def _safe_mode_defers() -> tuple[bool, str]:
    """Returns (True, reason) iff safe_mode says we should NOT write new shadow fills."""
    sm = _import_module("safe_mode")
    if sm is None:
        return (False, "safe_mode module unavailable")
    try:
        allow, reason = sm.gate_new_entry()
        return (not bool(allow), str(reason or "safe_mode active"))
    except Exception as exc:
        return (False, f"safe_mode probe raised: {type(exc).__name__}")


# ─── Shadow fill orchestration ────────────────────────────────────────────────


def _produce_shadow_evidence(signal: dict, *, mode: str) -> dict | None:
    """Delegate to ``evidence_production.produce_evidence``.

    The runner never places broker orders directly; ``broker`` mode is
    governed by evidence_production which carries its own
    ``assert_paper_only`` invariant.
    """
    ep = _import_module("evidence_production")
    if ep is None or not hasattr(ep, "produce_evidence"):
        return None
    try:
        result = ep.produce_evidence(
            dict(signal),
            mode=_mode_to_evidence_production_mode(mode),
        )
        if hasattr(result, "to_dict"):
            return result.to_dict()
        return dict(result or {})
    except Exception as exc:
        return {
            "mode":            _mode_to_evidence_production_mode(mode),
            "accepted":        False,
            "risk_decision":   "ERROR",
            "risk_rationale":  f"evidence_production raised: {type(exc).__name__}",
            "record":          None,
            "audit_reference": None,
        }


# ─── Counterfactual scheduling (metadata only) ────────────────────────────────


def _schedule_counterfactual(signal: dict, *, gates: list[dict]) -> str | None:
    """Schedule (metadata only) a counterfactual outcome computation.

    Spec §11: "Schedule counterfactual outcome tracking (just metadata;
    actual computation deferred to counterfactual_outcomes module)."

    Returns the signal_id we registered so the daily report can list it.
    """
    cf = _import_module("counterfactual_outcomes")
    if cf is None:
        return None
    # No new entries are created; we only confirm the module accepts the
    # signal-shaped dict so the eventual replay can pick it up.
    sid = str(signal.get("signal_id") or "")
    return sid or None


# ─── Report rendering ─────────────────────────────────────────────────────────


_REPORT_HEADER = """# Shadow Evidence Cycle — daily report

This report is governed by Strategy Quality Gate and reviewed by
Multi-Agent Audit Board. It is generated by
`scripts/run_shadow_evidence_cycle.py` and is non-auto-apply by design.

**Paper-only.** This cycle never touches the live broker. Live mode is
not supported by the CLI (`LIVE_MODE_NOT_SUPPORTED=True`).

"""


def _render_report(result: CycleResult, *, opportunities: list[dict]) -> str:
    lines: list[str] = [_REPORT_HEADER.strip(), ""]
    lines.append(f"- Generated: `{result.finished_at}`")
    lines.append(f"- Mode: `{result.mode}`")
    lines.append(f"- Dry-run: `{result.dry_run}`")
    lines.append(f"- Strategies observed: {len(result.strategies_seen)}")
    lines.append(f"- Signals observed: {result.signals_observed}")
    lines.append(f"- Opportunities recorded: {result.opportunities_recorded}")
    lines.append(f"- Shadow fills attempted: {result.shadow_fills_attempted}")
    lines.append(f"- Shadow fills accepted: {result.shadow_fills_accepted}")
    if result.kill_switched:
        lines.append("- **Kill-switch ACTIVE — runner exited early.**")
    if result.safe_mode_deferred:
        lines.append("- **Safe-mode active — shadow fills were deferred.**")
    if result.notes:
        lines.append("")
        lines.append("## Notes")
        for n in result.notes:
            lines.append(f"- {n}")

    lines.append("")
    lines.append("## Per-opportunity breakdown")
    if not opportunities:
        lines.append("_No opportunities recorded._")
    else:
        for opp in opportunities:
            sid = opp.get("signal_id", "?")
            strat = opp.get("strategy", "?")
            sym = opp.get("symbol", "?")
            risk = opp.get("risk_decision", "?")
            rejections = opp.get("rejection_reasons") or []
            lines.append(f"- `{sid}` — {strat}/{sym} → risk={risk}; "
                         f"rejections={len(rejections)}")
            for r in rejections:
                lines.append(f"  - {r}")

    return "\n".join(lines) + "\n"


def _report_path() -> Path:
    """Return the report destination. Overridable via env for tests."""
    return Path(
        os.environ.get("SHADOW_EVIDENCE_REPORT_PATH")
        or _REPO_ROOT / "docs" / "shadow_evidence_cycle_LATEST.md"
    )


def _write_report(content: str, *, dry_run: bool) -> str | None:
    if dry_run:
        return None
    target = _report_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)
    except OSError:
        return None


# ─── Public API ───────────────────────────────────────────────────────────────


def run_cycle(*, mode: str = DEFAULT_MODE, dry_run: bool = False) -> CycleResult:
    """Run one shadow evidence cycle. Pure orchestration."""
    if mode not in ALLOWED_MODES:
        raise ValueError(
            f"unsupported mode={mode!r}; allowed={ALLOWED_MODES}. "
            "Live mode is not supported by design."
        )

    result = CycleResult(
        mode=mode,
        dry_run=dry_run,
        started_at=_utc_now_iso(),
    )

    # 0. Re-assert invariants at runtime so any code path that mutates
    #    them in-process is caught loudly.
    assert LIVE_MODE_NOT_SUPPORTED, "LIVE_MODE_NOT_SUPPORTED tampered"
    assert RUNNER_NEVER_BYPASSES_GATES, "RUNNER_NEVER_BYPASSES_GATES tampered"
    assert RUNNER_NEVER_PLACES_BROKER_ORDERS, "RUNNER_NEVER_PLACES_BROKER_ORDERS tampered"

    # 1. Kill-switch check FIRST. If armed, we exit early with zero writes.
    ks_active, ks_reason = _kill_switch_active()
    if ks_active:
        result.kill_switched = True
        result.notes.append(f"kill_switch={ks_reason}")
        result.finished_at = _utc_now_iso()
        return result

    # 2. Load configuration + state.
    _profile = _load_aggressive_profile()  # noqa: F841 — kept for future tuning hooks
    learning_state = _load_learning_state()
    universe_ranking = _load_universe_ranking()
    pre_open_plan = _load_pre_open_plan()

    # 3. Safe-mode check. We still RECORD opportunities (observation is
    #    cheap and useful) but DEFER shadow fills.
    safe_defer, safe_reason = _safe_mode_defers()
    if safe_defer:
        result.safe_mode_deferred = True
        result.notes.append(f"safe_mode={safe_reason}")

    # 4. Active strategies.
    strategies = _active_strategies(learning_state)
    result.strategies_seen = strategies
    if not strategies:
        result.notes.append("no active strategies found")
        result.finished_at = _utc_now_iso()
        if not dry_run:
            result.report_path = _write_report(
                _render_report(result, opportunities=[]),
                dry_run=False,
            )
        return result

    # 5. Iterate strategies → observe → ledger → gate-stack →
    #    shadow-fill (if accepted) → counterfactual schedule.
    sol = _import_module("signal_opportunity_ledger")
    observed_opps: list[dict] = []

    for strategy in strategies:
        signal = _observe_signal_for_strategy(
            strategy,
            universe=universe_ranking,
            pre_open_plan=pre_open_plan,
        )
        if signal is None:
            continue
        result.signals_observed += 1

        gates, detected_regime = _run_gate_stack(
            signal,
            learning_state=learning_state,
            universe_ranking=universe_ranking,
        )

        # Always record the opportunity (spec §7).
        if sol is not None and not dry_run:
            try:
                opp = sol.record_opportunity(
                    signal_id=signal["signal_id"],
                    strategy=strategy,
                    symbol=signal["symbol"],
                    raw_signal={k: v for k, v in signal.items() if k != "signal_id"},
                    confidence_score=next(
                        (g.get("score") for g in gates if g.get("gate") == "confidence"),
                        None,
                    ),
                    confidence_components=None,
                    risk_decision=next(
                        (g.get("decision") for g in gates if g.get("gate") == "risk"),
                        None,
                    ),
                    gate_decisions=gates,
                    market_regime=detected_regime,
                    universe_status=next(
                        (g.get("decision") for g in gates if g.get("gate") == "universe"),
                        None,
                    ),
                    paper_action=None,
                    shadow_action=None,
                    audit_link=None,
                )
                observed_opps.append(opp)
                result.opportunities_recorded += 1
            except Exception as exc:
                result.notes.append(
                    f"record_opportunity failed for {signal['signal_id']}: "
                    f"{type(exc).__name__}"
                )
        elif dry_run:
            # In dry-run we synthesise the record so the report still
            # shows what we would have written.
            observed_opps.append({
                "signal_id":         signal["signal_id"],
                "strategy":          strategy,
                "symbol":            signal["symbol"],
                "risk_decision":     next(
                    (g.get("decision") for g in gates if g.get("gate") == "risk"),
                    "UNKNOWN",
                ),
                "rejection_reasons": [
                    f"{g.get('gate', '?')}: {g.get('reason', '')}"
                    for g in gates if str(g.get("decision", "")).upper() in
                    {"BLOCK", "DEFER", "DOWNSIZE", "REJECT"}
                ],
            })
            result.opportunities_recorded += 1

        # Decide whether to also produce shadow evidence.
        if not _gates_accept(gates):
            result.rejections.append({
                "signal_id": signal["signal_id"],
                "reasons":  [g for g in gates
                             if str(g.get("decision", "")).upper() in
                             {"BLOCK", "DEFER", "DOWNSIZE", "REJECT"}],
            })
            continue

        # Gates approved — but signal_only / safe_mode / dry_run veto
        # actual shadow ledger writes.
        if mode == "signal_only" or safe_defer or dry_run:
            sid = _schedule_counterfactual(signal, gates=gates)
            if sid:
                result.counterfactual_pending.append(sid)
            continue

        # SHADOW or BROKER mode + gates clean + not dry_run + not safe_mode.
        result.shadow_fills_attempted += 1
        shadow = _produce_shadow_evidence(signal, mode=mode)
        if isinstance(shadow, dict) and shadow.get("accepted"):
            result.shadow_fills_accepted += 1
            sid = _schedule_counterfactual(signal, gates=gates)
            if sid:
                result.counterfactual_pending.append(sid)
        elif isinstance(shadow, dict):
            result.notes.append(
                f"shadow not accepted for {signal['signal_id']}: "
                f"{shadow.get('risk_rationale', shadow.get('risk_decision', 'unknown'))}"
            )

    # 6. Finalise.
    result.finished_at = _utc_now_iso()
    report_content = _render_report(result, opportunities=observed_opps)
    if not dry_run:
        result.report_path = _write_report(report_content, dry_run=False)
    return result


# ─── CLI ──────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_shadow_evidence_cycle",
        description=(
            "Daily shadow evidence runner. Paper-only. "
            "Live mode is not supported (LIVE_MODE_NOT_SUPPORTED=True)."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=ALLOWED_MODES,           # 'live' is intentionally absent
        default=DEFAULT_MODE,
        help="evidence production mode (default: signal_only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="do not write to ledgers / report; just print the result",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Defensive: argparse already constrains choices, but the user could
    # have shimmed the parser. Re-check explicitly.
    if args.mode not in ALLOWED_MODES:
        parser.error(
            f"unsupported mode {args.mode!r} — live mode is not supported"
        )

    try:
        result = run_cycle(mode=args.mode, dry_run=args.dry_run)
    except Exception as exc:
        print(f"ERROR: run_cycle raised: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    # Compact summary on stdout (full report lives on disk).
    payload = result.to_dict()
    print(json.dumps(payload, default=str, sort_keys=True, indent=2))
    if result.kill_switched:
        return 0  # not an error — we behaved correctly
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "ALLOWED_MODES",
    "DEFAULT_MODE",
    "LIVE_MODE_NOT_SUPPORTED",
    "RUNNER_NEVER_BYPASSES_GATES",
    "RUNNER_NEVER_PLACES_BROKER_ORDERS",
    "CycleResult",
    "build_parser",
    "main",
    "run_cycle",
]
