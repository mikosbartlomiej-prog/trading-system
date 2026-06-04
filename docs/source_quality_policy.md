# Source Quality Policy (v3.15.0)

**Module:** `shared/source_quality.py`
**Audit-board feedback closed:** FB-006, FB-014, FB-015
**Status:** shipped, tests green

## Three-tier classification

| Tier | Confidence ceiling | Day-trade eligible alone | Examples |
|---|---|---|---|
| **TIER 1 — Primary** | 1.00 | Yes (still passes risk engine) | SEC filings, DOJ press, DoD contracts, Federal Reserve, court filings, House Clerk XML, verified CEO accounts, government agency channels |
| **TIER 2 — Verified** | 0.75 | Only with price/volume confirmation | Reuters, Bloomberg, WSJ, FT, whitelisted DD authors, verified analyst reports |
| **TIER 3 — Social/Secondary** | 0.45 | **Never alone** | Reddit (non-whitelisted), Twitter/X anonymous, Stocktwits, forums, rumors |
| TIER UNKNOWN | 0.35 | Never | Unmapped source — treated even more conservatively |

## Why this exists

Trader feedback: Reddit and Twitter are secondary sources. Twitter only
useful when the tweet comes from the primary source of the event (e.g.
SecDef tweets a sanction). DD from verified authors can be valuable but
**catalyst timing is unknown** — DD may pay off tomorrow, in a month, or
in six months. So DD is NOT a day-trading trigger by itself.

## Hard policy rules

1. **Tier 3 alone** cannot raise confidence above ALERT_ONLY threshold (0.65).
   Caps at 0.45 component contribution.
2. **Tier 2 alone** requires price/volume confirmation
   (`signal_confirmation.gate_news_signal`) before reaching day-trade eligible.
3. **Tier 1 alone** is eligible — but still passes risk_officer, governor,
   PDT guard, etc.
4. **Unknown source** → treated as Tier 3 (safer default).
5. **Verified DD** (Tier 2 whitelisted author) — `dd_is_day_trade_trigger()`
   requires BOTH price AND volume confirmation.
6. Every signal must record its `source_type` in the audit log.

## How it integrates with confidence

In `confidence_builder.build_confidence_inputs`:

```python
source_type="reddit", source_confirmation_present=False
# → meta.source_tier = "tier_3_social"
# → meta.source_tier_capped = True
# → primary_score -= 0.05 (Tier 3 alone penalty)
```

`risk_officer` consults `_v3150_meta.block_recommended` and rejects if set.

## What CHANGES the policy

| Scenario | Result |
|---|---|
| Reddit + same-direction price move + volume spike | Caller may add Tier 1/2 confirmation; ceiling becomes 1.00 |
| DD post that links to SEC 8-K | Caller should pass `source_type="sec_8k"` (Tier 1) instead |
| Tweet from anonymous account citing primary source | Pass primary source as `source_type`; Twitter is just the messenger |

## Audit trail

Every signal logs:
- `source_type` raw string
- `tier` (resolved)
- `confidence_ceiling`
- `day_trade_eligible_alone`
- `rationale`

## Tests

`tests/test_feedback_v3150.py::TestSourceQualityPolicy` — 8 tests covering
each tier path, unknown defaulting, ceiling enforcement, eligibility rules,
and DD policy.

## Future

When new monitors come online, extend `TIER_MAP` with their source types.
Defaults to TIER_UNKNOWN if not mapped → automatically conservative.
