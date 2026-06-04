"""v3.19.0 (2026-06-04) — ETAP 3 — Evidence Source Separation.

Closes audit-board STRAT-003 follow-up: the system MUST distinguish three
classes of empirical evidence about strategy behaviour, and refuse to mix
them as if they were equivalent.

WHY
---
The audit board on 2026-06-02 reaffirmed "NOT_SAFE_FOR_LIVE_TRADING".
The original `paper_experiment.py` ledger conflated PAPER trades with
anything else that called `record_paper_trade(...)`. A backtest replay
script or an event-replay scenario could (in principle) write to the
same JSONL and inflate `n_closed`, which would silently push a strategy
into EDGE_APPROVED_FOR_EXPERIMENT without any actual paper trading.

This module introduces an enum `EvidenceSource` (BACKTEST / REPLAY /
PAPER) and helpers `is_paper_only(...)` + `is_triage_only(...)` so every
ingestion path declares what kind of evidence it is producing.

CONTRACT
--------
- BACKTEST  — historical replay from `backtest/run.py` or similar. Used
              for *triage* (strategy candidate screening) only. CANNOT
              approve edge.
- REPLAY    — event-driven scenario replay (geopolitical event recall,
              earnings cycle, regime shift). Used for *triage* + stress
              testing. CANNOT approve edge.
- PAPER     — recorded by the live paper-trading pipeline. ONLY this
              class is allowed to feed into `edge_gate_decision(...)`.

Functions are pure. No external API calls. Deterministic. Fail-soft.

FREE OPERATION
--------------
The enum has zero runtime cost. There are no paid APIs invoked.

EXAMPLES
--------
    >>> from shared.evidence_source import EvidenceSource, is_paper_only
    >>> is_paper_only(EvidenceSource.PAPER)
    True
    >>> is_paper_only(EvidenceSource.BACKTEST)
    False
    >>> is_triage_only(EvidenceSource.BACKTEST)
    True
    >>> is_triage_only(EvidenceSource.PAPER)
    False
"""

from __future__ import annotations

from enum import Enum


class EvidenceSource(str, Enum):
    """The class of evidence a single ledger record belongs to."""

    BACKTEST = "BACKTEST"   # historical replay, triage only
    REPLAY = "REPLAY"        # event-driven replay, triage + stress only
    PAPER = "PAPER"          # paper trading, edge approval candidate


# ─── Helpers ──────────────────────────────────────────────────────────────────


def is_paper_only(source: EvidenceSource | str | None) -> bool:
    """Only PAPER counts as edge-approval evidence.

    Accepts both an enum instance and a raw string (tolerant of
    lower-case forms to be robust when reading old JSONL). Anything not
    explicitly PAPER returns False — the default is to refuse.
    """
    try:
        if source is None:
            return False
        if isinstance(source, EvidenceSource):
            return source == EvidenceSource.PAPER
        if isinstance(source, str):
            return source.strip().upper() == EvidenceSource.PAPER.value
        return False
    except Exception:
        return False


def is_triage_only(source: EvidenceSource | str | None) -> bool:
    """BACKTEST + REPLAY are triage only — they do NOT count toward edge.

    Useful as the inverse of `is_paper_only` for ingest code that needs
    to drop or annotate non-paper records.
    """
    try:
        if source is None:
            return False
        if isinstance(source, EvidenceSource):
            return source in (EvidenceSource.BACKTEST, EvidenceSource.REPLAY)
        if isinstance(source, str):
            return source.strip().upper() in (
                EvidenceSource.BACKTEST.value, EvidenceSource.REPLAY.value
            )
        return False
    except Exception:
        return False


def parse_source(value: EvidenceSource | str | None,
                 *, default: EvidenceSource = EvidenceSource.PAPER) -> EvidenceSource:
    """Best-effort enum coercion.

    Default for missing / malformed source is PAPER — but that decision
    is intentional only because the legacy ledger (pre-v3.19) wrote
    records without a ``source`` field, and those were always paper
    records. New code paths MUST set the source explicitly. The triage
    pipelines (backtest, replay) MUST NOT rely on this default.
    """
    try:
        if isinstance(value, EvidenceSource):
            return value
        if isinstance(value, str):
            v = value.strip().upper()
            for s in EvidenceSource:
                if s.value == v:
                    return s
        return default
    except Exception:
        return default


__all__ = [
    "EvidenceSource",
    "is_paper_only",
    "is_triage_only",
    "parse_source",
]
