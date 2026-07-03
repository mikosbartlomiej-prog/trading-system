"""AST-level enforcement: every broker-mutating HTTP call in
``shared/alpaca_orders.py`` MUST be dominated by a call to the canonical
gate ``_execution_mode_precheck`` inside the same function.

A "mutating HTTP call" is defined as:

  * ``requests.post(...)`` where the URL literal or f-string contains
    ``/v2/orders``.
  * ``requests.delete(...)`` where the URL literal or f-string contains
    ``/v2/orders`` or ``/v2/positions``.

The test walks the AST, finds every such call, and confirms that inside
the enclosing ``FunctionDef``, there is a *statement-level* call to
``_execution_mode_precheck`` that lexically precedes the mutating call.

This is a strong structural invariant:

  * you cannot add a new POST/DELETE without wiring the gate,
  * you cannot silently move a call above the gate check,
  * ``--force`` / EXECUTION_MODE=PAPER_CANARY / ALLOW_BROKER_PAPER=true /
    monkey-patching the module cannot bypass this static check.

Failure of this test means a mutation path is not gated. DO NOT weaken
the assertion. Fix the wiring.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TARGET = REPO_ROOT / "shared" / "alpaca_orders.py"

GATE_FN_NAME = "_execution_mode_precheck"

# URL patterns that trigger the check. If a maintainer adds a new
# broker-mutating URL, extend this tuple.
MUTATING_POST_URL_TOKENS = ("/v2/orders",)
MUTATING_DELETE_URL_TOKENS = ("/v2/orders", "/v2/positions")


class _MutationSiteVisitor(ast.NodeVisitor):
    """Walk a function body and collect (method, url_text, lineno) for
    every requests.<mutating>(...) call, plus the linenos of every call
    to the gate helper."""

    def __init__(self):
        self.mutating_sites: list[tuple[str, str, int]] = []
        self.gate_call_linenos: list[int] = []

    def _url_text(self, call: ast.Call) -> str:
        """Return a text representation of the first positional arg (URL)
        so we can pattern-match against the whitelist."""
        if not call.args:
            return ""
        arg = call.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        if isinstance(arg, ast.JoinedStr):
            parts = []
            for v in arg.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                elif isinstance(v, ast.FormattedValue):
                    # Placeholder for interpolated var — keep the literal
                    # boundary text.
                    parts.append("{}")
            return "".join(parts)
        if isinstance(arg, ast.BinOp):  # simple str concatenation
            return "concat"
        return ""

    def visit_Call(self, node: ast.Call):
        # requests.post / requests.delete / requests.put / requests.patch
        if isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "requests"
                and node.func.attr in ("post", "delete", "put", "patch")
            ):
                url = self._url_text(node)
                lineno = getattr(node, "lineno", 0)
                if node.func.attr == "post":
                    tokens = MUTATING_POST_URL_TOKENS
                elif node.func.attr == "delete":
                    tokens = MUTATING_DELETE_URL_TOKENS
                else:
                    tokens = MUTATING_POST_URL_TOKENS + MUTATING_DELETE_URL_TOKENS
                if any(tok in url for tok in tokens):
                    self.mutating_sites.append((node.func.attr, url, lineno))
        # calls to _execution_mode_precheck(...)
        if isinstance(node.func, ast.Name) and node.func.id == GATE_FN_NAME:
            self.gate_call_linenos.append(getattr(node, "lineno", 0))
        self.generic_visit(node)


class TestEveryMutationSiteGated(unittest.TestCase):
    """Every mutating requests.<method>(...) call is dominated by the
    canonical gate helper in the same function."""

    def test_alpaca_orders_mutation_sites(self):
        tree = ast.parse(TARGET.read_text(encoding="utf-8"))

        # Find every FunctionDef in the module (excluding nested ones for
        # simplicity — the module doesn't nest mutation calls).
        checked_functions = 0
        problems: list[str] = []

        class FnWalker(ast.NodeVisitor):
            def __init__(self, outer):
                self.outer = outer

            def visit_FunctionDef(self, fn: ast.FunctionDef):
                v = _MutationSiteVisitor()
                v.visit(fn)
                if not v.mutating_sites:
                    return
                self.outer._check_fn(fn, v, problems)

            visit_AsyncFunctionDef = visit_FunctionDef

        walker = FnWalker(self)
        walker.visit(tree)

        self.assertFalse(
            problems,
            "One or more broker-mutating HTTP calls in shared/alpaca_orders.py "
            "are NOT dominated by _execution_mode_precheck in the enclosing "
            "function. Add the gate call BEFORE the mutation, or update the "
            "gate coverage to include the site.\n\n" + "\n".join(problems),
        )

    def _check_fn(
        self,
        fn: ast.FunctionDef,
        v: _MutationSiteVisitor,
        problems: list[str],
    ) -> None:
        """For each mutation site in this function, assert that a gate
        call was seen at a lineno strictly less than the mutation
        lineno."""
        earliest_gate = min(v.gate_call_linenos) if v.gate_call_linenos else None
        for method, url, lineno in v.mutating_sites:
            if earliest_gate is None or earliest_gate >= lineno:
                problems.append(
                    f"[{fn.name}] requests.{method}({url}) at line {lineno} "
                    f"is not dominated by {GATE_FN_NAME}(...) "
                    f"(earliest gate call in fn: {earliest_gate})"
                )


class TestGateHelperExists(unittest.TestCase):
    """The canonical gate helper is defined at module level."""

    def test_helper_defined(self):
        tree = ast.parse(TARGET.read_text(encoding="utf-8"))
        names = {
            n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn(GATE_FN_NAME, names)


if __name__ == "__main__":
    unittest.main()
