# Politicians whitelist — politician-monitor

**Wersja:** 1.0 (2026-05-21)
**Monitor:** `politician-monitor` (STOCK Act PTRs + DJT Form 4 + cabinet trades)
**Strategia:** `strategies/politician-tracker.md` (TBD)
**Source-of-truth:** `docs/STRATEGY.md` §4.x (TBD)

Curated bipartisan list — 20 active disclosing politicians + admin
officials. Selection criteria: (a) public disclosure history within
last 24 months, (b) min. 10 PTR filings or active known trader, (c)
either party — bipartisan by design (oponentów też trackujemy).

Operator może dodawać/usuwać po manualnej weryfikacji track record.

---

## Channel architecture

Two lanes:

### Lane A — DJT Form 4 (real-time, auto-execute eligible)

Single instrument focus: **Trump Media & Technology Group (DJT)**.
SEC Form 4 filings — wszelkie insider transactions (Trump, family,
board members, TMTG officers) hit EDGAR within 2 business days.

- **CIK:** 0001849635 (verify at sec.gov before first run)
- **Endpoint:** `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001849635&type=4&dateb=&owner=include&count=40&output=atom`
- **Sizing:** $5,000 (half normal — DJT hyper-volatile, 50%+ daily moves not unusual)
- **Auto-execute:** TAK (real-time data, no significant lag)

### Lane B — STOCK Act bipartisan (lagged, alert-only)

Politicians from list below + cluster aggregation (3+ disclosures
same sector / 14 days → sector ETF basket BUY).

- **Endpoint:** `https://bff.capitoltrades.com/trades?page=0&pageSize=50` (undocumented JSON)
- **Fallback:** `https://housestockwatcher.com/api` (community scraper)
- **Min bracket:** $50,001-$100,000 (skip $1k-15k, $15k-50k — boring)
- **Auto-execute:** **NIE** (30-45 dni lag, default email-only)
- **Sector aggregation:** cluster ≥3 polityków w 14d → sector ETF
  (defense → ITA/XAR, semis → SMH, energy → XLE, financials → XLF, etc.)

---

## Whitelist (20 politicians)

Format: `<full_name> | <party> | <chamber> | <category> | <weight>`

Categories drive `source_type` w event_scoring + Curator persona context:
- `dem_trader_top`    → tracked_pol_top (cred 70) — high-conviction Dems
- `rep_trader_top`    → tracked_pol_top (cred 70) — high-conviction Reps
- `committee_insider` → tracked_pol_insider (cred 75) — committee-relevant
- `admin_official`    → tracked_admin (cred 80) — cabinet / VP / White House

Weight 1.0-2.0 — historical track-record bonus dla sizing.

### Democrats (10 names)

```
Nancy Pelosi          | D | House  | dem_trader_top    | 1.5
Sheldon Whitehouse    | D | Senate | committee_insider | 1.2
Dan Goldman           | D | House  | dem_trader_top    | 1.0
Josh Gottheimer       | D | House  | dem_trader_top    | 1.2
Ro Khanna             | D | House  | committee_insider | 1.1
Mark Warner           | D | Senate | committee_insider | 1.3
Diana DeGette         | D | House  | dem_trader_top    | 1.0
Susan Wild            | D | House  | dem_trader_top    | 1.0
Don Beyer             | D | House  | dem_trader_top    | 1.0
Mark Pocan            | D | House  | dem_trader_top    | 1.0
```

### Republicans (8 names)

```
Tommy Tuberville      | R | Senate | rep_trader_top    | 1.3
Dan Crenshaw          | R | House  | committee_insider | 1.1
Michael McCaul        | R | House  | committee_insider | 1.4
Patrick McHenry       | R | House  | committee_insider | 1.2
John Curtis           | R | House  | rep_trader_top    | 1.0
Lloyd Smucker         | R | House  | rep_trader_top    | 1.0
Marjorie Taylor Greene| R | House  | rep_trader_top    | 1.0
Marco Rubio           | R | Senate | admin_official    | 1.5
```

### Administration / VP (2 names — Trump 2 admin)

```
JD Vance              | R | VP / Senate | admin_official | 1.6
Pete Hegseth          | R | SecDef      | admin_official | 1.5
```

(Additional cabinet picks added as they file. Many divest before
taking office — signal may be limited for those.)

---

## Cluster signal logic (Lane B)

A "cluster" triggers signal when:
- ≥3 politicians (any party) disclose trades in same sector within 14d
- Aggregate disclosed amount ≥$200k (sum of bracket midpoints)
- Same side (all BUY or all SELL)
- VIX < 60 + drawdown OK + concentration cap OK

Sector mapping:
- **defense**     → ITA (XAR for redundancy backup)
- **semis**       → SMH
- **energy**      → XLE
- **financials**  → XLF
- **healthcare**  → XLV
- **tech (broad)**→ QQQ
- **software**    → ticker via `software_quality` bucket (v3.9.1)

Individual ticker (without cluster) only emits via Curator LLM
discretion. Default: alert-only email, no Alpaca order.

---

## Single-politician escalation (Lane B exception)

A single politician's trade CAN trigger immediate emit (without
cluster) if ALL these hold:
- weight ≥ 1.4 (high-conviction or admin official)
- bracket ≥ $100k-$250k
- Curator confidence "high"
- single-name ticker on whitelist
- VIX < 60 + concentration cap OK

This catches e.g. McCaul (defense committee) buying RTX $500k —
high-signal single-source even pre-cluster.

---

## Adding / removing politicians

1. Audit publiczna historia PTR (min. 10 disclosures, last 24 months)
2. Sprawdź czy track-record sygnalizuje edge (np. via Capitol Trades win rate)
3. Add wiersz w odpowiedniej sekcji
4. Set weight 1.0 dla nowych; podnieś po 3 miesiącach obserwacji
5. Commit + push; następny cron pobiera

## Removed (audit log)

(empty — first iteration)
