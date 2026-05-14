#!/usr/bin/env python3
"""Thin CLI wrapper for tools.e2e_system_test_agent."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.e2e_system_test_agent.main import run_cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(run_cli())
