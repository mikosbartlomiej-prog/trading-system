"""v3.11.3 (2026-05-30) — Strategy-coherence: conflicting options premium limits.

Satisfies `tools/strategy_coherence_agent/checks/tests_coverage.py::OPTIONS_PREMIUM_CONFLICT`.

Why it matters
--------------
`config/aggressive_profile.json` declares options premium budget under several
keys (`max_options_premium_pct_equity`, `max_options_premium_deployed_pct`).
`docs/STRATEGY.md` quotes the same number in a sizing table. If those drift
apart over time, the allocator + risk_officer compute against a different
cap than the strategy doc claims — silent risk-budget violation.

This test pins them together: any single canonical value declared in the
profile must match its sibling values within tolerance, AND must match
the value quoted in STRATEGY.md (when present).
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_profile() -> dict:
    p = REPO_ROOT / "config" / "aggressive_profile.json"
    with open(p) as f:
        return json.load(f)


def _extract_strategy_md_options_premium_pct() -> float | None:
    """Find `max_options_premium ... <N>%` in docs/STRATEGY.md (any heading)."""
    md_path = REPO_ROOT / "docs" / "STRATEGY.md"
    if not md_path.exists():
        return None
    text = md_path.read_text()
    # Match table-cell `max_options_premium | **N%** equity`  OR  list-item form.
    m = re.search(r"max_options_premium[^|\n]*\|\s*\*?\*?(\d+(?:\.\d+)?)\s*%",
                  text, flags=re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(r"max_options_premium_pct_equity\s*\(?\s*(\d+(?:\.\d+)?)\s*%",
                  text, flags=re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


class TestOptionsPremiumConflict(unittest.TestCase):
    """Conflicting-options-premium-limits coherence check."""

    def test_no_conflicting_options_premium_in_profile(self):
        """Profile's `max_options_premium_pct_equity` and
        `max_options_premium_deployed_pct` describe the same budget — they
        MUST equal within rounding (or be intentionally documented as
        different ratchets)."""
        profile = _load_profile()
        # max_options_premium_pct_equity — under "capital" / top-level
        top_keys = {}
        def _walk(d):
            for k, v in d.items():
                if isinstance(v, dict):
                    _walk(v)
                else:
                    top_keys[k] = v
        _walk(profile)
        a = top_keys.get("max_options_premium_pct_equity")
        b = top_keys.get("max_options_premium_deployed_pct")
        if a is None or b is None:
            self.skipTest(f"profile lacks one of the keys: a={a} b={b}")
        # MUST be equal (these are aliases for the same cap)
        self.assertAlmostEqual(
            float(a), float(b), places=4,
            msg=(
                f"OPTIONS_PREMIUM_CONFLICT: max_options_premium_pct_equity={a} "
                f"vs max_options_premium_deployed_pct={b} in aggressive_profile.json. "
                f"They name the same cap and MUST match. Either pick one canonical "
                f"key and remove the other, OR rename the second so its different "
                f"intent is clear (e.g. _at_risk_pct vs _deployed_pct)."
            ),
        )

    def test_strategy_md_quotes_match_profile(self):
        """If docs/STRATEGY.md quotes a percentage for `max_options_premium`,
        it must equal the profile's canonical value."""
        profile = _load_profile()
        # Find canonical value (search both common keys).
        def _find(d, target):
            for k, v in d.items():
                if k == target:
                    return v
                if isinstance(v, dict):
                    r = _find(v, target)
                    if r is not None:
                        return r
            return None
        canonical = _find(profile, "max_options_premium_pct_equity")
        if canonical is None:
            self.skipTest("profile has no max_options_premium_pct_equity")
        md_pct = _extract_strategy_md_options_premium_pct()
        if md_pct is None:
            self.skipTest("STRATEGY.md does not quote max_options_premium pct")
        # docs uses percent (25), profile uses fraction (0.25)
        profile_pct = float(canonical) * 100
        self.assertAlmostEqual(
            profile_pct, md_pct, places=1,
            msg=(
                f"OPTIONS_PREMIUM_CONFLICT: STRATEGY.md says {md_pct}% but "
                f"config/aggressive_profile.json::max_options_premium_pct_equity "
                f"is {canonical} ({profile_pct}%). Update one to match the other."
            ),
        )

    def test_at_risk_pct_is_subset_of_deployed_pct(self):
        """Logical invariant: at-risk premium ≤ deployed premium.
        (You cannot be 'at-risk' for more than you've deployed.)"""
        profile = _load_profile()
        def _find(d, t):
            for k, v in d.items():
                if k == t: return v
                if isinstance(v, dict):
                    r = _find(v, t)
                    if r is not None: return r
            return None
        deployed = _find(profile, "max_options_premium_deployed_pct")
        at_risk  = _find(profile, "max_options_premium_at_risk_pct")
        if deployed is None or at_risk is None:
            self.skipTest("profile missing both keys")
        self.assertLessEqual(
            float(at_risk), float(deployed),
            msg=(
                f"OPTIONS_PREMIUM_CONFLICT: at_risk_pct={at_risk} > "
                f"deployed_pct={deployed}. Cannot be at-risk for more than "
                f"deployed."
            ),
        )


if __name__ == "__main__":
    unittest.main()
