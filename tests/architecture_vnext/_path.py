"""Shared sys.path bootstrap for the architecture vnext test pack.

Importing this module from test_*.py adds repo's shared/, learning-loop/,
and scripts/ to sys.path so test files can `import runtime_config`,
`import portfolio_risk`, etc. directly.
"""
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for _sub in ("shared", "learning-loop", "scripts"):
    p = os.path.join(_REPO_ROOT, _sub)
    if p not in sys.path:
        sys.path.insert(0, p)
