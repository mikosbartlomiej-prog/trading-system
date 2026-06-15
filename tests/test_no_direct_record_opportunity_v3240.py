"""v3.24 (2026-06-15) — Enforcement: only signal_emitter may call record_opportunity.

WHY
---
Every monitor that wants to write to the opportunity ledger MUST route
through ``shared.signal_emitter.emit_signal_opportunity``. The emitter
is the only place that runs build_confidence_inputs + compute_confidence
and persists the resulting fields. If a monitor (or any new script)
bypasses the emitter and calls ``record_opportunity`` directly, the
ledger row will once again have ``confidence_score=null`` and the
shadow-eligibility gate stays stuck at zero.

AST-based static enforcement: walk every .py file under ``shared/``,
``scripts/``, and ``*-monitor/`` and ensure NO file (other than
``signal_emitter.py`` itself or files explicitly tagged
``LEGACY_DIRECT_LEDGER_ALLOWED``) calls or imports
``record_opportunity``.

HARD SAFETY
-----------
This test never imports any monitor module — only parses source code.
"""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# These files are explicitly allowed to keep direct ledger access.
# ``shared/signal_emitter.py`` is the single legitimate caller.
EXPLICIT_ALLOWLIST = {
    REPO_ROOT / "shared" / "signal_emitter.py",
    REPO_ROOT / "shared" / "signal_opportunity_ledger.py",
}

# Suffix-pattern allowlist for "duplicate-suffix" scratch files in the
# working tree (e.g. ``signal_emitter 2.py``). These exist as macOS
# Finder-created backups; ignore them entirely.
_DUPLICATE_SUFFIX_MARKERS = (" 2.py", " 3.py", " 4.py", " 5.py")

# Directories we walk.
WALK_DIRS = ("shared", "scripts")
# Monitor directories (any *-monitor/ at repo root).
MONITOR_GLOB = "*-monitor"

# Directories / paths we never walk.
SKIP_NAMES = {"tests", "docs", ".venv", "venv", "__pycache__", ".git"}


def _file_has_legacy_marker(path: Path) -> bool:
    """Return True if the file's first 10 lines contain
    ``LEGACY_DIRECT_LEDGER_ALLOWED``.
    """
    try:
        with open(path, encoding="utf-8") as f:
            head = []
            for _ in range(10):
                line = f.readline()
                if not line:
                    break
                head.append(line)
            return "LEGACY_DIRECT_LEDGER_ALLOWED" in "".join(head)
    except OSError:
        return False


def _is_duplicate_suffix(path: Path) -> bool:
    name = path.name
    return any(name.endswith(suffix) for suffix in _DUPLICATE_SUFFIX_MARKERS)


def _walk_python_files() -> list[Path]:
    out: list[Path] = []
    # shared/, scripts/
    for top in WALK_DIRS:
        top_path = REPO_ROOT / top
        if not top_path.exists():
            continue
        for root, dirs, files in os.walk(top_path):
            dirs[:] = [d for d in dirs if d not in SKIP_NAMES]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                out.append(Path(root) / fn)
    # *-monitor/
    for monitor_dir in REPO_ROOT.glob(MONITOR_GLOB):
        if not monitor_dir.is_dir():
            continue
        for root, dirs, files in os.walk(monitor_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_NAMES]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                out.append(Path(root) / fn)
    return out


def _find_direct_callsites(path: Path) -> list[str]:
    """Return list of "line:col description" strings for any direct
    ``record_opportunity`` reference in the file.
    """
    try:
        src = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        # Skip unparseable scratch files instead of FAILING the test.
        return []

    findings: list[str] = []
    for node in ast.walk(tree):
        # `record_opportunity(...)` - bare name call.
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "record_opportunity":
                findings.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno} call "
                    f"to record_opportunity(...)"
                )
            elif isinstance(func, ast.Attribute) and func.attr == "record_opportunity":
                findings.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno} call "
                    f"to <object>.record_opportunity(...)"
                )
        # `from signal_opportunity_ledger import record_opportunity`
        if isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[-1]
            if module == "signal_opportunity_ledger":
                for alias in node.names:
                    if alias.name == "record_opportunity":
                        findings.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno} "
                            f"`from signal_opportunity_ledger import "
                            f"record_opportunity`"
                        )
    return findings


class TestNoDirectRecordOpportunity(unittest.TestCase):
    """Enforce v3.24 single-entry-point contract."""

    def test_no_direct_record_opportunity_in_runtime_code(self):
        offenders: list[str] = []
        for path in _walk_python_files():
            if path in EXPLICIT_ALLOWLIST:
                continue
            if _is_duplicate_suffix(path):
                continue
            if _file_has_legacy_marker(path):
                continue
            findings = _find_direct_callsites(path)
            offenders.extend(findings)

        if offenders:
            msg = (
                "v3.24 contract violation: every runtime call to "
                "record_opportunity MUST go through "
                "shared.signal_emitter.emit_signal_opportunity. The "
                "following files bypass the emitter:\n  "
                + "\n  ".join(offenders)
                + "\n\nFix options:\n"
                "  1. Migrate the call to emit_signal_opportunity(...).\n"
                "  2. If the file genuinely needs direct ledger access "
                "(migration / diagnostic script), add the marker comment "
                "`# v3.24 LEGACY_DIRECT_LEDGER_ALLOWED` within the first "
                "10 lines."
            )
            self.fail(msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
