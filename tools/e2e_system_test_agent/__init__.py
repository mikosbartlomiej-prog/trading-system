"""e2e_system_test_agent — end-to-end testing harness for the trading system.

Public entry: `tools.e2e_system_test_agent.main.run_cli()`.
CLI wrapper:  `scripts/e2e_system_test_agent.py`.

Invariants:
  - never submits a real order
  - never hits real network
  - never needs real secrets
  - tests pass with LLM_ENABLED=false
"""

from .main import run, run_cli  # noqa: F401
