# Twitter / Bluesky — curated source accounts (4-tier system)

**Wersja:** 2.0 (2026-05-07 — 4-tier rozszerzenie: Trump admin + conflict leaders + tech/defense CEOs + tracked anon traders)
**Monitor:** `twitter-monitor` (Bluesky day-1; X API v2 Basic future upgrade)
**Strategia:** `strategies/twitter-news.md`
**Source-of-truth:** `docs/STRATEGY.md` §4.8

Format: `<bluesky_handle> | <twitter_handle (legacy)> | <category>`

Kategorie odzwierciedlają tier:

| Kategoria w pliku | Tier | Source-type → cred | Bypass keyword | Bypass FOLLOW-only |
|---|---|---|---|---|
| `high_priority_pol` | T1 / T1.5 | `official_government` (80) | ✅ | ✅ — IGNORE/WAIT też idą do routine |
| `high_priority_corp` | T2.5 | `tracked_corp_ceo` (75) | ✅ | ✅ |
| `ticker:SYM` | T2 | `tracked_corp_ceo` (75) | ✅ | ✅ |
| `tracked_anon_trader` | T3 | `tracked_anon_trader` (55) | ✅ | ✅ |
| `gov_us` | normal | `tweet_verified_pol` (45) | ❌ | ❌ |
| `macro` | normal | `major_outlet` (60) | ❌ | ❌ |
| `wire` | normal | `reuters_ap` (70) | ❌ | ❌ |
| `mil_il` | normal | `tweet_verified_pol` (45) | ❌ | ❌ |

---

## TIER 1 — Trump administration (high_priority_pol)

Always-candidates. Każdy post idzie na email + do routine niezależnie od scoringu. Administracja role-based — handle przypisany do roli, automatycznie aktualizuje się przy zmianie kadry.

```
@realdonaldtrump.bsky.social   | @realDonaldTrump      | high_priority_pol
@potus.bsky.social             | @POTUS                | high_priority_pol
@whitehouse.bsky.social        | @WhiteHouse           | high_priority_pol
@vp.bsky.social                | @VP                   | high_priority_pol
@secstate.bsky.social          | @SecState             | high_priority_pol
@secdef.bsky.social            | @SecDef               | high_priority_pol
@ustreasury.bsky.social        | @USTreasury           | high_priority_pol
@statedept.bsky.social         | @StateDept            | high_priority_pol
@presssec.bsky.social          | @PressSec             | high_priority_pol
@whcos.bsky.social             | @WHCOS                | high_priority_pol
@secgov.bsky.social            | @SECgov               | high_priority_pol
@federalreserve.bsky.social    | @federalreserve       | high_priority_pol
@congressionalrpt.bsky.social  | @CongressionalRpt     | high_priority_pol
```

---

## TIER 1.5 — Conflict leaders (high_priority_pol)

Przywódcy + ministerstwa zaangażowane w aktywne konflikty (Iran, Israel, Russia, Ukraine) + NATO/China dla kontekstu. Definicja "konflikt": eskalacja zbrojna albo sankcje w toku w ciągu ostatnich 12 miesięcy.

### Israel
```
@israelipm.bsky.social         | @IsraeliPM            | high_priority_pol
@idfdaily.bsky.social          | @IDF                  | high_priority_pol
@israelmfa.bsky.social         | @IsraelMFA            | high_priority_pol
@israelipresident.bsky.social  | @IsraeliPresident     | high_priority_pol
```

### Iran
```
@khamenei.bsky.social          | @khamenei_ir          | high_priority_pol
@iran-gov.bsky.social          | @Iran_GOV             | high_priority_pol
@irgc.bsky.social              | @IRGCofficial         | high_priority_pol
@iranforeignmin.bsky.social    | @IRIMFA_EN            | high_priority_pol
```

### Russia
```
@kremlin-eng.bsky.social       | @KremlinRussia_E      | high_priority_pol
@mfarussia.bsky.social         | @MFA_Russia           | high_priority_pol
@russiaun.bsky.social          | @RussiaUN             | high_priority_pol
```

### Ukraine
```
@zelenskyyua.bsky.social       | @ZelenskyyUa          | high_priority_pol
@defenceu.bsky.social          | @DefenceU             | high_priority_pol
@mfa-ukraine.bsky.social       | @MFA_Ukraine          | high_priority_pol
```

### NATO + Multilateral
```
@nato.bsky.social              | @NATO                 | high_priority_pol
@secgennato.bsky.social        | @SecGenNATO           | high_priority_pol
@un.bsky.social                | @UN                   | high_priority_pol
```

### China (selectively — tylko official government channels)
```
@mfachina.bsky.social          | @MFA_China            | high_priority_pol
@chinamissionun.bsky.social    | @Chinamission2un      | high_priority_pol
```

### Korea (latent)
```
@nkfreedom.bsky.social         | @NKFreedom            | high_priority_pol
```

---

## TIER 2 — Tech CEOs (ticker:SYM, source_type tracked_corp_ceo)

Każde konto CEO związane bezpośrednio z tickerem na whitelist. Bypass keyword (ich tweety mają zwykle niski volume więc większość warta uwagi). Pattern A (TICKER_DIRECT) z `strategies/twitter-news.md`.

