# Reddit — curated tracked users (track-record whitelist)

**Wersja:** 1.0 (2026-05-09)
**Monitor:** `reddit-monitor` (per-user submissions lane)
**Pair:** `.claude/rules/reddit-subs.md` (per-sub lane)

Lista użytkowników o **udokumentowanym track record** na publicznych
forach inwestycyjnych. Ich posty są skanowane indywidualnie
(`/user/<name>/submitted.json`) z **wyższą credibility** niż random
post na subie i **niższym progiem spike'u** (1 post tracked usera =
candidate signal, nie wymaga spike × 3).

## Kryteria dodania konta

Wszystkie muszą być spełnione:
- Min. 12 miesięcy publicznej historii postów
- Co najmniej **5 konkretnych calls** (entry + exit + ticker + thesis)
- **Win rate > 55%** na publicznych calls (audytowanych przez społeczność)
- Brak shilling kupowanych pakietów / kursów
- Brak rage-baiting / wojen z innymi traderami
- Brak pump-and-dump patterns na shitcoinach
- Konto **nie było banowane** za manipulację

Lista celowo krótka. Operator dodaje **osobiście** po obserwacji jakości
calls — nie indiscriminate following.

---

## Format whitelisty

Każdy wiersz: `<username> | <category> | <min_post_ups> | <weight>`

- **category** określa `source_type` w event_scoring:
  - `tracked_dd`         → 65  (high-quality DD writers, audited track record)
  - `tracked_options`    → 60  (options-specific edge, decent record)
  - `tracked_macro`      → 60  (macro/fundamentals analysts)
- **min_post_ups** — minimalna liczba upvotes żeby post wszedł w pipeline
  (filtrujemy stare niepopularne posty z ich historii)
- **weight** (1.0-2.5) — multiplier na sizing dla tego usera. Wyższy
  weight = lepszy track record = większy size.

Wartości `weight` dobiera operator manualnie podczas dodawania (po
review historii calls).

```
# Lista pusta — wszyscy seed userzy (DFV, 1RONYMAN, PlotinusEnjoyer,
# LavenderAutist, ChubbyBunnyy) okazali się martwi/nieaktywni przy
# pierwszym biegu prod (2026-05-09 12:14 UTC log):
#   - DFV:  10 postów = wszystkie linki/picture (porzucił DD-pisanie ~2021)
#   - 1RONYMAN: 0 postów (konto suspended/deleted)
#   - PlotinusEnjoyer: 3 posty wszystkie sprzed ~2.7 lat
#   - LavenderAutist: HTTP 403 (konto deleted/banned/private)
#   - ChubbyBunnyy: 2 posty = linki (not_self_text)
# Operator dodaje aktywnych userów manualnie wg kryteriów wyżej.
# Format wiersza: <username> | <category> | <min_post_ups> | <weight>
```

## Audit log — usunięci 2026-05-09

| User | Powód |
|---|---|
| DeepFuckingValue | 10 postów = same linki/picture; nie pisze już DDs |
| 1RONYMAN | 0 postów — konto suspended/deleted |
| PlotinusEnjoyer | Posty sprzed ~2.7 lat — konto martwe |
| LavenderAutist | HTTP 403 — konto deleted/banned |
| ChubbyBunnyy | Posty = same linki (not_self_text) |

---

## Endpoint format

Per-user submissions:
```
https://www.reddit.com/user/<username>/submitted.json?limit=10&sort=new
```

User comments (opcjonalne, na razie nieużywane w MVP):
```
https://www.reddit.com/user/<username>/comments.json?limit=10
```

Ten sam User-Agent + ToS guard (poll co ≥ 60 min) co per-sub lane.

---

## Scoring vs per-sub lane

| Źródło             | source_type           | cred | spike threshold |
|---|---|---|---|
| Random post na WSB | tracked_anon_trader   | 55   | 3× rolling 7d   |
| Quality sub        | major_outlet          | 60   | 3× rolling 7d   |
| **Tracked user**   | **tracked_dd / opts** | **65/60** | **lowered (no spike needed)** |

Dla tracked usera: wystarczy 1 post w ostatnich 24h spełniający warunki:
- `ups >= min_post_ups` (per-user config)
- ticker na whitelist
- sentiment skew |≥ 0.3|
- post type = self-text DD (nie link, nie meme)

Nawet bez spike'u, single post tracked usera może wygenerować signal
(ich edge jest "stand-alone").

## Rate-limit + cap

- Max 1 alert per run **per source lane** (sub vs user) — czyli ≤ 2
  alertów per cron run jeśli oba lanes coś znajdą jednocześnie
- Tracked-user lane ma priorytet (wyższa credibility)

---

## Adding a new user

1. Audytuj historię publicznych calls (last 12 months, ≥ 5 call DDs)
2. Policz win rate ręcznie: ile calls zamknęło się in-the-money vs out
3. Jeśli WR > 55%, dodaj wiersz w sekcji whitelisty wyżej
4. Ustaw weight 1.0 dla nowych userów; podnieś po 3 miesiącach
   obserwacji jeśli jakość się utrzymuje
5. Commit + push; następny cron pobiera

## Removing a user

Powody:
- 3+ losing calls z rzędu (cold streak)
- Zmiana stylu (z DD na shitcoin shilling)
- Konto zbanowane / usunięte
- Track record falsified (społeczność zdemaskowała backdated edits)

Zmiana → przenieś wiersz do sekcji "Removed users" poniżej z datą
i powodem (audit trail).

---

## Removed users (audit log)

(empty — first iteration)
