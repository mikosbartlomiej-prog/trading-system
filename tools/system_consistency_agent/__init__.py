"""
system_consistency_agent — deterministic auditor for the trading-system repo.

Single entry point: `tools.system_consistency_agent.main.run()`.
Public CLI: `scripts/system_consistency_agent.py`.

No LLM. No paid deps. Read-only against the working tree.
"""

from .main import run, run_cli  # noqa: F401
