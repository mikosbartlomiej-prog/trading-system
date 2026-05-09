"""
Lane 2 — auto-PR for LLM-proposed adapter heuristics.

When the daily learning-loop LLM produces a `new_heuristic_proposals`
entry with `lane=auto_pr`, this module:
  1. Validates the proposal (target_file whitelist, no destructive
     changes, code parses, syntax-only-add).
  2. Creates a branch `learning-loop/auto-<date>-<slug>`.
  3. Appends `code_patch` to `target_file` (currently only adapter.py).
  4. Appends `test_addition` to `learning-loop/test_adapter.py`.
  5. Runs `python -m unittest learning-loop.test_adapter` — must pass.
     If it fails, the branch is left for inspection but no PR is opened
     (CI gate: failing tests = bad patch).
  6. Pushes the branch and opens a PR via `gh` CLI.

Returns the PR URL on success, or None on any failure (fail-soft).
The deterministic adapter and Lane 1 state_overrides remain unaffected
— Lane 2 is strictly additive proposal-to-PR plumbing.

Limits enforced (matches routine-prompts.md):
  - target_file must equal "learning-loop/adapter.py" (MVP whitelist)
  - code_patch must parse as Python (ast.parse) and contain only
    function/class/assignment definitions — no `import` statements,
    no top-level expressions
  - test_addition must contain at least one `unittest.TestCase` subclass
  - max 1 PR per workflow run (caller enforces by passing only top-1
    auto_pr proposal)

Safety net: on any error, prints the error and returns None. Workflow
proceeds with the rest of the daily pipeline regardless.
"""

import ast
import os
import re
import subprocess
from datetime import datetime, timezone


REPO_ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ALLOWED_TARGETS = {"learning-loop/adapter.py"}  # MVP — expand later
TEST_FILE      = "learning-loop/test_adapter.py"

# Cap how many imports / mutations the patch can introduce. We disallow
# any top-level statement that isn't a Def/Assign — keeps the surface
# area small and prevents `import os; os.system(...)` style trickery.
ALLOWED_AST_TYPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Assign,
    ast.AnnAssign,
)


# ─── Validation ──────────────────────────────────────────────────────────────

def _validate_proposal(prop: dict) -> tuple[bool, str]:
    """Return (ok, reason). reason is empty on ok=True."""
    target = prop.get("target_file", "")
    if target not in ALLOWED_TARGETS:
        return False, f"target_file '{target}' not in whitelist {ALLOWED_TARGETS}"

    code_patch = prop.get("code_patch", "")
    if not code_patch.strip():
        return False, "code_patch is empty"

    # Patch must parse as Python
    try:
        tree = ast.parse(code_patch)
    except SyntaxError as e:
        return False, f"code_patch SyntaxError: {e}"

    # No top-level statements other than def/class/assign
    for node in tree.body:
        if not isinstance(node, ALLOWED_AST_TYPES):
            return False, (
                f"code_patch top-level node {type(node).__name__} not allowed; "
                f"only function/class/assignment definitions accepted"
            )

    test_addition = prop.get("test_addition", "")
    if not test_addition.strip():
        return False, "test_addition is empty"

    # Must contain at least one unittest.TestCase subclass
    try:
        ttree = ast.parse(test_addition)
    except SyntaxError as e:
        return False, f"test_addition SyntaxError: {e}"
    has_testcase = any(
        isinstance(n, ast.ClassDef) and any(
            (isinstance(b, ast.Attribute) and b.attr == "TestCase") or
            (isinstance(b, ast.Name) and b.id == "TestCase")
            for b in n.bases
        )
        for n in ttree.body
    )
    if not has_testcase:
        return False, "test_addition has no unittest.TestCase subclass"

    title = prop.get("title", "")
    if not title.strip():
        return False, "title is empty"

    return True, ""


def _slug(title: str, max_len: int = 40) -> str:
    """Branch-safe slug from proposal title."""
    s = re.sub(r"[^a-z0-9-]+", "-", title.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:max_len] or "patch"


# ─── Git helpers ─────────────────────────────────────────────────────────────

