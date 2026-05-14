"""audit_workflows.py — detects missing concurrency in fixture YAML."""
import os
import shutil
import sys
import tempfile
import unittest

import os, sys; sys.path.insert(0, os.path.dirname(__file__)); import _path  # noqa: F401

import audit_workflows


WF_BAD = """\
name: Bad Schedule
on:
  schedule:
    - cron: '0 * * * *'

permissions:
  contents: read

jobs:
  go:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""

WF_GOOD = """\
name: Good Schedule
on:
  schedule:
    - cron: '0 * * * *'

concurrency:
  group: ${{ github.workflow }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  go:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""

WF_WRITES_GIT = """\
name: Writes Git
on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  go:
    runs-on: ubuntu-latest
    steps:
      - name: commit
        run: |
          git add foo
          git commit -m "hi"
"""

WF_ECHO_SECRET = """\
name: Leaky
on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  go:
    runs-on: ubuntu-latest
    steps:
      - run: echo ${{ secrets.ANTHROPIC_TOKEN }}
"""


class TestAuditWorkflows(unittest.TestCase):
    def _audit(self, content: str) -> list[str]:
        from pathlib import Path
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write(content)
            path = Path(f.name)
        try:
            return audit_workflows.audit_workflow(path)
        finally:
            os.remove(path)

    def test_detects_missing_concurrency(self):
        issues = self._audit(WF_BAD)
        self.assertTrue(any("concurrency" in i for i in issues))

    def test_passes_when_concurrency_present(self):
        issues = self._audit(WF_GOOD)
        self.assertFalse(any("concurrency" in i for i in issues))

    def test_detects_git_without_write(self):
        issues = self._audit(WF_WRITES_GIT)
        self.assertTrue(any("git commit" in i or "git push" in i for i in issues))

    def test_detects_secret_echo(self):
        issues = self._audit(WF_ECHO_SECRET)
        self.assertTrue(any("echo-secret" in i for i in issues))


if __name__ == "__main__":
    unittest.main()
