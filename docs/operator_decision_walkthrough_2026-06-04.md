# Operator Decision Walkthrough — v3.15.x deferred items (2026-06-04)

## 1. TL;DR — pojedyncza tabela

| Item | Recommended next step | Effort (operator) | Effort (Claude) | Decision needed by |
|---|---|---|---|---|
| **FB-002 Pre-market data** | Ship Yahoo `v8/finance/chart` primary + Nasdaq fallback (Option 1) | ~10 min PR review | ~25-35 min | Można dziś — niski ryzyko |
| **Hourly crypto-bar backtest** | Ship full Alpaca harness + `--explain-zero-fires` (Option A) | 0 min UI clicks | ~75 min (worst-case 115) | Przed STRAT-002 close (2026-06-16) |
| **Event-driven backtest (geo-*)** | Phase 1 MVP only (GDELT, 30-day replay, ~30 events) | 0 min UI clicks | ~3-5h | Po crypto-harness; nie blokuj na tym |
| **DOJ monitor go-live** | Option B (SEC 8-K + DOJ RSS, emit-only, no Curator) z 30-day observation | ~45 min (workflow + secret + Cloudflare cron) | ~75-90 min | DEFER do czasu zamknięcia readiness gaps (heartbeat, P0 fixes) |
| **PL_GPW + US Microcap universe** | **Option 1 — Do nothing v3.16** (default-keep) | ~5 min (przeczytać + zarchiwizować) | 0 min | Można teraz — żadne nowe potrzeby nie wymagają wykonania |

## 2. Decision tree — sekwencja decyzyjna

```
START → Jakie są aktualne priorytety operatora?

├─ A. "Chcę żeby v3.15 deferred items się zamknęły zgodnie z planem"
│  │
│  ├─ KROK 1 (teraz): FB-002 Pre-market data → Option 1
│  │     └─ Reasoning: niskie ryzyko, reused pattern (Yahoo VIX), zero secrets,
│  │        odblokowuje `analyze_pre_open` ±0.10 confidence contribution
│  │
│  ├─ KROK 2 (po merge KROK 1): Hourly crypto-bar backtest → Option A
│  │     └─ BLOKUJE: STRAT-002 14-day observation close (2026-06-16)
│  │     └─ Reasoning: `--explain-zero-fires` odpowiada na 54-day silence
│  │        question; oversold-bounce decision (re-enable / kill / tune)
│  │        depends on this output
│  │
│  ├─ KROK 3 (po crypto-harness): Event-driven backtest → Phase 1 MVP
│  │     └─ NIE BLOKUJ na tym jeśli operator ma tight bandwidth
│  │     └─ Reasoning: re-używalne dla future event-driven monitorów
│  │        (Twitter, Reddit, politician backtest); klasifikator-refactor
│  │        side-effect = lepsza testowalność live geo-monitor
│  │
│  └─ KROK 4 (defer): DOJ monitor + PL/Microcap → patrz B i C
│
├─ B. "Mam open backlog z v3.13.x (heartbeat partial, LLM unavailable, P0 fixes)"
│  │
│  ├─ DEFER WSZYSTKIE 5 ITEMS
│  └─ Reasoning: per CLAUDE.md 2026-06-02 — 5 dni zero trade activity,
│     heartbeat 0/11 wired, Layer 1 false positives przed v3.11.1.
│     Każdy nowy monitor = większa attack surface bez stabilnej bazy.
│
└─ C. "Chcę odpowiedzieć trader-feedback (microcap edge?, DOJ?, PL?)"
   │
   ├─ Microcap edge → Option 1 (do nothing v3.16)
   │   └─ Można dziś szybko: `backtest.yml --tickers GME AMC NVAX RIOT MARA`
   │      (5 min experiment) PRZED jakimkolwiek code change
   │      └─ IWM już w whitelist daje small-cap exposure
   │
   ├─ PL_GPW → Option 1 (do nothing v3.16)
   │   └─ STRUKTURALNIE ZABLOKOWANE — żaden free PL paper broker
   │      nie istnieje. Building observation-only invites "just hook IBKR Pro" drift
   │
   └─ DOJ → Option B z 30-day observation (gdy stabilność wraca)
```