def _git(args: list[str], check: bool = True, capture: bool = True) -> tuple[int, str, str]:
    """Run git in REPO_ROOT. Returns (rc, stdout, stderr)."""
    r = subprocess.run(
        ["git", "-C", REPO_ROOT, *args],
        capture_output=capture, text=True, timeout=60,
    )
    if check and r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, r.args, r.stdout, r.stderr)
    return r.returncode, r.stdout, r.stderr


def _branch_exists(branch: str) -> bool:
    rc, _, _ = _git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
    return rc == 0


def _run_tests() -> tuple[bool, str]:
    """Return (pass, output)."""
    r = subprocess.run(
        ["python", "-m", "unittest", "learning-loop.test_adapter"],
        capture_output=True, text=True, timeout=60, cwd=REPO_ROOT,
    )
    return (r.returncode == 0, (r.stdout + r.stderr)[-2000:])


# ─── PR creation ─────────────────────────────────────────────────────────────

def create_pr_from_proposal(prop: dict, base_branch: str = "main") -> str | None:
    """
    Apply proposal as a new branch + PR. Returns PR URL on success, else None.
    Fail-soft on any error (logged, returns None).
    """
    ok, reason = _validate_proposal(prop)
    if not ok:
        print(f"  Lane2: rejected — {reason}")
        return None

    title = prop["title"]
    target_rel = prop["target_file"]            # e.g. "learning-loop/adapter.py"
    code_patch = prop["code_patch"].rstrip() + "\n"
    test_addition = prop["test_addition"].rstrip() + "\n"
    risk = prop.get("risk", "medium")
    rationale = prop.get("rationale", "(no rationale)")
    wire_note = prop.get("wire_into_adapt_strategy") or "(stand-alone — no wiring needed)"

    today = datetime.now(timezone.utc).date().isoformat()
    branch = f"learning-loop/auto-{today}-{_slug(title)}"

    if _branch_exists(branch):
        print(f"  Lane2: branch '{branch}' already exists — skipping (idempotent)")
        return None

    # Identity for commit
    _git(["config", "user.name",  "github-actions[bot]"], check=False)
    _git(["config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=False)

    try:
        # Ensure we're on a clean base
        _git(["fetch", "origin", base_branch])
        _git(["checkout", "-B", branch, f"origin/{base_branch}"])

        # Append patch + test
        target_abs = os.path.join(REPO_ROOT, target_rel)
        with open(target_abs, "a") as f:
            f.write("\n\n# ─── Lane2 auto-added — " + title + " ────────────\n")
            f.write(code_patch)

        # Auto-inject `from adapter import ...` at the top of test_addition
        # if the LLM didn't include it (today's failure mode 2026-05-09:
        # routine wrote a working test that called the new function but
        # never imported it -> NameError on every test method, CI red,
        # PR abandoned). Parse code_patch with AST to extract defined
        # top-level names, prepend a single from-import line.
        defined_names: list[str] = []
        try:
            for node in ast.parse(code_patch).body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    defined_names.append(node.name)
                elif isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            defined_names.append(tgt.id)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    defined_names.append(node.target.id)
        except SyntaxError:
            pass  # validation already ensured parseable; defensive

        # Only inject if the test_addition doesn't already import them
        needs_import = [n for n in defined_names if f"import {n}" not in test_addition]
        injected_test = test_addition
        if needs_import:
            module_name = os.path.splitext(os.path.basename(target_rel))[0]  # e.g. "adapter"
            import_line = (
                f"# Auto-injected by lane2_pr to expose new symbols to the test:\n"
                f"from {module_name} import {', '.join(needs_import)}  # noqa: E402,F401\n\n"
            )
            injected_test = import_line + test_addition

        test_abs = os.path.join(REPO_ROOT, TEST_FILE)
        with open(test_abs, "a") as f:
            f.write("\n\n# ─── Lane2 auto-added test for: " + title + " ─────\n")
            f.write(injected_test)

        # Run tests — gate
        passed, test_output = _run_tests()
        if not passed:
            print(f"  Lane2: tests RED on the new patch — abandoning branch")
            print(f"  --- test output (tail 2k chars) ---")
            print(test_output)
            # Don't push or PR; just log. Reset to clean working tree so
            # subsequent workflow steps aren't confused.
            _git(["checkout", "--", target_rel, TEST_FILE], check=False)
            _git(["checkout", base_branch], check=False)
            _git(["branch", "-D", branch], check=False)
            return None

        # Stage + commit + push
        _git(["add", target_rel, TEST_FILE])
        commit_msg = (
            f"learning-loop[auto]: {title}\n\n"
            f"Lane 2 auto-PR generated by daily learning-loop LLM "
            f"({today}).\n\n"
            f"Risk: {risk}\n"
            f"Rationale: {rationale}\n\n"
            f"Wire-into-adapt_strategy hint:\n  {wire_note}\n\n"
            f"Tests pass locally: `python -m unittest learning-loop.test_adapter`.\n"
            f"Operator: review the appended function in {target_rel}, "
            f"verify the wiring hint, merge when satisfied. The patch is "
            f"append-only — no existing code is modified."
        )
        _git(["commit", "-m", commit_msg])
        _git(["push", "-u", "origin", branch])

        # Open PR via gh CLI
        pr_body = (
            f"### Lane 2 auto-PR — LLM-proposed heuristic\n\n"
            f"**Title:** {title}\n"
            f"**Risk:** `{risk}`\n"
            f"**Target:** `{target_rel}`\n\n"
            f"**Rationale (from LLM):**\n{rationale}\n\n"
            f"**Wire-into-adapt_strategy hint:**\n{wire_note}\n\n"
            f"---\n\n"
            f"### Auto-PR safety contract\n"
            f"- Only `{target_rel}` and `{TEST_FILE}` modified, both append-only.\n"
            f"- Patch has been validated: parses as Python, only "
            f"function/class/assignment top-levels.\n"
            f"- `python -m unittest learning-loop.test_adapter` was run "
            f"locally on the branch and passed.\n"
            f"- This PR was created by `learning-loop/lane2_pr.py` — see "
            f"that module's docstring for the full validation rules.\n\n"
            f"### Review checklist\n"
            f"- [ ] Read the appended function — does the logic match the "
            f"rationale?\n"
            f"- [ ] Read the appended test — does it actually exercise the "
            f"new function?\n"
            f"- [ ] If wire-into-adapt_strategy is non-null, integrate the "
            f"call point in `adapt_strategy()` (a separate small commit on "
            f"this branch).\n"
            f"- [ ] CI green.\n"
        )

        # Try gh pr create with labels first; on label-related failure
        # (labels don't exist in repo yet), retry without --label so the
        # PR still opens. Operator can label manually or create the
        # `learning-loop` / `auto-pr` labels in repo settings later.
        pr_args_base = [
            "gh", "pr", "create",
            "--base", base_branch,
            "--head", branch,
            "--title", f"learning-loop[auto]: {title}",
            "--body", pr_body,
        ]
        for attempt in (
            ("with-labels",   pr_args_base + ["--label", "learning-loop,auto-pr"]),
            ("without-labels", pr_args_base),
        ):
            label, cmd = attempt
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60, cwd=REPO_ROOT,
            )
            if r.returncode == 0:
                pr_url = r.stdout.strip()
                print(f"  Lane2: PR opened ({label}) — {pr_url}")
                return pr_url
            err = (r.stderr or "")[:300]
            if "label" in err.lower() and label == "with-labels":
                print(f"  Lane2: gh pr create with labels failed — retrying without labels")
                continue
            # Non-label failure (auth, network, etc.) — log + bail
            print(f"  Lane2: gh pr create failed ({r.returncode}): {err}")
            print(f"  Lane2: branch was pushed — manual PR: "
                  f"https://github.com/mikosbartlomiej-prog/trading-system/"
                  f"compare/{base_branch}...{branch}?expand=1")
            return None
        return None

    except subprocess.CalledProcessError as e:
        print(f"  Lane2: git error — {e.cmd}: {e.stderr[:300]}")
        return None
    except Exception as e:
        print(f"  Lane2: unexpected error — {type(e).__name__}: {e}")
        return None
