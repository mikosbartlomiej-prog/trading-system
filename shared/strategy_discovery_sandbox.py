"""v3.21.0 (2026-06-04) — ETAP 5 — Strategy Discovery Sandbox v2.

WHY
---
After v3.20 shipped Evidence Lower Bounds + Strategy Variant Quarantine +
Experiment Scheduler, the audit board flagged a remaining gap: when a
strategy is in a transitional evidence state (sparse data, many gate
rejections, missing variants), nobody proposes concrete *variants* to
investigate. Operators have to design experiments by hand.

This module closes that gap deterministically. It reads the live
strategy ranking + opportunity ledger, identifies strategies whose
evidence is sparse / improving / has a high rejection ratio, and
produces a small set of variant proposals. Each proposal is then
forwarded to ``shared/strategy_variant_quarantine.register_variant``
so it sits in the quarantine zone — NEVER in the runtime trading
path, NEVER auto-enabled.

INVARIANTS
----------
- ``DISCOVERY_NEVER_ENABLES_RUNTIME = True`` — module never flips a
  strategy ``enabled`` field, never edits ``state.json``, never sets
  EDGE_GATE_ENABLED.
- ``DISCOVERY_NEVER_PLACES_TRADES   = True`` — module has no broker
  imports, no execution paths, no order construction.
- ``DISCOVERY_NEVER_REMOVES_GATES   = True`` — generated variants may
  TIGHTEN parameters (raise threshold, narrow window) but the override
  schema cannot represent disabling risk gates. The quarantine module
  itself only accepts the closed override whitelist
  (threshold / regime_filter / confidence_cap / universe_filter /
  exit_rule / cooldown).

REVIEW GATE
-----------
Promotion of a quarantined variant into a runtime strategy is gated
on Multi-Agent Audit Board review — explicitly non-auto-apply by
design. This module does NOT promote anything; it only proposes.

FREE OPERATION
--------------
Pure stdlib. No network. No paid APIs. Deterministic id derivation
inherited from quarantine module (sha256 first 12 chars).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# ─── Module location bootstrap ────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ─── Public invariants ────────────────────────────────────────────────────────

DISCOVERY_NEVER_ENABLES_RUNTIME:   bool = True
DISCOVERY_NEVER_PLACES_TRADES:     bool = True
DISCOVERY_NEVER_REMOVES_GATES:     bool = True

INVARIANTS: tuple[tuple[str, bool], ...] = (
    ("DISCOVERY_NEVER_ENABLES_RUNTIME", DISCOVERY_NEVER_ENABLES_RUNTIME),
    ("DISCOVERY_NEVER_PLACES_TRADES",   DISCOVERY_NEVER_PLACES_TRADES),
    ("DISCOVERY_NEVER_REMOVES_GATES",   DISCOVERY_NEVER_REMOVES_GATES),
)


# ─── Status triggers (which strategies get variant proposals) ────────────────

# Local closed enum — names match the conceptual states described in the
# spec. The discovery module classifies strategies into these states using
# evidence_lower_bounds output + opportunity ledger summaries. These are
# DIFFERENT from EVIDENCE_STATUSES in evidence_lower_bounds — they live
# only in this discovery layer and never propagate to runtime.

DISCOVERY_TRIGGER_TOO_SPARSE                = "TOO_SPARSE"
DISCOVERY_TRIGGER_HIGH_REJECTION_PROMISING  = "HIGH_REJECTION_BUT_PROMISING"
DISCOVERY_TRIGGER_NEEDS_VARIANT_DISCOVERY   = "NEEDS_VARIANT_DISCOVERY"
DISCOVERY_TRIGGER_EVIDENCE_IMPROVING        = "EVIDENCE_IMPROVING"

DISCOVERY_TRIGGERS: frozenset[str] = frozenset({
    DISCOVERY_TRIGGER_TOO_SPARSE,
    DISCOVERY_TRIGGER_HIGH_REJECTION_PROMISING,
    DISCOVERY_TRIGGER_NEEDS_VARIANT_DISCOVERY,
    DISCOVERY_TRIGGER_EVIDENCE_IMPROVING,
})


# ─── Caps ─────────────────────────────────────────────────────────────────────

MAX_VARIANTS_PER_STRATEGY  = 7   # one per kind family
MAX_STRATEGIES_PER_RUN     = 8
MAX_TOTAL_VARIANTS_PER_RUN = MAX_STRATEGIES_PER_RUN * MAX_VARIANTS_PER_STRATEGY


# ─── Variant kinds (closed set) ──────────────────────────────────────────────

VARIANT_KIND_WIDER_THRESHOLD          = "wider_threshold"
VARIANT_KIND_NARROWER_THRESHOLD       = "narrower_threshold"
VARIANT_KIND_DIFFERENT_CONFIDENCE_CAP = "different_confidence_cap"
VARIANT_KIND_DIFFERENT_REGIME_FILTER  = "different_regime_filter"
VARIANT_KIND_DIFFERENT_TIME_WINDOW    = "different_time_window"
VARIANT_KIND_DIFFERENT_UNIVERSE       = "different_universe_subset"
VARIANT_KIND_LIQUIDITY_FILTER         = "additional_liquidity_filter"
VARIANT_KIND_CONFIRMATION_REQUIREMENT = "additional_confirmation_requirement"

VARIANT_KINDS: tuple[str, ...] = (
    VARIANT_KIND_WIDER_THRESHOLD,
    VARIANT_KIND_NARROWER_THRESHOLD,
    VARIANT_KIND_DIFFERENT_CONFIDENCE_CAP,
    VARIANT_KIND_DIFFERENT_REGIME_FILTER,
    VARIANT_KIND_DIFFERENT_TIME_WINDOW,
    VARIANT_KIND_DIFFERENT_UNIVERSE,
    VARIANT_KIND_LIQUIDITY_FILTER,
    VARIANT_KIND_CONFIRMATION_REQUIREMENT,
)


# ─── Sandbox proposal dataclass ──────────────────────────────────────────────


@dataclass
class VariantProposal:
    """A single proposed variant, BEFORE quarantine registration."""

    parent_strategy:     str
    kind:                str
    change_rationale:    str
    expected_effect:     str
    risk_note:           str
    params:              dict[str, Any] = field(default_factory=dict)
    test_plan:           list[str] = field(default_factory=list)
    rollback_note:       str = ""
    promotion_criteria:  list[str] = field(default_factory=list)
    rejection_criteria:  list[str] = field(default_factory=list)
    trigger:             str = ""
    evidence_source:     str = "BACKTEST"

    def to_dict(self) -> dict:
        return {
            "parent_strategy":    self.parent_strategy,
            "kind":               self.kind,
            "change_rationale":   self.change_rationale,
            "expected_effect":    self.expected_effect,
            "risk_note":          self.risk_note,
            "params":             dict(self.params),
            "test_plan":          list(self.test_plan),
            "rollback_note":      self.rollback_note,
            "promotion_criteria": list(self.promotion_criteria),
            "rejection_criteria": list(self.rejection_criteria),
            "trigger":            self.trigger,
            "evidence_source":    self.evidence_source,
        }


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        v = int(x)
        return v
    except (TypeError, ValueError):
        return default


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        if v == float("inf") or v == float("-inf"):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _per_strategy_rejection_ratio(
    opportunity_ledger: Sequence[Mapping] | None,
) -> dict[str, float]:
    """For every strategy seen in the ledger, return rejected / total ratio.

    A row is treated as "rejected" if any gate has decision != PASS.
    Missing / non-mapping rows are ignored. Empty ledger → empty dict.
    """
    if not opportunity_ledger:
        return {}
    counts: dict[str, tuple[int, int]] = {}    # strategy -> (rejected, total)
    for raw in opportunity_ledger:
        if not isinstance(raw, Mapping):
            continue
        strat = raw.get("strategy")
        if not isinstance(strat, str) or not strat:
            continue
        gates = raw.get("gate_decisions") or raw.get("gates") or []
        rejected = False
        if isinstance(gates, Sequence):
            for g in gates:
                if not isinstance(g, Mapping):
                    continue
                dec = str(g.get("decision", "")).upper()
                if dec and dec != "PASS":
                    rejected = True
                    break
        r, t = counts.get(strat, (0, 0))
        counts[strat] = (r + (1 if rejected else 0), t + 1)
    return {
        s: (rej / tot) if tot else 0.0 for s, (rej, tot) in counts.items()
    }


def _classify_trigger(
    *,
    n_trades:        int,
    evidence_status: str | None,
    rejection_ratio: float,
    has_variants:    bool,
) -> str | None:
    """Decide whether and why a strategy needs variant proposals.

    Returns one of the DISCOVERY_TRIGGERS or None if the strategy is
    healthy / robust / outright rejected. The classifier is conservative:
    REJECT statuses never trigger discovery (they have a different remedy
    via strategy_quality_gate).
    """
    status = (evidence_status or "").upper()

    # Hard skip: outright rejected. Discovery is not the remedy.
    if status == "EVIDENCE_REJECT":
        return None
    # Hard skip: already robust + has variants in the queue.
    if status == "EVIDENCE_ROBUST_CANDIDATE" and has_variants:
        return None

    # Sparse: less than the audit-board's empirical lower bound
    # for any kind of statistical claim (~20). High priority.
    if n_trades < 20:
        return DISCOVERY_TRIGGER_TOO_SPARSE

    # High rejection ratio in opportunity ledger means many would-be
    # signals never reached execution. Often the threshold or universe
    # is mis-set. We mark it "promising" because evidence didn't outright
    # reject it.
    if rejection_ratio >= 0.60 and status not in ("EVIDENCE_REJECT",):
        return DISCOVERY_TRIGGER_HIGH_REJECTION_PROMISING

    # Improving but not yet robust → operator likely wants alternative
    # parameter sets to broaden the search.
    if status == "EVIDENCE_IMPROVING":
        return DISCOVERY_TRIGGER_EVIDENCE_IMPROVING

    # Sample size is adequate but no variant has been registered yet:
    # discovery makes sense as a sanity-check on the parameter surface.
    if n_trades >= 20 and not has_variants and status != "EVIDENCE_ROBUST_CANDIDATE":
        return DISCOVERY_TRIGGER_NEEDS_VARIANT_DISCOVERY

    return None


def _build_proposals_for(
    strategy: str,
    *,
    trigger: str,
    current_params: Mapping[str, Any] | None = None,
) -> list[VariantProposal]:
    """Return a fixed-shape list of proposals for one (strategy, trigger).

    Each proposal targets a single VARIANT_KIND and uses only override
    keys that the quarantine whitelist accepts. Anything else (e.g.
    risk caps, exposure limits) is intentionally omitted — the quarantine
    module would silently drop them anyway, and we don't want to give the
    impression that discovery can weaken risk gates. INVARIANT.
    """
    cp = dict(current_params or {})

    def _one(kind: str, params: dict[str, Any], *,
             expected: str, risk: str,
             promotion: list[str], rejection: list[str],
             rationale: str | None = None,
             test_plan: list[str] | None = None) -> VariantProposal:
        rationale = rationale or (
            f"{trigger.lower().replace('_', ' ')}: try {kind.replace('_', ' ')} "
            f"on {strategy}"
        )
        return VariantProposal(
            parent_strategy=strategy,
            kind=kind,
            change_rationale=rationale,
            expected_effect=expected,
            risk_note=risk,
            params=params,
            test_plan=test_plan or [
                "Replay last 90 days of opportunity ledger with the override",
                "Compare opportunity count and rejection mix to parent",
            ],
            rollback_note="Mark variant REJECTED in quarantine; no runtime impact.",
            promotion_criteria=promotion,
            rejection_criteria=rejection,
            trigger=trigger,
            evidence_source="BACKTEST",
        )

    # Conservative starting points if current_params don't carry numbers.
    cur_th = _safe_float(cp.get("threshold"), 0.50)
    cur_cap = _safe_float(cp.get("confidence_cap"), 0.65)
    cur_cool = _safe_int(cp.get("cooldown"), 0)
    cur_window = _safe_int(cp.get("time_window"), 30)
    cur_regime = cp.get("regime_filter") if isinstance(
        cp.get("regime_filter"), (list, tuple, str)) else None

    proposals: list[VariantProposal] = []

    # 1) Wider threshold.
    proposals.append(_one(
        VARIANT_KIND_WIDER_THRESHOLD,
        {"threshold": round(max(0.0, cur_th * 0.85), 4)},
        expected="More signal candidates; may admit lower-quality trades.",
        risk="Could degrade win rate if the wider band catches noise.",
        promotion=[
            "Wider threshold delivers >= 2x signal count over 90 days",
            "Wilson lower bound on win rate stays >= 0.40 after widening",
        ],
        rejection=[
            "Win rate lower bound drops below 0.40",
            "Profit factor lower bound drops below 1.0",
        ],
    ))

    # 2) Narrower threshold.
    proposals.append(_one(
        VARIANT_KIND_NARROWER_THRESHOLD,
        {"threshold": round(min(1.0, cur_th * 1.20), 4)},
        expected="Fewer but higher-conviction signals; may starve the strategy.",
        risk="Sample size may collapse below 20 (EVIDENCE_TOO_WEAK).",
        promotion=[
            "Profit factor lower bound improves vs parent",
            "Sample size stays >= 20 over 90 days",
        ],
        rejection=[
            "Sample size collapses below 10 over 90 days",
            "Profit factor lower bound drops below parent",
        ],
    ))

    # 3) Different confidence cap.
    new_cap = round(min(0.95, max(0.50, cur_cap + 0.05)), 2)
    proposals.append(_one(
        VARIANT_KIND_DIFFERENT_CONFIDENCE_CAP,
        {"confidence_cap": new_cap},
        expected="Only highest-confidence proposals survive; volume drops.",
        risk="Strategy may silence completely in low-confidence regimes.",
        promotion=[
            "Filtered-by-cap signals show higher Wilson WR lower bound",
            "Opportunity rejection ratio drops below 0.40",
        ],
        rejection=[
            "Sample drops below 10 over 90 days",
            "Win rate lower bound unchanged or worse",
        ],
    ))

    # 4) Different regime filter.
    if cur_regime is None or (
        isinstance(cur_regime, str) and cur_regime.upper() == "ALL"
    ):
        new_regime: list[str] = ["RISK_ON", "NEUTRAL"]
    elif isinstance(cur_regime, str):
        new_regime = [cur_regime, "NEUTRAL"] \
            if cur_regime.upper() != "NEUTRAL" else ["NEUTRAL"]
    else:
        # already a list — propose dropping the most-loose entry
        new_regime = list(cur_regime)[:max(1, len(cur_regime) - 1)] \
            or ["NEUTRAL"]
    proposals.append(_one(
        VARIANT_KIND_DIFFERENT_REGIME_FILTER,
        {"regime_filter": new_regime},
        expected="Signals only fire in selected regimes; reduces overfit risk.",
        risk="Strategy silenced in excluded regimes; lower throughput.",
        promotion=[
            "Per-regime PF lower bound improves vs parent in selected regimes",
            "Rejection ratio drops",
        ],
        rejection=[
            "PF lower bound drops in selected regimes",
            "Sample size collapses below 10",
        ],
    ))

    # 5) Different time window.
    new_window = int(max(5, cur_window // 2))
    proposals.append(_one(
        VARIANT_KIND_DIFFERENT_TIME_WINDOW,
        {"cooldown": new_window},   # quarantine accepts cooldown
        expected="Shorter cooldown lets the strategy re-arm sooner.",
        risk="Higher trade frequency may amplify cost drag.",
        promotion=[
            "Trade count rises 30%+ over 90 days",
            "Profit factor lower bound stays >= parent",
        ],
        rejection=[
            "Profit factor lower bound falls below 1.0",
            "Cost-adjusted expectancy goes negative",
        ],
    ))

    # 6) Different universe subset.
    proposals.append(_one(
        VARIANT_KIND_DIFFERENT_UNIVERSE,
        {"universe_filter": "MEGACAP_SUBSET"},
        expected="Limit the strategy to liquid mega-cap names.",
        risk="Loses exposure to small-cap edge if it existed.",
        promotion=[
            "Bootstrapped expectancy lower bound improves",
            "Spread / slippage rejection ratio drops",
        ],
        rejection=[
            "Sample size collapses below 10",
            "Wilson WR lower bound unchanged or worse",
        ],
    ))

    # 7) Additional liquidity filter (TIGHTENS) — expressed as universe
    # filter because quarantine whitelist has no separate "liquidity" key.
    proposals.append(_one(
        VARIANT_KIND_LIQUIDITY_FILTER,
        {"universe_filter": "MIN_ADV_5M"},
        expected="Require >=$5M average daily volume; cuts illiquid noise.",
        risk="Strategy silenced on small-cap names that may have edge.",
        promotion=[
            "Spread/slippage rejection ratio drops",
            "Realized cost drag improves",
        ],
        rejection=[
            "Sample size collapses",
            "PF lower bound unchanged or worse",
        ],
    ))

    # 8) Additional confirmation requirement (TIGHTENS) — expressed via
    # cooldown bump so it is permitted by quarantine.
    proposals.append(_one(
        VARIANT_KIND_CONFIRMATION_REQUIREMENT,
        {"cooldown": int(max(cur_cool, cur_window) + 5)},
        expected="Force a delay before re-entry; rejects repeat noise.",
        risk="Misses fast-moving setups; opportunity count drops.",
        promotion=[
            "Wilson WR lower bound improves",
            "Opportunity rejection ratio drops",
        ],
        rejection=[
            "Sample size collapses below 10",
            "PF lower bound drops below 1.0",
        ],
    ))

    # Cap at MAX_VARIANTS_PER_STRATEGY.
    return proposals[:MAX_VARIANTS_PER_STRATEGY]


# ─── Audit emission (fail-soft, never raises) ────────────────────────────────


def emit_audit_event(event_type: str, payload: Mapping) -> None:
    """Best-effort JSONL audit. Never raises into caller.

    Uses the standard pattern: build a Decision via shared.autonomy then
    write through shared.audit. We pick PAUSE_STRATEGY for REJECTED-style
    flags and RESUME_STRATEGY otherwise — both are reversible, neither
    implies a runtime mutation. The actual variant lifecycle remains
    governed by Strategy Quality Gate and the Multi-Agent Audit Board.
    """
    try:
        try:
            from audit import write_audit_event            # type: ignore
            from autonomy import make_decision             # type: ignore
        except ImportError:
            from shared.audit import write_audit_event     # type: ignore
            from shared.autonomy import make_decision      # type: ignore
        d = make_decision(
            decision_type="RESUME_STRATEGY",
            decision="DISCOVERY_PROPOSAL_REGISTERED",
            reason=f"strategy-discovery-sandbox: {event_type}",
            actor="strategy-discovery-sandbox",
            risk_metrics={
                "proposals_n":    _safe_int(payload.get("proposals_n"), 0),
                "strategies_n":   _safe_int(payload.get("strategies_n"), 0),
                "triggers":       list(payload.get("triggers") or []),
            },
            reversible=True,
        )
        write_audit_event(d, kind="trading")
    except Exception:
        return


# ─── Public API ──────────────────────────────────────────────────────────────


def identify_candidates(
    *,
    strategy_ranking:    Sequence[Mapping] | None,
    opportunity_ledger:  Sequence[Mapping] | None = None,
    evidence_summaries:  Mapping[str, Mapping] | None = None,
    existing_variants:   Mapping[str, Sequence[Mapping]] | None = None,
) -> list[dict[str, Any]]:
    """Return a list of (strategy, trigger, summary) candidate records.

    Pure / no side effects. Caller decides whether to pass each to
    ``generate_proposals``. Empty list when nothing qualifies.
    """
    if not strategy_ranking:
        return []

    rejection_ratios = _per_strategy_rejection_ratio(opportunity_ledger)
    summaries = dict(evidence_summaries or {})
    variants_map = dict(existing_variants or {})

    out: list[dict[str, Any]] = []
    for row in strategy_ranking:
        if not isinstance(row, Mapping):
            continue
        strategy = row.get("strategy") or row.get("name")
        if not isinstance(strategy, str) or not strategy.strip():
            continue
        n_trades = _safe_int(row.get("n_trades") or row.get("sample_size"), 0)
        status = (summaries.get(strategy, {}).get("status")
                  or row.get("evidence_status"))
        rej = float(rejection_ratios.get(strategy, 0.0))
        has_variants = bool(variants_map.get(strategy))
        trigger = _classify_trigger(
            n_trades=n_trades,
            evidence_status=status,
            rejection_ratio=rej,
            has_variants=has_variants,
        )
        if trigger is None:
            continue
        out.append({
            "strategy":         strategy,
            "trigger":          trigger,
            "n_trades":         n_trades,
            "evidence_status":  status or "",
            "rejection_ratio":  rej,
            "has_variants":     has_variants,
            "current_params":   dict(row.get("current_params") or row.get("params") or {}),
        })
        if len(out) >= MAX_STRATEGIES_PER_RUN:
            break
    return out


def generate_proposals(
    candidate: Mapping[str, Any],
) -> list[VariantProposal]:
    """Return concrete variant proposals for a single candidate record.

    Deterministic. Pure. Does NOT touch the quarantine zone. Caller is
    expected to invoke ``register_proposals_with_quarantine`` to persist.
    """
    strategy = candidate.get("strategy")
    trigger = candidate.get("trigger")
    if not isinstance(strategy, str) or not strategy.strip():
        return []
    if trigger not in DISCOVERY_TRIGGERS:
        return []
    return _build_proposals_for(
        strategy.strip(),
        trigger=trigger,
        current_params=candidate.get("current_params") or {},
    )


def register_proposals_with_quarantine(
    proposals: Iterable[VariantProposal],
) -> list[dict]:
    """Persist proposals via shared.strategy_variant_quarantine.

    Each call MUST go through ``register_variant`` — that is the ONLY
    path that respects the quarantine schema, status enum, and audit
    contract. We never write into the active strategy registry. INVARIANT.

    Returns the list of records returned by ``register_variant``. On any
    per-proposal failure we record an error dict in the list so the
    caller can see what fell through, but the run continues.
    """
    try:
        from strategy_variant_quarantine import register_variant      # type: ignore
    except ImportError:
        from shared.strategy_variant_quarantine import register_variant  # type: ignore

    records: list[dict] = []
    triggers_seen: set[str] = set()
    for prop in proposals:
        if not isinstance(prop, VariantProposal):
            records.append({
                "status": "REJECTED",
                "error":  f"not a VariantProposal: {type(prop).__name__}",
            })
            continue
        try:
            rec = register_variant(
                prop.parent_strategy,
                prop.change_rationale,
                prop.params,
                evidence_source=prop.evidence_source,
                promotion_criteria=prop.promotion_criteria,
                rejection_criteria=prop.rejection_criteria,
            )
            # Decorate with sandbox-specific metadata for downstream
            # readers (the experiment scheduler picks this up).
            rec["sandbox_kind"]            = prop.kind
            rec["sandbox_trigger"]         = prop.trigger
            rec["sandbox_expected_effect"] = prop.expected_effect
            rec["sandbox_risk_note"]       = prop.risk_note
            rec["sandbox_test_plan"]       = list(prop.test_plan)
            rec["sandbox_rollback_note"]   = prop.rollback_note
            records.append(rec)
            triggers_seen.add(prop.trigger)
        except Exception as e:                                       # noqa: BLE001
            records.append({
                "status": "REJECTED",
                "error":  f"{type(e).__name__}: {e}",
                "parent_strategy": prop.parent_strategy,
                "kind":   prop.kind,
            })

    emit_audit_event(
        "PROPOSALS_REGISTERED",
        {
            "proposals_n":  len(records),
            "strategies_n": len({r.get("parent_strategy")
                                 for r in records if r.get("parent_strategy")}),
            "triggers":     sorted(triggers_seen),
        },
    )
    return records


def run_discovery(
    *,
    strategy_ranking:    Sequence[Mapping] | None,
    opportunity_ledger:  Sequence[Mapping] | None = None,
    evidence_summaries:  Mapping[str, Mapping] | None = None,
    existing_variants:   Mapping[str, Sequence[Mapping]] | None = None,
) -> dict[str, Any]:
    """High-level entry point: identify candidates, build proposals,
    register them in quarantine.

    Returns a summary dict. Does not raise on per-strategy failures.
    Pure functional shape from the caller's perspective except for the
    quarantine writes performed by ``register_proposals_with_quarantine``.
    """
    candidates = identify_candidates(
        strategy_ranking=strategy_ranking,
        opportunity_ledger=opportunity_ledger,
        evidence_summaries=evidence_summaries,
        existing_variants=existing_variants,
    )

    all_proposals: list[VariantProposal] = []
    for c in candidates:
        proposals = generate_proposals(c)
        all_proposals.extend(proposals)
        if len(all_proposals) >= MAX_TOTAL_VARIANTS_PER_RUN:
            break

    records = register_proposals_with_quarantine(
        all_proposals[:MAX_TOTAL_VARIANTS_PER_RUN]
    )
    summary = {
        "candidates":         candidates,
        "proposals_count":    len(all_proposals),
        "registered_records": records,
        "invariants":         {
            name: value for name, value in INVARIANTS
        },
    }
    return summary


__all__ = [
    # invariants
    "DISCOVERY_NEVER_ENABLES_RUNTIME",
    "DISCOVERY_NEVER_PLACES_TRADES",
    "DISCOVERY_NEVER_REMOVES_GATES",
    "INVARIANTS",
    # triggers
    "DISCOVERY_TRIGGERS",
    "DISCOVERY_TRIGGER_TOO_SPARSE",
    "DISCOVERY_TRIGGER_HIGH_REJECTION_PROMISING",
    "DISCOVERY_TRIGGER_NEEDS_VARIANT_DISCOVERY",
    "DISCOVERY_TRIGGER_EVIDENCE_IMPROVING",
    # kinds
    "VARIANT_KINDS",
    "VARIANT_KIND_WIDER_THRESHOLD",
    "VARIANT_KIND_NARROWER_THRESHOLD",
    "VARIANT_KIND_DIFFERENT_CONFIDENCE_CAP",
    "VARIANT_KIND_DIFFERENT_REGIME_FILTER",
    "VARIANT_KIND_DIFFERENT_TIME_WINDOW",
    "VARIANT_KIND_DIFFERENT_UNIVERSE",
    "VARIANT_KIND_LIQUIDITY_FILTER",
    "VARIANT_KIND_CONFIRMATION_REQUIREMENT",
    # caps
    "MAX_VARIANTS_PER_STRATEGY",
    "MAX_STRATEGIES_PER_RUN",
    "MAX_TOTAL_VARIANTS_PER_RUN",
    # dataclass
    "VariantProposal",
    # API
    "identify_candidates",
    "generate_proposals",
    "register_proposals_with_quarantine",
    "run_discovery",
    "emit_audit_event",
]
