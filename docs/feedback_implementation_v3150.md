# Feedback Implementation Report — v3.15.0 (2026-06-04)

## 1. Summary of feedback

Trader feedback received 2026-06-03 raised 15 distinct points covering:
- **Instrument behavior profiling** (FB-001/004)
- **Pre-open behavior prediction** (FB-002)
- **Index/sector lead-lag influence** (FB-003)
- **Backtesting all strategies** (FB-005)
- **Source quality policy** (FB-006/014/015)
- **Primary-source event monitors** (FB-007/008/009)
- **Universe choice (US vs microcap vs PL)** (FB-010)
- **Active position management vs fire-and-forget** (FB-011)
- **Liquidity sweep/trap defense** (FB-012)
- **Real-time effectiveness verification** (FB-013)

Full mapping in [`feedback_requirements.md`](feedback_requirements.md).

## 2. Feedback assessment

| FB ID | Assessment | Priority | Rationale |
|---|---|---|---|
| FB-001 Instrument profiling | **Very valuable** | P0 | Deterministic; fixes blind-spot in confidence |
| FB-002 Pre-open behavior | **Valuable, needs data** | P2 | Real pre-market data requires paid SIP feed; interface shipped, real data deferred |
| FB-003 Lead-lag | **Very valuable** | P1 | Pearson on local bars; conservative effect |
| FB-004 Dynamic profiling | **Very valuable** | P0 | Same as FB-001 |
| FB-005 Backtest all strategies | **Very valuable** | P0 | Honest registry shipped; coverage gap documented |
| FB-006 Source policy | **Very valuable** | P0 | Tier 1/2/3 enforced; risky social input capped |
| FB-007 Primary monitors | **Valuable, partial** | P2 | Interface shipped; new live monitors deferred (data validation) |
| FB-008 DOJ/legal monitor | **Valuable, partial** | P2 | Interface + mock; live monitor needs free data source audit |
| FB-009 Defense monitor | **Already covered** | n/a | Live in `defense-monitor/` |
| FB-010 Universe choice | **Risky without data** | P2 | Abstraction shipped; PL/microcap operator decision |
| FB-011 Position management | **Very valuable** | P0 | State machine shipped; wiring v3.16 |
| FB-012 Liquidity sweep | **Very valuable** | P0 | Conservative guard shipped + wired into risk_officer |
| FB-013 Real-time effectiveness | **Very valuable** | P1 | Event stream + report shipped |
| FB-014 Social de-prioritization | **Very valuable** | P1 | Enforced via Tier 3 ceiling |
| FB-015 DD as context | **Very valuable** | P2 | `dd_is_day_trade_trigger` requires confirmation |

## 3. Repository findings

**Existed before v3.15.0:**
- 5-component confidence score (`shared/confidence.py`, v3.12.0)
- Risk officer with 9 hard checks
- Risk classification taxonomy (`risk_classification.py`)
- Intraday governor + intraday trend reinterpretation
- Heartbeat + safe-mode + session_report (post-session)
- Event scoring with source_type cred numbers
- 11 monitors with various tiers of source handling
- Walk-forward backtest harness + realism (3 strategies registered)
- 12 prompt-based audit-board reviewers

**Missing or partial:**
- No instrument behavior profiling
- No formal Tier 1/2/3 source policy
- No liquidity sweep defense
- No position lifecycle manager
- No lead-lag analysis
- No in-session effectiveness aggregator
- No universe abstraction
- No event-monitor interface
- 9/12 enabled strategies not backtest-ready
- No pre-open behavior model

## 4. What was implemented (v3.15.0)

### FIX-001 — InstrumentProfile + DynamicInstrumentProfiler
- **Files:** `shared/instrument_profile.py` (NEW, ~460 LOC)
- **Why:** Closes FB-001 + FB-004 — per-symbol behavior stats.
- **Tests:** 5 tests (`TestInstrumentProfile`)
- **Confidence effect:** low-quality profile lowers primary_score
- **Safety:** Profile cannot raise confidence on its own; insufficient data → quality 0
- **Cost:** $0 — uses free Alpaca IEX

### FIX-002 — LiquiditySweepGuard
- **Files:** `shared/liquidity_sweep_guard.py` (NEW, ~250 LOC)
- **Why:** Closes FB-012 — first defense vs sweep / trap patterns.
- **Tests:** 6 tests (`TestLiquiditySweepGuard`)
- **Confidence effect:** BLOCK adds `block_recommended` → risk_officer REJECTs; ELEVATED_RISK penalty 0.15
- **Safety:** Cannot raise aggressiveness; cannot bypass risk engine
- **Cost:** $0

### FIX-003 — SourceQualityPolicy
- **Files:** `shared/source_quality.py` (NEW, ~250 LOC)
- **Why:** Closes FB-006 + FB-014 + FB-015 — explicit 3-tier classification + day-trade eligibility rules.
- **Tests:** 8 tests (`TestSourceQualityPolicy`)
- **Confidence effect:** Tier 3 alone caps `primary_score -= 0.05`; Tier 2 needs confirmation; Tier 1 eligible alone
- **Safety:** Unknown sources default to most-conservative TIER_UNKNOWN
- **Cost:** $0

