# Reddit — curated subs (no-API path via public JSON + RSS)

**Wersja:** 1.0 (2026-05-09 — public endpoints, no OAuth, no token)
**Monitor:** `reddit-monitor` (Reddit `.json` endpoints + RSS feeds)
**Strategia:** `strategies/reddit-sentiment.md`
**Source-of-truth:** `docs/STRATEGY.md` §4.7

## Channel: Reddit public endpoints

Każdy publiczny URL Reddita ma JSON-owy odpowiednik — dopisz `.json`:

```
https://www.reddit.com/r/<sub>/top.json?t=day&limit=25
https://www.reddit.com/r/<sub>/hot.json?limit=25
https://www.reddit.com/r/<sub>/new.json?limit=25
https://www.reddit.com/r/<sub>/.rss          (RSS, alternative)
```

**ToS guard:** poll co ≥ 60 min, custom `User-Agent`, max 1-2 req/s burst.
Anonymous rate limit = ~60 req/min. Z 5 subów × 1 req/sub × cron 60min =
5 req/h — daleko poniżej limitu.

---

## Per-sub config

Format: `<sub_name> | <category> | <min_upvotes> | <min_comments> | <weight>`

Category determines `source_type` w event_scoring:
- `wsb`           → tracked_anon_trader (cred 55) — high noise, high velocity
- `quality_sub`   → major_outlet (cred 60) — investing/stocks/securityanalysis
- `options_sub`   → tracked_anon_trader (cred 55) — options-specific signal
- `crypto_sub`    → tracked_anon_trader (cred 55) — crypto-specific

**Weight** (1.0-2.0) — per-sub size_multiplier mnożnik dla downstream sizing.
Wyższy weight = sub o lepszej historycznej jakości signalu.

```
wallstreetbets    | wsb           | 500  | 50  | 1.0
options           | options_sub   | 100  | 20  | 1.2
stocks            | quality_sub   | 200  | 30  | 1.3
investing         | quality_sub   | 200  | 30  | 1.4
securityanalysis  | quality_sub   | 100  | 20  | 1.5
valueinvesting    | quality_sub   | 100  | 20  | 1.4
```

## Per-sub keyword filter (post tytuł + flair)

Tylko posty zawierające jeden z poniższych keywordów (case-insensitive)
przechodzą dalej. Reszta odrzucona — to ogranicza noise (memes, shitposts).

```
wallstreetbets:
    DD, due diligence, gain, loss, yolo, position, calls, puts,
    earnings, breakout, squeeze, gamma, pivot, target
options:
    calls, puts, iv, volatility, expiry, strike, gamma, theta, delta,
    earnings, breakout, dd, due diligence
stocks / investing / securityanalysis / valueinvesting:
    DD, due diligence, analysis, valuation, earnings, fundamentals,
    bullish, bearish, undervalued, overvalued, catalyst, thesis
```

## Sentiment keywords (per ticker mention)

Wykrywanie tonu wokół ekstrahowanego tickera. Window = ±30 słów od mention.

```
BULLISH: bullish, long, calls, buy, rocket, moon, undervalued, breakout,
         beat, earnings beat, raised, upgraded, target, bottoming, bounce,
         catalyst, opportunity, oversold, accumulate, conviction
BEARISH: bearish, short, puts, sell, dump, crash, overvalued, breakdown,
         miss, earnings miss, cut, downgraded, decline, top, exit, avoid,
         overpriced, distribution, rejection, weak
```

## Ticker extraction

Z każdego posta (tytuł + body) ekstrahujemy tickery na 2 sposoby:

1. **Cashtag:** `$AAPL`, `$NVDA` — eksplicytny
2. **All-caps standalone:** `AAPL`, `NVDA` — heurystyka (3-5 znaków,
   zawarty w `tickers-whitelist.md`)

Off-whitelist tickery → odrzucone (iron rule).

---

## Spike detection (Pattern A z strategies/reddit-sentiment.md)

Ticker triggers signal jeśli:
- Mentions w ostatnich 24h ≥ 3× rolling 7-day average
- Co najmniej 1 post wysokiej jakości (upvotes ≥ min_upvotes, comments
  ≥ min_comments per sub config)
- Sentiment skew: ratio (bullish_mentions - bearish_mentions) /
  total_mentions ≥ 0.3 dla BUY signal
- VIX < 60 (HALT only above)
- Drawdown OK
- Concentration nie naruszona

## Direction policy

- Strong bullish skew + spike → BUY signal
- Strong bearish skew + spike → SELL_SHORT signal (gated on
  STRATEGY.md per-strategy short rules)
- Mixed sentiment → IGNORE (event_scoring.WAIT_FOR_CONFIRMATION)

---

## State storage

Per-ticker rolling mention counts mieszczą się w
`learning-loop/state.json::reddit_state` jako sliding window:

```json
"reddit_state": {
  "AAPL": {
    "mentions_per_day": {"2026-05-04": 3, "2026-05-05": 2, ...},
    "last_signal": "2026-05-09T13:00:00Z"
  }
}
```

Workflow commit + push aktualizuje stan każdą runą.

---

## Risk note

Reddit is the noisiest signal source — niższa wiarygodność niż curated
Bluesky / news feeds. Iron rule: `reddit-sentiment` strategia ma:
- size_usd $5,000 (vs Twitter $5-6k, vs geo $8k+)
- max 4 open positions
- mandatory stop-loss -6%, TP +14%
- VIX HALT > 60 (not 35)
- DUP_POSITION_GUARD enforced

Dziennie max 4 alerty — `MAX_ALERTS_PER_RUN=1` + cron co 60 min.
