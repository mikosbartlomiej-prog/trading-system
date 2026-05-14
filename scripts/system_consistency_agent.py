#!/usr/bin/env python3
"""
Thin CLI wrapper for tools.system_consistency_agent.

Usage:
    python scripts/system_consistency_agent.py
    python scripts/system_consistency_agent.py --strict
    python scripts/system_consistency_agent.py --category paper_only
    python scripts/system_consistency_agent.py --json
    python scripts/system_consistency_agent.py --markdown
    python scripts/system_consistency_agent.py --output-dir reports/system-consistency
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.system_consistency_agent.main import run_cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(run_cli())