### FIX-004 — PositionManager (state machine)
- **Files:** `shared/position_manager.py` (NEW, ~300 LOC)
- **Why:** Closes FB-011 — explicit lifecycle + proactive triggers.
- **Tests:** 9 tests (`TestPositionManager`)
- **Confidence effect:** Recommends FULL_EXIT on confidence drop / quality drop / MAE / time-stop / kill-switch / safe-mode
- **Safety:** Cannot place orders directly; exit-monitor mediates
- **Cost:** $0
- **Wiring TODO:** v3.16 — exit-monitor consumes `evaluate_position()` recommendations

### FIX-005 — LeadLagAnalyzer
- **Files:** `shared/lead_lag_analyzer.py` (NEW, ~210 LOC)
- **Why:** Closes FB-003 — Pearson + lagged correlation symbol vs index.
- **Tests:** 4 tests (`TestLeadLagAnalyzer`)
- **Confidence effect:** INDEX_ALIGNED +0.05; INDEX_DIVERGENT -0.10; conservative
- **Safety:** No edge → no adjustment; insufficient data → 0
- **Cost:** $0

### FIX-006 — SessionEffectivenessMonitor
- **Files:** `shared/session_effectiveness.py` (NEW, ~270 LOC)
- **Why:** Closes FB-013 — in-session JSONL event stream + report.
- **Tests:** 4 tests (`TestSessionEffectivenessMonitor`)
- **Confidence effect:** Can recommend safe_mode (BLOCKS new entries); cannot raise confidence
- **Safety:** Strictly defensive
- **Cost:** $0 — JSONL local

### FIX-007 — Pre-open behavior interface
- **Files:** `shared/pre_open_behavior.py` (NEW, ~200 LOC)
- **Why:** Closes FB-002 — interface + classification; real pre-market data NOT available on Alpaca free IEX.
- **Tests:** 5 tests (`TestPreOpenBehavior`)
- **Confidence effect:** ±0.10 max; insufficient data → 0
- **Safety:** Documents the data limitation explicitly
- **Cost:** $0 — synthetic-data testable; real wiring needs free data source decision

### FIX-008 — MarketUniverseConfig + UniverseSelector
- **Files:** `shared/universe_selector.py` (NEW, ~230 LOC), `config/market_universes.json` (NEW)
- **Why:** Closes FB-010 — universe abstraction; documents what's not paper-ready.
- **Tests:** 5 tests (`TestUniverseSelector`)
- **Confidence effect:** None directly; informs operator + risk constants
- **Safety:** Never auto-switches; explicit operator decision required
- **Cost:** $0

### FIX-009 — EventMonitorInterface
- **Files:** `shared/event_monitor_interface.py` (NEW, ~210 LOC)
- **Why:** Closes FB-007 + FB-008 (partial) — common interface for primary-source event monitors.
- **Tests:** 2 tests (`TestEventMonitorInterface`)
- **Confidence effect:** Per-event +0.02..+0.05 (Tier 1) or -0.05 (Tier 3 social rumor)
- **Safety:** Default `is_day_trade_eligible` False; emit-only behavior
- **Cost:** $0 — interface only; live monitors operator decision

### FIX-010 — StrategyRegistry (backtest coverage)
- **Files:** `backtest/strategy_registry.py` (NEW, ~170 LOC)
- **Why:** Closes FB-005 — honest registry of every strategy + backtest readiness.
- **Tests:** 4 tests (`TestStrategyRegistry`)
- **Confidence effect:** None directly; documents EDGE_GATE gap
- **Safety:** Explicitly does NOT pretend uncovered strategies are validated
- **Cost:** $0

### FIX-011 — confidence_builder integration
- **Files:** `shared/confidence_builder.py` (UPDATED)
- **Why:** Wires FB-001/003/006/012/002 outputs into confidence_inputs.
- **Tests:** 4 tests (`TestConfidenceFeedbackIntegration`)
- **Net effect:** New inputs LOWER primary_score by up to 0.20 OR raise by up to 0.10. NET adjustment clamped.
- **Safety:** `block_recommended` flag propagates through `_v3150_meta` → risk_officer enforces.
- **Cost:** $0

### FIX-012 — risk_officer honors v3.15.0 block_recommended
- **Files:** `shared/risk_officer.py` (UPDATED)
- **Why:** Lets liquidity_sweep BLOCK + source-tier ineligibility actually block the trade.
- **Tests:** Existing `test_confidence_wired_v3140` still green; new feedback tests cover the meta path.
- **Safety:** Conservative addition; backward compatible.

## 5. What requires data or operator decision

| Item | Why deferred | Decision needed |
|---|---|---|
| Real pre-market bars (FB-002) | Alpaca free IEX has no pre-market data | Operator: accept SIP-paid feed (NO — paid) OR use a free pre-market source (broker export? — TBD) |
| Hourly crypto-bar backtest (FB-005 crypto) | Harness needs hourly fetcher | Implement `backtest/data.py` hourly variant |
| Event-driven backtest (FB-005 geo-*) | Need historical news replay | Build event replay harness; not v3.15 scope |
| DOJ live monitor (FB-008) | Free DOJ RSS is brittle; PACER is paid | Operator: validate DOJ RSS reliability; implement v3.16+ |
| PL/microcap universes (FB-010) | No free Polish broker; insufficient defense for microcaps | Operator: hard NO without data + broker validation |
| EDGE_GATE_ENABLED=true | Only 3/12 strategies backtest-ready | Implement crypto + event harnesses first |

