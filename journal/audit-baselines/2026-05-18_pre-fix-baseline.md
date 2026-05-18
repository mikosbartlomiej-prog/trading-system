# Audit baseline — 2026-05-18 17:30 UTC

> Notatka porównawcza — co system robił PRZED 5 audit fixes z dzisiaj.
> Jutro (2026-05-19) po wieczornym daily-learning sprawdź każdą sekcję
> "PREDYKCJA" i porównaj z rzeczywistym outputem.
>
> 5 commitów na main: `e07f7c6` `691952a` `99eaabb` `ecf3f06` `37a07cb`
> (HEAD przed fixami: `5bfbd86`)

---

## 1. Konto Alpaca — stan przed fixami

| Pole | Wartość 17:14 UTC | Źródło |
|---|---|---|
| Equity | $95,368.42 | `runtime_state.json::intraday_governor.current_equity` |
| Intraday P&L | +$1,438.07 (+1.53%) | runtime_state.json |
| Intraday peak | $1,438.07 | peak_at 16:30:48 UTC |
| pnl_state | GREEN | — |
| Open positions | 6 (AMD, GLD, NVDA, OXY, QQQ, SMH, SPY, USO) | position_mfe |
| Session start equity | $93,930.35 | — |
| Cumulative ROI today | +0.04% (po pierwszym daily-learning runie) | history/2026-05-18.md |

**UWAGA:** Senior PM 01:31 UTC widział equity $92,743 (-1.26%), Senior PM 08:09 UTC widział $93,971 (+0.04%). Czyli między 01:31 a 08:09 system odzyskał $1,228 bez widocznych tradów w `by_strategy`. **Ten gap był flagowany przez Senior PM jako 'matematycznie niemożliwa anomalia'.**

---

## 2. Routine budget — przed fixami

```json
"routine_budget": {
  "by_routine": {"daily-learning-pm": 2},
  "by_tier": {"P0_essential": 2},
  "date": "2026-05-18",
  "total": 2
}
```

- Internal counter: tylko 2 calls tracked
- Rzeczywiście odbyło się dziś: 2 Senior PM + 4 reddit_curate = 6 calls
- Curator calls NIE rejestrowane (workflow nie commitował runtime_state)

### Wczoraj (2026-05-17): 18 LLM calls total
- 2 Senior PM (01:30, 06:51)
- 15 reddit_curate (rolling 12:00-21:58)
- 1 weekly-retro (22:43 — **FAILED**)

### Sobota+niedziela (2026-05-16 + 17): 23 curator calls
→ Anthropic 24h rolling window cały weekend obciążony.

### PREDYKCJA dla 2026-05-19

| Metryka | Oczekiwane jutro |
|---|---|
| `routine_budget.by_routine.daily-learning-pm` | **3** (round 1 + round 3 revise) — przy starym kodzie było 2 |
| `routine_budget.by_routine.daily-learning-challenger` | **1** (round 2) — **NIE BYŁO ANI RAZU** od 3 dni |
| `routine_budget.by_routine.daily-learning-revise` | **1** (round 3) — **NIE BYŁO ANI RAZU** od 3 dni |
| `routine_budget.by_routine.reddit-curator` | **≤ 4** (P2 cap teraz 4/day) |
| `routine_budget.by_tier.P0_essential` | **5** (3 daily-learning + 0-2 retry) |
| `routine_budget.by_tier.P2_optional` | **≤ 4** (capped) |
| `routine_budget.total` | **8-10** (3 P0 + 4 P2 + sporadic curator) |

---

## 3. Learning loop output — kontekst

### history/2026-05-18.md (dzisiaj) — co tam jest

