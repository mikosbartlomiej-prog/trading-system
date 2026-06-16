# Strategy variant quarantine (v3.27.0)

**Generated:** `2026-06-15T15:26:06.354042+00:00`
**git_head:** `7cbe74139c8d8ada43bfda120b59755ae9d4cd48`
**variants_seeded:** 4

Quarantined variants are SHADOW descriptions of proposed strategy changes. They NEVER touch the runtime trading path. `allowed_modes` is locked to `{replay, shadow}` — never `live` or `paper`. Promotion to active strategies requires a separate audited PR.

| Variant ID | Parent | Description | Status | Allowed modes | Source |
|---|---|---|---|---|---|
| `crypto-momentum--rsi_threshold_55` | `crypto-momentum` | Lower RSI threshold from 60 to 55 (entry band shift -5 points) | `QUARANTINED` | `replay, shadow` | `threshold_reality + near_miss seed` |
| `crypto-momentum--24h_bracket_relaxed_2pct` | `crypto-momentum` | Lower 24h move bracket floor from 3% to 2% (entry filter widening) | `QUARANTINED` | `replay, shadow` | `threshold_reality + near_miss seed` |
| `crypto-oversold-bounce--rsi_threshold_33` | `crypto-oversold-bounce` | Raise RSI threshold from 30 to 33 (entry band shift +3 points) | `QUARANTINED` | `replay, shadow` | `threshold_reality + near_miss seed` |
| `momentum-long--breakout_threshold_1_5pct` | `momentum-long` | Lower breakout threshold from 2.0% to 1.5% (entry sensitivity raise) | `QUARANTINED` | `replay, shadow` | `threshold_reality + near_miss seed` |

## Standing markers

- `EDGE_GATE_ENABLED=false`
- `ALLOW_BROKER_PAPER=false`
- `LIVE_TRADING_UNSUPPORTED`
- `NO_ORDER_PLACEMENT`
- `OBSERVATIONS_DO_NOT_COUNT_AS_OPPORTUNITIES`
- `REAL_MARKET_EVIDENCE_REMAINS_REQUIRED`
- `VARIANT_NEVER_AUTO_PROMOTED`
- `VARIANT_NEVER_REACHES_RUNTIME`
- `VARIANT_NEVER_ENABLES_LIVE_OR_PAPER`
- `SEEDER_DOES_NOT_FETCH_NETWORK`