**Co BLOKUJE inne items:**

- **Crypto backtest** odblokowuje decyzję o `crypto-momentum` / `crypto-oversold-bounce` EDGE_GATE flip. Bez tego — strategie pozostają enabled bez backtest validation (effective `EDGE_GATE_ENABLED=false`).
- **Heartbeat partial wiring** (v3.13.3 sesja) BLOKUJE DOJ monitor — nowy monitor bez heartbeat = niewidoczny dla `confidence.score_system_health()`.
- **Nic nie blokuje FB-002** — pure interface wire-in.

## 3. Per-item walkthrough

### FB-002 — Pre-market data source

- **Status:** Interface (`shared/pre_open_behavior.py`) shipped v3.15.0 z 8 classification labels + ±0.10 confidence cap. Caller-supplied bars, ZERO I/O. Aktualnie zawsze zwraca `INSUFFICIENT_DATA` bo żaden caller nie przekazuje real pre-market bars. Alpaca IEX free tier nie ma pre-market.
- **Najważniejsze opcje:**
  - **Option 1:** Yahoo `v8/finance/chart` (primary) + Nasdaq summary (fallback) — REKOMENDOWANE
  - **Option 2:** Stub-only (zawsze `INSUFFICIENT_DATA`) — feature dark indefinitely
  - **Option 3:** Manual broker CSV drop — kills autonomy, ~40h/year operator time
  - **Option 4:** Wait for free SIP equivalent — żadne nie pojawiły się w 5 lat
- **Rekomendacja:** **Option 1**. Repo już używa Yahoo dla VIX (`shared/risk_guards.py:63-86`) — extending same gray-zone pattern z fail-soft contract i ±0.10 cap który bounds blast radius. Zero new deps, zero new secrets, zero workflow YAML changes.
- **Co operator musi zrobić:**
  1. Approve PR (10 min review)
  2. Verify pierwszy fetch z Yahoo zadziała (next 09:25 ET pre-market window)
  3. (opcjonalne) Approve `pre-market-snapshot.yml` cron jeśli chcesz decouple od morning-allocator
- **Co Claude może zrobić bez decyzji:**
  - Stworzyć `shared/pre_market_data.py` z Yahoo + Nasdaq cascade
  - Wire-in do `learning-loop/confidence_builder.py` i `shared/confidence.py::score_signal_strength`
  - Napisać `tests/no_network/test_pre_market_data.py` + captured fixtures
  - Update docs (FREE_TIER_LIMITS.md, feedback_implementation_v3150.md)
- **Trigger do re-decyzji:**
  - Yahoo zwraca sustained HTTP 429 (3+ dni STALE) → switch na Nasdaq primary
  - Alpaca paper account graduates to Algo Trader Plus → switch na Alpaca SIP primary
- **Open questions dla operatora:**
  1. Akceptujesz Yahoo gray-zone ToS (taki sam już accepted dla VIX)?
  2. Czy chcesz osobnego `pre-market-snapshot.yml` cron (rekomendowane Phase 2)?

---

### Hourly crypto-bar backtest harness

- **Status:** Live `crypto-monitor` używa Alpaca v1beta3 z `timeframe=1Hour` dla BTC/USD od miesięcy. `crypto-monitor/monitor.py:168-195` ma działający fetcher. **Backtest harness nie ma** — `backtest/strategy_registry.py:126-141` flaguje `crypto-momentum` i `crypto-oversold-bounce` jako `INTERFACE` z notatką `"harness needs hourly crypto-bar fetcher"`. **Zero trades w 54 dni** dla obu strategii live — bez backtestu nie wiemy czy to silence-correct (no setup) czy pipeline bug.
- **Najważniejsze opcje:**
  - **Option A:** Pełny Alpaca harness + `--explain-zero-fires` comparison — REKOMENDOWANE
  - **Option B:** A + Kraken fallback adapter (+30 min, podwójna resilience)
  - **Option C:** Defer do STRAT-002 close (2026-06-16) — ryzyko że live window nie zawiera deep-oversold setup
  - **Option D:** Minimum-viable (tylko oversold-bounce, tylko BTC/USD) — half-shipment risk
