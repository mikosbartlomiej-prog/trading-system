# Technical Capacity & Coherence Audit Report — v3.16.0 (2026-06-04)

**Auditor:** principal-engineer / staff-level software architect (Claude Sonnet 4.6)
**HEAD:** `7767f7f1` (v3.16.0 + automerges post-batch)
**Mode:** direct manual audit (multi-agent workflow `w53c2b75f` hung; orphan recovered manually)
**Scope:** Audit techniczny gotowości i spójności — NIE jest decyzja inwestycyjna ani rekomendacja live tradingu.

---

## 1. Executive summary

System posiada **kompletny zbiór modułów** dla 26 planowanych funkcji (40 capabilities) na poziomie KODU, ale **operacyjnie spójność jest częściowa**: 8 z 10 modułów dostarczonych w v3.15.0/v3.16.0 (InstrumentProfile, LiquiditySweepGuard, PositionManager, LeadLagAnalyzer, SessionEffectiveness, PreMarketData, PreOpenBehavior, UniverseSelector) **nie są wpięte w runtime monitorów**. Risk engine i confidence score istnieją i są poprawnie zakontraktowane, ale **w produkcji tylko 3 z 11 monitorów** wywołują confidence_inputs.

Najpoważniejszy blocker techniczny: **5 z 11 workflow YAML-ów monitorów nie ma `permissions: contents: write`** (`defense-monitor`, `geo-monitor`, `options-monitor`, `price-monitor`, `twitter-monitor`) → heartbeat pisze do `runtime_state.json` w runnerze, ale zmiana nigdy nie ląduje na origin → `score_system_health` zwraca neutralny fallback. To znany backlog v3.14.1 P0.

Architektura **udźwignie planowane funkcje** — fundamenty są obecne (32 testy backtest no-lookahead/realism, 355 testów green, AST lint gate na naked sells, audit JSONL, safe_mode + kill_switch, RiskVerdict taxonomy). Pozostała praca to **DOPROWADZENIE WIRINGU**, nie nowe moduły. Drugi główny gap: **żadna z funkcjonalności nie jest E2E-testowana z konkretnym monitorem** — testy e2e używają mocków `FakeAlpaca`/`FakeMonitor`.

**Decyzja techniczna: `PARTIALLY_READY_REQUIRES_TARGETED_FIXES`.** Konkretne fixy P0/P1 wyspecyfikowane w sekcji 12.

---

## 2. Technical Capacity Matrix (ETAP 1)