```
@elonmusk.bsky.social          | @elonmusk             | ticker:TSLA
@tim_cook.bsky.social          | @tim_cook             | ticker:AAPL
@sundarpichai.bsky.social      | @sundarpichai         | ticker:GOOGL
@satyanadella.bsky.social      | @satyanadella         | ticker:MSFT
@ajassy.bsky.social            | @ajassy               | ticker:AMZN
@finkd.bsky.social             | @finkd                | ticker:META
@jensenhuang.bsky.social       | @JensenHuang          | ticker:NVDA
@brian-armstrong.bsky.social   | @brian_armstrong      | ticker:COIN
@saylor.bsky.social            | @saylor               | ticker:MSTR
@reneharas.bsky.social         | @ReneHaas             | ticker:ARM
@charlesliang.bsky.social      | @CharlesLiang         | ticker:SMCI
```

(Większość CEO nie ma jeszcze Bluesky presence — monitor zaloguje "feed empty" i pojedzie. Po upgrade do X API odblokuje pełną listę.)

---

## TIER 2.5 — Defense corporate accounts (high_priority_corp)

Big-5 + mid-cap defense — corporate handles (CEO osobnych kont nie prowadzi). Bypass keyword. Source_type `tracked_corp_ceo` (cred 75).

### Big-5
```
@lockheedmartin.bsky.social    | @LockheedMartin       | high_priority_corp
@raytheontech.bsky.social      | @RaytheonTech         | high_priority_corp
@northropgrumman.bsky.social   | @Northropgrumman      | high_priority_corp
@generaldynamics.bsky.social   | @GeneralDynamics      | high_priority_corp
@boeing.bsky.social            | @Boeing               | high_priority_corp
```

### Mid-cap
```
@kratos.bsky.social            | @Kratos_Defense       | high_priority_corp
@palantirtech.bsky.social      | @PalantirTech         | high_priority_corp
@axon-us.bsky.social           | @Axon_US              | high_priority_corp
@leidosinc.bsky.social         | @LeidosInc            | high_priority_corp
@saicinc.bsky.social           | @SAICinc              | high_priority_corp
@caciintl.bsky.social          | @CACIIntl             | high_priority_corp
```

### European ADR
```
@baesystemsplc.bsky.social     | @BAESystemsplc        | high_priority_corp
@airbus.bsky.social            | @Airbus               | high_priority_corp
```

---

## TIER 3 — Tracked anon traders / influencers (tracked_anon_trader)

Anonimowe konta z udokumentowanym track record (analogicznie do Reddit: nie credibility-by-default, ale wybrane manualnie po obserwacji jakości calls).

**Kryteria dodania konta:**
- Min. 6 miesięcy historii widocznej publicznie
- Co najmniej 5 konkretnych calls (entry + exit + ticker), nie tylko kilkudniowe spekulacje
- Win rate > 50% na publicznych calls
- Brak shilling kupowanych pakietów / kursów
- Brak rage-baiting / wojen z innymi traderami

```
@aleabitoreddit.bsky.social    | @aleabitoreddit       | tracked_anon_trader
@unusualwhales.bsky.social     | @unusual_whales       | tracked_anon_trader
@zerohedge.bsky.social         | @zerohedge            | tracked_anon_trader
```

(Lista celowo krótka. Dodaje user osobiście po obserwacji; nie indiscriminate following.)

---

## Standard tiers (bez override) — pozostają z v1.0

### Markets / macro (`macro`)
```
@business.bsky.social          | @business             | macro
@cnbc.bsky.social              | @CNBC                 | macro
@wsjmarkets.bsky.social        | @WSJmarkets           | macro
@ft.bsky.social                | @FT                   | macro
@marketwatch.bsky.social       | @MarketWatch          | macro
```

### Wire services (`wire`)
```
@reuters.bsky.social           | @Reuters              | wire
@ap.bsky.social                | @AP                   | wire
@bloomberg.bsky.social         | @business             | wire
```

---

## Keyword filter (per-category) — bez zmian dla standard tiers

```
gov_us:
    sanctions, executive order, military, troops, missile, strike,
    ceasefire, treaty, tariff, sanction lifted, deployment, congress
mil_il / mil_*:
    operation, strike, intercept, casualties, hostage, hostile, rocket
macro:
    rate, inflation, cpi, ppi, fomc, fed, recession, gdp, jobless,
    earnings beat, earnings miss, guidance cut, guidance raised
wire:
    breaking, exclusive, just in, confirmed
```

**High-priority (T1, T1.5, T2, T2.5, T3) — keyword filter pomijany.**

---

## Adding a new account

1. Wybierz tier wg charakteru konta — high-priority TYLKO jeśli realnie chcesz każdy post na email
2. Append do właściwej sekcji
3. (Opcjonalne) Dodaj Twitter equivalent
4. Update `strategies/twitter-news.md` + `docs/STRATEGY.md` jeśli dodajesz nowy ticker / kraj
5. Commit + push; następny cron pobiera

---

## Realność Bluesky vs X API

Stan na 2026-05-07: **wiele kont z list T1 / T1.5 / T2 / T2.5 NIE MA jeszcze Bluesky presence**. Monitor zaloguje "feed empty" dla braku konta i pojedzie dalej bez błędu — to OK. Po upgrade do X API v2 Basic ($100/mo, future) automatycznie odblokuje się reszta. SocialClient interface w `twitter-monitor/monitor.py` jest tak skonstruowany że swap = jeden config flip.

Aktualnie aktywne na Bluesky (potwierdzone): głównie T3 anon-traders + niektóre macro outlets. Tier 1/1.5 polityczny ma niską migrację.
