"""Data types used by the Strategy Coherence Agent.

Intentionally NOT imported from `tools/system_consistency_agent.models` —
the two agents must be able to evolve independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


SEVERITIES   = ("INFO", "PASS", "WARN", "FAIL", "BLOCKED")
STATUSES     = ("PASS", "WARN", "FAIL", "BLOCKED", "SKIP")
OVERALL      = ("PASS", "WARN", "FAIL", "BLOCKED")


@dataclass
class Evidence:
    """A single file:line:snippet excerpt supporting a Finding."""
    file:    str
    line:    int = 0
    snippet: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Finding:
    """One strategy-coherence check result.

    A finding can flag a missing principle wiring, a conflict between
    documentation and code, or a missing test. Severity drives both the
    score and the exit code (see main._exit_code_for).
    """
    id:                str
    category:          str
    severity:          str                       # PASS | WARN | FAIL | BLOCKED
    status:            str                       # PASS | WARN | FAIL | BLOCKED | SKIP
    message:           str
    principle:         str = ""
    evidence:          list[Evidence] = field(default_factory=list)
    recommendation:    str = ""
    expected:          str = ""                  # canonical value / behaviour
    observed:          str = ""                  # what was actually found
    blocking:          bool = False              # FAIL + blocking → overall BLOCKED

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() if isinstance(e, Evidence) else dict(e) for e in self.evidence]
        return d


@dataclass
class ConflictingValue:
    """Same logical setting with different numbers across sources.

    Surfaced separately in the JSON output (`conflicting_values`) so an
    operator can fix the lot in one pass without scanning all findings.
    """
    name:        str                              # canonical setting name
    occurrences: list[dict] = field(default_factory=list)  # [{file, line, value, kind}]
    expected:    str = ""
    severity:    str = "WARN"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CategoryResult:
    """Aggregated state for one of the 15 strategy-coherence categories."""
    name:     str
    weight:   int                                # contribution to total score
    findings: list[Finding] = field(default_factory=list)

    # ── score / status accessors ─────────────────────────────────────────

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
    def blocked_count(self) -> int:
        return sum(1 for f in self.findings if f.status == "BLOCKED")

    @property
    def skip_count(self) -> int:
        return sum(1 for f in self.findings if f.status == "SKIP")

    @property
    def has_blocking_fail(self) -> bool:
        return any(
            (f.blocking and f.status == "FAIL") or f.status == "BLOCKED"
            for f in self.findings
        )

    def score(self) -> float:
        """0..weight points. BLOCKED / blocking FAIL → 0; FAIL costs 60%
        of weight per finding; WARN costs 25% per finding. PASS is neutral."""
        if not self.findings:
            return 0.0
        if self.has_blocking_fail:
            return 0.0
        score = float(self.weight)
        n = len(self.findings)
        for f in self.findings:
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
            "name":          self.name,
            "weight":        self.weight,
            "score":         round(self.score(), 2),
            "status":        self.overall_status(),
            "pass":          self.pass_count,
            "warn":          self.warn_count,
            "fail":          self.fail_count,
            "blocked":       self.blocked_count,
            "skip":          self.skip_count,
            "blocking_fail": self.has_blocking_fail,
            "findings":      [f.to_dict() for f in self.findings],
        }


@dataclass
class StrategyCoherenceReport:
    """Top-level report returned by `main.run`."""
    overall_status:      str   = "PASS"             # PASS | WARN | FAIL | BLOCKED
    score:               float = 100.0
    generated_at:        str   = ""
    repo_sha:            str   = ""
    categories:          dict[str, CategoryResult] = field(default_factory=dict)
    conflicting_values:  list[ConflictingValue]    = field(default_factory=list)

    @property
    def all_findings(self) -> list[Finding]:
        out: list[Finding] = []
        for cat in self.categories.values():
            out.extend(cat.findings)
        return out

    def principle_coverage(self) -> dict[str, str]:
        """Map of 'high-level principle' -> overall status across cats.

        Matches the 8 principles from the spec executive-summary table.
        Each principle is computed from one or more underlying category
        statuses (worst-case across them).
        """
        cats = self.categories

        def status_of(name: str) -> str:
            c = cats.get(name)
            return c.overall_status() if c else "SKIP"

        def worst(*names: str) -> str:
            statuses = [status_of(n) for n in names]
            for s in ("BLOCKED", "FAIL", "WARN"):
                if s in statuses:
                    return s
            if "PASS" in statuses:
                return "PASS"
            return "SKIP"

        return {
            "paper-only / deterministic":         worst("autonomy_and_determinism"),
            "aggressive paper mode":              status_of("strategy_aggressiveness"),
            "full deployment (98–100%)":          status_of("capital_deployment"),
            "account-aware allocation":           status_of("account_awareness"),
            "learning-loop → allocator":          status_of("learning_loop_allocator"),
            "regime / event switch":              status_of("regime_event_switch"),
            "intraday profit protection":         status_of("intraday_profit_protection"),
            "intraday trend reinterpretation":    status_of("intraday_trend_management"),
            "risk discipline":                    worst("risk_consistency"),
            "options coherence":                  status_of("options_strategy_consistency"),
            "auditability of strategic decisions": status_of("auditability"),
            "runtime state policy":               status_of("runtime_state_policy"),
            "doc / config / code parity":         status_of("documentation_parity"),
            "tests for strategy edges":           status_of("tests_coverage"),
        }

    def to_dict(self) -> dict:
        findings = self.all_findings
        summary = {
            "pass":    sum(1 for f in findings if f.status == "PASS"),
            "warn":    sum(1 for f in findings if f.status == "WARN"),
            "fail":    sum(1 for f in findings if f.status == "FAIL"),
            "blocked": sum(1 for f in findings if f.status == "BLOCKED"),
            "skip":    sum(1 for f in findings if f.status == "SKIP"),
        }
        recommended_fixes = [
            {"id": f.id, "severity": f.status, "fix": f.recommendation}
            for f in findings if f.recommendation and f.status in ("FAIL", "WARN", "BLOCKED")
        ]
        missing_tests = [
            {"id": f.id, "message": f.message}
            for f in findings if f.category == "tests_coverage"
            and f.status in ("FAIL", "WARN", "BLOCKED")
        ]
        missing_wiring = [
            {"id": f.id, "message": f.message}
            for f in findings
            if f.status in ("FAIL", "BLOCKED") and "wiring" in (f.id + f.message).lower()
        ]

        return {
            "overall_status":      self.overall_status,
            "score":               round(self.score, 2),
            "generated_at":        self.generated_at,
            "repo_sha":            self.repo_sha,
            "summary":             summary,
            "principle_coverage":  self.principle_coverage(),
            "categories":          {n: c.to_dict() for n, c in self.categories.items()},
            "findings":            [f.to_dict() for f in findings],
            "recommended_fixes":   recommended_fixes,
            "missing_tests":       missing_tests,
            "missing_wiring":      missing_wiring,
            "conflicting_values":  [cv.to_dict() for cv in self.conflicting_values],
        }
