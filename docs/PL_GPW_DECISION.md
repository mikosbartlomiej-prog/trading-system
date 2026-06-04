# PL GPW universe — filing decision (2026-06-04)

**Decision:** **Do nothing in v3.16.**
**Status:** Filed; abstraction shipped v3.15.0 as documentation-only scaffolding.
**Re-decision trigger:** see bottom of doc.

## Context

Trader feedback (2026-06-03) suggested Polish GPW market as potential edge
("rynek USA jest zbyt konkurencyjny ... rozważyć PL"). v3.15.0 shipped
`shared/universe_selector.py` + `config/market_universes.json` with PL_GPW
declared but disabled.

## Why disabled and staying disabled

### Structural blocker — no free Polish paper broker

The trading system requires automated paper-trading execution. As of
2026-06-04, no free Polish broker offers a paper-trading API:

- **XTB** — no paper API
- **Bossa.pl** — no paper API
- **mBank brokerage** — no paper API
- **Saxo Bank** — paid only
- **Interactive Brokers Pro** — has PL market access but charges USD 10/month
  inactivity fee unless minimum monthly trade volume met → **fails the
  hard "zero dollars per month" constraint** stated in `docs/FREE_TIER_LIMITS.md`
  and project CLAUDE.md

This is **not a code-side problem**. No software change in this repo can
make a Polish paper broker integration appear.

### Free data exists but is useless without execution

Free Polish data sources exist:
- GPW open data (https://www.gpw.pl/akcje, daily snapshots)
- Stooq CSV history for PL tickers
- TradingView free Polish quotes (delayed)

But data alone is observation-only. Building a Polish observation-only
monitor invites "just hook IBKR Pro" drift later, and adds attack surface
to a system already short on Quarter-1 readiness gaps.

### Strategies do not transfer across universes

Even if execution were available, the existing US-validated momentum and
event-driven strategies have **zero empirical evidence** of working on
WIG20, mWIG40, or sWIG80. Different market microstructure, different
sectoral composition, different correlation regime. Would need full
per-strategy backtest in PL data — substantial work for unverified
hypothesis.

## What v3.15.0 abstraction did ship

`shared/universe_selector.py` + `config/market_universes.json::PL_GPW`
exist as documentation-only scaffolding. They:

- Make the disabled-state explicit + audit-able
- Provide a starting point IF a free PL paper broker ever materializes
- Carry the per-universe risk_limit_multipliers conservatively
  (size 0.5, sl 1.2, tp 1.2)
- Document the structural blocker in machine-readable JSON

## Re-decision triggers

Reopen this decision if **any of** these become true:

1. A free Polish broker paper API materializes (XTB Algo, Bossa OpenAPI,
   etc.). Probability assessed near-zero in 12-month horizon.
2. Operator accepts non-zero monthly cost AND explicitly chooses to break
   the "zero $/month" rule for this specific use case.
3. Operator commits to observation-only PL monitor (no execution path)
   AND defines a specific WIG20-tied hypothesis that justifies the
   attack surface.

## Operator action required

None. Filing is the action. Backlog entry already in
`learning-loop/heuristic_proposals.md::v3.15.x backlog` notes
"v3.17 P2: pre-open behavior real data source (operator decision)" — that
P2 was about pre-market for US; PL is a separate strictly P3 item.

## Audit reference

Walkthrough rationale: `docs/operator_decision_walkthrough_2026-06-04.md`
section "3. Per-item walkthrough" → "PL_GPW + US Microcap universe
enablement" and section "5. Hard NO list" → "5.1 PL_GPW live execution".
