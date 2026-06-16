"""v3.28.0 (2026-06-16) — Agent 3B / ETAP 10 — Discovery incident banner.

Shared helper used by the four v3.27 discovery reporters:

* ``build_shadow_candidate_queue.py``
* ``build_trigger_watchlist.py``
* ``build_opportunity_density_plan.py``
* ``build_confidence_precalibration_readiness.py``

These reporters MUST remain observation-only. During an active
``BROKER_REPAIR_REQUIRED`` incident this helper prepends a fixed
markdown banner to the report so the operator sees the incident
context immediately. The banner is informational ONLY — it never
removes rows, never promotes variants, never lowers thresholds,
never changes priorities, never enables trading paths.

Contract
========
* The helper reads ``learning-loop/broker_repair_required_latest.json``
  through ``shared.broker_repair_required.load_state``. If the helper
  module is unimportable for any reason, the banner is silently
  omitted — discovery reporters keep running.
* The banner is prepended ONLY when at least one
  ``BrokerRepairRequired`` entry exists. When no incident is active,
  the report markdown is returned verbatim.
* The banner is a single deterministic blockquote. The wording is
  fixed and is what the test suite asserts on. Each reporter passes
  its own report path so the banner can reference it for grep-ability.

Standing markers (reaffirmed inside the banner):
* ``EDGE_GATE_ENABLED=false``
* ``ALLOW_BROKER_PAPER=false``
* ``LIVE_TRADING_UNSUPPORTED``
* ``DISCOVERY_LAYER_OBSERVATION_ONLY``
* ``BANNER_NEVER_CHANGES_PRIORITIES_OR_VARIANTS``
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable

# ── State / runbook locations ────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNBOOK_PATH_RELATIVE = "docs/RUNBOOK_AVAXUSD_P13_2026-06-16.md"

# Status line is required by ETAP-10 spec verbatim.
INCIDENT_STATUS = "DISCOVERY_ACTIVE_BUT_TRADING_BLOCKED_BY_P13"


def _load_blocked_symbols() -> list[str]:
    """Return the sorted, de-duplicated symbol list currently in
    ``broker_repair_required`` state.

    Fail-soft: any import or read error → empty list. The reporter
    will treat that as "no incident" and skip the banner. That matches
    the contract — we never raise from the discovery layer.
    """
    # Make sure the project root is on sys.path so ``shared.…`` resolves
    # in both production (where the reporter is invoked as
    # ``python3 scripts/build_*.py``) and inside the unittest harness.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    try:
        from shared.broker_repair_required import load_state  # type: ignore
    except Exception:
        return []

    try:
        state = load_state()
    except Exception:
        return []

    if not isinstance(state, dict):
        return []

    symbols = []
    for sym in state.keys():
        try:
            s = str(sym).strip()
        except Exception:
            continue
        if s and s not in symbols:
            symbols.append(s)
    symbols.sort()
    return symbols


def build_incident_banner(blocked_symbols: Iterable[str]) -> str:
    """Construct the deterministic banner text.

    Returns a multi-line markdown blockquote followed by a blank line.
    The wording is what the test suite asserts on; do NOT vary by
    reporter name.
    """
    syms = [s for s in (str(x).strip() for x in blocked_symbols) if s]
    syms.sort()
    if not syms:
        return ""
    if len(syms) == 1:
        symbol_phrase = f"`{syms[0]}` in BROKER_REPAIR_REQUIRED state"
        list_phrase = f"`{syms[0]}`"
    else:
        symbol_phrase = (
            f"`{syms[0]}` (and {len(syms) - 1} more) in "
            f"BROKER_REPAIR_REQUIRED state"
        )
        list_phrase = ", ".join(f"`{s}`" for s in syms)

    lines = [
        f"> INCIDENT ACTIVE: {symbol_phrase}.",
        ">",
        f"> Blocked symbols: {list_phrase}",
        f"> Discovery layer remains active for analysis but trading "
        f"is BLOCKED until manual repair.",
        f"> Status: {INCIDENT_STATUS}",
        f"> See: [{RUNBOOK_PATH_RELATIVE}]({RUNBOOK_PATH_RELATIVE})",
        "",
        "",
    ]
    return "\n".join(lines)


def prepend_incident_banner(
    md_text: str,
    *,
    override_blocked_symbols: list[str] | None = None,
) -> str:
    """Public entry point for the four discovery reporters.

    * If ``BROKER_REPAIR_REQUIRED`` state lists at least one symbol,
      prepend the fixed banner to ``md_text``.
    * Otherwise return ``md_text`` verbatim.

    ``override_blocked_symbols`` is exposed for the unit tests so they
    can drive the function without touching the real on-disk state
    file. Discovery reporters never pass it in production.

    The function is total — it never raises. On any error the unchanged
    ``md_text`` is returned (fail-soft: never break a reporter).
    """
    try:
        if override_blocked_symbols is None:
            symbols = _load_blocked_symbols()
        else:
            symbols = [
                str(s).strip()
                for s in override_blocked_symbols
                if str(s).strip()
            ]
        if not symbols:
            return md_text
        banner = build_incident_banner(symbols)
        if not banner:
            return md_text
        return banner + md_text
    except Exception:
        return md_text


__all__ = [
    "build_incident_banner",
    "prepend_incident_banner",
    "INCIDENT_STATUS",
    "RUNBOOK_PATH_RELATIVE",
]
