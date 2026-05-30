"""
Event Probability & Contrarian Reaction Layer

Interpretation layer between event detection (a news signal, a tweet, a
DoD contract scrape) and the trading decision. Decomposes each trigger
into 4 scores and yields a stance:

  FOLLOW_REACTION       -- credible event + market not over-reacting -> trade with the move
  IGNORE_EVENT          -- low credibility / negligible probability shift / weak reaction -> skip
  CONTRARIAN_CANDIDATE  -- weak event + strong market reaction       -> trade against the move
  WAIT_FOR_CONFIRMATION -- mid scores; let the next candle settle    -> defer

The point: today's geo / defense monitors fire on headline detection
alone. The market often uses news as a pretext for stop-hunts and
liquidity grabs. This module filters for those traps and surfaces
contrarian setups instead of always following the first reaction.

MVP scope (2026-05-06):
  - Heuristic scoring only (no external data lookups)
  - Scores 0-100, all caller-supplied; this module just normalises and
    combines them
  - Stocks/CFD only; options-chain & max-pain modelling are out of scope
  - Per docs/STRATEGY.md backlog entry "Event Probability & Contrarian
    Reaction Layer"

Source-types & default credibility (caller can override):
  filing                -> 90  (SEC, official corporate filing)
  contract_award        -> 85  (DoD contract, signed deal)
  official_government   -> 80  (POTUS, SecDef, SecState...)
  reuters_ap            -> 70  (major wires)
  major_outlet          -> 60  (Bloomberg, WSJ, FT, CNBC)
  niche_outlet          -> 50  (Defense One, Breaking Defense)
  tweet_verified_pol    -> 45  (verified politician tweet)
  tweet_verified_corp   -> 50  (verified CEO tweet)
  tweet_anon            -> 25  (anonymous account, even verified)
  rumor                 -> 15  (unverified / blog / forum)

Probability-shift hints (caller supplies, this is just guidance):
  signed_contract       -> 80  (a signed deal IS the future event)
  rate_decision         -> 90  (hard data point)
  earnings_release      -> 75
  budget_passed         -> 70
  policy_announced      -> 50  (spoken intent, not yet action)
  threat_or_warning     -> 25  (rhetoric)
  rumor_unconfirmed     -> 10
"""

from __future__ import annotations  # v3.11.3: PEP 604 (X | None) parseable on Py 3.9 (local) + 3.11 (CI).

# ─── Score thresholds ─────────────────────────────────────────────────────────

# A "weak" signal scores below this on credibility OR probability shift
WEAK_SCORE   = 40
# A "strong" market reaction is above this
STRONG_REACTION = 65
# Floor for "follow with confidence"
FOLLOW_FLOOR = 55


# ─── Source defaults (override per call when needed) ──────────────────────────

SOURCE_CREDIBILITY = {
    "filing":               90,
    "contract_award":       85,
    "official_government":  80,
    "tracked_corp_ceo":     75,   # T2: tech/defense CEO we explicitly track
    "reuters_ap":           70,
    "major_outlet":         60,
    "tracked_anon_trader":  55,   # T3: anon traders w/ track record (e.g. @aleabitoreddit)
    "niche_outlet":         50,
    "tweet_verified_corp":  50,
    "tweet_verified_pol":   45,
    "tweet_anon":           25,
    "rumor":                15,
}

EVENT_TYPE_PROB_SHIFT = {
    "signed_contract":   80,
    "rate_decision":     90,
    "earnings_release":  75,
    "budget_passed":     70,
    "policy_announced":  50,
    "threat_or_warning": 25,
    "rumor_unconfirmed": 10,
}


# ─── Scoring primitives ───────────────────────────────────────────────────────

def event_credibility(source_type: str,
                       corroborated: bool = False,
                       source_track_record: float | None = None) -> int:
    """
    Map source type to credibility score (0-100).

    `corroborated`: another source has the same item -> +10
    `source_track_record`: optional 0-1 multiplier (history of accuracy)
    """
    base = SOURCE_CREDIBILITY.get(source_type, 30)
    if corroborated:
        base += 10
    if source_track_record is not None and 0 <= source_track_record <= 1:
        base = int(base * (0.5 + 0.5 * source_track_record))
    return max(0, min(100, base))


def probability_shift(event_type: str,
                       magnitude: str = "normal") -> int:
    """
    Map event type to probability-shift score (0-100).

    `magnitude`: "small" (-15), "normal" (0), "large" (+15)
    """
    base = EVENT_TYPE_PROB_SHIFT.get(event_type, 30)
    bump = {"small": -15, "normal": 0, "large": 15}.get(magnitude, 0)
    return max(0, min(100, base + bump))