- **Rekomendacja:** **Option A**. `--explain-zero-fires` empirycznie odpowiada na single highest-value testable claim: "is 54-day silence market reality lub pipeline bug?" Bez tego v3.13.3 relaxation decision is faith-based. Alpaca endpoint jest proven free, already authenticated by existing repo secrets, zero operator-side work.
- **Co operator musi zrobić:**
  1. Approve PR (~10 min)
  2. Trigger pierwszy backtest: `python -m backtest.run --strategy crypto-oversold-bounce --tickers BTC/USD ETH/USD --hours 4320 --mode both`
  3. Read result + decide:
     - WR ≥ 50% AND PF ≥ 1.3 → flip `EDGE_GATE_ENABLED=true`
     - WR < 30% OR PF < 0.8 → disable z backtest-evidence rationale
     - 30-50% → continue STRAT-002 observation
- **Co Claude może zrobić bez decyzji:**
  - Stworzyć `backtest/crypto_data.py` (paginated Alpaca v1beta3)
  - Port `check_crypto_signal` do pure `crypto_momentum_signal_at` + `crypto_oversold_bounce_signal_at`
  - Extend `backtest/strategies.py`, `backtest/run.py`, `backtest/realism.py` (crypto-tier slippage)
  - 12-15 tests including no-lookahead + parity test z live monitor
  - Flip strategy_registry z `INTERFACE` na `HAS_SIGNAL`
- **Trigger do re-decyzji:**
  - Live oversold-bounce fires w STRAT-002 window (≥1 trade do 2026-06-16) → backtest staje się secondary
  - Alpaca zwraca ≥3 consecutive non-200 → consider Kraken fallback (Option B)
- **Open questions dla operatora:**
  1. Wytrzymujesz ryzyko że pełen port `check_crypto_signal` może wymagać partial refactor live monitora (worst-case +30-40 min)?
  2. Czy `--explain-zero-fires` output ma być w emailu czy tylko w `backtest/results/`?

---

### Event-driven backtest harness (geo-defense / geo-energy / geo-gold)

- **Status:** Live geo-monitor classifier shipped (`geo-monitor/monitor.py:273-337`). Event-scoring core + signal-gate są pure i deterministyczne (reusable). **Backtest harness nie ma** — `backtest/strategy_registry.py:91-115` flaguje wszystkie 3 strategie `EVENT_DRIVEN` z `backtest_data_needed="historical_news_events_with_tickers"`. Live evidence: ~2-3 trades/month peak (20 trades 2026-06-01 burst, typicznie 0-3/month). 6-month backtest = upper-bound ~120 signals.
- **Najważniejsze opcje:**
  - **Option A:** Phase 1 MVP only (GDELT + 30-day replay + classifier refactor) — REKOMENDOWANE
  - **Option B:** Phase 1 + Phase 2 (6-month corpus) w jednym push (8-13h Claude)
  - **Option C:** Defer entirely, observe live 3-6 miesięcy (bardzo wolne — 18 trades w 6 miesięcy)
  - **Option D:** Forward A/B (dwa classifiery równolegle, no historical replay)
