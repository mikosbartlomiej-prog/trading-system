"""Test inventory — classify tests by type / staleness / weakness."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TestRecord:
    path: str
    test_class: str = ""
    test_name: str = ""
    classification: str = "unit"     # unit | integration | e2e | weak
    has_assertions: bool = True
    asserts_count: int = 0
    line: int = 0


_RE_TEST_DEF = re.compile(r"^\s*def\s+(test_\w+)\s*\(")
_RE_CLASS_DEF = re.compile(r"^\s*class\s+(\w+)\s*\(")


def _classify(path: str, name: str, body: str) -> str:
    p = path.lower()
    n = name.lower()
    if "/e2e/" in p or "_e2e" in n:
        return "e2e"
    if "integration" in p or "integration" in n:
        return "integration"
    if body.count("assert ") == 0 and body.count(".assert") == 0:
        return "weak"
    return "unit"


def scan(root: Path | None = None) -> list[TestRecord]:
    r = root or Path(__file__).resolve().parent.parent.parent
    out: list[TestRecord] = []
    for tests_dir in [r / "tests", r / "learning-loop"]:
        if not tests_dir.exists():
            continue
        for path in tests_dir.rglob("test_*.py"):
            relp = str(path.relative_to(r))
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            current_cls = ""
            for i, line in enumerate(lines, start=1):
                m_cls = _RE_CLASS_DEF.match(line)
                if m_cls:
                    current_cls = m_cls.group(1)
                    continue
                m_tst = _RE_TEST_DEF.match(line)
                if m_tst:
                    name = m_tst.group(1)
                    body = "\n".join(lines[i:i + 30])  # peek 30 lines
                    cls = _classify(relp, name, body)
                    asserts = body.count("assert ") + body.count("self.assert")
                    out.append(TestRecord(
                        path=relp, test_class=current_cls,
                        test_name=name,
                        classification=cls,
                        has_assertions=asserts > 0,
                        asserts_count=asserts,
                        line=i,
                    ))
    return out


def summary(records: list[TestRecord]) -> dict:
    total = len(records)
    by_cls = {"unit": 0, "integration": 0, "e2e": 0, "weak": 0}
    for r in records:
        by_cls[r.classification] = by_cls.get(r.classification, 0) + 1
    return {
        "total":            total,
        "by_classification": by_cls,
        "without_asserts":  sum(1 for r in records if not r.has_assertions),
    }
