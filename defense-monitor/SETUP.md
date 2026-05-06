# Defense Market Monitor — Setup Instructions

## Krok 1: NewsAPI Key (opcjonalny, ale zalecany)

1. Wejdź na https://newsapi.org/ → zarejestruj się (plan darmowy: 100 req/dzień)
2. Skopiuj API key

## Krok 2: Cloudflare Worker — `defense-proxy`

1. Wejdź na https://dash.cloudflare.com → Workers & Pages → Create
2. Nazwa: `defense-proxy`
3. Wklej kod:

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

4. Deploy → skopiuj URL workera (np. `https://defense-proxy.xxx.workers.dev`)
5. W Settings → Variables → dodaj:
   - `ROUTINE_ENDPOINT` = (URL Routiny z Kroku 3)
   - `ANTHROPIC_TOKEN`  = (Twój Anthropic API key)

## Krok 3: Claude Routine — `Defense Market Handler`

1. Wejdź na https://claude.ai/routines → New Routine
2. Nazwa: `Defense Market Handler`
3. Opis: "Handles defense market signals — buys/shorts defense stocks based on news scoring"
4. Connectors: dodaj **Alpaca** (paper trading)
5. Prompt routiny:

```
You are a defense market trading agent. You receive a JSON signal from the defense monitor.

The signal contains:
- symbol: ticker to trade (LMT, RTX, NOC, GD, BA, KTOS, PLTR, AXON, LDOS, SAIC, CACI, ITA, XAR, DFEN, BAESY, EADSY)
- action: BUY or SELL_SHORT
- strategy: defense-long or defense-short
- size_usd: dollar amount to invest
- sl_pct: stop loss percent (e.g. 0.03 = 3%)
- tp_pct: take profit percent (e.g. 0.06 = 6%)
- score: number of matching keywords (quality signal)
- keywords: list of matched keywords
- source: news source
- headline: news headline

Your job:
1. Parse the incoming JSON from {{text}}
2. Get current account info — check if daily loss > -4% (skip if so)
3. Count open defense positions (strategy contains "defense") — skip if >= 4
4. Get current price for the symbol
5. Calculate:
   - For BUY: stop_loss = price * (1 - sl_pct), take_profit = price * (1 + tp_pct)
   - For SELL_SHORT: stop_loss = price * (1 + sl_pct), take_profit = price * (1 - tp_pct)
   - qty = floor(size_usd / price)
6. Place a LIMIT order at current market price (use latest ask for BUY, latest bid for SELL_SHORT)
7. Log: "DEFENSE [action] [symbol] qty=[qty] price=[price] sl=[stop_loss] tp=[take_profit] | [headline]"

If score < 2 or qty < 1, skip and log reason.
Do not trade BAESY or EADSY as SELL_SHORT.
Do not trade ITA, XAR, DFEN as SELL_SHORT.
```

6. Zapisz rutynę → skopiuj endpoint URL (z sekcji "Call via API")
7. Wróć do Cloudflare Worker → Settings → Variables → wklej endpoint jako `ROUTINE_ENDPOINT`

## Krok 4: GitHub Secrets

W repozytorium → Settings → Secrets and variables → Actions → dodaj:

| Secret Name                    | Value                                      |
|--------------------------------|--------------------------------------------|
| `CLOUDFLARE_DEFENSE_WORKER_URL`| URL Cloudflare Workera z Kroku 2           |
| `NEWSAPI_KEY`                  | Twój NewsAPI key (jeśli masz)              |

## Krok 5: Push do GitHub

```bash
cd /Users/bartlomiejmikos/Downloads/investing
git add defense-monitor/ strategies/defense-market.md .github/workflows/defense-monitor.yml
git commit -m "Add defense market monitor — 30min scan"
git push
```

## Krok 6: Weryfikacja

1. GitHub → Actions → "Defense Market Monitor" → Run workflow
2. Sprawdź logi — powinieneś zobaczyć:
   ```
   [DoD] Scrapuję kontrakty...
   [RSS] Pobieram feed'y...
   [NewsAPI] Pobieram artykuły...
   Łącznie itemów do analizy: XXX
   Sygnałów wygenerowanych: X
   ```
3. Jeśli są sygnały → sprawdź Alpaca paper account czy pojawia się zlecenie

## Uwagi

- Workflow uruchamia się co 30 minut → ~48 razy dziennie
- GitHub Actions darmowy plan: 2000 min/miesiąc → każdy run ~2-3 min → ~144 min/dzień → OK
- DoD publikuje kontrakty zazwyczaj ok. 17:00 ET w dni robocze
- RSS feed'y i NewsAPI działają 24/7
- Jeśli NEWSAPI_KEY jest pusty, monitor pomija ten krok (nie błęduje)