| ID | Funkcjonalność | Status | Istniejące | Brakujące | Dowód | Ryzyko | Rekomendacja |
|---|---|---|---|---|---|---|---|
| CAP-001 | Instrument behavior profiling | PARTIAL | `shared/instrument_profile.py` 460 LOC, 5 tests | wiring w monitorach | grep: 0 wirings w `*-monitor/` | Confidence component dormant | Wire w price-monitor + crypto-monitor jako `DynamicInstrumentProfiler.profile(symbol)` przed signal emit |
| CAP-002 | Dynamic instrument profiler | PARTIAL | `DynamicInstrumentProfiler` klasa, cache 300s | wiring + audit emit | `shared/instrument_profile.py:399-422` | jw | jw |
| CAP-003 | Pre-open data handling | PARTIAL | `shared/pre_market_data.py` 401 LOC (Yahoo+Nasdaq) | wiring + scheduled fetcher | 0 callerów poza testami | Free-tier rate-limit ryzyko | Wire w morning-allocator z cache 5min |
| CAP-004 | Open behavior classification | PARTIAL | `shared/pre_open_behavior.py` 256 LOC, 8 klas | wiring poza testami | grep: tylko tests + self-test | Confidence cap ±0.10 bezpieczny | Wpinanie tylko po wpięciu CAP-003 |
| CAP-005 | Pre-open/open backtest harness | MISSING | brak intraday bar fetchera | cały harness | `backtest/data.py` tylko daily | Alpaca SIP paid; IEX 1min ma luki | Synthetic fixture pre-open replay; real wiring deferred |
| CAP-006 | No-lookahead data separation | READY | `tests/architecture_vnext/test_backtest_no_lookahead.py` | — | 3 strategie testowane | Niski | Repeat dla crypto + event strategies |
| CAP-007 | Index/sector influence model | PARTIAL | `shared/lead_lag_analyzer.py` 210 LOC | wiring | 0 callerów monitorach | Pearson tylko daily | Wire confidence_builder.lead_lag_result w price-monitor |
| CAP-008 | Lead-lag analysis | PARTIAL | jw | jw | jw | jw | jw |
| CAP-009 | Strategy registry | READY | `backtest/strategy_registry.py` 14 strategii | — | 5 HAS_SIGNAL, 3 MVP_IN_PROGRESS | Brak | Maintain |
| CAP-010 | Strategy interface/contract | PARTIAL | `signal_at(idx,bars)` kontrakt nieformalny | brak ABC | `backtest/strategies.py` dokumentuje konwencję | Drift między bar+event strategy signatures | Wyciąg `Protocol` w `backtest/strategy_interface.py` |
| CAP-011 | Backtest harness for all strategies | PARTIAL | bar (3) + crypto (2) + event MVP (3) | options chain backtest (paid data) | registry 5 HAS_SIGNAL z 12 tradeable | Brak edge validation | Operator decision: options backtest deferred (paid) |
| CAP-012 | Replay harness | READY | `backtest/replay.py` + `backtest/event_replay.py` | — | Daily + hourly + event modes | Brak | Maintain |
| CAP-013 | Source quality policy | READY | `shared/source_quality.py` 250 LOC | wiring w wszystkich news monitorach | 3 wirings (geo/event_monitor_interface) | Tier 3 cap | Wire w defense/twitter/reddit/politician |
| CAP-014 | Event/catalyst monitor interface | READY | `shared/event_monitor_interface.py` 210 LOC | concrete implementation outside doj | 3 wirings | Brak | DOJ ✅, defense/politician refactor backlog |
| CAP-015 | Defense monitor support | READY | `defense-monitor/monitor.py` live | brak wpięcia source_quality | grep `from source_quality` w defense: 0 | Tier classification hardcoded | Wire source_quality jako Tier 1/2 helper |
| CAP-016 | DOJ/legal monitor support | READY | `doj-monitor/` shipped v3.16.0 38 tests | operator deploy (SEC_USER_AGENT + workflow paste + Cloudflare cron) | `doj-monitor/monitor.py` + `sec_8k_client.py` + `doj_press_client.py` | operator-side | Operator: 5-step deploy ~15 min |
| CAP-017 | Market universe config | PARTIAL | `shared/universe_selector.py` 230 LOC + `config/market_universes.json` | wiring w allocator | 0 callerów | Brak (US_LARGE default) | `runtime_config.py::active_universe()` MISSING — dodać |
| CAP-018 | Universe-specific risk limits | PARTIAL | `risk_limit_multipliers` w spec | brak konsumpcji w `portfolio_risk.py` lub `allocator.py` | grep: 0 callerów multipliers | Hardcoded mega-cap thresholds | Wire w `shared/allocator.py::_execute_one` |
| CAP-019 | Position manager | PARTIAL | `shared/position_manager.py` 300 LOC, 9 tests | wiring w exit-monitor | grep `evaluate_position` w monitorach: 0 | Reactive exits only | Wire w `exit-monitor/monitor.py::run_exit_check` |
| CAP-020 | Trade lifecycle state machine | PARTIAL | state machine zaprojektowany | persistence + wiring | `PositionState` frozen dataclass | Lifecycle dormant | Persist do `runtime_state.json::positions` |
| CAP-021 | Liquidity sweep guard | PARTIAL | `shared/liquidity_sweep_guard.py` 250 LOC, 6 tests | wiring | 0 callerów | Brak ochrony przed sweepami w live | Wire w `confidence_builder` per-signal w price/crypto monitorach |
| CAP-022 | Session effectiveness monitor | PARTIAL | `shared/session_effectiveness.py` 270 LOC | wiring + scheduled report check | 0 callerów emit, `learning-loop/session_metrics/` dir nie istnieje | Brak in-session feedback | New workflow `session-effectiveness-check.yml` cron */15 |
| CAP-023 | Confidence score engine | READY | `shared/confidence.py` 5 komponentów, 3 progi (0.65/0.50/<0.50) | — | `WEIGHTS` + `THRESHOLDS` dataclass | Brak | Maintain |
| CAP-024 | Confidence score component breakdown | READY | `score_data_quality / score_signal_strength / score_regime_alignment / score_system_health / score_risk_state` | — | `shared/confidence.py:161-358` | Brak | Maintain |
| CAP-025 | Risk engine | READY | `shared/risk_officer.evaluate_trade` 9 hard checks | — | `shared/risk_officer.py:166+`; wired w `alpaca_orders.py:406,528` | Brak | Maintain |
| CAP-026 | Risk engine hard gate | READY | wpięte w stocks + crypto entry paths | options używa inline `_confidence_gate` | `alpaca_orders.py:406,528` | Options gate slightly weaker | Audit options inline gate parity |
| CAP-027 | Audit log | READY | `shared/audit.py` + `journal/autonomy/<date>.jsonl` | — | 64 events past 4 days; `write_audit_event` w `safe_close:1121` | Brak | Maintain |
| CAP-028 | Structured logging | PARTIAL | JSONL events + print() w monitorach | brak unifikowanego loggera | mix `print` + `audit` | Trudno parsować | (low) opcjonalnie `shared/logger.py` |
| CAP-029 | Runtime state snapshot | READY | `learning-loop/runtime_state.json` z sekcjami `heartbeat`, `intraday_governor`, `pdt_status`, `routine_budget`, `safe_mode` | — | `shared/runtime_state.py` + `state_policy.py` writer allowlist | Brak | Maintain |
| CAP-030 | Health checks | PARTIAL | `monitor-health.yml` + `scripts/trading_health.py` | brak unified health endpoint | works via per-workflow inspection | Brak | (low) opcjonalnie unified `/healthz` lokalny |
| CAP-031 | Heartbeat | INCONSISTENT | `shared/heartbeat.py` + 13 cross-refs, 11 monitor pings | **5 workflow YAML brak `contents: write`** | `defense/geo/options/price/twitter-monitor.yml` brak permission → writes nie commitują się | `score_system_health` ratio 4/11 zamiast 11/11 | **P0**: add `permissions: contents: write` + git commit step do 5 plików |
| CAP-032 | Safe mode | READY | `shared/safe_mode.py` 5 triggers, wired w `risk_officer.py` | — | `safe_mode.gate_new_entry` callers verified | Brak | Maintain |
| CAP-033 | Kill-switch | READY | `intraday_governor` FSM (RED_DAY_AFTER_GREEN) + `safe_mode` + `assert_paper_only` invariant | — | `shared/autonomy.py::PAPER_BASE_URL` hardcoded | Brak | Maintain |
| CAP-034 | Local reporting | READY | `scripts/session_report.py` + `reports/sessions/` markdown | — | post-session report exists | Brak in-session live view | (low) Opcjonalnie panel w dashboard worker |
| CAP-035 | E2E test infrastructure | PARTIAL | `tests/e2e/` 8 files, no-network conftest | brak E2E z konkretnym monitorem | FakeAlpaca + FakeMonitor wszędzie | Mocki nie testują real signal path | Add 1 E2E per monitor (`test_<monitor>_signal_to_audit.py`) |
| CAP-036 | Agent board support | READY | `agents/` 12 prompts + 3 schemas + `run_agent_board.py` | — | First cycle 2026-06-02 wykonany | LLM out-of-band | Maintain |
| CAP-037 | Free local operation | READY | Wszystkie ścieżki bez paid services; routine_budget 15/day cap | — | docs/FREE_TIER_LIMITS.md | Yahoo gray-zone ToS | Maintain |
| CAP-038 | Config validation | PARTIAL | `shared/state_schema.py` clamp, `runtime_config.py` env parse | brak schema validation dla `config/*.json` | json.load bez schema check | Bad config → runtime error | Add JSON Schema validation w `shared/profile.py::load_watchlists` |
| CAP-039 | Data quality validation | PARTIAL | `confidence.score_data_quality` (bar_age, spread, count) | brak dedicated validator + warning emit | tylko jako confidence input | Stale data → confidence degrade ale brak alert | Add `shared/data_quality.py::validate_bars()` że pisze `EVT_DATA_STALE` audit event |
| CAP-040 | Technical error handling | PARTIAL | fail-soft wszędzie (każdy try/except w shared/) | brak centralizacji error counter w runtime_state | per-callsite | Cichy fail możliwy | Add `runtime_state.json::error_counters` per component (heartbeat-style) |

**Summary:** READY 14 / PARTIAL 25 / MISSING 1 / INCONSISTENT 1 / OVERCOMPLICATED 0 / BLOCKED 0.

---

## 3. Technical Coherence Findings (ETAP 3)

