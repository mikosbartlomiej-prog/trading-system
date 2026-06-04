"""v3.15.0 (2026-06-04) — EventMonitorInterface (FB-007 + FB-008).

Closes audit-board feedback FB-007 (primary-source event monitors) +
FB-008 (DOJ / legal proceedings monitor).

WHY
---
Trader feedback: defense monitor is a good pattern because DoD contract
awards are primary-source catalysts. Similar primary-source channels exist
for company-specific catalysts:
  - DOJ press releases (e.g. lawsuits filed)
  - SEC 8-K filings (Item 1.01 Material Definitive Agreements, Item 8.01
    Other Events, Item 5.02 Officer Departures, ...)
  - PACER court records (no free public API though)
  - Regulatory action announcements (FTC, FDA, FCC)

The existing defense-monitor + politician-monitor have grown organically
without a common interface. This module defines `EventMonitorInterface` so
future monitors plug in uniformly and inherit:
  - source tier classification (auto-Tier 1 for primary sources)
  - audit emission contract
  - rate limiting
  - dedup
  - market validation requirement before day-trade trigger

NEVER LIVE-CALLS
----------------
This file is an INTERFACE + reference mock implementation. It does NOT
make HTTP calls. Existing live monitors (defense-monitor/, politician-monitor/)
keep their own code but can be refactored to implement this interface
later (out-of-scope for v3.15.0).

CONTRACT
--------
Implementing class must provide:
  - `event_type` — short code like "doj_lawsuit_filed"
  - `source_tier` — TIER_1 / TIER_2 / TIER_3
  - `fetch_events(now_iso) -> Iterable[EventCandidate]` — read from data source
  - `is_day_trade_eligible(event) -> bool` — usually False for legal events
    (catalyst timing unknown)
  - `to_signal_dict(event) -> dict` — convert to monitor signal format

Default behavior:
  - All events are EMITted as `[POL-FILING]`-style alert emails (operator
    visibility), NOT auto-executed.
  - Tier 1 events still need risk_officer.evaluate_trade for execution.
  - Day-trade eligible only if explicit price/volume confirmation present.

DESIGN
------
Pure interface + reference mock. Real implementations live in their own
monitor directories.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict, field
from typing import Iterable, Optional

try:
    from source_quality import TIER_1, TIER_2, TIER_3, TIER_UNKNOWN
except ImportError:
    try:
        from shared.source_quality import TIER_1, TIER_2, TIER_3, TIER_UNKNOWN
    except ImportError:
        TIER_1 = "tier_1_primary"
        TIER_2 = "tier_2_verified"
        TIER_3 = "tier_3_social"
        TIER_UNKNOWN = "tier_unknown"


# ─── Event types ──────────────────────────────────────────────────────────────

# DOJ / legal
EVT_DOJ_LAWSUIT_FILED         = "doj_lawsuit_filed"
EVT_DOJ_LAWSUIT_UPDATE        = "doj_lawsuit_update"
EVT_DOJ_PRESS_RELEASE         = "doj_press_release"
EVT_REGULATORY_ACTION         = "regulatory_action"
EVT_SEC_8K_FILING             = "sec_8k_filing"
EVT_COURT_RULING              = "court_ruling"

# Defense / government / corporate primary
EVT_DEFENSE_CONTRACT_AWARD    = "defense_contract_award"
EVT_GOVERNMENT_ACTION         = "government_action"
EVT_COMPANY_OFFICIAL          = "company_official_announcement"
EVT_FED_ANNOUNCEMENT          = "fed_announcement"

VALID_EVENT_TYPES = (
    EVT_DOJ_LAWSUIT_FILED, EVT_DOJ_LAWSUIT_UPDATE, EVT_DOJ_PRESS_RELEASE,
    EVT_REGULATORY_ACTION, EVT_SEC_8K_FILING, EVT_COURT_RULING,
    EVT_DEFENSE_CONTRACT_AWARD, EVT_GOVERNMENT_ACTION, EVT_COMPANY_OFFICIAL,
    EVT_FED_ANNOUNCEMENT,
)


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EventCandidate:
    """Raw event surfaced by a monitor before any market validation."""
    event_id:           str             # unique dedup key (e.g. doj-press-2026-06-04-123)
    event_type:         str
    detected_at_iso:    str
    headline:           str
    summary:            str
    tickers:            tuple           # affected tickers (best-effort)
    source_url:         str
    source_tier:        str
    severity:           str             # "high" / "medium" / "low"
    catalyst_timing:    str             # "immediate" / "days" / "weeks_months" / "unknown"
    requires_day_trade_confirmation: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EventEmissionDecision:
    """Decision of what to do with a fetched event."""
    emit:                       bool
    day_trade_eligible:         bool
    requires_confirmation:      bool
    confidence_adjustment:      float
    rationale:                  str
    audit_payload:              dict


# ─── Interface ────────────────────────────────────────────────────────────────

class EventMonitorInterface(ABC):
    """Base class for primary-source event monitors.

    Concrete monitors implement `fetch_events` (reading from their free
    public data source) and override only methods that need monitor-specific
    behavior. The base class provides the common decision flow:
      1. Classify source tier.
      2. Apply rate limiting + dedup.
      3. Decide if event is day-trade eligible (default: only with
         confirmation + Tier 1).
      4. Compute conservative confidence adjustment.
      5. Emit audit event.
    """

    event_type: str = "generic_event"
    source_tier: str = TIER_1
    rate_limit_per_run: int = 3        # max events to emit per cron tick

    def __init__(self):
        self._seen_ids: set[str] = set()

    @abstractmethod
    def fetch_events(self, now_iso: str) -> Iterable[EventCandidate]:
        """Return raw event candidates from the data source. Fail-soft."""
        raise NotImplementedError

    def is_day_trade_eligible(self, event: EventCandidate) -> bool:
        """Default: only Tier 1 + immediate catalyst timing.

        Override if the monitor knows when an event is day-trade vs swing
        (e.g. earnings beat = immediate, lawsuit filing = weeks_months).
        """
        return (event.source_tier == TIER_1
                and event.catalyst_timing == "immediate")

    def confidence_adjustment(self, event: EventCandidate) -> float:
        """Conservative +/- adjustment.

        - Tier 1 immediate = +0.05
        - Tier 1 weeks/months = +0.02
        - Tier 2 = 0
        - Tier 3 = -0.05 (social rumour about legal/regulatory action)
        - Unknown = 0
        """
        t = event.source_tier
        timing = event.catalyst_timing
        if t == TIER_1:
            return 0.05 if timing == "immediate" else 0.02
        if t == TIER_2:
            return 0.0
        if t == TIER_3:
            return -0.05
        return 0.0

    def decide(self, event: EventCandidate) -> EventEmissionDecision:
        """Apply the standard policy to a single fetched event."""
        if event.event_id in self._seen_ids:
            return EventEmissionDecision(
                emit=False, day_trade_eligible=False,
                requires_confirmation=False, confidence_adjustment=0.0,
                rationale="dedup_already_seen", audit_payload={"event_id": event.event_id},
            )
        self._seen_ids.add(event.event_id)
        eligible = self.is_day_trade_eligible(event)
        adj = self.confidence_adjustment(event)
        rationale_bits = [f"tier={event.source_tier}", f"timing={event.catalyst_timing}"]
        if not eligible:
            rationale_bits.append("not_day_trade_eligible_emit_only")
        rationale = "; ".join(rationale_bits)
        return EventEmissionDecision(
            emit=True,
            day_trade_eligible=eligible,
            requires_confirmation=event.requires_day_trade_confirmation,
            confidence_adjustment=adj,
            rationale=rationale,
            audit_payload={
                "event_id":   event.event_id,
                "event_type": event.event_type,
                "tickers":    list(event.tickers),
                "tier":       event.source_tier,
                "severity":   event.severity,
                "url":        event.source_url,
            },
        )

    def run(self, now_iso: str) -> list[tuple[EventCandidate, EventEmissionDecision]]:
        """Convenience: fetch + decide for each. Caps at rate_limit_per_run."""
        out = []
        try:
            for ev in self.fetch_events(now_iso):
                if len(out) >= self.rate_limit_per_run:
                    break
                decision = self.decide(ev)
                if decision.emit:
                    out.append((ev, decision))
        except Exception:
            return out
        return out


# ─── Reference mock implementation (for tests + docs) ─────────────────────────

class MockDOJMonitor(EventMonitorInterface):
    """Reference mock implementation of a DOJ-press monitor.

    Real implementation would parse https://www.justice.gov/news (RSS) or
    SEC EDGAR 8-K Item 1.01. This mock returns a hard-coded list for tests.
    """
    event_type = EVT_DOJ_LAWSUIT_FILED
    source_tier = TIER_1
    rate_limit_per_run = 5

    def __init__(self, mock_events: list[EventCandidate] | None = None):
        super().__init__()
        self._mock = list(mock_events or [])

    def fetch_events(self, now_iso: str) -> Iterable[EventCandidate]:
        return list(self._mock)


__all__ = [
    "EVT_DOJ_LAWSUIT_FILED", "EVT_DOJ_LAWSUIT_UPDATE", "EVT_DOJ_PRESS_RELEASE",
    "EVT_REGULATORY_ACTION", "EVT_SEC_8K_FILING", "EVT_COURT_RULING",
    "EVT_DEFENSE_CONTRACT_AWARD", "EVT_GOVERNMENT_ACTION",
    "EVT_COMPANY_OFFICIAL", "EVT_FED_ANNOUNCEMENT",
    "VALID_EVENT_TYPES",
    "EventCandidate", "EventEmissionDecision",
    "EventMonitorInterface", "MockDOJMonitor",
]