def market_reaction(price_move_atr: float,
                     volume_ratio: float,
                     gap_pct: float = 0.0) -> int:
    """
    Score how strongly the market reacted (0-100). Inputs:
      price_move_atr: today's |price move| / ATR(14). 1.0 = one ATR.
      volume_ratio:   today's volume / 20d avg volume. 1.0 = average.
      gap_pct:        opening gap as a percentage (0 if intraday).

    A "violent reaction" is multi-ATR move on multi-x volume + gap.
    """
    # ATR component: 0..1.0 ATR = 0..40, 1..2 = 40..70, >2 = 70..90
    atr_part = min(40.0 * price_move_atr, 90.0) if price_move_atr <= 1 else \
               (40.0 + min(50.0 * (price_move_atr - 1) / 1.5, 50.0))
    # Volume component: 1x avg = 20, 2x = 40, 3x+ = 60
    vol_part = min(20.0 * volume_ratio, 60.0)
    # Gap component
    gap_part = min(abs(gap_pct) * 5.0, 30.0)
    score = (atr_part * 0.55 + vol_part * 0.35 + gap_part * 0.10)
    return max(0, min(100, int(round(score))))


# ─── Decision ─────────────────────────────────────────────────────────────────

def decide_stance(credibility: int,
                   prob_shift: int,
                   reaction: int) -> tuple[str, str]:
    """
    Combine the three scores into a stance.

    Returns (stance, rationale) where stance is one of
    FOLLOW_REACTION | IGNORE_EVENT | CONTRARIAN_CANDIDATE | WAIT_FOR_CONFIRMATION.
    """
    weak_event = credibility < WEAK_SCORE or prob_shift < WEAK_SCORE
    big_move   = reaction >= STRONG_REACTION
    strong_event = credibility >= FOLLOW_FLOOR and prob_shift >= FOLLOW_FLOOR

    if weak_event and big_move:
        # Classic stop-hunt / liquidity-grab pattern: rumour-grade headline,
        # market over-reacting. Edge is on the OTHER side.
        return ("CONTRARIAN_CANDIDATE",
                f"weak event (cred {credibility}, shift {prob_shift}) + big reaction ({reaction}) "
                f"-> potential trap; consider opposite direction")

    if weak_event and not big_move:
        return ("IGNORE_EVENT",
                f"weak event (cred {credibility}, shift {prob_shift}) + soft reaction ({reaction}) "
                f"-> nothing to trade")

    if strong_event and big_move:
        return ("FOLLOW_REACTION",
                f"strong event (cred {credibility}, shift {prob_shift}) confirmed by reaction ({reaction})")

    if strong_event and not big_move:
        return ("FOLLOW_REACTION",
                f"strong event (cred {credibility}, shift {prob_shift}) — market hasn't priced it yet, "
                f"early-mover edge; reaction {reaction}")

    # Mid-range: both event and reaction are mediocre. Wait.
    return ("WAIT_FOR_CONFIRMATION",
            f"mid-range scores (cred {credibility}, shift {prob_shift}, reaction {reaction}); "
            f"defer until next candle / next data point")


def score_and_decide(*,
                     source_type: str,
                     event_type: str,
                     price_move_atr: float = 0.0,
                     volume_ratio: float   = 1.0,
                     gap_pct: float        = 0.0,
                     corroborated: bool    = False,
                     source_track_record: float | None = None,
                     magnitude: str        = "normal") -> dict:
    """
    Convenience wrapper that produces a full scoring report from raw inputs.

    Returns a dict with all four scores + final stance + rationale,
    suitable for embedding in a signal payload (and a journal entry).
    """
    credibility = event_credibility(source_type, corroborated, source_track_record)
    shift       = probability_shift(event_type, magnitude)
    reaction    = market_reaction(price_move_atr, volume_ratio, gap_pct)
    stance, rationale = decide_stance(credibility, shift, reaction)
    return {
        "credibility": credibility,
        "prob_shift":  shift,
        "reaction":    reaction,
        "stance":      stance,
        "rationale":   rationale,
        "inputs": {
            "source_type":         source_type,
            "event_type":          event_type,
            "price_move_atr":      price_move_atr,
            "volume_ratio":        volume_ratio,
            "gap_pct":             gap_pct,
            "corroborated":        corroborated,
            "source_track_record": source_track_record,
            "magnitude":           magnitude,
        },
    }
