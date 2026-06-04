"""v3.15.0 (2026-06-04) — SourceQualityPolicy.

Closes audit-board feedback FB-006 (formal Tier 1/2/3 source classification)
+ FB-014 (social media de-prioritization) + FB-015 (DD as context not trigger).

WHY
---
Trader feedback: Reddit/Twitter are secondary sources. Twitter is only useful
if the tweet comes from the primary source (the person/institution at the
center of the event). Verified DD can be context but is not a day-trading
trigger because catalysts can take months. Defense/DOJ filings are primary.

`event_scoring.py` already had per-source credibility numbers, but no formal
Tier 1/2/3 policy and no hard rule preventing Tier 3 alone from raising
confidence to trade level.

CONTRACT
--------
This module classifies sources into 3 tiers and exposes:
  - `tier_for(source_type)` — int 1/2/3 or None for unknown
  - `tier_for_label(source_type)` — short human-readable tier label
  - `confidence_ceiling(tier)` — max confidence component contribution
  - `is_day_trade_eligible(tier)` — Tier 1 yes, Tier 2 only with price/volume
    confirmation, Tier 3 never alone

Risk engine + confidence builder consult this module. A trade NEVER goes
through purely from Tier 3 input. Tier 2 DD needs price/volume confirmation
(checked by signal_confirmation.py).

Tiers
-----
**Tier 1 (Primary):** Cred 75-90
  - SEC filings (10-K, 10-Q, 8-K, Form 4)
  - SEC EDGAR Atom feed
  - DOJ press releases
  - Federal Reserve / Treasury announcements
  - DoD contract awards (DefenseDOTGov RSS)
  - Court filings (where available)
  - Official corporate announcements (Reuters/AP wires of these)
  - Official accounts of person/institution at the center of the event
    (verified Twitter/Bluesky of CEOs, government officials, agencies)
  - House Clerk financial disclosure XML feed (politicians)

**Tier 2 (Verified/Curated):** Cred 55-70
  - Reuters / Bloomberg / WSJ / FT articles linking primary source
  - Verified-authorship DD posts on Reddit (whitelisted authors)
  - Analyst reports from established sellside firms
  - Verified financial news (CNBC business segments with primary citation)

**Tier 3 (Social/Secondary):** Cred 30-50
  - Reddit (non-whitelisted authors)
  - Twitter/X (non-primary accounts)
  - Stocktwits, forums
  - Reposts without citation
  - Influencer commentary

POLICY ENFORCED
---------------
1. Tier 1 alone CAN reach trade-eligible confidence after market validation.
2. Tier 2 alone CAN reach trade-eligible confidence ONLY with price/volume
   confirmation (`signal_confirmation`).
3. Tier 3 alone CANNOT raise confidence above ALERT_ONLY threshold (0.65 cap).
4. DD (Tier 2) is NOT a day-trade trigger unless price moves within 24h with
   volume confirmation.
5. Unknown source → treated as Tier 3 by default (safer).

NEVER
-----
- Tier 3 input does not raise confidence beyond cap.
- No promotion across tiers.
- Risk engine always final.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

# ─── Tier enum (string for JSON-friendliness) ─────────────────────────────────

TIER_1 = "tier_1_primary"
TIER_2 = "tier_2_verified"
TIER_3 = "tier_3_social"
TIER_UNKNOWN = "tier_unknown"

VALID_TIERS = (TIER_1, TIER_2, TIER_3, TIER_UNKNOWN)

# Confidence ceiling per tier — max contribution to confidence score
# component from this source ALONE (without confirmation).
CONFIDENCE_CEILING = {
    TIER_1:       1.00,   # primary can drive full confidence
    TIER_2:       0.75,   # verified — needs market confirmation for top tier
    TIER_3:       0.45,   # social — caps below ALLOW threshold of 0.65
    TIER_UNKNOWN: 0.35,   # unknown — even more conservative
}


# ─── Source-type → tier mapping ───────────────────────────────────────────────

# Maps source_type strings (used by event_scoring.py + monitors) to tiers.
# Add new sources here when new monitors come online.
TIER_MAP = {
    # ── TIER 1 (primary) ──────────────────────────────────────────────────────
    "sec_edgar":              TIER_1,
    "sec_filing":             TIER_1,
    "sec_form_4":             TIER_1,
    "sec_8k":                 TIER_1,
    "sec_10k":                TIER_1,
    "doj_press":              TIER_1,
    "doj_filing":             TIER_1,
    "dod_contract":           TIER_1,
    "defense_contract":       TIER_1,
    "federal_reserve":        TIER_1,
    "treasury":               TIER_1,
    "fomc":                   TIER_1,
    "court_filing":           TIER_1,
    "house_clerk_xml":        TIER_1,
    "capitol_trades_ptr":     TIER_1,
    "ptr_filing":             TIER_1,
    "official_government":    TIER_1,
    "tracked_admin":          TIER_1,
    "tracked_pol_insider":    TIER_1,
    "company_official":       TIER_1,
    "verified_ceo":           TIER_1,
    "tracked_corp_ceo":       TIER_1,

    # ── TIER 2 (verified / curated) ───────────────────────────────────────────
    "reuters":                TIER_2,
    "reuters_ap":             TIER_2,
    "bloomberg":              TIER_2,
    "wsj":                    TIER_2,
    "ft":                     TIER_2,
    "cnbc":                   TIER_2,
    "marketwatch":            TIER_2,
    "major_outlet":           TIER_2,
    "tracked_pol_top":        TIER_2,
    "tracked_dd":             TIER_2,        # whitelisted DD authors
    "verified_analyst":       TIER_2,
    "newsapi_curated":        TIER_2,
    "tweet_verified_pol":     TIER_2,

    # ── TIER 3 (social / secondary) ───────────────────────────────────────────
    "reddit":                 TIER_3,
    "reddit_anon":            TIER_3,
    "reddit_wsb":             TIER_3,
    "twitter_anon":           TIER_3,
    "twitter_unknown":        TIER_3,
    "stocktwits":             TIER_3,
    "tracked_anon_trader":    TIER_3,
    "forum_post":             TIER_3,
    "blog":                   TIER_3,
    "wsb":                    TIER_3,
    "social":                 TIER_3,
    "rumor":                  TIER_3,
    "speculation":            TIER_3,
}


@dataclass(frozen=True)
class SourceClassification:
    source_type:           str
    tier:                  str
    confidence_ceiling:    float
    day_trade_eligible_alone: bool
    rationale:             str

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Public API ───────────────────────────────────────────────────────────────

def tier_for(source_type: str | None) -> str:
    """Classify source_type → tier label. Unknown → TIER_UNKNOWN (safer)."""
    if not source_type:
        return TIER_UNKNOWN
    key = str(source_type).strip().lower()
    return TIER_MAP.get(key, TIER_UNKNOWN)


def tier_number(tier: str) -> int:
    """Tier label → number (1, 2, 3, 9 for unknown)."""
    return {TIER_1: 1, TIER_2: 2, TIER_3: 3}.get(tier, 9)


def confidence_ceiling_for(source_type: str | None) -> float:
    """Max confidence contribution a single source of this tier can drive."""
    return CONFIDENCE_CEILING[tier_for(source_type)]


def is_day_trade_eligible_alone(source_type: str | None) -> bool:
    """Can this single source carry a day-trade signal without confirmation?

    Only Tier 1. Tier 2 needs market confirmation. Tier 3 / unknown never.
    """
    return tier_for(source_type) == TIER_1


def classify(source_type: str | None, *,
              confirmation_present: bool = False) -> SourceClassification:
    """Full classification — used by signal builders + audit log.

    `confirmation_present` is True when price/volume confirmation has
    been independently verified (e.g. signal_confirmation.gate_news_signal
    passed). Tier 2 + confirmation = day-trade eligible.
    """
    tier = tier_for(source_type)
    ceiling = CONFIDENCE_CEILING[tier]
    eligible_alone = is_day_trade_eligible_alone(source_type)
    eligible = eligible_alone or (tier == TIER_2 and confirmation_present)

    if tier == TIER_1:
        rationale = "primary source — day-trade eligible"
    elif tier == TIER_2 and confirmation_present:
        rationale = "verified source + confirmation — eligible"
    elif tier == TIER_2:
        rationale = "verified source — confirmation required for day-trade"
    elif tier == TIER_3:
        rationale = "social/secondary — ceiling capped below ALLOW threshold"
    else:
        rationale = "unknown source — treated as social (safer default)"

    return SourceClassification(
        source_type=source_type or "",
        tier=tier,
        confidence_ceiling=ceiling,
        day_trade_eligible_alone=eligible,
        rationale=rationale,
    )


def dd_is_day_trade_trigger(source_type: str | None,
                              has_price_confirmation: bool = False,
                              has_volume_confirmation: bool = False,
                              ) -> bool:
    """FB-015: DD is NOT a day-trade trigger without price AND volume
    confirmation.

    Returns False when:
      - source is Tier 2 DD without both confirmations
      - source is Tier 3 (DD posted on social w/o whitelisted author)
    """
    tier = tier_for(source_type)
    if tier == TIER_1:
        return True   # primary source — separate rules
    if tier == TIER_2:
        return has_price_confirmation and has_volume_confirmation
    return False  # Tier 3 / unknown — never day-trade trigger


__all__ = [
    "TIER_1", "TIER_2", "TIER_3", "TIER_UNKNOWN",
    "CONFIDENCE_CEILING", "TIER_MAP",
    "SourceClassification",
    "tier_for", "tier_number", "confidence_ceiling_for",
    "is_day_trade_eligible_alone", "classify",
    "dd_is_day_trade_trigger",
]
