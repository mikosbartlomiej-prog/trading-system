"""News/social confirmation gates. Spec §8."""

from __future__ import annotations

from pathlib import Path

from ..models import Finding
from ..utils import read_text


CATEGORY = "signal_confirmation"
PRINCIPLE = "NEWS_SOCIAL_CONFIRMATION"


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    sc = root / "shared" / "signal_confirmation.py"
    if not sc.exists():
        findings.append(Finding(
            id="SIGCONF_MODULE_EXISTS",
            category=CATEGORY, severity="FAIL", status="FAIL",
            message="shared/signal_confirmation.py missing.",
            principle=PRINCIPLE,
            recommendation="Restore shared/signal_confirmation.py.",
            blocking=True,
        ))
        return findings

    text = read_text(sc)
    required = ["confirm_price_volume", "dedupe_event", "CooldownTracker",
                "article_fresh", "EventCache"]
    missing = [s for s in required if s not in text]
    findings.append(Finding(
        id="SIGCONF_API_PRESENT",
        category=CATEGORY,
        severity="PASS" if not missing else "FAIL",
        status="PASS" if not missing else "FAIL",
        message="signal_confirmation exposes confirm/dedupe/cooldown/freshness." if not missing
                else f"Missing: {missing}",
        principle=PRINCIPLE,
        recommendation="Restore missing primitives." if missing else "",
    ))

    # Backlog: defense/geo/twitter/reddit MAY not yet wire signal_confirmation
    # (acknowledged in ARCHITECTURE_VNEXT.md). Surface as WARN, not FAIL.
    #
    # v3.11.3 (2026-05-30) — fix audit rule: v3.10.1 refactored the 4 news
    # monitors to use the DRY helper `shared/news_signal_gate.py::gate_news_signal`
    # (replaces direct confirm_event_signal/confirm_price_volume calls).
    # The audit rule needs to recognize EITHER pattern.
    monitors = ["defense-monitor", "geo-monitor", "twitter-monitor", "reddit-monitor"]
    wired = []
    unwired = []
    for m in monitors:
        mp = root / m / "monitor.py"
        if not mp.exists():
            continue
        text = read_text(mp)
        if (
            "confirm_event_signal" in text
            or "confirm_price_volume" in text
            or "gate_news_signal" in text          # v3.10.1 DRY helper
            or "from news_signal_gate" in text     # v3.10.1 import marker
        ):
            wired.append(m)
        else:
            unwired.append(m)
    findings.append(Finding(
        id="SIGCONF_MONITORS_WIRED",
        category=CATEGORY,
        severity="PASS" if not unwired else "WARN",
        status="PASS" if not unwired else "WARN",
        message=f"Wired: {wired}. Unwired (backlog): {unwired}.",
        principle=PRINCIPLE,
        recommendation=("Wire signal_confirmation.confirm_event_signal() in: "
                        + ", ".join(unwired)) if unwired else "",
    ))

    return findings
