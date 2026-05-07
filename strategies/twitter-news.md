# Strategia: Twitter / Social-Graph News (Bluesky MVP) — v1.0

**Wersja:** 1.0 (2026-05-07)
**Źródło prawdy:** `docs/STRATEGY.md` §4.8
**Monitor:** `twitter-monitor` (data source: Bluesky AT-Protocol; X API jako future upgrade)
**Routine:** `Twitter Handler` (claude.ai)
**Status:** LIVE — pierwszy smoke test 2026-05-07 (login OK, 19 kont załadowanych, czeka na keyword-matched post)

---

## Opis

System czyta posty z curated whitelist kont (Bluesky → docelowo X) co 5 min
podczas sesji + co 15 min 24/7. Każdy post przechodzi przez:

1. **Keyword filter per kategoria** (gov_us, mil_il, macro, wire, ticker:*)
2. **Event-probability scoring** (`shared/event_scoring.py`) z real-bar-data
   reaction metrics (SPY proxy lub per-ticker dla `ticker:SYM`)
3. Tylko `FOLLOW_REACTION` trafia do routine — IGNORE/WAIT są dropped, CONTRARIAN_CANDIDATE flagged-only

Routine `Twitter Handler` interpretuje post w jednym z 5 wzorców
(A/B/C/D/E poniżej) i wystawia bracket order via Alpaca MCP. Iron rule:
SL obowiązkowy, LIMIT only, paper account.

**Cel ekspozycji:** zaliczane do soft cap defense+geo+twitter combined =
**$25k gross** (patrz `docs/STRATEGY.md` §2.3, §4.5).

---

## 5 wzorców interpretacji (A-E)

Routine klasyfikuje post na podstawie `category` + `matched_kw` + treści:

### Pattern A — TICKER_DIRECT (CEO/insider account)

**Trigger:** `category = ticker:SYM` (np. `ticker:TSLA`)
**Logika:** każdy post od account-CEO o jego spółce → trade na ten ticker
**Direction:** BUY jeśli ton bullish (product launch, contract, beat),
SELL_SHORT jeśli ton bearish (resignation, miss, recall)

| Parametr | Wartość |
|---|---|
| size_usd | **$5,000** |
| stop_loss | -6% |
| take_profit | +14% |
| R:R | 2.33 |

Tickery: TSLA (Musk), AAPL (Cook), GOOGL (Pichai), MSFT (Nadella).
Max 1 pozycja per ticker w jednym dniu.

### Pattern B — GEO_ESCALATION

**Trigger:** `category in {gov_us, mil_il}` + keyword in
{sanctions, executive order, military, missile, strike, tariff, deployment}
**Logika:** geopolityczna eskalacja → bull defense + energy + safe-haven

| Direction | Tickery | size_usd per ticker | SL | TP |
|---|---|---|---|---|
| BUY | RTX, LMT, NOC, GD, BA | **$8,000** | -5% | +12% |
| BUY | ITA, XAR, DFEN | **$6,000** | -5% | +12% |
| BUY | XLE, XOM, CVX | **$6,000** | -5% | +12% |
| BUY | GLD | **$6,000** | -5% | +12% |

**Cap: 2 pozycje per pojedynczy post** (priorytet: Big-5 > ETF > geo basket).
Reszta zostawiona na kolejne tweety albo defense-monitor pickup.

### Pattern C — GEO_DEESCALATION

**Trigger:** `category in {gov_us, mil_il}` + keyword in
{ceasefire, peace deal, treaty, troop withdrawal, end of conflict}
**Logika:** risk-on po deeskalacji

| Direction | Tickery | size_usd | SL | TP |
|---|---|---|---|---|
| BUY | SPY, QQQ | **$6,000** | -5% | +12% |
| SELL | XLE, GLD | **$6,000** | +5% | -12% |

**Cap: 2 pozycje per post.**

### Pattern D — MACRO_DATA

**Trigger:** `category = macro` + keyword in
{cpi, inflation, fomc, rate, recession, gdp, jobless, earnings beat/miss, guidance}
**Logika:** interpretacja bull/bear z keywords

| Sygnał | Action | Tickery |
|---|---|---|
| Rate cut surprise / dovish Fed | BUY | SPY, QQQ |
| Rate hike surprise / hawkish Fed | SELL | SPY; BUY GLD |
| CPI niższe niż oczekiwane | BUY | SPY |
| CPI wyższe niż oczekiwane | SELL | SPY; BUY GLD |
| Earnings beat (z ticker name w treści) | BUY | wymieniony ticker |
| Earnings miss / guidance cut | SELL | wymieniony ticker |

| Parametr | Wartość |
|---|---|
| size_usd | **$6,000** |
| stop_loss | -5% |
| take_profit | +12% |

### Pattern E — WIRE_BREAKING