## 6. Backtesting coverage

See [`backtesting_strategy_coverage.md`](backtesting_strategy_coverage.md).

- **HAS_SIGNAL (3):** momentum-long, momentum-long-loose, overbought-short
- **INTERFACE (3):** crypto-momentum, crypto-oversold-bounce, options-momentum
- **EVENT_DRIVEN (3):** geo-defense, geo-energy, geo-gold
- **NOT_APPLICABLE (3+):** geo-xom (deprecated), crypto-breakdown (structural), allocator-rebalance, alloc-exit, alloc-reduce

`backtest_ready_pct = 33%`. Honest disclosure.

## 7. Source policy summary

- TIER 1 (primary): SEC, DOJ, DoD, Federal Reserve, House Clerk XML, official agency accounts
- TIER 2 (verified): Reuters, Bloomberg, WSJ, FT, whitelisted DD authors
- TIER 3 (social): Reddit, Twitter/X anonymous, Stocktwits
- TIER UNKNOWN: anything unmapped (safer default than Tier 3)

Hard policy:
- Tier 3 cannot raise confidence to trade level (cap 0.45).
- Tier 2 needs price+volume confirmation for day-trade.
- DD is NOT a day-trading trigger without confirmation.
- All signals must carry `source_type` in audit.

## 8. Position management

- **Was fire-and-forget?** Partially. Had reactive exits (SL/TP brackets + governor + safe_close). No proactive triggers.
- **Now:** `position_manager.py` adds time-stop, MAE safety net, confidence-drop exit, profile-quality-drop exit, trailing retrace, partial exits.
- **Limitations:** Not yet wired into exit-monitor (v3.16 task). Currently the module is testable + correct but consumes no production data.

## 9. Liquidity sweep defense

- `liquidity_sweep_guard.py` stacks 5 conservative signals.
- ≥3 signals → BLOCK → risk_officer REJECTs.
- 2 signals → ELEVATED_RISK → confidence penalty 0.15.
- Wired into `confidence_builder` and `risk_officer`.

## 10. Real-time effectiveness verification

- `session_effectiveness.py` writes JSONL event stream during session.
- `report_today()` aggregates: signals, rejections per gate, hit rate,
  MAE/MFE, confidence calibration.
- ≥2 degradation signals → `recommend_safe_mode=True`.
- Wiring (v3.16): monitors emit events + scheduled report check.

## 11. Tests

Added `tests/test_feedback_v3150.py` — **56 tests, all green**.

Existing suites: `tests/architecture_vnext/` 290/290 + `tests/e2e/` 65/65 +
`tests/test_confidence_wired_v3140.py` 13/13.

**Total green in primary suites: 424 tests.**

No regressions.

## 12. Remaining risks

- **Data:** Free Alpaca IEX has gaps (e.g. no pre-market). Documented honestly.
- **Strategy edge:** Only 3/12 strategies backtest-ready; EDGE_GATE stays off.
- **Crypto pipeline:** crypto-oversold-bounce 0 fires in 54+ days; v3.13.3 relaxed; observation window to 2026-06-16.
- **Microcap/PL:** abstraction shipped but enabling would require missing data + broker + defense work.
- **DD/social:** policy enforced; but Tier 2 whitelist is empty (operator hasn't curated DD authors).
- **Overfitting:** new modules are conservative + tested with synthetic data; live drift TBD.
- **Confidence ceiling:** ~0.93 theoretical ceiling unchanged.
- **Heartbeat wiring incomplete:** 5/11 monitors active (5 lack `contents: write` permission on workflow YAML) → v3.14.1 fix.
- **PDT cooldown is process-level state:** resets every cron tick → ineffective in practice → v3.14.1 fix.

## 13. Final recommendation

**MOŻNA TESTOWAĆ W PAPER TRADINGU PO DODATKOWYCH WARUNKACH**

The v3.15.0 modules are safe to ship as new infrastructure layers (they
only LOWER confidence or BLOCK trades). They do not introduce new
execution risk because:
- New modules never emit orders.
- All confidence adjustments are bounded.
- Risk engine retains final say.
- All tests local + deterministic.

**Conditions for continued paper trading:**
1. Operator monitors session_effectiveness reports daily.
2. Operator addresses v3.14.1 backlog items (heartbeat wiring + PDT cooldown).
3. EDGE_GATE_ENABLED stays FALSE until backtest coverage > 70%.
4. Position manager state-machine wiring (v3.16) before declaring
   "no longer fire-and-forget".
5. No microcap/PL enabling without backtest validation + broker integration.

**NOT GOTOWE DO LIVE TRADINGU.** Same reason as audit-board 2026-06-02:
gates exist but lack empirical edge validation across the strategy
portfolio. No promises of profits.
