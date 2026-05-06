# Sesja 5 maja 2026 — PEŁNA DOKUMENTACJA

## Status końcowy
**5 z 6 systemów aktywnych i działających ✅**  
**1 system czeka na Reddit API ⏳**

---

## KONTA I PLATFORMY — DOKŁADNE DANE

### Alpaca Paper Trading
- **URL:** https://app.alpaca.markets/paper/dashboard/overview
- **Typ konta:** Paper trading (symulacja)
- **Equity:** ~$100,009 (stan na 05.05.2026)
- **Serwer MCP:** `alpaca-mcp-server` na Render.com (Oregon region)
- **Klucze API:** Dwa zestawy:
  1. **GitHub Actions** (zmienne środowiskowe): `ALPACA_API_KEY` + `ALPACA_SECRET_KEY`
  2. **Render MCP Server** (env vars w serwisie): `APCA_API_KEY_ID` + `APCA_API_SECRET_KEY`
  - ⚠️ WAŻNE: Oba zestawy muszą zawierać te same klucze z Alpaca paper account
  - Klucze zaktualizowane w tej sesji po błędzie 401

### Render.com
- **URL:** https://dashboard.render.com
- **Projekt:** "My project"
- **Środowisko:** "Production"
- **Serwis:** `alpaca-mcp-server` (status: Deployed, Oregon, Image runtime, ostatni deploy 10d temu)
- **Zmienne env do zaktualizowania gdy klucze Alpaca się zmienią:**
  - `APCA_API_KEY_ID` → Alpaca API Key ID
  - `APCA_API_SECRET_KEY` → Alpaca Secret Key

### GitHub
- **Repo:** `mikosbartlomiej/trading-system` (nazwa lokalna: `trading-system`)
- **Ścieżka lokalna:** `/Users/bartlomiejmikos/Documents/Git/trading-system`
- **Gałąź główna:** `main`

#### GitHub Secrets (WSZYSTKIE)
| Nazwa sekretu | Zawartość | Używany przez |
|---------------|-----------|--------------|
| `FINNHUB_API_KEY` | Klucz Finnhub API | price-monitor, geo-monitor |
| `NEWSAPI_KEY` | Klucz NewsAPI.org | geo-monitor |
| `CLOUDFLARE_WORKER_URL` | `https://tradingview-proxy.mikosbartlomiej.workers.dev` | price-monitor |
| `CLOUDFLARE_GEO_WORKER_URL` | `https://geopolitical-proxy.mikosbartlomiej.workers.dev` | geo-monitor |
| `CLOUDFLARE_EXIT_WORKER_URL` | `https://exit-monitor-proxy.mikosbartlomiej.workers.dev` | exit-monitor |
| `CLOUDFLARE_CRYPTO_WORKER_URL` | `https://crypto-proxy.mikosbartlomiej.workers.dev` | crypto-monitor |
| `CLOUDFLARE_LEARNING_WORKER_URL` | `https://learning-loop-proxy.mikosbartlomiej.workers.dev` | weekly-learning |
| `CLOUDFLARE_REDDIT_WORKER_URL` | `https://reddit-proxy.mikosbartlomiej.workers.dev` | reddit-monitor ⏳ |
| `ALPACA_API_KEY` | Alpaca paper API Key ID | exit-monitor, crypto-monitor, learning-loop |
| `ALPACA_SECRET_KEY` | Alpaca paper Secret Key | exit-monitor, crypto-monitor, learning-loop |
| `REDDIT_CLIENT_ID` | Reddit app client_id ⏳ | reddit-monitor |
| `REDDIT_CLIENT_SECRET` | Reddit app client_secret ⏳ | reddit-monitor |

### Cloudflare Workers
- **Account:** mikosbartlomiej
- **Dashboard:** https://dash.cloudflare.com

| Worker | URL | ROUTINE_ENDPOINT (trig_...) | Status |
|--------|-----|----------------------------|--------|
| `tradingview-proxy` | https://tradingview-proxy.mikosbartlomiej.workers.dev | (z poprzedniej sesji) | ✅ |
| `geopolitical-proxy` | https://geopolitical-proxy.mikosbartlomiej.workers.dev | (z poprzedniej sesji) | ✅ |
| `exit-monitor-proxy` | https://exit-monitor-proxy.mikosbartlomiej.workers.dev | trig_01QL21osTHsnNvpyawXCdkiQ | ✅ |
| `crypto-proxy` | https://crypto-proxy.mikosbartlomiej.workers.dev | trig_01Y1QB5MCF1jtrGS51QixSrR | ✅ |
| `learning-loop-proxy` | https://learning-loop-proxy.mikosbartlomiej.workers.dev | trig_0175V2oDoLMn9y75HoDx8NGd | ✅ |
| `reddit-proxy` | https://reddit-proxy.mikosbartlomiej.workers.dev | (do ustawienia po Reddit API) | ⏳ |