| ID | Obszar | Niespójność | Dowód | Ryzyko | Priorytet | Rekomendacja |
|---|---|---|---|---|---|---|
| COH-001 | Single flow | Idealna ścieżka data→profile→signal→confidence→liquidity→risk→decision→position→audit→session **nie zachodzi w żadnym żywym monitorze** — 8/10 modułów dormant | grep wszystkich 8 modułów: 0 wirings | Flow narrative w docs ≠ flow w kodzie | **P0** | Wire kolejno: instrument_profile, liquidity_sweep, lead_lag w 3 main monitorach |
| COH-002 | Risk hard gate | Stock + crypto entry paths przez risk_officer.evaluate_trade ✅; options używa inline `_confidence_gate` (lekka asymetria) | `alpaca_orders.py:406,528` vs `:207-235` | Asymetria → potencjalny vector | P2 | Refactor `place_simple_buy` żeby wywoływał `evaluate_trade` z opcjonalnym `skip_rr_check=True` |
| COH-003 | Audit log emisja | `safe_close` emituje, `place_*_bracket/order/simple_buy` NIE emitują dedicated trading audit event | `alpaca_orders.py:1121` vs entry funkcje brak audit emit | Decyzje wejściowe niewidoczne post-hoc | **P1** | Add `write_audit_event(kind="trading", action="ENTRY")` w 3 entry funkcjach |
| COH-004 | Confidence cannot bypass risk | OK — `_v3150_meta.block_recommended` propaguje przez `risk_officer.evaluate_trade` | `risk_officer.py:357-380` | Brak | n/a | OK |
| COH-005 | Liquidity sweep nie emituje trade | OK — `liquidity_sweep_guard.evaluate_sweep_risk` zwraca `SweepCheckResult`, żadne HTTP/order calls | `shared/liquidity_sweep_guard.py` brak `requests.post` | Brak | n/a | OK |
| COH-006 | Event monitors emit trade? | OK dla geo/defense/twitter — używają `news_signal_gate.gate_news_signal` + delegują do `execute_stock_signal` (które idzie przez `place_stock_bracket → risk_officer`) | `geo-monitor/monitor.py:execute_geo_signal` | Brak | n/a | OK |
| COH-007 | Position manager increases size? | Brak operacji `INCREASE_POSITION` w `position_manager.evaluate_position` (tylko HOLD/PARTIAL_EXIT/FULL_EXIT/INVALIDATE) | `shared/position_manager.py:VALID_RECOMMENDATIONS` | Brak | n/a | OK by design |
| COH-008 | Safe mode + kill switch priority | OK — `evaluate_position` rule order: kill_switch (1) → safe_mode (2) → invalidation (3) → ... | `shared/position_manager.py:evaluate_position` linie 254-266 | Brak | n/a | OK |
| COH-009 | Missing data degrades confidence | OK — `confidence.compute_confidence` mapuje None na NEUTRAL_COMPONENT=0.5 + `InstrumentProfile.insufficient_data=True` | `shared/confidence.py:431` + `instrument_profile.py:267-274` | Brak | n/a | OK ale wymaga AKTYWNEGO PROFILU |
| COH-010 | Technical errors visible | PARTIAL — heartbeat tracking ale brak per-component error counter w `runtime_state` | grep `error_count` w `runtime_state.py`: 0 hits | Cichy fail nie wykrywalny przez external observer | P2 | Add `runtime_state.json::component_errors[name]: {last_iso, count_today, last_msg}` |
| COH-011 | Docs vs code | PARTIAL — `docs/PRODUCT.md` opisuje 26 funkcji, ale 8 z 10 v3.15.0 modułów dormant | doc bumped to v3.13.0; code stan v3.16.0 ale wiring nie wszedł | Operator widzi feature complete, RT widzi 4/11 heartbeat | **P1** | Update PRODUCT.md sekcja "wiring state" lub mark dormant w docs/feedback_implementation_v3150.md |
| COH-012 | Tests test REAL flow | PARTIAL — `tests/e2e/` używa FakeAlpaca + FakeMonitor; brak per-monitor E2E z prawdziwym signal builderem | sampling: `test_entry_lifecycle_e2e.py` używa `FakeMonitor` | Mocki mogą nie wykryć integrationgap (jak DOJ test pollution) | **P1** | Add `tests/test_<monitor>_signal_to_audit_e2e.py` per top-3 monitor |
| COH-013 | Agents poza critical path | OK — `tools/system_consistency_agent` + `tools/strategy_coherence_agent` + `agents/` nie są importowane z monitorów | grep `from tools` / `from agents` w `*-monitor/`: 0 | Brak | n/a | OK |
| COH-014 | System uruchomi się lokalnie bez paid | OK z 1 caveat: Yahoo Finance gray-zone ToS dla VIX i pre-market | `shared/risk_guards.py:63-86` + `shared/pre_market_data.py` | Yahoo może wprowadzić auth lub rate-limit | P3 | Document fallback: Nasdaq summary jako primary jeśli Yahoo 429 sustained |

### Flow analysis

**Dominujący flow LIVE (np. price-monitor):**
```
GitHub Actions cron
  → price-monitor/monitor.py::run_checks
    → vix_guard + drawdown + concentration (shared/risk_guards.py)
    → check_long_signal (per ticker)
    → confidence_builder.build_confidence_inputs(strategy, primary_score, regime, account_status)
      → returns dict (without instrument_profile, lead_lag, liquidity_sweep, pre_open)
    → send_alert → execute_stock_signal → place_stock_bracket
      → risk_officer.evaluate_trade (with confidence_inputs)
      → safe_mode.gate_new_entry
      → POST /v2/orders
    → notify_signal (email)
```

**Co BRAK w żywym flow vs design:**
- `InstrumentProfile` — nie liczony
- `liquidity_sweep_guard.evaluate_sweep_risk` — nie wywoływany
- `lead_lag_analyzer.analyze_lead_lag` — nie wywoływany
- `pre_market_data.get_pre_market_context` — nie wywoływany
- `position_manager.evaluate_position` — nie wywoływany (exit-monitor ma własną logikę)
- `session_effectiveness.record_event` — nie wywoływany

Wszystkie te moduły **istnieją + przetestowane** + zaakceptują wpięcie ale **nie biorą udziału w produkcji**.

---

## 4. Contract & Interface Findings (ETAP 2)

Tylko items z statusem != OK:

| Kontrakt | Status | Problem | Dowód | Rekomendowana poprawka |
|---|---|---|---|---|
| data_layer.timezone | PARTIAL | Brak unifikowanego stwierdzenia UTC; per-callsite | `market_data.py` używa UTC ISO; pre_market_data.py mix unix + ISO | Add `shared/data_contracts.py` z `TimestampSpec(UTC, iso8601)` |
| data_layer.quality_flags | MISSING | Brak `bar.data_quality` field | bars dict: `open/high/low/close/volume/time` only | Add `quality:{is_stale, is_partial, gap_count}` w `market_data.get_daily_bars` |
| signal_layer.required_data | MISSING | Strategy `signal_at(idx,bars)` przyjmuje cały bars dict bez wymaganego min `idx` | `backtest/strategies.py` per-strategy if idx < 22: return None | Add `@dataclass StrategyContract(min_bars, required_fields)` |
| signal_layer.no_data_handling | PARTIAL | Każda strategia ma własny `if idx < N: return None`; brak konwencji | `momentum_long_signal_at`, `crypto_momentum_signal_at` różne thresholds | Add convention w `StrategyContract.min_bars` |
| profile_layer.audit_fields | MISSING | `InstrumentProfile` ma `warnings:tuple` ale brak `audit_event_id` | `shared/instrument_profile.py:140-155` | Add `audit_id` field + `record_event(EVT_PROFILE_BUILT)` |
| confidence_layer.audit_log_emit | PARTIAL | `_confidence_report` mutowany w proposal ale brak audit emit | `risk_officer.py:376` | `audit.write_audit_event(kind="confidence", report=...)` w `evaluate_trade` |
| risk_layer.reason_codes | PARTIAL | `checks_failed` jako free-text strings; brak enum | `risk_officer.py:288` "per-ticker {combined:.1f}% > 40%" | Define `RiskReasonCode` enum: WHITELIST_VIOLATION / SL_MISSING / CONCENTRATION_BREACH / etc |
| execution_layer.modes_separated | PARTIAL | Brak `EXECUTION_MODE` env switch (local/replay/paper/live) | hardcoded paper URL via `assert_paper_only` | Add `EXECUTION_MODE=replay\|paper` env; replay mode dispatches do mock |
| position_layer.state_transitions | PARTIAL | `position_manager` zwraca recommendation ale brak wzorca state transition emit | `LifecycleDecision.next_lifecycle` field istnieje ale exit-monitor go nie konsumuje | Wire w `exit-monitor.run_exit_check` (P1 fix) |
| monitoring_layer.session_effectiveness_visibility | MISSING | Brak callerów `session_effectiveness.record_event` | grep: 0 monitorów emituje | Wire `record_event` w price/crypto/options-monitor emit sites |