**Trigger:** `category = wire` + keyword in {breaking, exclusive, just in, confirmed}
**Logika:** wire-grade alert (Reuters, AP) — interpretuj jak GEO_* na podstawie treści

Jeśli treść jednoznacznie eskalacja → Pattern B; deeskalacja → C; macro → D.
Jeśli niejednoznaczne → **SKIP** ("Insufficient classification confidence").

---

## Event-probability gating (kluczowy filtr)

Przed routine, **monitor sam filtruje** posty przez `score_and_decide`:

| Stance | Akcja monitora | Akcja routine |
|---|---|---|
| `FOLLOW_REACTION` | Forward do routine + email | Wystawia trade per pattern |
| `CONTRARIAN_CANDIDATE` | **Email-only flag**, nie idzie do routine | n/a (nie wywoływana) |
| `IGNORE_EVENT` | Drop, log only | n/a |
| `WAIT_FOR_CONFIRMATION` | Drop, log only | n/a |

**Dlaczego ważne:** Twitter to najgłośniejsze źródło. Bez tej warstwy
flood polityczych tweetów Trumpa wystawiałby setki niemal-duplikatów.
Layer credibility×reaction filtruje noise PRZED execution.

**Mapowanie source_type (per category):**
- `ticker:*` → `tweet_verified_corp` (cred 50)
- `gov_us`, `mil_il` → `tweet_verified_pol` (cred 45)
- `macro` → `major_outlet` (cred 60)
- `wire` → `reuters_ap` (cred 70)
- inne → `tweet_anon` (cred 25)

**Mapowanie event_type (z keyword sniffing):**
- "earnings beat/miss", "guidance" → `earnings_release` (shift 75)
- "rate", "fomc" → `rate_decision` (shift 90)
- "sanctions", "executive order", "treaty" → `policy_announced` (shift 50)
- "strike", "missile", "operation" → `threat_or_warning` (shift 25)
- wire fallback → `policy_announced`

---

## Reaction metrics (real-bar data)

Monitor pobiera bary z Alpaca (`shared/market_data.py::compute_reaction_metrics`):

- `category = ticker:SYM` → bary tego konkretnego tickera
- `gov_us`/`mil_il`/`macro`/`wire` → **SPY** jako market-wide proxy

Wyliczane:
- `price_move_atr` = |today_close − prev_close| / ATR(14)
- `volume_ratio` = today_volume / 20d avg
- `gap_pct` = open_today vs close_yesterday

Cache per-tick (jeden cron = jeden Python process, cache resetuje się naturalnie).

---

## Risk management

### Limity twardych
- **Max pozycji defense+geo+twitter combined: 6** (shared cap z `docs/STRATEGY.md` §4.5)
- **Cap per pojedynczy post: 2** pozycje (Pattern B/C)
- **Per-ticker cap: 40% equity** (enforce via `concentration_ok` w monitorze)
- **Drawdown guard**: -12% daily P&L → HALT new entries
- **VIX guard**: > 60 → HALT
- **Dup-position guard**: jeśli mam już daną pozycję LONG/SHORT → SKIP zamiast podwajać

### Limity miękkie
- `MAX_POSTS_PER_RUN = 10` (anti-spam, większość runów < 10 candidates)
- `LOOKBACK_MINUTES = 30` (każdy post pobierany raz, dedup po `uri`)
- Earnings ±1d: NIE filtrujemy w twitter-monitor bo Pattern A może być
  ważnym sygnałem PRZED earnings (CEO pre-announcement); routine sama
  decyduje per kontekst

### Iron rule preservation
- Każde zlecenie **LIMIT** + bracket (entry + SL + TP)
- Stop-loss **MANDATORY** — żaden naked
- Tylko whitelist tickery (`docs/STRATEGY.md` §10)
- Paper account only

---

## Korelacja z innymi strategiami / monitorami

### Cross-monitor deduplication
Twitter post o RTX + defense-monitor wykrywa ten sam DoD contract w tej
samej godzinie → **dup-position guard** w defense-monitor pominie drugi
sygnał (RTX już otwarte przez routine). To zachowanie celowe: pierwszy
do strzału (zwykle Twitter ze względu na latencję) wygrywa.

### Pattern A + price-monitor overlap
@elonmusk wrzuca bullish TSLA tweet → twitter-monitor sygnalizuje BUY
TSLA $5k. Później price-monitor wykrywa breakout TSLA → drugi sygnał.
**dup-position guard** pomija drugi (TSLA już LONG). System nie podwaja.

### Geo-alert HIGH zamyka crypto LONG
Pattern B (eskalacja) → routine może sprawdzić open positions i zamknąć
crypto LONG przed otwarciem defense LONG (cross-strategy hedge,
dziedzictwo z `strategies/crypto-strategy.md`).

---

## Tickery (whitelist Twitter-driven)

Wszystkie z `.claude/rules/tickers-whitelist.md`. Powtórzone tu dla
przejrzystości:

- **Pattern A:** TSLA, AAPL, GOOGL, MSFT (CEOs na liście)
- **Pattern B:** RTX, LMT, NOC, GD, BA, ITA, XAR, DFEN, XLE, XOM, CVX, GLD
- **Pattern C:** SPY, QQQ + SELL na XLE, GLD
- **Pattern D:** SPY, QQQ, GLD + każdy ticker z whitelist wymieniony w treści
- **Pattern E:** mapowane do B/C/D

---

## Curated accounts

Pełna lista: `.claude/rules/twitter-accounts.md` (v1.0 ma 19 kont).

Kategorie:
- 5 × `gov_us` (POTUS, WhiteHouse, StateDept, SecDef, IDF)
- 7 × `macro` (zerohedge, business, CNBC, WSJ, FT, Reuters, AP)
- 4 × `ticker:*` (Musk/Cook/Pichai/Nadella)
- 4 × `gov_us` government feeds (CongressionalRpt, Treasury, SEC, Fed)
- (placeholder) influencerzy finansowi — empty for v1.0 by design

Wiele kont nie ma jeszcze Bluesky presence → monitor zaloguje "feed empty"
i pojedzie dalej bez błędu. X API upgrade ($100/mo) odblokuje pełną listę.

---

## Wzorce decyzyjne (przykłady z routine system prompt)

```
INPUT:  @realDonaldTrump.bsky / category=gov_us / kw=["sanctions","missile"]
        text="Hereby ordering full sanctions on Iran. Military will respond"
SCORING: cred=45 (tweet_verified_pol) + shift=50 (policy) + react=SPY-based
PATTERN: B (GEO_ESCALATION)
ACTION:  BUY RTX $8,000 + BUY XLE $6,000 (cap=2 per post)
```

```
INPUT:  @elonmusk.bsky / category=ticker:TSLA / kw=["<ticker-ceo>"]
        text="Cybertruck production hitting record highs"
SCORING: cred=50 (tweet_verified_corp) + shift=50 + react=TSLA-based
PATTERN: A (TICKER_DIRECT, bullish)
ACTION:  BUY TSLA $5,000
```

```
INPUT:  @reuters.bsky / category=wire / kw=["breaking","confirmed"]
        text="BREAKING: Confirmed ceasefire signed in Middle East"
SCORING: cred=70 (reuters_ap) + shift=50 + react=violent SPY = high
PATTERN: C (GEO_DEESCALATION)
ACTION:  BUY SPY $6,000 + SELL XLE $6,000
```

```
INPUT:  @business.bsky / category=macro / kw=["cpi","inflation"]
        text="CPI 0.3% MoM, below expectations of 0.4%"
SCORING: cred=60 + shift=50 + react=SPY-based
PATTERN: D (MACRO_DATA, dovish surprise)
ACTION:  BUY SPY $6,000  (lower CPI = rate cut bias = risk-on)
```

```
INPUT:  rumor source / category=gov_us / kw=["military","strike"]
        + ATR move 3.0× + volume 4× (juz wybicie)
SCORING: cred=25 + shift=25 + react=85
RESULT:  CONTRARIAN_CANDIDATE → email-only flag, NIE trafia do routine.
         User decyduje manualnie (zwykle: nie ufać i albo skip albo trade kontra).
```

---

## Historia i wyniki

| Data | Pattern | Source | Ticker(s) | Entry | Exit | P&L% | Notatka |
|------|---------|--------|-----------|-------|------|------|---------|
| 2026-05-07 | — | smoke test | — | — | — | — | Bluesky login OK, 19 kont załadowanych, 0 candidates (no recent keyword match) |
| —    | —       | —      | —         | —     | —    | —    | v1.0 LIVE 2026-05-07 |

---

## Próg ostrożności w pierwszych 7 dniach (zalecenie)

System ma agresywny risk budget v2.0. Twitter jest najnowszy + najgłośniejszy.
Sugerowane manualne audyty w pierwszym tygodniu:

1. Codzienny przegląd `[BUY] [twitter-news] ...` maili — czy klasyfikacja
   pattern A/B/C/D/E była sensowna?
2. Jeśli routine wystawia trade który Ty byś odrzucił → poszerzyć keyword
   filter w `.claude/rules/twitter-accounts.md` (zaostrzyć), albo zaostrzyć
   credibility threshold w event_scoring (np. wymagać shift ≥ 45 dla
   `tweet_verified_pol`)
3. Po 7 dniach: ocenić ROI per pattern (TICKER_DIRECT zwykle najlepszy ROI;
   GEO_ESCALATION ma duży tail risk; MACRO_DATA wymaga rygorystycznego
   keyword set)

Po stabilizacji: rozważyć upgrade do X API v2 Basic ($100/mo) dla pełnej
listy kont (większość polityków/CEO nie ma jeszcze Bluesky).
