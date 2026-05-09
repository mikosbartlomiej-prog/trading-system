# Learning Loop — Daily + Weekly Adaptation v1.1 (LLM-augmented)

**Wersja:** 1.1 (2026-05-07 — LLM augmentation layer added on top of v1.0 deterministic adapter)
**Status:** LIVE (po deploy `daily-learning.yml` + `weekly-retro.yml` user-side)
**Źródło prawdy:** `docs/STRATEGY.md` §5.6
**Implementacja:** `learning-loop/`

---

## Filozofia

Jeden cel: **zawsze zarobić więcej.** System adaptuje swoje parametry na
podstawie własnych wyników, nie cudzych benchmarków. Goal się nie zmienia —
tylko sposób jego osiągania.

Adaptacja działa w dwuwarstwowej pętli sprzężenia zwrotnego:

```
Alpaca trades  →  daily analyzer  →  deterministic adapter  →  LLM (Senior PM) override
                  (21:00 UTC)         (heuristics)              (whitelist-enforced)
                                                                       │
                                                                       ▼
                                                    state.json + rationale.md
                                                    (committed via git → audit log)
                                                                       │
                                                                       ▼
                                                       monitors read at startup
                                                                       │
                                                                       ▼
                                                          new Alpaca trades

Sunday 22:00 UTC → weekly_retro.py → 7-day strategist review (P&L story, scorecard,
                                     allocation rebalance, structural mistakes, next-week experiments)
```

Dwie warstwy decyzyjne:
1. **Deterministic adapter** — zawsze działa (heurystyki w `adapter.py`). Idiotoodporna baseline.
2. **LLM strategist (Senior PM persona)** — *dodatkowa* warstwa nakładana na propozycje adaptera.
   Może je zatwierdzić, zmienić, albo zaproponować nowe. Wszystkie zmiany przechodzą przez
   `safe_apply_overrides()` (whitelist enforcement → halucynacje LLM nie psują state).
   **Fail-soft:** gdy LLM niedostępny (HTTP 429 / brak Worker URL / `USE_LLM_LEARNING=false`),
   deterministic adapter pracuje sam — system nigdy nie zatrzymuje się przez problem z LLM.

Każda zmiana parametru jest:
- **Mierzalna** — oparta o konkretne thresholdy (win_rate, P&L %, consecutive losses)
- **Audytowalna** — `git log learning-loop/state.json` pokazuje każdą zmianę
- **Reversibilna** — manualne edytowanie `state.json` możliwe w każdej chwili
- **Wieczna** — nigdy nie kasujemy historii decyzji (`rationale.md` append-only)

---

## Co loop robi codziennie

### 1. Pobiera dane (raz na 24h)
- `/v2/orders?after=24h_ago` — wszystkie zlecenia (filled, canceled, rejected)
- `/v2/account` — equity, last_equity (P&L %)

### 2. Rekonstruuje trady
- Paruje open + close orders (FIFO per symbol)
- Per trade: P&L $, P&L %, hold hours, winner/loser, direction
- Przypisuje do strategii via `client_order_id` prefix

### 3. Computuje statystyki
Per strategy / asset class / source:
- Trades count (7d window i lifetime)
- Win rate
- Total P&L $ i % equity
- Consecutive losses (od najnowszej)
- Long P&L vs Short P&L (dla options bias)
- Fill rate (placed vs filled vs canceled vs rejected)

### 4. Adaptuje parametry per strategia
Heurystyki w `learning-loop/adapter.py`:

#### Per-strategy heuristics (v1.0 — pierwotne)
| Trigger | Akcja |
|---|---|
| Lifetime trades < 10 | Hold (insufficient sample) |
| 7d win rate < 35% (z ≥ 5 trades) | `size_multiplier *= 0.8` |
| 7d win rate > 60% (z ≥ 5 trades) | `size_multiplier *= 1.10` |
| 7d P&L < -2% equity | `size_multiplier *= 0.7` |
| 7d P&L > +3% equity | `size_multiplier *= 1.05` |
| 5 consecutive losers | `enabled = false` (3-day pause) |
| Lifetime ROI < -10% | `enabled = false` (manual review) |
| Options long P&L < 0 + short P&L > \|long P&L\| | `side_bias = "short"` |
| Options short P&L < 0 + long P&L > \|short P&L\| | `side_bias = "long"` |

Granice: `0.30 ≤ size_multiplier ≤ 2.00`. Pause auto-resumuje po 3 dniach.

