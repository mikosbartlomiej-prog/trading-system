"""Code-autonomy safety contract. Spec §3."""

from __future__ import annotations

from pathlib import Path

from ..models import Finding
from ..utils import read_text


CATEGORY = "code_autonomy"
PRINCIPLE = "CODE_AUTONOMY_BOUNDED"


def _check_exists_with_symbols(root: Path, relpath: str, symbols: list[str],
                                check_id: str, blocking: bool = False) -> Finding:
    p = root / relpath
    if not p.exists():
        return Finding(
            id=check_id, category=CATEGORY, severity="FAIL", status="FAIL",
            message=f"{relpath} is missing.",
            principle=PRINCIPLE,
            recommendation=f"Restore {relpath} with symbols: {', '.join(symbols)}.",
            blocking=blocking,
        )
    text = read_text(p)
    missing = [s for s in symbols if s not in text]
    if missing:
        return Finding(
            id=check_id, category=CATEGORY, severity="FAIL", status="FAIL",
            message=f"{relpath} missing symbols: {missing}",
            principle=PRINCIPLE,
            recommendation=f"Ensure {relpath} exposes: {', '.join(symbols)}.",
            blocking=blocking,
        )
    return Finding(
        id=check_id, category=CATEGORY, severity="PASS", status="PASS",
        message=f"{relpath} present with required symbols.",
        principle=PRINCIPLE,
    )


def run(root: Path) -> list[Finding]:
    findings: list[Finding] = []

    # 1. Validator exists with key entry points
    findings.append(_check_exists_with_symbols(
        root, "learning-loop/patch_validator.py",
        ["validate_patch", "PatchMetadata", "ValidationResult",
         "FORBIDDEN_PATHS", "LOW_RISK_PATHS", "MEDIUM_RISK_PATHS"],
        "CODE_AUTONOMY_VALIDATOR_EXISTS",
        blocking=True,
    ))

    # 2. Validator self-modify is forbidden
    pv = root / "learning-loop" / "patch_validator.py"
    if pv.exists():
        text = read_text(pv)
        self_modify_forbidden = "learning-loop/patch_validator.py" in text and "FORBIDDEN_PATHS" in text
        findings.append(Finding(
            id="CODE_AUTONOMY_VALIDATOR_NO_SELF_MODIFY",
            category=CATEGORY,
            severity="PASS" if self_modify_forbidden else "FAIL",
            status="PASS" if self_modify_forbidden else "FAIL",
            message=("Validator's own file is in FORBIDDEN_PATHS."
                     if self_modify_forbidden
                     else "Validator does NOT forbid self-modification."),
            principle=PRINCIPLE,
            recommendation="Add 'learning-loop/patch_validator.py' to FORBIDDEN_PATHS." if not self_modify_forbidden else "",
            blocking=not self_modify_forbidden,
        ))

    # 3. Validator forbids live endpoints + risk-gate removal.
    # The validator stores its forbidden patterns inside a regex, so the
    # actual string is `api\.alpaca\.markets` (escaped) — we check by
    # looking for the named-pattern marker `live_endpoint` and the
    # alpaca.markets substring with either escaping style.
    if pv.exists():
        text = read_text(pv)
        forbids_live = ("live_endpoint" in text and
                        ("alpaca.markets" in text or r"alpaca\.markets" in text))
        # Test-skip patterns: validator stores them as a regex string so
        # accept either the @skip literal or a regex pattern that catches it.
        forbids_test_skip = ("@unittest.skip" in text
                              or "pytest.mark.skip" in text
                              or "disable_test" in text or "xfail" in text)
        findings.append(Finding(
            id="CODE_AUTONOMY_VALIDATOR_BLOCKS_LIVE",
            category=CATEGORY,
            severity="PASS" if forbids_live else "FAIL",
            status="PASS" if forbids_live else "FAIL",
            message="Validator blocks live endpoint additions." if forbids_live
                    else "Validator does NOT block live endpoint additions.",
            principle=PRINCIPLE,
            recommendation="Add LIVE_ENDPOINT pattern to FORBIDDEN_CONTENT_PATTERNS." if not forbids_live else "",
            blocking=not forbids_live,
        ))
        findings.append(Finding(
            id="CODE_AUTONOMY_VALIDATOR_BLOCKS_TEST_SKIP",
            category=CATEGORY,
            severity="PASS" if forbids_test_skip else "WARN",
            status="PASS" if forbids_test_skip else "WARN",
            message="Validator blocks test-skip markers." if forbids_test_skip
                    else "Validator may not detect test-skip markers.",
            principle=PRINCIPLE,
            recommendation="Add @skip / xfail to FORBIDDEN_CONTENT_PATTERNS." if not forbids_test_skip else "",
        ))

    # 4. code_autonomy module exists
    findings.append(_check_exists_with_symbols(
        root, "learning-loop/code_autonomy.py",
        ["run_once", "evaluate", "apply_and_commit", "revert_commit"],
        "CODE_AUTONOMY_LOOP_EXISTS",
    ))

    # 5. autonomy_bounds.json exists with daily cap
    bounds = root / "config" / "autonomy_bounds.json"
    if not bounds.exists():
        findings.append(Finding(
            id="CODE_AUTONOMY_BOUNDS_CONFIG",
            category=CATEGORY, severity="FAIL", status="FAIL",
            message="config/autonomy_bounds.json missing.",
            principle=PRINCIPLE,
            recommendation="Restore config/autonomy_bounds.json with code_loop.max_patches_per_day.",
        ))
    else:
        text = read_text(bounds)
        has_cap = "max_patches_per_day" in text
        findings.append(Finding(
            id="CODE_AUTONOMY_BOUNDS_CONFIG",
            category=CATEGORY,
            severity="PASS" if has_cap else "WARN",
            status="PASS" if has_cap else "WARN",
            message="autonomy_bounds.json defines daily patch cap." if has_cap
                    else "autonomy_bounds.json missing max_patches_per_day.",
            principle=PRINCIPLE,
            recommendation="Add code_loop.max_patches_per_day to bounds." if not has_cap else "",
        ))

    # 6. Auto-merge workflow has gates
    wf = root / ".github" / "workflows" / "autonomous-code-loop.yml"
    if wf.exists():
        text = read_text(wf)
        gates = ["audit_workflows", "secret_scan", "unittest"]
        missing_gates = [g for g in gates if g not in text]
        findings.append(Finding(
            id="CODE_AUTONOMY_WORKFLOW_HAS_GATES",
            category=CATEGORY,
            severity="PASS" if not missing_gates else "WARN",
            status="PASS" if not missing_gates else "WARN",
            message="autonomous-code-loop.yml runs audit + secret-scan + tests." if not missing_gates
                    else f"autonomous-code-loop.yml missing gates: {missing_gates}",
            principle=PRINCIPLE,
            recommendation="Add missing CI steps before merge." if missing_gates else "",
        ))

    return findings