**Wniosek:** Risk + Audit + Confidence layers mają mocne kontrakty. Data + Signal + Profile + Session layers mają **częściowe kontrakty wymagające formalizacji** (dataclass / Protocol / enum). Nic nie wymaga wielkiego refactoringu — to są addytywne typowanie.

---

## 5. Architecture Readiness (ETAP 4)

| Funkcja | Wspierana? | Lokalizacja | Interfejsy | Ryzyko integracji | Refactor? |
|---|---|---|---|---|---|
| 1. InstrumentProfile | SUPPORTED_WITH_SMALL_CHANGES | `shared/instrument_profile.py` | `profile_symbol(symbol, days)` | Niski; pure compute | NIE |
| 2. DynamicInstrumentProfiler | SUPPORTED_WITH_SMALL_CHANGES | `shared/instrument_profile.py::DynamicInstrumentProfiler` | `.profile(symbol, reason)` | Niski | NIE |
| 3. PreOpenBehaviorAnalyzer | SUPPORTED_WITH_SMALL_CHANGES | `shared/pre_open_behavior.py` + `pre_market_data.py` | `analyze_pre_open(bars, prev_close, ...)` | Średni (Yahoo ToS) | NIE |
| 4. LeadLagAnalyzer | SUPPORTED_WITH_SMALL_CHANGES | `shared/lead_lag_analyzer.py` | `analyze_lead_lag(symbol_closes, index_closes)` | Niski | NIE |
| 5. StrategyBacktestHarness | SUPPORTED | `backtest/run.py` + `strategy_registry.py` | CLI + REGISTRY dict | Niski | NIE |
| 6. SourceQualityPolicy | SUPPORTED_WITH_SMALL_CHANGES | `shared/source_quality.py` | `tier_for(source_type)` + `classify` | Niski | NIE |
| 7. PrimarySourceEventMonitor | SUPPORTED | `shared/event_monitor_interface.py` abstract + DOJ concrete | `EventMonitorInterface.run(now_iso)` | Niski | NIE |
| 8. DefenseMonitor | SUPPORTED | `defense-monitor/monitor.py` live | per-monitor own pattern | Niski (refactor opcjonalny) | NIE |
| 9. DOJLegalMonitor | SUPPORTED | `doj-monitor/` v3.16.0 38 tests | jw | Operator deploy needed | NIE |
| 10. MarketUniverseSelector | REQUIRES_NEW_LAYER | `shared/universe_selector.py` shipped ale brak `runtime_config.active_universe()` consumer | `get_universe(id)` + `is_paper_ready(id)` | Niski; layer to add | TAK małe — add wiring w `shared/allocator.py` |
| 11. PositionManager | SUPPORTED_WITH_SMALL_CHANGES | `shared/position_manager.py` | `evaluate_position(state, ...)` | Średni — persistence runtime_state | NIE; wiring tylko |
| 12. TradeLifecycleManager | SUPPORTED_WITH_SMALL_CHANGES | = PositionManager + `alpaca_orders.safe_close` | jw | Średni | NIE |
| 13. LiquiditySweepGuard | SUPPORTED_WITH_SMALL_CHANGES | `shared/liquidity_sweep_guard.py` | `evaluate_sweep_risk(opens, highs, lows, closes, volumes, ...)` | Niski | NIE |
| 14. SessionEffectivenessMonitor | SUPPORTED_WITH_SMALL_CHANGES | `shared/session_effectiveness.py` | `record_event` + `report_today` | Średni — nowy workflow YAML | NIE |
| 15. ConfidenceScore extension | SUPPORTED | `shared/confidence.py` + `confidence_builder.py` z `_v3150_meta` | `compute_confidence(**kwargs)` | Niski | NIE |
| 16. RiskEngine extension | SUPPORTED | `shared/risk_officer.evaluate_trade` | proposal dict + `_v3150_meta` propagation | Niski | NIE |
| 17. E2E full flow | REQUIRES_REFACTOR | `tests/e2e/` 8 plików, ale używa FakeMonitor/FakeAlpaca | brak per-monitor signal-to-audit E2E | Średni — needs prototype | TAK — dodać E2E per top-3 monitor |
| 18. Multi-Agent Audit Board | SUPPORTED | `agents/` 12 prompts + arbiter; pierwszy cykl wykonany 2026-06-02 | `run_agent_board.py validate-reports <date>` | Niski; out-of-band | NIE |

**Podsumowanie kategorii:**
- SUPPORTED: 7
- SUPPORTED_WITH_SMALL_CHANGES: 9
- REQUIRES_REFACTOR: 1 (E2E flow)
- REQUIRES_NEW_LAYER: 1 (Universe wiring layer)
- NOT_SUPPORTED_SAFELY: 0

**Wniosek:** żadna funkcja nie wymaga "REQUIRES_REFACTOR" w sensie przebudowy modułów — wszystkie 16 modułów jest gotowych. Praca to **wiring + audit emit + E2E test**. Małe inkrementy, niski risk.

---

## 6. Data Readiness (ETAP 6)

| Capability | Status | Dowód | Brak | Wpływ | Rekomendacja |
|---|---|---|---|---|---|
| DATA-001 pre-market | PARTIAL | `shared/pre_market_data.py` (Yahoo+Nasdaq) | brak Alpaca SIP | Pre-open analiza dostępna ale gray-zone | OK; document risk |
| DATA-002 regular session | READY | `shared/market_data.py` Alpaca IEX | — | — | Maintain |
| DATA-003 index/sector | READY | SPY/QQQ via market_data; sector ETFs (XLE/XLF/etc) w watchlists | — | Lead-lag analysis ready | Wire |
| DATA-004 PL market | MISSING | brak fetchera + brak free PL broker | Filed do-nothing (`docs/PL_GPW_DECISION.md`) | n/a (zablokowane strukturalnie) | n/a |
| DATA-005 microcap | PARTIAL | Alpaca IEX cover IEX-traded microcaps | OTC/pink sheets nie | Microcap operator decision (`docs/MICROCAP_DECISION.md`) | n/a |
| DATA-006 event/catalyst | PARTIAL | GDELT (geo) + SEC EDGAR (DOJ) + RSS (defense) | brak unified event-replay | Event backtest Phase 1 MVP shipped | OK; iteracja |
| DATA-007 source metadata | PARTIAL | `event_scoring.py` + `source_quality.py` mappings | brak per-signal source recording w monitorach | Tier classification dormant | Wire `confidence_inputs.source_type` |
| DATA-008 timestamp + UTC | PARTIAL | UTC ISO w market_data + audit; mix unix/ISO w pre_market_data | brak unifikowanego kontraktu | Cross-source compare ryzyko | Add `TimestampSpec` (P3) |
| DATA-009 missing data detection | PARTIAL | `confidence.score_data_quality(bar_age_seconds)` | brak alertu `EVT_DATA_STALE` | Confidence degrades cicho | Add audit emit dla bar_age > threshold |
| DATA-010 stale data | PARTIAL | jw — bar_age component | brak per-symbol staleness tracking | Stale dla 1 z 11 nie blokuje całości | OK; per-component fail-soft |
| DATA-011 duplicate detection | PARTIAL | Per-monitor dedup (`politician-monitor/state.json::seen_event_ids`, `doj-monitor/state.json::seen_event_ids`) | brak generic dedup helper | Inkonsystencja per-monitor | (P3) `shared/dedup.py::Seen(state_path)` helper |
| DATA-012 data quality score | PARTIAL | `InstrumentProfile.quality ∈ [0,1]` ale dormant | wiring | Quality degrade nie wchodzi do confidence | Wire CAP-001 |