- **Rekomendacja:** **Option A**. Infra (GDELT fetcher, event-to-news adapter, event_replay loop) genuinely reusable dla future event-driven monitorów. Classifier-refactor side-effect ("extract `_classify_news_to_signals` do `shared/geo_classifier.py`") = GOOD HYGIENE niezależnie od backtest outcome. **HARD CONSTRAINT:** nie flip `EDGE_GATE_ENABLED=true` dla geo-* aż n ≥ 50 backtest trades AND ≥ 20 live trades concur. Current threshold n ≥ 10 jest calibrated dla bar-driven strategii, NOT event-driven.
- **Co operator musi zrobić:**
  1. Approve PR (review classifier extraction safety — touches LIVE geo-monitor)
  2. Run 30-day replay: `python -m backtest.run --strategy geo-defense --days 30 --start 2024-10-01`
  3. Eyeball verify: czy RTX BUY fires kiedy expected? Czy GOLD fires na high-tone day?
  4. Decide na Phase 2 expansion (corpus monthly workflow): tylko jeśli Phase 1 ujawnia bug LUB confirms hypothesis worth deeper investigation
- **Co Claude może zrobić bez decyzji:**
  - Stworzyć `backtest/event_data.py` (GDELT fetcher z cache)
  - Extract `_classify_news_to_signals` do `shared/geo_classifier.py` (single source of truth)
  - Stworzyć `backtest/event_replay.py` + `event_to_news_adapter.py`
  - 5 fixture-based tests (major defense event, energy event, gold safe-haven, noisy non-event, dedup)
  - Update strategy_registry honestnie (`MVP_in_progress`, NIE flip na `HAS_SIGNAL`)
- **Trigger do re-decyzji:**
  - Po Phase 1: jeśli backtest ujawnia bug w live classifierze → wysoki value, ship Phase 2
  - Po Phase 1: jeśli backtest powtarza co już wiemy z live data → stay Option C/D mode
- **Open questions dla operatora:**
  1. Akceptujesz że backtest answers "if my CURRENT classifier had run during 2024" — NIE "what actually happened"?
  2. Czy refactor `_classify_news_to_signals` jest acceptable touch na live code (mitigation: existing tests must keep passing)?

---

### DOJ / legal proceedings monitor go-live

- **Status:** Interface (`shared/event_monitor_interface.py`) + MockDOJMonitor shipped v3.15.0. Tier 1 source mapping ready (`source_quality.py:107-116`). **Zero live monitor code** — `doj-monitor/` directory nie istnieje. FB-008 = `Valuable, partial` / P2. Free DOJ RSS reliability unverified.
- **Najważniejsze opcje:**
  - **Option A:** Tylko SEC 8-K lane (~700 LOC, ~60 min) — najmniejszy scope
  - **Option B:** SEC 8-K + DOJ RSS, emit-only, no Curator — REKOMENDOWANE dla balanced shipping
  - **Option C:** Full stack (8-K + DOJ + CourtListener + FTC + Curator) — largest scope, drains P2 routine budget
  - **Option D:** Defer entirely — REKOMENDOWANE PRZY OPEN BACKLOG
- **Rekomendacja (warunkowa):**
  - **Jeśli readiness gaps zamknięte (heartbeat fully wired, brak P0 incidents):** **Option B** z 30-day observation gate
  - **Jeśli backlog v3.13.x niezamknięte:** **Option D — defer**
  - Per CLAUDE.md 2026-06-02: heartbeat partial-wired (4/11 monitors), 5 dni zero trade activity, LLM unavailable 3 dni. **System stability dominates new monitor value.**
- **Co operator musi zrobić (jeśli Option B):**
  1. Approve PR (~15 min)
  2. Add `SEC_USER_AGENT` secret w GitHub (~2 min)
  3. Paste `scripts/workflow-templates/doj-monitor.yml` via UI (~3 min)
  4. Add doj-monitor entry do Cloudflare cron-trigger Worker (~3 min)
  5. Trigger pierwszy manual run + verify `[DOJ-FILING]` email arrives (~10 min)
  6. 30-day observation: review `[DOJ-FILING]` emails dla false positive rate (~5-10 min/week)
- **Co Claude może zrobić bez decyzji:**
  - Cały code path (sec_8k_client + doj_press_client + monitor + state + tests + docs)
  - Wire-in z `news_signal_gate.gate_news_signal` + `notify.send_email`
  - Default `AUTO_EXECUTE_DOJ=false` + `MAX_ALERTS_PER_RUN=3`
  - Audit check `DOJ_MONITOR_TIER_1` w system_consistency_agent