#### WAŻNE: Kod każdego Cloudflare Worker (aktualny, z wszystkimi nagłówkami)
```javascript
export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }
    const body = await request.json();
    const routinePayload = {
      text: JSON.stringify(body)
    };
    const response = await fetch(env.ROUTINE_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type":      "application/json",
        "Authorization":     `Bearer ${env.ANTHROPIC_TOKEN}`,
        "anthropic-version": "2023-06-01",
        "anthropic-beta":    "experimental-cc-routine-2026-04-01",
      },
      body: JSON.stringify(routinePayload),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  },
};
```

**Sekrety w każdym workerze:**
- `ROUTINE_ENDPOINT` — URL routiny (trig_... z tabeli powyżej)
- `ANTHROPIC_TOKEN` — token z sekcji "Call via API" danej routiny w claude.ai

### Claude Routines
- **URL:** claude.ai → Routines (lub claude.ai/code/routines)
- **Trigger format:** Call via API
- **Payload format do triggerowania:** `{"text": "{JSON jako string}"}`
- **Wymagane nagłówki:**
  - `Authorization: Bearer {ANTHROPIC_TOKEN}`
  - `anthropic-version: 2023-06-01`
  - `anthropic-beta: experimental-cc-routine-2026-04-01`

| Routina | Trigger URL (trig_...) | Connector | Status |
|---------|----------------------|-----------|--------|
| Morning Portfolio Brief | (z poprzedniej sesji) | Alpaca MCP | ✅ |
| Alert Handler | (z poprzedniej sesji) | Alpaca MCP | ✅ (zaktualizowany o long+short) |
| Geopolitical Alert Handler | (z poprzedniej sesji) | Alpaca MCP | ✅ |
| Exit Monitor Handler | trig_01QL21osTHsnNvpyawXCdkiQ | Alpaca MCP | ✅ przetestowany |
| Crypto Handler | trig_01Y1QB5MCF1jtrGS51QixSrR | Alpaca MCP | ✅ |
| Weekly Strategy Updater | trig_0175V2oDoLMn9y75HoDx8NGd | brak (tylko repo) | ✅ |
| Reddit Sentiment Handler | (do utworzenia) | Alpaca MCP | ⏳ |

---

## GITHUB ACTIONS WORKFLOWS — 6 PLIKÓW

### Lokalizacja w repo
```
.github/workflows/
├── price-monitor.yml     # co 5 min, 9:30-16:00 ET (pon-pt)
├── geo-monitor.yml       # co 15 min, 9:00-17:00 ET (pon-pt)
├── reddit-monitor.yml    # co 6h: 7,13,16,20 UTC (pon-pt) ⏳
├── crypto-monitor.yml    # co 30 min, 24/7
├── exit-monitor.yml      # co 1h: 12:30-21:30 UTC + noc dla crypto
└── weekly-learning.yml   # niedziela 20:00 UTC
```

### Harmonogram
| Workflow | Cron | Godziny aktywności |
|----------|------|-------------------|
| price-monitor | `*/5 13-20 * * 1-5` | 9:00-16:00 ET, pon-pt |
| geo-monitor | `*/15 13-21 * * 1-5` | 9:00-17:00 ET, pon-pt |
| reddit-monitor | `0 7,13,16,20 * * 1-5` | 4x dziennie, pon-pt |
| crypto-monitor | `0 * * * *` + `30 * * * *` | 24/7 |
| exit-monitor | `30 12-21 * * 1-5` + `0 22,0,2 * * *` | market hours + noc |
| weekly-learning | `0 20 * * 0` | niedziela 16:00 ET |

---

## PLIKI SKRYPTÓW PYTHON

