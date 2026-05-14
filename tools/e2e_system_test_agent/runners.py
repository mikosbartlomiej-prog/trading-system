"""Test runners — invoke unittest discovery + parse results."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TestRunResult:
    suite:   str
    ran:     int = 0
    failed:  int = 0
    errors:  int = 0
    skipped: int = 0
    seconds: float = 0.0
    output:  str = ""
    ok:      bool = True


_RE_RAN = re.compile(r"^Ran\s+(\d+)\s+tests?\s+in\s+([\d.]+)s", re.M)
_RE_RESULT = re.compile(r"^(?:OK|FAILED)(?:\s*\((.*)\))?", re.M)


def _parse(stdout: str, stderr: str, suite: str) -> TestRunResult:
    text = stdout + "\n" + stderr
    m = _RE_RAN.search(text)
    ran = int(m.group(1)) if m else 0
    secs = float(m.group(2)) if m else 0.0
    m2 = _RE_RESULT.search(text)
    failed = errors = skipped = 0
    ok = "OK" in text and "FAILED" not in text
    if m2 and m2.group(1):
        body = m2.group(1)
        for part in body.split(","):
            part = part.strip()
            if part.startswith("failures="):
                failed = int(part.split("=")[1])
            elif part.startswith("errors="):
                errors = int(part.split("=")[1])
            elif part.startswith("skipped="):
                skipped = int(part.split("=")[1])
        ok = failed == 0 and errors == 0
    return TestRunResult(
        suite=suite, ran=ran, failed=failed, errors=errors,
        skipped=skipped, seconds=secs, output=text[-4000:], ok=ok,
    )


def run_unittest(suite_path: str, *, cwd: Path) -> TestRunResult:
    """Run `python -m unittest discover -s <suite_path> -p test_*.py`."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "unittest", "discover",
             "-s", suite_path, "-p", "test_*.py", "-v"],
            capture_output=True, text=True, cwd=str(cwd), timeout=180,
        )
        return _parse(r.stdout, r.stderr, suite_path)
    except Exception as e:  # pragma: no cover
        return TestRunResult(suite=suite_path, ok=False,
                              output=f"runner crashed: {type(e).__name__}: {e}")


def run_default_suites(cwd: Path) -> list[TestRunResult]:
    """Run the suites the agent considers part of the E2E view."""
    suites = [
        "tests/architecture_vnext",
        "tests/e2e",
    ]
    results: list[TestRunResult] = []
    for s in suites:
        if (cwd / s).exists():
            results.append(run_unittest(s, cwd=cwd))
    return results