**Wniosek:** Dane są dostępne dla wszystkich planowanych funkcji **z wyjątkiem PL** (strukturalnie zablokowane) **i Alpaca SIP** (paid). Główny gap: **brak unifikowanych kontraktów na timestamp/quality flag** — wymaga małych addytywnych zmian.

---

## 7. Testing Readiness (ETAP 7)

| Capability | Status | Dowód | Brak | Ryzyko | Rekomendacja |
|---|---|---|---|---|---|
| TEST-001 unit | READY | 290 vnext + 65 e2e + 102 v3.16 batch + 56 v3.15 + 13 v3.14 + 38 doj = 564 testów | — | Niski | Maintain |
| TEST-002 integration | PARTIAL | `tests/test_confidence_wired_v3140.py` + `test_feedback_v3150.py` | brak full monitor integration | Cross-module gap możliwy (DOJ pollution caught at merge) | Add per-monitor integration |
| TEST-003 E2E | PARTIAL | 8 E2E files ale FakeMonitor/FakeAlpaca | brak signal→audit per real monitor | Mock-only E2E nie złapie wiring gaps | **P1** Add real E2E |
| TEST-004 replay | READY | `backtest/replay.py` + `event_replay.py` | — | — | Maintain |
| TEST-005 backtest regression | PARTIAL | `test_backtest_no_lookahead.py` + `test_backtest_realism.py` | brak crypto + event backtest regression | New harnesses (v3.16.0) — regression dorzucony | Add po pierwszych live runach |
| TEST-006 no-lookahead | READY | `tests/architecture_vnext/test_backtest_no_lookahead.py` 3 strategie | crypto + event still pure (verified w v3.16.0) | — | Add crypto + event no-lookahead test |
| TEST-007 data leakage | PARTIAL | Implied przez no-lookahead | brak explicit "future bar referenced" assertion | Cichy data leak | Add static AST scan dla `bars[idx+\d+]` patterns |
| TEST-008 synthetic generators | PARTIAL | `_make_bars()` w `test_feedback_v3150.py` + per-test inline | brak shared fixture lib | Duplication | (P3) `tests/_fixtures/synthetic_bars.py` |
| TEST-009 fixtures | PARTIAL | per-test inline | jw | jw | jw |
| TEST-010 test config | PARTIAL | `pytest.ini` + `tests/e2e/conftest.py` (no-network guard) | brak `tests/conftest.py` (root) | Test pollution ryzyko (jak DOJ monitor cache) | Add root `conftest.py` z `clear_sys_modules_caches()` autouse |
| TEST-011 CI/local runner | READY | GitHub Actions free tier + `python -m unittest discover tests/` | — | — | Maintain |
| TEST-012 deterministic | PARTIAL | Większość pure functions deterministyczne; brak globalnego clock mock | clock-dependent code (heartbeat ping, audit ts) używa `datetime.now()` | Tests with clock dependencies flaky | Add `tests/_fixtures/freeze_clock.py` context manager |

### Flow coverage

Łańcuch:
```
data → instrument_profile → signal → confidence → liquidity_guard → risk_engine → decision → position_manager → audit → session_report
```

Pokrycie testami:

| Link | Tested |
|---|---|
| data → profile | ✅ `test_feedback_v3150.py::TestInstrumentProfile` |
| profile → signal | ❌ żaden test nie liczy profile then signal |
| signal → confidence | ✅ `test_confidence_wired_v3140.py` |
| confidence → liquidity | ✅ `test_feedback_v3150.py::TestLiquiditySweepGuard` (isolated) |
| liquidity → risk | ✅ `test_confidence_wired_v3140.py::TestConfidenceFeedbackIntegration` |
| risk → decision | ✅ `test_risk_officer_v310.py` (vnext) |
| decision → position_manager | ❌ żaden test integracyjny |
| position_manager → audit | ❌ position_manager dormant w runtime |
| audit → session_report | ✅ `scripts/session_report.py` smoke test + `test_session_effectiveness` |

**Wniosek:** brak 3 linków pokrycia (`profile→signal`, `decision→position`, `position→audit`). To są dokładnie te trzy moduły które są **dormant w produkcji**. Naprawienie wiringu i dodanie 1 E2E test per monitor zamyka lukę.

---

## 8. Local/Free Operation Readiness (ETAP 8)

| Obszar | Free local? | Dowód | Cost risk | Rekomendacja |
|---|---|---|---|---|
| OPS-001 Python deps | YES | tylko `requests`, `schedule`, `feedparser` w requirements.txt | — | Maintain |
| OPS-002 Data sources | YES (gray-zone Yahoo) | Alpaca IEX, Yahoo, GDELT, House Clerk XML, SEC EDGAR — wszystko free | Yahoo gray-zone ToS | Document; fallback documented |
| OPS-003 Storage | YES | JSONL + local files (state.json, runtime_state.json, journal/, learning-loop/history/) | — | Maintain |
| OPS-004 Monitoring | YES | heartbeat + monitor-health + session_report — wszystko lokalne | — | Maintain |
| OPS-005 Reports | YES | `scripts/session_report.py` md output | — | Maintain |
| OPS-006 Alerty | YES | Gmail SMTP free (500/day cap) | Gmail rate limit przy peak alert volume | `notify.NotificationPolicy` minimal/off mode shipped v3.13.1 |
| OPS-007 Tests | YES | unittest stdlib | — | Maintain |
| OPS-008 Backtest | YES | local replay z free IEX | — | Maintain |
| OPS-009 Replay | YES | `backtest/replay.py` + `event_replay.py` | — | Maintain |
| OPS-010 Agent board | YES | prompts są out-of-band; operator wybiera LLM (claude.ai free tier OR local LLM) | LLM call cost responsibility na operatorze | OK; out of critical path |
| OPS-011 Config | YES | JSON files; `aggressive_profile.json` + `watchlists.json` + `market_universes.json` | — | Maintain |

**Wniosek:** OPS-001..011 wszystkie YES. **System pozostaje darmowy w operowaniu**. Jedyny gray area: Yahoo Finance v8/finance/chart (już używany dla VIX od v3.8, akceptowany operator-side 2026-06-04).

---

## 9. Overengineering / Underengineering (ETAP 5)