### Struktura repo
```
trading-system/
├── price-monitor/
│   ├── monitor.py          # LONG + SHORT + LEVERAGED signals
│   └── requirements.txt    # requests, schedule, pytz
├── geo-monitor/
│   ├── monitor.py
│   └── requirements.txt    # requests, feedparser
├── reddit-monitor/
│   ├── monitor.py          # ⏳ czeka na API
│   └── requirements.txt    # requests
├── crypto-monitor/
│   ├── monitor.py          # BTC/USD + ETH/USD, Alpaca Market Data
│   └── requirements.txt    # requests
├── exit-monitor/
│   ├── monitor.py          # Alpaca REST bezpośrednio (nie MCP)
│   └── requirements.txt    # requests
├── learning-loop/
│   ├── analyzer.py         # analiza tygodniowych tradów
│   └── requirements.txt    # requests
└── strategies/
    ├── aggressive-momentum.md
    ├── leveraged-etf.md
    ├── options-strategy.md
    ├── crypto-strategy.md
    ├── geopolitical.md
    └── reddit-sentiment.md
```

### Kluczowe parametry skryptów

**price-monitor/monitor.py:**
- LONG tickery: AAPL, MSFT, GOOGL, NVDA, SPY, META, AMZN
- SHORT tickery: AAPL, MSFT, GOOGL, NVDA, META, TSLA, AMZN
- LEVERAGED: TQQQ, SQQQ, SPXL, SPXS, UPRO
- LONG signal: RSI 50-70 + cena > 20d high + vol > 1.5x avg
- SHORT signal: RSI > 72 + near resistance + vol fade + bearish candle (3/4 warunki)
- Sizes: long=$600, short=$400, leveraged=$300
- Finnhub API endpoint: `/stock/candle`, resolution=D

**crypto-monitor/monitor.py:**
- Symbole: BTC/USD, ETH/USD (ze ukośnikiem — wymagane przez Alpaca API)
- API: `https://data.alpaca.markets/v1beta3/crypto/us/bars`
- Timeframe: `1Hour` (nie `1H` — to powoduje 400)
- Start: 5 dni temu (wymagane, domyślnie API daje tylko ~17 świec)
- LONG signal: cena > 20h high + vol > 2x avg + RSI 45-68
- SHORT signal: cena < 20h low + vol > 1.5x avg + RSI < 35
- Sizes: long=$250 (weekday)/$125 (weekend), short=$200/$100

**exit-monitor/monitor.py:**
- API: `https://paper-api.alpaca.markets` bezpośrednio
- Auth headers: `APCA-API-KEY-ID` + `APCA-API-SECRET-KEY` (z GitHub Secrets ALPACA_API_KEY/SECRET_KEY)
- Endpointy: `/v2/positions`, `/v2/account`, `/v2/orders`
- Klasyfikacje: HOLD / CLOSE_EMERGENCY / CLOSE_DECAY / CLOSE_FLAT / CONSIDER_TP
- Progi: emergency=-5%, quick_profit=3%, flat=1%, time_decay=6h

---

## STRATEGIE INWESTYCYJNE

| Plik | Instrumenty | Size USD | SL | TP | Max pozycje |
|------|-------------|----------|----|----|-------------|
| aggressive-momentum.md | akcje long/short | 600/400 | -1.5×ATR | +2.5×ATR | 3L+2S |
| leveraged-etf.md | TQQQ/SQQQ/SPXL/SPXS | 300 | -4% | +8% | 2 |
| options-strategy.md | calls/puts, ATM 14-21 DTE | 150/kontrakt | -50% premii | +80% premii | 2 |
| crypto-strategy.md | BTC/USD, ETH/USD | 250/200 | -4%/+4% | +8%/-8% | 1+1 |
| geopolitical.md | XLE/XOM/GLD/RTX/LMT | 300 | -2.5% | +4% | 2 |
| reddit-sentiment.md | whitelist 21 tickerów | 200 | -3% | +5% | 1 |

---

## TESTY PRZEPROWADZONE W TEJ SESJI

| System | Test | Wynik | Notatka |
|--------|------|-------|---------|
| exit-monitor | GitHub Actions run | ✅ | Wykrył XOM CLOSE_FLAT po 22h |
| exit-monitor → Cloudflare Worker | HTTP | ✅ 200 | Po dodaniu nagłówków beta |
| exit-monitor → Claude Routine | Payload | ✅ | Po zmianie format na `{"text": "..."}` |
| Alpaca MCP w routine | get_account_info | ✅ | Po aktualizacji kluczy w Render |
| crypto-monitor | GitHub Actions run | ✅ | BTC/USD RSI=64.1, ETH/USD RSI=63.5 |
| crypto-monitor API | Alpaca data | ✅ | Po dodaniu start=5d, format BTC/USD |

