"""Check modules. Each exposes `run(root: Path) -> list[Finding]`."""

from . import (
    paper_only,
    autonomy_trading,
    code_autonomy,
    free_tier,
    deterministic_execution,
    portfolio_risk,
    options_safety,
    signal_confirmation,
    state_policy,
    learning_loop,
    emergency_remediation,
    auditability,
    workflows,
    security,
    documentation,
)

# Ordered (matches spec §"NAJWAŻNIEJSZE PRINCIPLES" 1..15)
CATEGORY_MODULES = [
    ("paper_only",                 paper_only,                 15),
    ("trading_autonomy",           autonomy_trading,           12),
    ("deterministic_execution",    deterministic_execution,    12),
    ("portfolio_risk",             portfolio_risk,             10),
    ("code_autonomy",              code_autonomy,              10),
    ("options_safety",             options_safety,              8),
    ("state_policy",               state_policy,                7),
    ("emergency_remediation",      emergency_remediation,       7),
    ("workflows",                  workflows,                   6),
    ("security",                   security,                    5),
    ("documentation",              documentation,               5),
    ("signal_confirmation",        signal_confirmation,         5),
    ("learning_loop",              learning_loop,               4),
    ("auditability",               auditability,                4),
    ("free_tier",                  free_tier,                   3),
]
