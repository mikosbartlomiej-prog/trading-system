"""Learning-loop anti-overfitting. Spec §10."""

from __future__ import annotations

from pathlib import Path

from ..models import Finding
from ..utils import read_text


CATEGORY = "learning_loop"
PRINCIPLE = "LEARNING_LOOP_BOUNDED"


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    v = root / "learning-loop" / "validation.py"
    if not v.exists():
        findings.append(Finding(
            id="LL_VALIDATION_MODULE_EXISTS",
            category=CATEGORY, severity="FAIL", status="FAIL",
            message="learning-loop/validation.py missing.",
            principle=PRINCIPLE,
            recommendation="Restore learning-loop/validation.py with sample-size rules.",
        ))
        return findings

    text = read_text(v)
    required = ["MIN_SAMPLE_INCREASE", "MIN_SAMPLE_DISABLE",
                "MIN_SAMPLE_BIAS_OPTIONS", "MAX_DAILY_SIZE_MULT_STEP_UP",
                "MAX_DAILY_SIZE_MULT_STEP_DOWN", "validate_adaptation"]
    missing = [s for s in required if s not in text]
    findings.append(Finding(
        id="LL_VALIDATION_RULES_PRESENT",
        category=CATEGORY,
        severity="PASS" if not missing else "FAIL",
        status="PASS" if not missing else "FAIL",
        message="Sample-size + step-bound rules present." if not missing
                else f"Missing: {missing}",
        principle=PRINCIPLE,
        recommendation="Restore validation.py rules." if missing else "",
    ))

    # Once-per-day enforcement
    once_per_day = "last_validated_at" in text and "second_run" in text
    findings.append(Finding(
        id="LL_ONCE_PER_DAY_RULE",
        category=CATEGORY,
        severity="PASS" if once_per_day else "WARN",
        status="PASS" if once_per_day else "WARN",
        message="Once-per-day adaptation enforced." if once_per_day
                else "validation.py missing once-per-day check.",
        principle=PRINCIPLE,
        recommendation="Block second-run adaptations unless allow_double_run." if not once_per_day else "",
    ))

    # Analyzer integration
    az = root / "learning-loop" / "analyzer.py"
    if az.exists():
        az_text = read_text(az)
        wired = "validate_adaptation" in az_text
        findings.append(Finding(
            id="LL_VALIDATION_WIRED_INTO_ANALYZER",
            category=CATEGORY,
            severity="PASS" if wired else "FAIL",
            status="PASS" if wired else "FAIL",
            message="analyzer.py calls validate_adaptation." if wired
                    else "analyzer.py does NOT call validate_adaptation.",
            principle=PRINCIPLE,
            recommendation="Chain validate_adaptation after safe_apply_overrides." if not wired else "",
        ))

    return findings