- **Trigger do re-decyzji:**
  - Po 30-day window: ≥5 events corresponded do >2% next-day move → escalate to Option C (add Curator)
  - W observation: ≥3 consecutive `audit:STALE` alerts (>72h between events) → drop DOJ RSS lane, keep tylko 8-K
  - Stack ≥2 P0 incidents w tym samym tygodniu co DOJ ship attempt → rollback do Option D
- **Open questions dla operatora:**
  1. **NAJWAŻNIEJSZE:** Czy v3.13.x readiness gaps są wystarczająco zamknięte żeby ship nowy monitor? (Mój audit honest answer: NIE — heartbeat partial, LLM unavailable 3 dni z rzędu = signal że nie czas)
  2. Akceptujesz że bez LLM Curator ticker extraction ma 5-15% headline-mismatch rate?
  3. Czy gotowy na 30-day observation window przed jakimkolwiek auto-execute consideration?

---

### PL_GPW + US Microcap universe enablement

- **Status:** Abstraction shipped v3.15.0 (`shared/universe_selector.py` + `config/market_universes.json`). **Zero wiring** — `universe_selector.py:21` references `runtime_config.py::active_universe()` która **nie istnieje**. Flipping `enabled=true` w JSON zmienia ZERO real behavior. IWM (Russell 2000 ETF) już w whitelist daje small-cap exposure bez microcap single-name risk.
- **Najważniejsze opcje:**
  - **Option 1:** Do nothing v3.16 (default-keep) — REKOMENDOWANE
  - **Option 2:** Backtest-only US microcap (research path, no live wiring)
  - **Option 3:** PL observation-only monitor (no execution path exists)
  - **Option 4:** Both (Option 2 + Option 3)
- **Rekomendacja:** **Option 1 — do nothing v3.16**. Reasoning:
  - **PL strukturalnie zablokowane** — żaden free PL paper broker nie istnieje. Żaden code change tego nie zmieni. IBKR Pro ma USD 10/month inactivity fee = fails "zero $/month guaranteed".
  - **Microcap = unverified hypothesis** — "might offer edge" to NOT actionable evidence. Operator może uruchomić `backtest.yml --tickers GME AMC NVAX RIOT MARA` w 5 min **bez żadnego code change** żeby zacząć generate evidence.
  - **IWM już daje small-cap exposure** z mega-cap risk controls.
  - **Open backlog dominates** — building infra dla universe którego system *nie może trade* invites future drift ("just hook IBKR Pro").
- **Co operator musi zrobić:**
  1. Read this decision + filing decision (~5 min)
  2. (opcjonalne) Run informal microcap experiment: `backtest.yml --tickers <list> --strategy momentum-long --days 180`
  3. Update CLAUDE.md backlog notes że v3.15.0 universe abstraction = scaffolding, enablement out of scope until concrete need emerges
- **Co Claude może zrobić bez decyzji:**
  - Nic (do nothing path)
  - LUB jeśli operator chce informal microcap experiment: pomoc w wyborze 5-10 Russell 2000 tickers verified IEX-tradeable
  - LUB jeśli operator chce dokumentacji: update `docs/MICROCAP_DECISION.md` + `docs/PL_GPW_DECISION.md` z explicit triggers do revisit
- **Trigger do re-decyzji (Option 2 — microcap backtest):**
  1. Operator run informal backtests via existing `backtest.yml` i widzi *any* result worth formalizing
  2. US_LARGE backlog has zero P0/P1 items
  3. Operator ma specific microcap-momentum hypothesis (np. "Russell 2000 breakouts during VIX < 20 RISK_ON")
- **Trigger do re-decyzji (Option 3 — PL observer):**
  1. Free Polish paper-broker API appears (highly unlikely w 12-month horizon)
  2. OR operator accepts observation-only mental model
  3. AND specific PL hypothesis tied to Polish economic events (np. NBP rate decision moves WIG20 banks differently than Fed moves XLF)
