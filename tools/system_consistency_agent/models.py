"""Data types used across check modules."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# Severity ordering used by the orchestrator to decide overall status.
SEVERITIES = ("INFO", "PASS", "WARN", "FAIL")
STATUSES = ("PASS", "WARN", "FAIL", "SKIP")


@dataclass
class Evidence:
    """One file:line:snippet excerpt supporting a Finding."""
    file: str
    line: int = 0
    snippet: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Finding:
    """A single check result. See spec §"Format wyniku"."""
    id: str
    category: str
    severity: str               # INFO | PASS | WARN | FAIL
    status: str                 # PASS | WARN | FAIL | SKIP
    message: str
    principle: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    recommendation: str = ""
    blocking: bool = False      # if true and status=FAIL → overall BLOCKED

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() if isinstance(e, Evidence) else e
                         for e in self.evidence]
        return d


@dataclass
class CategoryResult:
    """Aggregated state for one of the 15 categories."""
    name: str
    weight: int                 # contribution to total score
    findings: list[Finding] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for f in self.findings if f.status == "PASS")

    @property
    def warn_count(self) -> int:
        return sum(1 for f in self.findings if f.status == "WARN")

    @property
    def fail_count(self) -> int:
        return sum(1 for f in self.findings if f.status == "FAIL")

    @property
    def skip_count(self) -> int:
        return sum(1 for f in self.findings if f.status == "SKIP")

    @property
    def has_blocking_fail(self) -> bool:
        return any(f.blocking and f.status == "FAIL" for f in self.findings)

    def score(self) -> float:
        """0..weight points. Each FAIL drops weight by N, each WARN by N/2."""
        if not self.findings:
            return 0.0
        # Strict scoring: blocking FAIL → 0; non-blocking FAIL costs 60% of weight
        # split per finding; WARN costs 25% split per finding; PASS adds nothing
        # negative. Cap at [0, weight].
        score = float(self.weight)
        n = len(self.findings)
        for f in self.findings:
            if f.status == "FAIL" and f.blocking:
                return 0.0
            if f.status == "FAIL":
                score -= self.weight * 0.6 / max(1, n)
            elif f.status == "WARN":
                score -= self.weight * 0.25 / max(1, n)
        return max(0.0, score)

    def overall_status(self) -> str:
        if self.has_blocking_fail:
            return "BLOCKED"
        if self.fail_count > 0:
            return "FAIL"
        if self.warn_count > 0:
            return "WARN"
        return "PASS"

    def to_dict(self) -> dict:
        return {
            "name":            self.name,
            "weight":          self.weight,
            "score":           round(self.score(), 2),
            "status":          self.overall_status(),
            "pass":            self.pass_count,
            "warn":            self.warn_count,
            "fail":            self.fail_count,
            "skip":            self.skip_count,
            "blocking_fail":   self.has_blocking_fail,
            "findings":        [f.to_dict() for f in self.findings],
        }


@dataclass
class AuditReport:
    """Top-level report returned by the orchestrator."""
    overall_status: str = "PASS"   # PASS | WARN | FAIL | BLOCKED
    score: float = 100.0
    generated_at: str = ""
    repo_sha: str = ""
    categories: dict[str, CategoryResult] = field(default_factory=dict)

    @property
    def all_findings(self) -> list[Finding]:
        out: list[Finding] = []
        for cat in self.categories.values():
            out.extend(cat.findings)
        return out

    def to_dict(self) -> dict:
        findings = self.all_findings
        summary = {
            "pass": sum(1 for f in findings if f.status == "PASS"),
            "warn": sum(1 for f in findings if f.status == "WARN"),
            "fail": sum(1 for f in findings if f.status == "FAIL"),
            "skip": sum(1 for f in findings if f.status == "SKIP"),
        }
        return {
            "overall_status":  self.overall_status,
            "score":           round(self.score, 2),
            "generated_at":    self.generated_at,
            "repo_sha":        self.repo_sha,
            "summary":         summary,
            "categories":      {n: c.to_dict() for n, c in self.categories.items()},
            "findings":        [f.to_dict() for f in findings],
        }