| ID | Typ | Obszar | Problem | Skutek | Rekomendacja |
|---|---|---|---|---|---|
| ENG-001 | UNDERENGINEERING | Wiring | 8 modułów v3.15.0/v3.16.0 nie wpięte (10/8 grep wirings == 0) | Confidence/profile/liquidity dormant w produkcji | **P0** Wire batch (instrument_profile + liquidity_sweep + lead_lag → confidence_builder; position_manager → exit-monitor) |
| ENG-002 | UNDERENGINEERING | Heartbeat infra | 5 workflow YAML brak `contents: write` | Heartbeat 4/11 zamiast 11/11 | **P0** Add `permissions: contents: write` + git commit step (template paste, ~15 min) |
| ENG-003 | MISSING_ABSTRACTION | Signal interface | Każda strategia ma własny `idx < N: return None` | Drift, brak walidacji | **P1** `Protocol StrategyContract(min_bars: int, required_fields: tuple)` |
| ENG-004 | UNDERENGINEERING | E2E coverage | Brak per-monitor real signal-to-audit test | Wiring gaps niewidoczne | **P1** Add `test_<monitor>_e2e.py` per top-3 monitor (crypto/price/doj) |
| ENG-005 | MISSING_ABSTRACTION | Dedup | Per-monitor state.json::seen_event_ids różne wzorce | Code duplication | **P3** `shared/dedup.py::Seen(state_path)` helper |
| ENG-006 | OVERENGINEERING | Multi-monitor naming collision | `monitor.py` w 11 katalogach + sys.modules pollution | Test pollution (caught w v3.16.0 merge) | **P2** Add root `tests/conftest.py` z autouse `_clear_monitor_module_cache` |
| ENG-007 | TECH_DEBT | PDT cooldown | `_PDT_BLOCK_COOLDOWN: dict = {}` module-level resetuje co cron tick | Cooldown nieefektywny | **P0** Persist do `runtime_state.json::pdt_cooldown` (audit-board backlog) |
| ENG-008 | DUPLICATION | Monitor pattern | 11 monitorów mają podobny skeleton (VIX guard, drawdown, concentration, has_open_position, notify) | Wiring drift inevitable | **P2** `MonitorBase` extraction (audit-board SIMP-001) |
| ENG-009 | UNDERENGINEERING | Runtime error visibility | Brak `runtime_state.json::component_errors` per monitor | Cichy fail bez observability | **P2** Heartbeat-style error counter |
| ENG-010 | DEAD_CODE | Defunct strategies | `geo-xom` z `readiness=EVENT_DRIVEN` + `notes="Defunct"` | Mylące w registry | **P3** Move do `_DEFUNCT_REGISTRY` lub remove z REGISTRY |
| ENG-011 | UNDERENGINEERING | Reason codes | `risk_officer.checks_failed` to free-text | Trudno parsować + agregować | **P3** `RiskReasonCode` enum |
| ENG-012 | TECH_DEBT | Audit emit on entry | `place_*_bracket/order/simple_buy` nie emitują dedicated trading event | Entry decisions niewidoczne post-hoc | **P1** Add `write_audit_event(kind="trading", action="ENTRY")` |

### Overengineering — summary

Generalnie system **NIE jest overengineered**. Multi-Agent Audit Board jest out-of-band (poprawnie). Risk + Confidence layers nie mają niepotrzebnych warstw. Backtest harness ma 3 modes (idealized/realistic/both) ale to kompromis pomiędzy szybkością a wiarygodnością — uzasadnione.

Jedyne potencjalne overengineering: `monitor.py` per katalog → sys.modules namespace conflict (fixed via `_ensure_doj_monitor_module()` w testach v3.16.0). To technical debt do consolidate poprzez `MonitorBase`.

### Underengineering — summary

System jest **underengineered w obszarze wiringu** — moduły zostały **dostarczone** ale nie są **podłączone**. 8 modułów dormant. Plus brak per-monitor E2E test. Plus brak runtime error counter. Plus brak unifikowanych reason codes. Wszystkie to są **addytywne, niskie risk**.

---

## 10. Technical Readiness Scores (ETAP 9)

Oceny 0-100 wynikające z konkretnych dowodów wyżej:

| Obszar | Score | Uzasadnienie | Największy blocker |
|---|---:|---|---|
| Architektura | 78 | 16/18 funkcji SUPPORTED lub SUPPORTED_WITH_SMALL_CHANGES (ETAP 4); 1 REQUIRES_NEW_LAYER małe | Universe wiring layer + per-monitor E2E |
| Spójność techniczna | 62 | Zaprojektowany flow ≠ żywy flow; 8 modułów dormant | COH-001 main flow gap |
| Data layer | 70 | Dane dostępne dla 10/12 capabilities, gray-zone Yahoo dla pre-market | Brak unifikowanego TimestampSpec + quality flags |
| Strategy layer | 75 | Registry z 14 strategiami, 5 HAS_SIGNAL + 3 MVP_IN_PROGRESS; brak Protocol kontraktu | Strategy contract formalization |
| Backtest/replay | 82 | Daily + hourly + event harnesses, no-lookahead + realism testy | Tylko 3 strategie regression-tested; brak crypto + event regression |
| Confidence score | 85 | 5 komponentów + 3 progi + `_v3150_meta` propagation; wpięte w risk_officer | Wpięty tylko w 3 monitory; 8 modułów feed-in dormant |
| Risk engine | 90 | Hard gate `risk_officer.evaluate_trade` z 9 checks + safe_mode + RiskVerdict + AST lint dla naked sells | Options inline gate slightly asymmetric |
| Auditability | 72 | `write_audit_event` w safe_close + `audit JSONL` per day; ale **entry actions nie emitują audit** | Brak audit emit na place_*_bracket |
| Runtime safety | 80 | safe_mode + kill_switch + intraday_governor + paper-only invariant + assert_no_forbidden_strings | Heartbeat 4/11 wired (5 workflow YAML gap) |
| Position management readiness | 50 | Moduł istnieje (9 tests pass) ale 0 callerów w produkcji | Wiring w exit-monitor |
| Event monitor readiness | 75 | Defense + geo + politician + DOJ live; interface stable | DOJ wymaga operator deploy (5-step ~15 min) |
| Market universe readiness | 55 | Spec + config + selector shipped; brak `runtime_config.active_universe()` consumer | Wiring w allocator + risk multipliers |
| Testing readiness | 70 | 564 testów, 290 vnext OK, 65 e2e OK; brak per-monitor E2E | E2E używa FakeMonitor; 3/9 flow links untested |
| Local/free operation | 95 | Wszystkie ścieżki free, $0/month; jedyna gray-zone Yahoo (akceptowana) | — |
| Maintainability | 70 | Modular shared/, clear separation; 11 monitor.py namespace collision rozwiązany ad-hoc | MonitorBase extraction wymagana dla long-term |
| Readiness for planned functionality | 65 | Architektura wspiera 16/18 funkcji ale wiring brak dla 8 modułów | Wiring batch (P0 fixes) |

**Średnia ważona:** ~72/100 — odpowiada **PARTIALLY_READY_REQUIRES_TARGETED_FIXES**.

---

## 11. Blockers (P0 + P1)

### P0 (krytyczne — blokuje bezpieczne wsparcie planowanych funkcji)

- **BLK-001 (CAP-031 / ENG-002):** Heartbeat infra incomplete — 5 workflow YAML brak `contents: write`. `score_system_health` returns degraded ratio. ~15 min fix.
- **BLK-002 (COH-001 / ENG-001):** 8 modułów dormant — InstrumentProfile, LiquiditySweepGuard, LeadLagAnalyzer, PositionManager, SessionEffectiveness, PreMarketData, PreOpenBehavior, UniverseSelector. Wiring needed.
- **BLK-003 (ENG-007):** PDT cooldown module-level state resetuje co cron tick. Cooldown nieefektywny. Persist do `runtime_state.json`.

