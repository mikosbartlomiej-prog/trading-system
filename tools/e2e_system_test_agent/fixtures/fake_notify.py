"""FakeNotify — captures emails in-memory, never sends."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# Patterns that indicate a secret would have leaked into the email body.
_SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"Bearer\s+[A-Za-z0-9_.\-]{20,}"),
)


@dataclass
class CapturedEmail:
    subject: str
    body: str


@dataclass
class FakeNotify:
    sent: list[CapturedEmail] = field(default_factory=list)

    def send(self, subject: str, body: str) -> bool:
        self.sent.append(CapturedEmail(subject=subject, body=body))
        return True

    def by_subject_prefix(self, prefix: str) -> list[CapturedEmail]:
        return [e for e in self.sent if e.subject.startswith(prefix)]

    def assert_no_secret_leak(self) -> list[str]:
        """Return list of (subject, leak-pattern-name) tuples; empty list if clean."""
        leaks = []
        for e in self.sent:
            joined = e.subject + "\n" + e.body
            for pat in _SECRET_PATTERNS:
                if pat.search(joined):
                    leaks.append(f"{e.subject!r}: matched {pat.pattern}")
                    break
        return leaks

    def clear(self) -> None:
        self.sent.clear()