```
**Equity:** $93,971.37 (starting: $93,930.35; ROI: +0.04%)
**Cumulative trades:** 0
**Cumulative P&L:** $0.00

Rationale:
- LLM[low] regime=choppy: ... fill_rate.unknown (6 placed, 0 filled) to TRZECI dzień ...
  options-momentum odblokowuje się jutro (2026-05-19), SPY RSI 69.8 poniżej PUT-gate 75 ...
- LLM edge: ... PUT-side options jutro jest najlepiej uzasadnionym setupem ...
- crypto-momentum: SILENT — enabled but 0 trades lifetime (25 days tracked)
- geo-defense / geo-energy / geo-gold / geo-xom: wszystkie SILENT (25 dni)
- fill-rate alert [unknown]: fill rate 0% below 50% (0 canceled / 6 placed)
```

### Brakuje (skutek 429 na Challenger/Revise)

```
NIE MA:
- "Challenger critique" section
- "revision_log[]" entries
- "LLM[high]" tag (jest tylko LLM[low])
- Konkretne state_overrides od Senior PM
- Lane 2 PR proposals
```

### PREDYKCJA dla history/2026-05-19.md

| Sekcja | Oczekiwane | Aktualne stan jutro |
|---|---|---|
| Tag w pierwszym wierszu rationale | `LLM[high]` zamiast `LLM[low]` | TBD |
| Sekcja "Challenger critique" z DECISION (SURVIVED/MODIFIED/REJECTED) | obecna | TBD |
| Sekcja "revision_log" z DEFENDED/ACCEPTED/MODIFIED/ADDED | obecna | TBD |
| fill_rate.unknown z `sample_open_ids` + `sample_open_symbols` | obecne (P2 #1 fix) | TBD |
| fill_rate.unknown.other counter | wystawiony (był silent) | TBD |

---

## 4. Alpaca rejection — USO + OXY szczegóły

### Run #1 (16:20 UTC) — wszystko OK
```
USO BUY placed: BUY 110.0000 @ $152.75  id=e42e3327-92da-4082-ae3b-aee1062158b0
OXY BUY placed: BUY 281.0000 @ $59.99  id=d43e2466-8bc0-4064-89ec-1740e77b5579
AMD BUY placed: BUY 6.6492 @ $426.11  id=335b79c2-5437-403a-84b8-76d2f6c70368
+ 5 inne (SMH/NVDA exit, GLD/SPY/QQQ reduce)
```

### Run #2 (16:39 UTC) — duplikat z 2 rejections
```
USO BUY: derived qty=110 from target=$16,895 @ $152.86 (no prior position)
USO BUY failed
OXY BUY: derived qty=281 from target=$16,895 @ $60.10 (no prior position)
OXY BUY failed
AMD BUY placed: BUY 6.6492 @ $426.11  id=a149217f-8dcb-4d5d-981c-4cc368ddf96d
```

### Skutki
- **AMD podwójnie kupione**: 6.6492 + 6.6492 = 13.3 shares (target był 6.6)
- USO + OXY: LIMIT z run #1 nadal otwarte na Alpaca (jeśli się nie wypełniły do końca sesji)
- GLD/SPY/QQQ REDUCE: pewnie ok, ale każdy z 2 sekwencji — wymaga sprawdzenia
- SMH/NVDA EXIT: pierwszy wypełnił, drugi no-op (no position)

### PREDYKCJA dla operatora (manual check w Alpaca dashboard)
- Sprawdź czy AMD pozycja > target $16,895 (= ~40 shares @ $426). Jeśli tak, reduce.
- Sprawdź czy USO/OXY LIMIT @ $152.75 / $59.99 nadal otwarte → cancel ręcznie
- Po dzisiejszych fixach **jutro nie powinno się powtórzyć** (idempotency + skip-if-open-order)

---

## 5. GH Actions cron drift — baseline

### monitor-health snapshot 16:46 UTC

| Workflow | Status | Last run mins ago | Observed | 24h S/F |
|---|---|---|---|---|
| price-monitor | STALE | 22 | 94.2 min vs 5 expected (18.8×) | 2/0 |
| crypto-monitor | STALE | 28 | 119.2 vs 5 (23.8×) | 14/0 |
| defense-monitor | STALE | 19 | 6.7 vs 5 (1.3×) | 16/0 |
| twitter-monitor | STALE | 26 | 120.0 vs 5 (24.0×) | 18/0 |
| options-monitor | STALE | 24 | 93.8 vs 5 (18.8×) | 2/0 |
| reddit-monitor | OK | 21 | 68.8 vs 30 (2.3×) | 12/0 |
| exit-monitor | OK | 15 | 109.6 vs 5 (21.9×) | 20/0 |
| daily-learning | OFF_HOURS | 521 | 398.4 vs 1440 (0.28×) | 2/0 |
| weekly-retro | **FAILING** | 1083 | — | 0/1 |

### PREDYKCJA jutro (post-fix)

- **price-monitor / options-monitor**: 24h successes — oczekuj **40-60** (z 2 wczoraj). NIE wynika z dzisiejszych fixów, ale watchdog ma już 58 successful runs.
- **weekly-retro**: nadal niski 24h count bo cron tylko niedziele. Ale następna niedziela 2026-05-24 22:00 UTC powinna mieć fail-soft path.
- **reddit-monitor**: 24h successes ~10-12 zamiast 12 wcześniej (cron */30 → hourly + nightly = ~9 ticks). Każdy tick teraz commituje runtime_state.json.

---

## 6. Strategies state — przed fixami

```json
"strategies": {
  "alloc-exit":           {"enabled": true,  "size_multiplier": 1.0, "trades_7d": 0},
  "allocator-rebalance":  {"enabled": true,  "size_multiplier": 1.0, "trades_7d": 0},
  "crypto-breakdown":     {"enabled": false},
  "crypto-momentum":      {"enabled": true,  "trades_lifetime": 0,   "trades_7d": 0},
  "geo-defense":          {"enabled": true,  "trades_lifetime": 0,   "trades_7d": 0},
  "geo-energy":           {"enabled": true,  "trades_lifetime": 0,   "trades_7d": 0},
  "geo-gold":             {"enabled": true,  "trades_lifetime": 0,   "trades_7d": 0},
  "geo-xom":              {"enabled": true,  "trades_lifetime": 0,   "trades_7d": 0},
  "options-momentum":     {"enabled": false, "size_multiplier": 0.5, "paused_until": "2026-05-19"},
  "overbought-short":     {"enabled": false}
}
```

### PREDYKCJA jutro

- **options-momentum** powinno auto-resume rano (paused_until=2026-05-19 minione) **ALE** SPY-overbought gate sprawdzi: jeśli SPY RSI > 75 → znów pause +1 dzień. SPY RSI wczoraj było 69.8 → **prawdopodobnie odpali**.
- 5× SILENT strategy flags (crypto-momentum + 4 geo-*) — wciąż prawdopodobne jutro, te strategie nie generują tradów od 25 dni.
- Senior PM może podjąć override decyzję dla SILENT strategies (np. disable jednego z 4 geo-*).

---

## 7. Allocator execution log — pattern

### Plan generated 01:31 UTC, executed 16:20 + 16:39 UTC

Plan (`learning-loop/allocations/2026-05-18.json`) zawierał 8 rebalance orderów:
- 2× EXIT (SMH, NVDA)
- 3× REDUCE (GLD, SPY, QQQ)
- 3× BUY (USO, OXY, AMD)

### PREDYKCJA jutro

- Plan jutra zostanie wygenerowany 04:00 UTC daily-learning
- Allocator wykona 13:35 UTC cron (jeśli GH Actions nie skipuje)
- **Jeśli operator manualnie triggernie 2-3×**: pierwszy fire executes; drugi+ kończy się `IDEMPOTENCY GUARD: ... already executed N min ago. Skipping re-execution.`
- Jeśli plan zawiera BUY na ticker który ma open LIMIT z poprzedniego dnia → `BUY skipped: existing open BUY order ...` (P1 fix)

---

## 8. Hard checklist do weryfikacji jutro

Operator po przyjściu rano (~05:00 UTC po wieczornym daily-learning) powinien:

```bash
cd ~/Documents/Git/trading-system
git pull origin main

# 1. Senior PM ↔ Challenger ↔ Revise — 3 rounds?
cat learning-loop/history/2026-05-19.md | head -40
# Oczekuj:
#  - LLM[high] zamiast LLM[low]
#  - Sekcja "Challenger critique"
#  - Sekcja "revision_log"

# 2. Routine budget — wszystkie 3 rounds zarejestrowane?
python3 -c "
import json
s = json.load(open('learning-loop/runtime_state.json'))
print(json.dumps(s['routine_budget'], indent=2))
"
# Oczekuj: by_routine ma daily-learning-pm + daily-learning-challenger + daily-learning-revise

# 3. fill_rate diagnostics — IDs surfaced?
grep -A 5 "fill_rate" learning-loop/history/2026-05-19.md | head -20
# Oczekuj: sample_open_ids + sample_open_symbols
# albo: "fill_rate.unknown" już nie raportuje 6/0 (bo Senior PM zidentyfikował problem)

# 4. Alpaca — czy AMD nie podwojony?
# (manual check w Alpaca dashboard https://app.alpaca.markets/paper/dashboard/overview)
# AMD position value powinno być ~$16,895 (target), nie ~$33,000

# 5. Allocator execution dla 2026-05-19
cat learning-loop/allocations/2026-05-19.execution.json 2>/dev/null | head -20
# Oczekuj: n_placed jakaś liczba, n_failed=0 (chyba że Alpaca rejected legitimately)

# 6. Czy weekly-retro będzie test'owy? (następna niedziela)
ls learning-loop/weekly-retros/ | tail -3
# Tu nic do sprawdzenia jutro — weekly retro to niedziela
```

---

## 9. Co BĘDZIE PROBLEMEM jutro nawet po fixach

| Problem | Status | Effort fix |
|---|---|---|
| AMD podwójnie kupiony | wymaga manual cancel w Alpaca UI | 1 min operator |
| GH Actions cron drift price/options/twitter/crypto */5 → 90-120 min observed | inherent GH Actions issue, watchdog mitiguje ale nie eliminuje | self-hosted runner (kilka godzin) |
| Weekend curator activity nadal pali budget | częściowo (cron zredukowany do hourly weekend daily limit zachowany) | TBD jeśli problem persists |
| SILENT strategies (geo-*, crypto-momentum) nie generują tradów | strukturalne — wymaga audytu czemu nie wykrywają sygnałów | 2-3h operator review |
| Anthropic 24h rolling window — nawet z naszymi capami nie kontrolujemy globalnego limitu Anthropic | nie do naprawienia z naszej strony | upgrade do API |

---

## 10. Successful baseline metrics — jak wygląda zdrowy dzień

Te liczby z 2026-05-15 (sobota, dobry dzień):
- daily-learning fired 21:00 UTC (przed v3.8.5 migration)
- LLM[high] z pełnym 3-round dialogiem
- 23/93 testów green, 70 P0_essential calls dziennie OK

To porównanie wskazuje że jutro w przypadku 100% sukcesu fixów:
- `runtime_state.json::routine_budget.total = 5-8`
- `history/2026-05-19.md` ma "Challenger critique" + "revision_log" sections
- `runtime_state.json::routine_budget.by_routine` zawiera 3 keye daily-learning-*

---

**Autor:** Claude (audit + fixes 2026-05-18 17:30-17:45 UTC)
**Następna weryfikacja:** 2026-05-19 ~05:00 UTC po wieczornym 04:00 UTC daily-learning
**Branch baseline:** zachowany jako `journal/audit-baselines/2026-05-18_pre-fix-baseline.md`
