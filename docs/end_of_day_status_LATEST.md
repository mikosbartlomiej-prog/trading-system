# End-of-Day System Status — Local Backfill Discovery Seeded

Generated: 2026-06-15T17:00:00Z (Claude v3.27 FINAL-PHASE — backfill seeder + replay discovery + watchlist/queue population + density plan)
HEAD: `1b2a7b9825753d2e05fc7f218fafdc168709dce2`  (pre-v3.27 commit; v3.27 staged for commit)

## TL;DR

The system is in `SHADOW_ONLY`, **NOT live-ready**. v3.27 feeds the v3.26
discovery layer with real local backfill data so it can produce actionable
replay candidates, near-miss insights, shadow candidate queue rows and a
prioritized trigger watchlist. Where no local backfill data exists, the
seeders honestly emit `NO_LOCAL_BACKFILL_DATA` instead of fabricating.

v3.27 does NOT flip any safety flag, does NOT enable trading, does NOT
place any order, does NOT lower thresholds automatically, does NOT
promote any variant to active runtime, does NOT add paid services, does
NOT introduce LLM calls into the runtime path. `EDGE_GATE_ENABLED`
remains `false`. `ALLOW_BROKER_PAPER` remains `false` (default). LLM
stays advisory only. Canary stays preflight-only. `LIVE_TRADING_UNSUPPORTED`.
`NO_ORDER_PLACEMENT`. `REPLAY_NOT_PAPER`. `BACKFILL_NOT_PAPER`.
`NO_FABRICATION`.

## 1. Repo status

- **Branch:** `main`
- **HEAD:** `1b2a7b9825753d2e05fc7f218fafdc168709dce2`
- **Working tree:** v3.27 staged for commit
- **Worktrees:** single — `main` only

## 2. System status flags (canonical, hard-pinned)

| Flag                          | Value     | Notes                                  |
| ----------------------------- | --------- | -------------------------------------- |
| `EDGE_GATE_ENABLED`           | **false** | Hard-pinned. v3.27 does not flip this. |
| `ALLOW_BROKER_PAPER`          | **false** | Hard-pinned default.                   |
| `LIVE_TRADING_UNSUPPORTED`    | **true**  | CLI rejects `--mode live`.             |
| `NO_ORDER_PLACEMENT`          | **true**  | Reporters/seeders never call any order path. |
| `REPLAY_NOT_PAPER`            | **true**  | Replay candidates are not trade evidence. |
| `BACKFILL_NOT_PAPER`          | **true**  | Backfill snapshots are not trade evidence. |
| `NO_FABRICATION`              | **true**  | Seeders emit `NO_LOCAL_BACKFILL_DATA` honestly. |
| `BROKER_PAPER_CANARY_BLOCKED` | **true**  | Unlock gate has not flipped.           |

This LATEST refresh is a documentation pass. It does **NOT** flip any
flag, mutate any safety state file, or place any order.

## 3. v3.27 — what shipped today

### ETAP 2 — backfill snapshot seeder
- `scripts/seed_backfill_snapshots.py` (~580 LOC) — derives per-symbol
  backfill snapshots from local ledger / market_data artefacts.
- Output: `learning-loop/backfill_snapshots/*.json` (15 symbols seeded
  via `LEDGER_DERIVED_PARTIAL` path).
- Status doc: `docs/BACKFILL_SNAPSHOT_STATUS.md` auto-regenerates.
- Verdict semantics: `NO_LOCAL_BACKFILL_DATA` / `LEDGER_DERIVED_PARTIAL`
  / `LOCAL_BACKFILL_AVAILABLE`.
- No synthetic OHLCV — refuses to fabricate.

### ETAP 3 — replay discovery wired to seeded data
- `scripts/replay_entry_candidate_discovery.py` consumes the seeded
  backfill snapshots and emits replay candidates per strategy.
- Replay candidates are NOT trade evidence (`REPLAY_NOT_PAPER`).