### Błędy napotkane i rozwiązania

| Błąd | Przyczyna | Rozwiązanie |
|------|-----------|-------------|
| Cloudflare Worker → Routine: HTTP 404 | Brak nagłówków `anthropic-version` i `anthropic-beta` | Dodano do kodu wszystkich Workers |
| Routine nie otrzymywała payloadu | Worker wysyłał raw JSON, routine oczekuje `{"text": "..."}` | Zmieniono format w Worker |
| Alpaca MCP 401 w routine | Stare/złe klucze w Render MCP server | Zaktualizowano env vars w Render |
| crypto-monitor 400 Bad Request | Timeframe `1H` zamiast `1Hour`, brak parametru `start` | Poprawiono oba parametry |
| crypto-monitor "za mało świec" | API domyślnie zwraca ~17h danych | Dodano `start=5 dni temu` |
| exit-monitor TypeError sorted() | `filled_at` może być `None` | Zmieniono `o.get("filled_at", "")` na `o.get("filled_at") or ""` |
| f-string ValueError | `{rsi:.1f if rsi else 'N/A'}` jest niepoprawne | Zmieniono na `{f'{rsi:.1f}' if rsi else 'N/A'}` |

---

## OTWARTE POZYCJE (stan na 05.05.2026 ~16:37 UTC)

| Symbol | Strona | Qty | Entry | Cena bieżąca | P&L | Hold | Status |
|--------|--------|-----|-------|-------------|-----|------|--------|
| XLE | long | 10 | $58.95 | $59.62 | +$6.74 (+1.14%) | 3.1h | HOLD |
| XOM | long | 3 | $153.90 | $154.81 | +$2.72 (+0.59%) | 22.1h | CLOSE_FLAT (routine próbuje zamknąć) |

---

## KOLEJNE KROKI

| Krok | Zadanie | Priorytet |
|------|---------|-----------|
| 33 | Obserwacja paper tradingu, pierwsze realne trady po aktywacji | ⏳ W toku |
| 34 | Aktywacja Reddit Monitor po zatwierdzeniu API | ⏳ Czeka na email |
| 35 | Sprawdzenie Weekly Learning Loop (niedziela 20:00 UTC) | ⏳ |
| 36 | Email powiadomienia o tradach | ⏳ |
| 37 | Opcje trading — aktywacja (Alpaca obsługuje opcje) | ⏳ |
| 38 | Przejście na live (po 4 tygodniach paper tradingu) | ⏳ Daleka przyszłość |

---

## RESUME POINT — REDDIT MONITOR

**Plik:** `RESUME-REDDIT.md` w folderze investing/  
**Gdy przyjdzie email od Reddit:**
1. reddit.com/prefs/apps → create app → typ: script → `trading-monitor` → `http://localhost:8080`
2. Utwórz `reddit-proxy` Worker w Cloudflare (kod jak wyżej)
3. Utwórz routine "Reddit Sentiment Handler" (API trigger, Alpaca MCP)
4. Dodaj GitHub Secrets: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, CLOUDFLARE_REDDIT_WORKER_URL
5. Push .github/workflows/reddit-monitor.yml do repo
6. Test manualny

---

## SZYBKIE KOMENDY

```bash
# Push zmian
cd /Users/bartlomiejmikos/Documents/Git/trading-system
git add -A && git commit -m "opis" && git push

# Test exit monitora manualnie
# GitHub → Actions → Exit Monitor → Run workflow

# Test curl na worker (sprawdź czy działa)
curl -s -X POST "https://exit-monitor-proxy.mikosbartlomiej.workers.dev" \
  -H "Content-Type: application/json" \
  -d '{"test": true}' -w "\nHTTP: %{http_code}"

# Sprawdź otwarte pozycje Alpaca (zastąp klucze)
curl -s "https://paper-api.alpaca.markets/v2/positions" \
  -H "APCA-API-KEY-ID: TWOJ_KEY" \
  -H "APCA-API-SECRET-KEY: TWOJ_SECRET"
```

---

*Dokument wygenerowany 05.05.2026. Następna sesja: obserwacja pierwszych autonomicznych tradów.*
