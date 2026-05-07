# Twitter / Bluesky — curated source accounts

**Wersja:** 1.0 (2026-05-07 MVP — Bluesky-first, X API as future upgrade)
**Monitor:** `twitter-monitor` (yes, name kept; data source on day one is `bsky.app`)
**Source-of-truth:** `docs/STRATEGY.md` backlog entry "X / Twitter integration"

The monitor reads recent posts from this whitelist and filters by keywords
+ event-probability scoring before forwarding to a routine. Accounts that
do not yet exist on Bluesky will fall back to "missing" and be revisited
when the X API is wired (Path 1 in the backlog).

Format: `<bluesky_handle> | <twitter_handle (legacy)> | <category>`

---

## Politics & geo (high priority)

```
@potus.bsky.social        | @POTUS              | gov_us
@whitehouse.bsky.social   | @WhiteHouse         | gov_us
@statedept.bsky.social    | @StateDept          | gov_us
@secdef.bsky.social       | @SecDef             | gov_us
@idfdaily.bsky.social     | @IDF                | mil_il
```

(Some of these have no Bluesky presence yet; the monitor logs missing
handles as `not-on-bsky` and continues.)

## Markets / macro

```
@zerohedge.bsky.social    | @zerohedge          | macro
@business.bsky.social     | @business           | macro      # Bloomberg
@cnbc.bsky.social         | @CNBC               | macro
@wsjmarkets.bsky.social   | @WSJmarkets         | macro
@ft.bsky.social           | @FT                 | macro
@reuters.bsky.social      | @Reuters            | wire
@ap.bsky.social           | @AP                 | wire
```

## Single-ticker insider (corp accounts)

```
@elonmusk.bsky.social     | @elonmusk           | ticker:TSLA
@tim_cook.bsky.social     | @tim_cook           | ticker:AAPL
@sundarpichai.bsky.social | @sundarpichai       | ticker:GOOGL
@satyanadella.bsky.social | @satyanadella       | ticker:MSFT
```

(Ditto — many corp CEOs aren't on Bluesky yet. Track as we go.)

## Government feeds

```
@congressionalrpt.bsky.social | @CongressionalRpt | gov_us
@ustreasury.bsky.social   | @USTreasury         | gov_us
@secgov.bsky.social       | @SECgov             | gov_us
@federalreserve.bsky.social | @federalreserve   | gov_us
```

## Finance influencers (start small, hand-pick)

```
# Add 10-15 high-conviction accounts here over time.
# Avoid follower-counts — favour track record and concrete calls.
# Empty for v1.0 by design.
```

---

## Keyword filter (per-category)

The monitor only emits an alert when the post contains at least one
keyword from the category list:

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
ticker:<sym>:
    any post from that account is a candidate (CEO accounts low-volume)
```

A post matching multiple categories is scored by the highest-priority match.

---

## Adding a new account

1. Append a line to the right category above with the Bluesky handle
2. (Optional) Add Twitter equivalent for future cross-reference
3. Update `docs/STRATEGY.md` if it changes asset-class allocation
4. Commit + push; next monitor run picks it up automatically