#### Fill-rate heuristics (v1.2 — added 2026-05-08/09 from LLM proposals)
| Function | Trigger | Effect |
|---|---|---|
| `heuristic_options_limit_too_tight` | options-momentum fill_rate < 50% over ≥ 5 placed | Emit alert (no state change) |
| `heuristic_fill_rate_size_cut` | cancel_rate ≥ 50% over ≥ 3 placed | Cap options-momentum `size_multiplier` to factor in [0.40, 0.75] |
| `heuristic_fill_rate_alert` | any strategy with fill_rate < 50% over ≥ 3 placed | Returns sorted alert list (worst first); analyzer emits to rationale |
| `heuristic_options_chronic_fill` | options-momentum fill_rate < 50% over ≥ 5 placed (multi-session pattern) | Emit chronic-fill warning recommending midpoint+5% pricing |

All fire after the per-strategy loop in `adapt()` and write to `rationale` for daily history visibility.

### 5. LLM strategist annotation (Senior PM persona) — NEW v1.1
Po deterministic adapter, ale PRZED zapisem `state.json`, analyzer wysyła payload do
istniejącego Cloudflare Workera `learning-loop-proxy` → routine `Learning Loop Strategist`
(claude.ai). Routine type-dispatchuje na `payload.type == "daily_learning_annotation"`.

**Co LLM dostaje** (`payload`):
- `today_stats` — pełne statystyki dnia (per-strategy, per-asset-class, per-source, fill-rate)
- `proposed_state` — to, co adapter już proponuje (pre-LLM)
- `deterministic_rationale` — bullet list zmian z heurystyk
- `recent_rationale_tail` — ostatnie 20 wpisów z `rationale.md` dla kontekstu

**Co LLM zwraca** (pure JSON — patrz `learning-loop/routine-prompts.md`):
```jsonc
{
  "narrative": "2-4 zdania w stylu PM, konkrety + liczby",
  "regime_assessment": "trending_up|trending_down|choppy|risk_on|risk_off|unclear",
  "edge_assessment": "gdzie mamy edge, gdzie tracimy",
  "state_overrides": {
    "strategies": {
      "<name>": {"size_multiplier": 0.4, "side_bias": "short", "rationale": "..."}
    },
    "global_overrides": {"options_side_bias": "short"}
  },
  "new_heuristic_proposals": ["Pause strategy X if 3 daily losses with hold<1h"],
  "confidence": "high|medium|low"
}
```

**Co system robi z odpowiedzią:**
- `safe_apply_overrides()` filtruje przez whitelist — tylko `size_multiplier` (clamp 0.30-2.00),
  `enabled` (bool), `side_bias` (`long|short|null`), `rationale`, `paused_until`, `llm_note`.
  Wszystko poza whitelist jest **silently dropped** + zapisane w applied log.
- LLM `narrative` + `edge_assessment` → wstawione na początku `rationale.md` z prefiksem
  `LLM[confidence] regime=<x>:`
- `new_heuristic_proposals` → appended do `learning-loop/heuristic_proposals.md`
  (tickbox queue dla ręcznej oceny / wpisania do `adapter.py`)

**Fail-soft:** gdy LLM zwróci 429 / non-JSON / brak Worker URL / `USE_LLM_LEARNING=false` →
analyzer drukuje `"LLM unavailable (skipped) — deterministic adapter only"` i kontynuuje. Stan
deterministic-only nigdy nie jest blokowany przez LLM.

### 6. Zapisuje stan
- `state.json` — bieżące adapted parameters (machine-readable, post-LLM-overrides)
- `rationale.md` — append narrative (LLM headline + deterministic deltas)
- `history/YYYY-MM-DD.md` — pełny dzienny report
- `heuristic_proposals.md` — kolejka idei od LLM (open/closed checkboxes)

### 7. Commit + push do main
Workflow `daily-learning.yml`:
```yaml
- run: |
    git config user.name  "github-actions[bot]"
    git config user.email "github-actions[bot]@users.noreply.github.com"
    git add learning-loop/state.json learning-loop/rationale.md learning-loop/history/
    git add learning-loop/heuristic_proposals.md 2>/dev/null || true
    if ! git diff --cached --quiet; then
      git commit -m "learning: daily update YYYY-MM-DD"
      git push origin main
    fi
```

`GITHUB_TOKEN` z `permissions: contents: write` na poziomie workflow. Workflow
exposes `CLOUDFLARE_LEARNING_WORKER_URL` + `USE_LLM_LEARNING=true` so the LLM
augmentation step works.

---

## Weekly retrospective (Sunday 22:00 UTC) — NEW v1.1

Drugi cron, ten sam routine (type-dispatch). Workflow `weekly-retro.yml` →
`learning-loop/weekly_retro.py`.