- **Open questions dla operatora:**
  1. Czy "trader-feedback question" wymaga formalnego shipping infra, czy 5-min informal backtest experiment wystarczy?
  2. Czy IWM exposure (already in whitelist) wystarcza dla small-cap hypothesis?

## 4. Recommended sequencing

### Teraz (po tej rozmowie, dziś)

1. **PL_GPW + Microcap → Option 1 (do nothing)** — najszybsza decyzja, najmniejszy risk. Operator filing decision do CLAUDE.md backlog z explicit re-trigger conditions. **Czas: 5 min.**

2. **FB-002 Pre-market data → Option 1** — operator approve, Claude implements w jednej sesji. **Czas total: ~45 min** (25-35 min Claude + 10 min review). **Niski ryzyko, immediate confidence-builder contribution.**

3. **(Opcjonalne) Informal microcap backtest** — operator triggers `backtest.yml` z hand-picked tickers (GME, AMC, NVAX, RIOT, MARA) jako 5-min experiment przed dyskusją o formalnym shipping. **Czas: 5 min trigger + interpretation w nast. sesji.**

### W ciągu 7 dni

4. **Hourly crypto-bar backtest harness → Option A** — ship before STRAT-002 14-day observation close (2026-06-16). **Czas: ~75-90 min Claude + ~10 min operator interpretation.** Output drives crypto-momentum / crypto-oversold-bounce decision (re-enable / kill / tune).

5. **Verify readiness gaps** — sprawdź czy heartbeat został fully wired w 11 monitors (v3.13.3 wired tylko 4/11), czy LLM unavailable issue z 2026-05-30/06-02 jest resolved, czy są open P0/P1 incidents. **TO JEST GATE dla DOJ monitor decision.**

### W ciągu 30 dni

6. **Event-driven backtest (geo-*) → Phase 1 MVP** — tylko po stabilizacji systemu. **Czas: ~3-5h Claude.** Classifier-refactor side-effect = good hygiene niezależnie od backtest outcome. **NIE flip EDGE_GATE_ENABLED dla geo-* aż n ≥ 50 backtest + n ≥ 20 live concur.**

7. **DOJ monitor decision point** — IF readiness gaps closed AND brak P0 incidents w ostatnim tygodniu → ship Option B z 30-day observation. **Czas: ~80 min Claude + ~45 min operator (workflow + secret + Cloudflare cron + observation review).**

### Po walidacji data sources

8. **Crypto backtest Phase 2** — Kraken fallback adapter jeśli Alpaca crypto endpoint kiedykolwiek wykazuje schema instability (≥3 consecutive non-200).

9. **Event-driven Phase 2** — 6-month corpus replay TYLKO jeśli Phase 1 produces ≥30 candidate signals AND classifier behavior matches operator's manual judgment on eyeball sample.

10. **DOJ Phase 2** — add CourtListener + LLM Curator po 30-day observation IF email volume <20/day AND ≥5 events corresponded do >2% moves.

11. **Microcap formalization → Option 2** — TYLKO IF (a) informal backtest evidence positive, (b) US_LARGE backlog empty, (c) specific hypothesis defined.

## 5. Hard NO list

Następujące items **NIE SĄ wykonalne na obecnym free stacku** lub naruszają hard constraints:

### 5.1 PL_GPW live execution

- **Powód:** Żaden free Polish paper broker nie istnieje. XTB, Bossa, mBank, Saxo — none ship free paper API.
- **IBKR Pro** wymaga USD 10/month inactivity fee waived only przez minimum trade volume → **fails "zero $/month guaranteed"** rule.
- **Strukturalny blocker**, nie code-side.

### 5.2 OTC / pink-sheet microcap

- **Powód:** Alpaca paper NIE executes OTC. Free data sources (Alpaca IEX, Yahoo, Stooq) inconsistently cover OTC. Question moot.

### 5.3 Pre-market 1-min bars z paid SIP feed