### Agent 3A — near-miss + variant + queue seeders
- `scripts/seed_near_miss_from_evidence.py` (~530 LOC) — derives
  near-miss rows from REAL evidence + REPLAY candidates + BACKFILL
  snapshots. Source distribution tracked.
- `scripts/seed_strategy_variant_quarantine.py` (~310 LOC) — registers
  quarantined variants (NEVER auto-promotes).
- `scripts/seed_shadow_candidate_queue.py` (~580 LOC) — populates the
  shadow-candidate queue with priority signals.
- Tests: 13 + 9 + (~10 new each) — all green.

### Agent 3B — watchlist priority + diag integration
- `scripts/build_trigger_watchlist.py` upgraded to v3.27 with
  P1/P2/P3/BLOCKED priority rubric.
- New schema fields: `distance_to_trigger`, `near_miss_count_7d`,
  `replay_candidate_support`, `variant_support`, `priority`,
  `priority_reason`.
- Watchlist-aware monitor diagnostic integration.

### ETAP 9-11 — pre-cal separation + density plan + workflow
- `scripts/build_opportunity_density_plan.py` (~660 LOC) —
  section-by-section opportunity density plan.
- `scripts/build_confidence_precalibration_readiness.py` separated
  from runtime pre-calibration concerns.
- New workflow surface for the v3.27 seeders chain.

## 4. Tests — what is green

| Suite             | Tests | Status |
| ----------------- | ----- | ------ |
| v3.27 (new)       | 90    | OK     |
| v3.26 regression  | 89    | OK     |
| v3.24+v3.25       | 64    | OK     |
| v3.22+v3.30       | 62    | OK (1 skipped) |
| **Total checked** | **305** | **OK** |

## 5. Hard-pinned guarantees

EDGE_GATE_ENABLED=false. ALLOW_BROKER_PAPER=false.
LIVE_TRADING_UNSUPPORTED. NO_ORDER_PLACEMENT. REPLAY_NOT_PAPER.
BACKFILL_NOT_PAPER. NO_FABRICATION.

- No broker flag flipped.
- No order placed.
- No live trading enabled.
- No strategy threshold automatically lowered.
- No variant promoted to active runtime.
- No paid services added.
- No fabricated evidence — seeders honestly emit `NO_LOCAL_BACKFILL_DATA`
  when no local data exists.
- LLM stays advisory only.
- Canary stays preflight-only.
- Replay / near-miss / shadow / backfill candidates are NOT trade evidence.

## 6. What v3.27 explicitly does NOT do

- Flip `EDGE_GATE_ENABLED`, `ALLOW_BROKER_PAPER`, `LIVE_TRADING_ENABLED`,
  `GO_LIVE`, `BROKER_EXECUTION_ENABLED`, `OPERATOR_APPROVED_BROKER_PAPER_CANARY`.
- Call `submit_order`, `place_order`, `safe_close`, `place_stock_order`,
  `place_crypto_order`, `place_option_order`, `close_position`,
  `close_all_positions` in any new code.
- Import `alpaca_orders` from any new module.
- Mutate readiness counters manually.
- Fabricate market data, shadow records, outcomes, P/L.
- Generate synthetic OHLCV as real backfill.
- Count replay / near-miss / shadow / backfill / fixture / quarantine
  variant as paper edge.
- Reduce any risk threshold automatically.
- Promote a quarantined variant to active runtime.
- Increase position sizes / leverage.
- Add paid APIs, paid services, paid market data.
- Add LLM calls to the runtime trading path.
- Bypass evidence gates.
- Commit secrets.
- Force-push.

## 7. v3.27 standing markers

EDGE_GATE_ENABLED=false | ALLOW_BROKER_PAPER=false | LIVE_TRADING_UNSUPPORTED |
NO_ORDER_PLACEMENT | REPLAY_NOT_PAPER | BACKFILL_NOT_PAPER | NO_FABRICATION |
PURE_LOCAL_FILE_OPERATIONS | NEAR_MISS_IS_NOT_TRADE_EVIDENCE |
SHADOW_IS_NOT_BROKER_PAPER | LLM_ADVISORY_ONLY
