"""Strategy-coherence checks. Each module exposes `run(root) -> list[Finding]`.

CATEGORY_MODULES is the canonical ordered list consumed by the orchestrator.
Weights sum to ~100; the actual normalisation happens in main.run().
"""

from __future__ import annotations

from pathlib import Path

from . import (
    strategy_aggressiveness,
    capital_deployment,
    account_awareness,
    learning_loop_allocator,
    regime_event_switch,
    momentum_scoring,
    intraday_profit_protection,
    intraday_trend_management,
    options_strategy_consistency,
    risk_consistency,
    autonomy_and_determinism,
    auditability,
    runtime_state_policy,
    tests_coverage,
    documentation_parity,
)


# (name, module, weight). Weight = contribution to total 0-100 score.
CATEGORY_MODULES = [
    ("strategy_aggressiveness",      strategy_aggressiveness,       8),
    ("capital_deployment",           capital_deployment,           10),
    ("account_awareness",            account_awareness,             8),
    ("learning_loop_allocator",      learning_loop_allocator,       6),
    ("regime_event_switch",          regime_event_switch,           8),
    ("momentum_scoring",             momentum_scoring,              5),
    ("intraday_profit_protection",   intraday_profit_protection,   12),
    ("intraday_trend_management",    intraday_trend_management,     4),
    ("options_strategy_consistency", options_strategy_consistency,  6),
    ("risk_consistency",             risk_consistency,             10),
    ("autonomy_and_determinism",     autonomy_and_determinism,      8),
    ("auditability",                 auditability,                  5),
    ("runtime_state_policy",         runtime_state_policy,          5),
    ("tests_coverage",               tests_coverage,                4),
    ("documentation_parity",         documentation_parity,          5),
]


def collect_conflicting_values(root: Path) -> list:
    """Aggregate same-name numeric settings across known config + doc files.

    Delegates to `documentation_parity.scan_conflicting_values` so a single
    pass produces both the top-level `conflicting_values` array AND the
    findings inside `documentation_parity`.
    """
    return documentation_parity.scan_conflicting_values(root)
