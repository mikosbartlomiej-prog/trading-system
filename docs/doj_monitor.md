# doj-monitor (v3.16 — SEC 8-K + DOJ press, emit-only)

## Why ship it

Closes audit-board feedback **FB-008** with **Option B** from the
operator walkthrough: an emit-only, primary-source legal/governance
event monitor that:

1. Surfaces SEC 8-K material item filings (1.01, 1.02, 1.03, 5.02, 8.01)
   for every US-listed issuer.
2. Surfaces DOJ press releases (indictments, settlements, investigations)
   when a ticker can be resolved best-effort.
3. Never auto-executes. Never invokes an LLM Curator (in this iteration).
   Never places trades.
4. Honors the existing source-tier policy: every event is Tier 1 primary,
   so day-trade eligibility follows the base-class rule in
   `shared/event_monitor_interface.EventMonitorInterface`.

Net effect: the inbox starts collecting tradeable legal/governance
catalysts that previously required manual SEC EDGAR / DOJ checks. The
operator decides whether to act on each one.

## Architecture

```
GitHub Actions cron (every 2h)
  → doj-monitor/monitor.py
      ├── Lane A — SEC 8-K Atom feed (~40 latest filings)
      │       ↳ classify items (1.01/1.02/1.03/5.02/8.01)
      │       ↳ CIK → ticker via SEC company_tickers.json
      │       ↳ build EventCandidate (Tier 1 primary)
      ├── Lane B — DOJ press release RSS
      │       ↳ classify catalyst_timing (immediate/days/weeks_months)
      │       ↳ best-effort ticker extraction (cashtag + alias map)
      │       ↳ build EventCandidate (Tier 1 primary)
      ├── EventMonitorInterface.decide() → dedup + confidence adj.
      ├── shared/notify.send_email("[DOJ-FILING] ...")
      └── doj-monitor/state.json (FIFO 1000 seen event_ids)
```

No Cloudflare Worker. No Anthropic Routine. No Alpaca side-effect.

## Source-tier classification

Every event built by this monitor is tagged `tier_1_primary`. This means:

* `confidence_ceiling_for(source)` → **1.00** (matches what the
  audit board allows for primary sources).
* `is_day_trade_eligible_alone(source)` → **True** for the source
  itself, but the base-class `EventMonitorInterface.is_day_trade_eligible`
  also requires `catalyst_timing == "immediate"`.

In practice:

| Lane | Item / Keyword                   | Severity | Catalyst   | Day-trade eligible alone? |
|------|----------------------------------|----------|------------|---------------------------|
| 8-K  | 1.03 Bankruptcy                  | high     | immediate  | **Yes** (Tier 1 + immediate) |
| 8-K  | 1.01 Material Agreement          | medium   | days       | No                        |
| 8-K  | 1.02 Termination                 | medium   | days       | No                        |
| 8-K  | 5.02 Officer Departure           | medium   | days       | No                        |
| 8-K  | 8.01 Other Events                | low      | weeks/mo.  | No                        |
| DOJ  | indictment / arrest / fraud      | high     | immediate  | **Yes**                   |
| DOJ  | settlement / plea / sentenced    | medium   | days       | No                        |
| DOJ  | investigation / probe / civil    | low      | weeks/mo.  | No                        |

`day_trade_eligible_alone=False` does not block the email — every
candidate still emits `[DOJ-FILING]`. It only controls the
`day_trade_eligible` flag the operator sees in the email body.

## Operator setup steps

1. **GitHub Secrets** — add or verify:
   * `SEC_USER_AGENT` (mandatory; SEC rejects requests without a real
     contact). Example: `"trading-system doj-monitor you@example.com"`.
   * `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `NOTIFY_EMAIL` (already
     configured for the rest of the system).
   * `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `FINNHUB_API_KEY`
     (optional — used by the soft drawdown / VIX guards; fail-open if
     missing).
2. **Workflow file** — copy
   `scripts/workflow-templates/doj-monitor.yml` into
   `.github/workflows/doj-monitor.yml`. The automatic
   `sync-workflows.yml` job will do this on the next push if you have
   `WORKFLOW_PAT` configured.
3. **Cloudflare cron-trigger Worker** — add `doj-monitor` to the
   `*/15` workflow_dispatch list (medium-frequency lane) so the monitor
   keeps firing even when GitHub Actions cron skips. Two new entries
   per hour is the target cadence.
4. **First run** — trigger manually via `gh workflow run doj-monitor`
   and confirm one `[DOJ-FILING]` test email arrives within ~3 minutes.
5. **Initial seeding** — commit the empty `doj-monitor/state.json`
   shipped with this iteration. On the first real run the dedup cache
   will populate with ~40 SEC 8-K accessions and the DOJ press IDs;
   subsequent runs only emit fresh events.

## 30-day observation policy

Per the audit-board walkthrough this is a feedback gathering run, not a
trade source:

* For 30 days from first deploy: collect every `[DOJ-FILING]` email,
  log whether the underlying ticker moved ≥3% in the next 24h, and tag
  the event in a spreadsheet.
* No auto-execute, no Curator. Every emission is operator-reviewed.
* `AUTO_EXECUTE_DOJ` stays `false` in workflow env.
* `USE_DOJ_CURATOR` stays `false`.

At day 30 the operator + audit board reviews the catch rate. Possible
follow-ups:

| Observation                                          | Re-decision           |
|------------------------------------------------------|-----------------------|
| ≥10 immediate-catalyst events with ≥3% same-day move | Promote Lane A 1.03 + DOJ-indict to Curator + auto-execute, half-size |
| Lots of noise, low signal                            | Tighten MATERIAL_ITEMS to {1.03} only |
| Many DOJ press without ticker resolution             | Expand `SHORT_NAME_ALIASES` map |
| SEC blocks our requests                              | Verify `SEC_USER_AGENT` contact string, slow `SEC_RATE_SLEEP_S` |

## Re-decision triggers per walkthrough

* **Trigger A — quality:** ≥30 events emitted, ≥40% had material price
  reaction within 24h → graduate to Curator-gated Lane.
* **Trigger B — false-positives:** ≥10 events caused operator inbox
  noise without actionability → tighten material item filter and/or
  DOJ keyword set.
* **Trigger C — coverage gap:** operator notices a real catalyst that
  monitor missed → add the missing source / pattern (e.g. add new
  alias to `SHORT_NAME_ALIASES`).

## What this monitor will NOT do

* Submit any order. The `AUTO_EXECUTE_DOJ` flag is reserved but the
  code path that would use it is intentionally absent — adding it
  requires wiring `shared/risk_officer` + `shared/news_signal_gate`
  + `shared/confidence_builder` first, which is the next iteration.
* Call any paid API. SEC EDGAR is free; DOJ RSS is free.
* Hold persistent network state. Only a small JSON dedup cache.

## Files in this iteration

```
doj-monitor/
├── monitor.py            # main scan, EventMonitorInterface impl
├── sec_8k_client.py      # Lane A — SEC 8-K Atom feed + CIK→ticker
├── doj_press_client.py   # Lane B — DOJ press RSS + ticker extraction
├── state.json            # FIFO dedup cache (seen event_ids)
└── requirements.txt      # requests only
scripts/workflow-templates/doj-monitor.yml
tests/test_doj_monitor_v3160.py    # 12+ scenarios, no network
docs/doj_monitor.md       # this file
```