### Co LLM dostaje (`payload`)
- `daily_reports` — full markdown z ostatnich 7 plików `history/*.md`
- `rationale_tail` — ostatnie 50 wpisów z `rationale.md`
- `current_state` — pełny `state.json`

### Co LLM zwraca (pure JSON — type=`weekly_retrospective`)
```jsonc
{
  "week_pl_story": "3-4 zdania makro + jak strategie złapały / przegapiły",
  "market_regime": "trending_up|trending_down|choppy|risk_on|risk_off|transitional",
  "strategy_scorecard": [
    {"name": "...", "rank": 1, "pnl_usd": 234.50, "verdict": "keep|cut|boost"}
  ],
  "allocation_recommendation": {
    "stocks_pct": 50, "leveraged_etf_pct": 15, "crypto_pct": 10,
    "options_pct": 10, "defense_geo_pct": 10, "twitter_pct": 5,
    "rationale": "..."
  },
  "best_sources":  [{"source": "...", "win_rate": 0.7, "pnl": 123.0}],
  "worst_sources": [{"source": "...", "win_rate": 0.2, "pnl": -88.0}],
  "structural_mistakes": [{"description": "...", "lost_usd": 200, "remediation": "..."}],
  "experiments_next_week": [{"hypothesis": "...", "metric": "...", "revert_if": "..."}],
  "state_overrides": {"strategies": {...}, "global_overrides": {...}},
  "confidence": "high|medium|low"
}
```

### Output artifacts
- `learning-loop/weekly-retros/<week_end>.md` — full retro markdown (formatted)
- `state.json` — strategist może wymusić cięcia/wzrosty
- `rationale.md` — headline z prefiksem `WEEKLY[confidence] regime=<x>`
- `heuristic_proposals.md` — `WEEKLY EXP:` items od strategist

### Budget
- Daily annotator: 1 routine call/day
- Weekly retro: 1 routine call/week (Sunday)
- **Total: ~1.14 routine calls/day vs 15/day Anthropic limit → ~13.86 w rezerwie**

Inne monitory (price/crypto/defense/twitter/exit) zostały przerzucone na
deterministic Alpaca REST execution w v2.2 właśnie po to, żeby learning loop
miał gwarantowaną przepustowość routine'ów. Jest priorytetem strategicznym.

### Fail-soft (weekly)
Gdy LLM niedostępny w niedzielę, `weekly_retro.py` zapisuje minimalny
markdown ze stanu lokalnego (per-strategia statystyki z ostatniego
state.json). Plik nigdy nie jest pusty.

---

## Jak monitory korzystają

Każdy monitor który chce adaptować się do learning loop importuje helper:

```python
from learning_state import load_strategy_state

# Na początku run_scan():
state = load_strategy_state("momentum-long")    # nazwa strategii z client_order_id
if not state.get("enabled", True):
    print(f"  Learning loop: paused (until {state.get('paused_until')})")
    return

mult = state.get("size_multiplier", 1.0)
SIZE_LONG_TODAY = int(SIZE_LONG_BASE * mult)
```

Dla options-monitor (z side_bias):
```python
state = load_strategy_state("options-momentum")
bias = state.get("side_bias")
if bias == "short" and proposal["option_type"] == "call":
    continue  # skip CALL — system uczy się że puts dają więcej
```

Fail-safe: brak `state.json` → helper zwraca `{}` → monitor używa baseline parameters.

---

## Status implementacji per monitor

| Monitor | Strategy keys w state | Wired | Notes |
|---|---|---|---|
| **options-monitor** | `options-momentum` | ✅ v1.0 | Reads size_multiplier + side_bias |
| price-monitor | `momentum-long`, `overbought-short`, `leveraged-etf` | ⏳ TODO Phase 2 | size_multiplier ready to wire |
| crypto-monitor | `crypto-long`, `crypto-short` | ⏳ TODO Phase 2 | size_multiplier ready to wire |
| defense-monitor | `defense-long`, `defense-short` | ⏳ TODO Phase 2 | size_multiplier ready to wire |
| twitter-monitor | `twitter-A-direct`, `twitter-B-escalation`, `twitter-C-deescalation`, `twitter-D-macro-*` | ⏳ TODO Phase 2 | per-pattern multiplier |
| geo-monitor | n/a (uses asset_map mapping) | ⏳ skip | No clean strategy key yet |
| exit-monitor | n/a (manages existing positions) | ⏳ skip | Reads exit thresholds, not entry sizing |

Phase 2 (next session): wire remaining monitors. Each is a 5-line addition.