- **Powód:** Alpaca SIP = $99/month. Fails "zero $/month" constraint repeatedly stated w docs.
- **Workaround:** Yahoo `v8/finance/chart` gray-zone (already accepted dla VIX).

### 5.4 Real-time crypto bars z premium APIs

- **Powód:** CoinGecko hourly = $35/month (Basic tier). Alpha Vantage 25 calls/DAY = 53 tickers × 1 scan > 2 days quota burned.
- **Workaround:** Alpaca v1beta3 (free, already authenticated).

### 5.5 PACER court records direct access

- **Powód:** $0.10/page, $3/doc cap = unpredictable spend. Fails free constraint.
- **Workaround:** CourtListener RECAP API (free, 5k req/day anonymous, 50k registered).

### 5.6 NewsAPI.org historical (>24h lookback)

- **Powód:** $449/month. Fails free constraint.
- **Workaround:** GDELT 2.0 + Wikipedia Current Events Portal.

### 5.7 Binance crypto data

- **Powód:** GEO-BLOCKED dla US IPs (GitHub Actions runners primarily Azure US). Workaround przez Cloudflare proxy = added complexity bez clear benefit nad Alpaca.

### 5.8 X API v2 Basic ($100/month dla Twitter monitor upgrade)

- **Powód:** Fails free constraint. Bluesky path działa za $0.

### 5.9 EDGE_GATE_ENABLED=true dla event-driven strategies przy n < 50

- **Powód:** Current threshold n ≥ 10 calibrated dla bar-driven strategies (fire weekly). Event-driven fires monthly. n=10 ma zero discriminating power dla geo-*. **Hard constraint** — confidence inflation risk.

## 6. Pytania, na które operator MUSI odpowiedzieć teraz

1. **READINESS GAP STATUS:** Czy v3.13.x readiness gaps są zamknięte? Specifically:
   - Heartbeat fully wired across 11 monitors? (v3.13.3 wired tylko 4/11)
   - LLM unavailable issue z 2026-05-30/06-02 resolved?
   - Brak open P0/P1 incidents w ostatnim tygodniu?
   - **Wpływ:** Determinuje czy DOJ monitor ship teraz vs defer.

2. **CRYPTO STRATEGY PHILOSOPHY:** Czy gotów na potencjalny outcome backtestu który mówi "crypto-momentum has no edge" → disable strategy permanently? Czy preferred answer "uncertain edge, continue observation"?
   - **Wpływ:** Determinuje czy crypto backtest = decision tool czy validation theatre.

3. **YAHOO TOS RISK ACCEPTANCE:** Akceptujesz extending Yahoo gray-zone dependency z 1 endpoint (VIX, ~12 calls/morning) do dwóch endpoints (VIX + pre-market 53 tickers × 12 ticks ≈ 636 calls/morning)?
   - **Wpływ:** Determinuje FB-002 ship vs stub.

4. **CLASSIFIER REFACTOR ACCEPTANCE:** Akceptujesz że Event-driven backtest Phase 1 wymaga touch na LIVE `geo-monitor/monitor.py` (extract `_classify_news_to_signals` → `shared/geo_classifier.py`)?
   - **Wpływ:** Determinuje event-driven backtest Phase 1 vs defer.

5. **MICROCAP/PL FINAL VERDICT:** Filing decision dla obu (Option 1 do nothing) — confirmed? LUB chcesz informal 5-min microcap backtest experiment przed final filing?
   - **Wpływ:** Closes 2 z 5 items immediately, frees attention dla pozostałych 3.

---

**Audit-engineer final note:** Risk engine ma ostatnie słowo. Nawet jeśli ten walkthrough rekomenduje shipping order, każdy nowy item musi przejść przez existing risk_officer + confidence gates BEZ obniżania thresholds. Backtest evidence służy do **disabling** strategy gdy WR/PF/MDD są złe — nie do **enabling** gdy są dobre bez statistical power floor (n ≥ 20 minimum dla bar-driven, n ≥ 50 dla event-driven). Confidence boost MUSI come from data, never from "we shipped a thing".