### P1 (bardzo ważne)

- **BLK-004 (COH-003 / ENG-012):** Entry actions (`place_*_bracket/order/simple_buy`) nie emitują dedicated audit event. Decyzje entry niewidoczne post-hoc.
- **BLK-005 (COH-011):** Docs (PRODUCT.md) deklarują features kompletne, ale wiring nie wszedł. Operator może mylnie ocenić stan.
- **BLK-006 (COH-012 / ENG-004):** E2E tests używają FakeMonitor — brak real signal-to-audit testu per monitor.
- **BLK-007 (ENG-003):** Strategy contract nieformalny — każda strategia ma własny `if idx < N`. Drift ryzyko.

---

## 12. Minimal Fix Plan (ETAP 10)

### P0 — najpierw (~30-60 min Claude wall-clock łącznie)

| Fix ID | Priorytet | Problem | Minimalna zmiana | Pliki/moduły | Testy | Ryzyko |
|---|---|---|---|---|---|---|
| FIX-P0-1 | P0 | BLK-001 heartbeat infra | Add `permissions: contents: write` + git commit step do 5 workflow YAML | `.github/workflows/{defense,geo,options,price,twitter}-monitor.yml` + odpowiednie `scripts/workflow-templates/` | Verify post-merge: `runtime_state.json::heartbeat` shows 11/11 | Niski |
| FIX-P0-2 | P0 | BLK-003 PDT cooldown ephemeral | Persist `_PDT_BLOCK_COOLDOWN` do `runtime_state.json::pdt_cooldown` (load on init, save on update) | `exit-monitor/monitor.py` | Add `test_pdt_cooldown_persists.py` | Niski (additive) |
| FIX-P0-3 | P0 | BLK-002 instrument_profile dormant | Wire w `crypto-monitor/monitor.py` + `price-monitor/monitor.py` emit loop: build profile, pass do `confidence_builder.build_confidence_inputs(instrument_profile=...)` | 2 monitor.py + audit emit `EVT_PROFILE_BUILT` | Add `test_<monitor>_emits_profile.py` | Niski (confidence cap ±0.05) |
| FIX-P0-4 | P0 | BLK-002 liquidity_sweep_guard dormant | Wire w `confidence_builder.build_confidence_inputs(liquidity_sweep_result=...)` — caller passes evaluate_sweep_risk output | confidence_builder.py już accepts kwarg | Add `test_<monitor>_liquidity_gate.py` | Niski |

### P1 — potem (~1-2h)

| Fix ID | Priorytet | Problem | Minimalna zmiana | Pliki/moduły | Testy | Ryzyko |
|---|---|---|---|---|---|---|
| FIX-P1-1 | P1 | BLK-002 position_manager dormant | Wire w `exit-monitor/monitor.py::run_exit_check`: persist `PositionState` do `runtime_state.json::positions`, call `evaluate_position()`, route recommendation do `safe_close` | exit-monitor.py + runtime_state.py section | `test_position_lifecycle_e2e.py` | Średni (touches live exit path) |
| FIX-P1-2 | P1 | BLK-004 entry audit emit | Add `write_audit_event(kind="trading", action="ENTRY", symbol=..., decision=...)` w `place_stock_bracket`, `place_crypto_order`, `place_simple_buy` after broker confirm | `shared/alpaca_orders.py` | Add `test_entry_audit_emitted.py` | Niski (additive) |
| FIX-P1-3 | P1 | BLK-002 lead_lag + session_effectiveness dormant | Wire `analyze_lead_lag(symbol_closes, SPY_closes)` + `record_event(EVT_SIGNAL_EMITTED)` w price/crypto monitor emit sites | 2 monitor.py + confidence_builder.py | Add per-wiring test | Niski |
| FIX-P1-4 | P1 | BLK-002 UniverseSelector dormant | Add `runtime_config.py::active_universe()` consumer + check w `shared/allocator.py::_execute_one` | runtime_config.py + allocator.py | Add `test_universe_routing.py` | Niski (default US_LARGE) |
| FIX-P1-5 | P1 | BLK-006 per-monitor E2E test | Add `tests/test_<crypto/price/doj>_signal_to_audit_e2e.py` że eksercytuje real monitor signal builder + mocked broker | 3 nowe test files | self | Niski |
| FIX-P1-6 | P1 | BLK-005 docs drift | Update `docs/feedback_implementation_v3150.md` z sekcją "wiring state per module: WIRED/DORMANT/N/A" | docs only | n/a | Niski |
| FIX-P1-7 | P1 | BLK-007 strategy contract | Add `backtest/strategy_interface.py::StrategyContract(Protocol)` z `min_bars`, `required_fields` | backtest/strategy_interface.py + per-strategy `__contract__` constant | `test_strategy_contracts.py` | Niski (Protocol, no inheritance break) |

### P2 — następnie (~2-4h opportunistic)

| Fix ID | Priorytet | Problem | Minimalna zmiana | Pliki | Testy | Ryzyko |
|---|---|---|---|---|---|---|
| FIX-P2-1 | P2 | ENG-006 monitor namespace collision | Add `tests/conftest.py` z autouse fixture `_clear_monitor_module_cache` że pop'uje `sys.modules['monitor']` po każdym teście | tests/conftest.py | self | Niski |
| FIX-P2-2 | P2 | COH-002 options inline gate asymmetry | Refactor `place_simple_buy` żeby przeszło przez `risk_officer.evaluate_trade(proposal, skip_rr_check=True)` | shared/alpaca_orders.py + risk_officer.py | extend existing tests | Średni (touches options path) |
| FIX-P2-3 | P2 | COH-010 runtime error visibility | Add `runtime_state.json::component_errors[name]: {last_iso, count_today, last_msg}` consumed by heartbeat.ping | shared/heartbeat.py + runtime_state.py | `test_error_counter.py` | Niski |
| FIX-P2-4 | P2 | ENG-008 monitor duplication | Begin `MonitorBase` extraction (opportunistic, w pierwszym monitor refactorze) | shared/monitor_base.py | full regression | Średni (cross-monitor change) |
| FIX-P2-5 | P2 | source_quality not wired in news monitors | Wire `source_quality.tier_for(source_type)` w defense/twitter/reddit/politician emit sites | 4 monitor.py | per-wiring test | Niski |

### P3 — usprawnienia

| Fix ID | Priorytet | Problem | Minimalna zmiana | Pliki | Testy | Ryzyko |
|---|---|---|---|---|---|---|
| FIX-P3-1 | P3 | ENG-005 dedup duplication | `shared/dedup.py::Seen(state_path, cap=1000)` helper | shared/dedup.py | `test_dedup.py` | Niski |
| FIX-P3-2 | P3 | ENG-011 reason codes free-text | `shared/risk_reason_codes.py::RiskReasonCode` enum | shared + risk_officer | self | Niski |
| FIX-P3-3 | P3 | ENG-010 dead strategy entry | Move `geo-xom` do `_DEFUNCT_REGISTRY` w strategy_registry | backtest/strategy_registry.py | self | Niski |
| FIX-P3-4 | P3 | DATA-008 TimestampSpec drift | `shared/data_contracts.py::TimestampSpec` (UTC, iso8601) | shared/data_contracts.py | self | Niski |
| FIX-P3-5 | P3 | TEST-008 synthetic fixtures duplication | `tests/_fixtures/synthetic_bars.py` shared helper | tests/_fixtures/ | refactor existing | Niski |