---

## state.json — przykład po 14 dniach

```jsonc
{
  "version": "1.0",
  "last_updated": "2026-05-21T21:05:00Z",
  "days_tracked": 14,
  "cumulative": {
    "total_trades": 87,
    "total_pnl_usd": 1234.50,
    "starting_equity": 100000.00
  },
  "strategies": {
    "momentum-long": {
      "trades_lifetime": 32, "trades_7d": 12,
      "win_rate_lifetime": 0.62, "win_rate_7d": 0.66,
      "pnl_usd_lifetime": 856.30, "pnl_usd_7d": 234.50,
      "size_multiplier": 1.21,
      "enabled": true,
      "side_bias": null,
      "rationale": "7d win-rate 66% > 60% -> +10% (3rd consecutive day)"
    },
    "options-momentum": {
      "trades_lifetime": 18, "trades_7d": 5,
      "win_rate_lifetime": 0.27, "win_rate_7d": 0.20,
      "pnl_usd_lifetime": -420.0, "pnl_usd_7d": -180.0,
      "pnl_long_7d": -200.0, "pnl_short_7d": 20.0,
      "size_multiplier": 0.45,
      "enabled": true,
      "side_bias": "short",
      "rationale": "7d win-rate 20% < 35% -> -20% | options long $-200, short $20 -> bias=short"
    }
  },
  "asset_classes": {
    "stocks":  { "trades_7d": 8,  "win_rate_7d": 0.625, "pnl_usd_7d": 412.0 },
    "crypto":  { "trades_7d": 3,  "win_rate_7d": 0.66,  "pnl_usd_7d": 88.5 },
    "options": { "trades_7d": 5,  "win_rate_7d": 0.20,  "pnl_usd_7d": -180.0 }
  },
  "sources": {},
  "next_actions": [
    "options-momentum: size_multiplier 0.50 -> 0.45",
    "options-momentum: side_bias null -> short"
  ]
}
```

---

## rationale.md — przykład

```markdown
# Learning Loop — Rationale Log

- 2026-05-21 · momentum-long: size_multiplier 1.10 -> 1.21 · 7d win-rate 66% > 60% -> +10%
- 2026-05-21 · options-momentum: size_multiplier 0.50 -> 0.45 · 7d win-rate 20% < 35% -> -20%
- 2026-05-21 · options-momentum: side_bias null -> short · options long $-200, short $20 -> bias=short

- 2026-05-20 · momentum-long: size_multiplier 1.00 -> 1.10 · 7d win-rate 65% > 60% -> +10%
- 2026-05-19 · options-momentum: enabled True -> False · 5 consecutive losses; auto-resume after 3 days

(...older entries below...)
```

---

## Phase 2 (kolejna sesja) — co dalej

- [x] LLM augmentation (Senior PM persona) — daily + weekly ✅ v1.1 (2026-05-07)
- [ ] Wire price-monitor / crypto-monitor / defense-monitor / twitter-monitor do read state
- [ ] Per-source attribution (which Bluesky account → trade outcome)
- [ ] Per-news-event attribution (defense DoD scrape vs RSS feed efficacy)
- [ ] More heuristics: ATR-relative size, max drawdown circuit, regime detection
- [ ] Rolling window option (configurable: 7d / 14d / 30d)
- [ ] Email summary: daily learning report sent to user
- [ ] Auto-promotion: heurystyki z `heuristic_proposals.md` z high success-track wstawione do `adapter.py`

---

## Manualne overridy

User w każdej chwili może edytować `state.json`:

```bash
# Force-disable strategy
git checkout main
jq '.strategies."options-momentum".enabled = false' learning-loop/state.json > tmp && mv tmp learning-loop/state.json
git commit -am "manual override: disable options-momentum"
git push

# Force size multiplier
jq '.strategies."momentum-long".size_multiplier = 0.5' learning-loop/state.json > tmp && mv tmp learning-loop/state.json
```

Following daily-learning run accept user overrides as starting point and adapts further from there.

---

## Limitations (znane, do naprawy w Phase 2+)

1. **Window = 24h, lifetime = first run**. Real lifetime tracking wymaga akumulacji w state.json (TODO).
2. **Order pairing FIFO** — gdy mamy multiple open positions na ten sam symbol, parowanie może się pomylić.
3. **No per-source attribution** — analyzer nie wie który Bluesky tweet wygenerował który trade.
4. **No regime detection** — adaptacja jest reaktywna, nie predykcyjna.
5. **GitHub Actions runtime** — workflow musi mieć `permissions: contents: write` żeby commitować.
