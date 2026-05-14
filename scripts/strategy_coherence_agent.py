#!/usr/bin/env python3
"""Thin CLI wrapper for the Strategy Coherence Agent.

Usage examples (see `--help` for full list):

    python3 scripts/strategy_coherence_agent.py
    python3 scripts/strategy_coherence_agent.py --json --no-files
    python3 scripts/strategy_coherence_agent.py --category intraday_profit_protection
    python3 scripts/strategy_coherence_agent.py --strict
    python3 scripts/strategy_coherence_agent.py --non-blocking
"""

from __future__ import annotations

import os
import sys

# Make `tools.strategy_coherence_agent` importable when run from anywhere.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.strategy_coherence_agent.main import run_cli   # noqa: E402

if __name__ == "__main__":
    sys.exit(run_cli())