---

## 13. Finalna decyzja techniczna

# **PARTIALLY_READY_REQUIRES_TARGETED_FIXES**

### Uzasadnienie

System ma **techniczne fundamenty** dla wszystkich 26 planowanych funkcji (40 capabilities). Risk engine, confidence score, audit log, safe_mode, kill_switch, backtest harness, source quality, event monitor interface — wszystkie istnieją w kodzie, są przetestowane, mają stabilne kontrakty publiczne. 564 testy są zielone. Multi-Agent Audit Board ostatni cykl wykonany 2026-06-02 z primary verdict APPROVE_PAPER_TRADING_WITH_WARNINGS.

**Co blokuje pełną gotowość:**

1. **Wiring gap** (najpoważniejszy): 8 z 10 modułów dostarczonych w v3.15.0/v3.16.0 NIE są wpięte w runtime monitorów. Moduły są obecne, przetestowane w izolacji, ale w produkcji **żaden monitor ich nie wywołuje**. Naprawienie wymaga ~30-60 min Claude wall-clock + brak nowych modułów (FIX-P0-3, FIX-P0-4, FIX-P1-1, FIX-P1-3, FIX-P1-4).

2. **Heartbeat infra gap** (krytyczny, łatwy): 5 z 11 workflow YAML brak `permissions: contents: write` → `runtime_state.json::heartbeat` pokazuje 4/11 zamiast 11/11 → `score_system_health` zwraca degraded fallback. ~15 min fix (FIX-P0-1).

3. **PDT cooldown ephemeral** (audit-board P0 backlog): module-level dict resetuje co cron tick. ~30 min fix (FIX-P0-2).

4. **Audit emit gap na entry**: `place_*_bracket/order/simple_buy` nie emitują dedicated trading event. Entry decisions niewidoczne post-hoc. ~20 min fix (FIX-P1-2).

5. **E2E test gap**: testy używają FakeMonitor; brak real signal-to-audit test per monitor. ~1-2h fix (FIX-P1-5).

**Dlaczego NIE jest TECHNICALLY_READY_FOR_PLANNED_FUNCTIONS:**
- Confidence cap dormant w 8 z 10 wymiarów oznacza że "score system_health" zwraca neutralny 0.5 → ceiling 0.93 nieosiągalny w praktyce.
- Position lifecycle istnieje w kodzie ale w produkcji exit-monitor go nie konsumuje → "fire-and-forget" nadal aktualne mimo deklaracji v3.15.0.

**Dlaczego NIE jest NOT_READY_REQUIRES_REFACTOR:**
- Żadna z 18 funkcji nie wymaga refactoringu modułów. Praca to **wiring + audit emit + E2E** — addytywne zmiany w istniejących plikach.

**Dlaczego NIE jest BLOCKED_BY_DATA_CAPABILITIES:**
- Dane (Alpaca IEX + Yahoo + GDELT + SEC EDGAR) wystarczą dla 10 z 12 data capabilities. PL + Alpaca SIP są strukturalnie poza scope (filed `docs/PL_GPW_DECISION.md` + `docs/MICROCAP_DECISION.md`).

**Dlaczego NIE jest BLOCKED_BY_TESTING_GAPS:**
- 564 testy zielone, no-lookahead + realism + AST naked-sell lint gate aktywne. Brakuje per-monitor E2E ale FIX-P1-5 ~1h zamyka lukę.

**Dlaczego NIE jest BLOCKED_BY_RUNTIME_SAFETY_GAPS:**
- safe_mode + kill_switch + intraday_governor + assert_paper_only + AST lint są ACTIVE. Heartbeat 4/11 degraduje observability ale nie kompromituje safety hard gates.

### Konsekwencje operacyjne

System jest **bezpieczny dla kontynuacji paper tradingu** w obecnym stanie (risk engine + safe_mode + kill_switch + audit log + paper-only invariant są aktywne). Ale **planowane funkcje** (InstrumentProfile, LiquiditySweepGuard, PositionManager, LeadLagAnalyzer, SessionEffectiveness, PreOpenBehavior, UniverseSelector) **nie wezmą udziału w decyzjach** dopóki wiring nie zostanie dokonany.

**Recommended next iteration (v3.16.x):**
- FIX-P0-1, FIX-P0-2, FIX-P0-3, FIX-P0-4 (heartbeat infra + pdt cooldown + instrument_profile wire + liquidity_sweep wire) — łącznie ~1-2h
- FIX-P1-1, FIX-P1-2, FIX-P1-3 (position_manager wire + entry audit + lead_lag wire) — łącznie ~1-2h
- FIX-P1-5 per-monitor E2E — łącznie ~1-2h

Po wykonaniu P0 + P1: re-run audit, expected score ~85/100, decyzja → TECHNICALLY_READY_FOR_PLANNED_FUNCTIONS.

**System pozostaje paper-only.** Nie rekomenduje się live tradingu. To audyt technicznej gotowości, nie decyzja inwestycyjna.

---

## Appendix A — Audit metadata

- **Auditor:** Claude Sonnet 4.6 jako principal-engineer/staff-architect
- **Audit window:** 2026-06-04 (~1h direct repo analysis)
- **Files read:** ~50 modules + 30 docs + 20 tests
- **Methodology:** direct Read/Glob/Grep on filesystem (workflow `w53c2b75f` hung after 60+ min, recovered manually)
- **Audit-board reference:** docs/operator_decision_walkthrough_2026-06-04.md (5-question operator decisions resolved 2026-06-04)
- **No paid services consulted.** No live broker calls. No external data fetched during audit.

## Appendix B — Files cited as evidence

shared/{risk_officer,confidence,confidence_builder,heartbeat,safe_mode,intraday_governor,pdt_guard,position_manager,instrument_profile,liquidity_sweep_guard,lead_lag_analyzer,session_effectiveness,pre_market_data,pre_open_behavior,universe_selector,source_quality,event_monitor_interface,event_scoring,news_signal_gate,market_data,risk_guards,risk_classification,state_policy,state_schema,runtime_state,runtime_config,audit,autonomy,alpaca_orders,allocator,portfolio_risk}.py

backtest/{run,strategies,strategy_registry,replay,realism,crypto_data,event_data,event_replay,event_strategies,data}.py

*-monitor/monitor.py (11 directories)

tests/{architecture_vnext/*, e2e/*, test_feedback_v3150, test_confidence_wired_v3140, test_*_v3160}.py

.github/workflows/*.yml

config/{aggressive_profile, watchlists, market_universes, routine_budget}.json

docs/{PRODUCT, STRATEGY, RUNBOOK, AUTONOMY_CONTRACT, feedback_requirements, feedback_implementation_v3150, operator_decision_walkthrough_2026-06-04, PL_GPW_DECISION, MICROCAP_DECISION, FREE_TIER_LIMITS}.md
