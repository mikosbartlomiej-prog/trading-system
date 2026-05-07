# Learning Loop — Daily Adaptation v1.0

**Wersja:** 1.0 (2026-05-07)
**Status:** LIVE (po deploy `daily-learning.yml` user-side)
**Źródło prawdy:** `docs/STRATEGY.md` §5.6
**Implementacja:** `learning-loop/`

---

## Filozofia

Jeden cel: **zawsze zarobić więcej.** System adaptuje swoje parametry na
podstawie własnych wyników, nie cudzych benchmarków. Goal się nie zmienia —
tylko sposób jego osiągania.

Adaptacja działa w pętli sprzężenia zwrotnego:

```
Alpaca trades  →  daily analyzer  →  state.json + rationale.md  →  monitors  →  Alpaca trades
                  (21:00 UTC)         (committed via git)            (read at startup)
```

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
Heurystyki w `learning-loop/adapter.py` (v1.0):

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

### 5. Zapisuje stan
- `state.json` — bieżące adapted parameters (machine-readable)
- `rationale.md` — append narrative o ZMIANACH (only when something changed)
- `history/YYYY-MM-DD.md` — pełny dzienny report

### 6. Commit + push do main
Workflow `daily-learning.yml`:
```yaml
- run: |
    git config user.name  "github-actions[bot]"
    git config user.email "github-actions[bot]@users.noreply.github.com"
    git add learning-loop/state.json learning-loop/rationale.md learning-loop/history/
    if ! git diff --cached --quiet; then
      git commit -m "learning: daily update YYYY-MM-DD"
      git push origin main
    fi
```

`GITHUB_TOKEN` z `permissions: contents: write` na poziomie workflow.

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

- [ ] Wire price-monitor / crypto-monitor / defense-monitor / twitter-monitor do read state
- [ ] Per-source attribution (which Bluesky account → trade outcome)
- [ ] Per-news-event attribution (defense DoD scrape vs RSS feed efficacy)
- [ ] More heuristics: ATR-relative size, max drawdown circuit, regime detection
- [ ] Rolling window option (configurable: 7d / 14d / 30d)
- [ ] Email summary: daily learning report sent to user

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
