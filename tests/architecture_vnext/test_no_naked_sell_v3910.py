"""v3.9.10 (2026-05-27) ARCHITECTURAL INVARIANT — naked-sell lint test.

After three same-class incidents in 6 days (2026-05-22 / 26 / 27), this test
enforces: NO file in the repo may call `requests.post(.../v2/orders, side="sell"|"buy")`
EXCEPT the centralized `shared/alpaca_orders.py::safe_close` function.

ROOT CAUSE OF INCIDENTS:
1. **2026-05-22:** RECREATE_EXIT_PLAN MARKET-closed 7 positions
2. **2026-05-26:** emergency_engine duplicate_exits → MARKET close 3 positions
3. **2026-05-27:** allocator EXIT MARKET on stale plan → NOW -169 naked SHORT

Each time, the fix was a POINT FIX at a specific callsite. The root cause
was decentralized SELL emission — every monitor/script could POST a sell
order without verifying the live position exists.

v3.9.10 SOLUTION:
- ONE function `alpaca_orders.safe_close` performs pre-flight position check
- ALL sell/exit/buy-to-cover paths refactored to use it
- THIS TEST is the architectural gate that prevents regression

To bypass this test, you must add the file path to ALLOWED_FILES below,
explaining why the bypass is safe (e.g. DELETE /v2/positions is idempotent,
or a script is documentation/test-only).

If this test fails on a PR adding new code, the fix is:
- Refactor your new SELL/EXIT path to call `safe_close()` instead of
  `requests.post(/v2/orders, side='sell')` directly.

See: docs/INCIDENT-2026-05-22-positions-closed.md for full history.
"""

import ast
import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Files allowed to make direct sell POST requests (i.e. they ARE the
# implementation of safe_close, or they wrap it intentionally, or they
# are provably entry-only with documented client_order_id prefix).
ALLOWED_FILES = {
    "shared/alpaca_orders.py",   # safe_close() lives here, also place_oco_exit + crypto
    # options-monitor: entry-only (BUY_TO_OPEN_CALL/PUT), client_order_id
    # prefix "options-momentum-" — never closes positions. CLOSE for
    # options goes through options-exit-monitor which uses safe_close.
    "options-monitor/monitor.py",
    # v3.21 broker_paper_adapter: hardened paper-only wrapper. Hard-asserts
    # paper URL (ADAPTER_PAPER_ONLY=True), requires idempotency_key,
    # MAX_ORDER_NOTIONAL_USD=100, gated behind ALLOW_BROKER_PAPER env flag,
    # default dry-run. Submits its own paper orders by design — does NOT
    # close positions through the system's normal exit paths.
    "shared/broker_paper_adapter.py",
}

# DELETE /v2/positions is SAFE — Alpaca refuses to over-sell or create shorts
# via this endpoint. So we only forbid POST + side='sell'/'buy'.
FORBIDDEN_METHOD = "post"
FORBIDDEN_URL_FRAGMENTS = ("/v2/orders",)
FORBIDDEN_SIDE_VALUES = {"sell", "buy"}  # buy = covers buy_to_cover from short

# Directories scanned (excluding tests, venv, etc.)
SCAN_DIRS = ["shared", "exit-monitor", "options-exit-monitor", "crypto-monitor",
             "scripts", "learning-loop", "options-monitor", "geo-monitor",
             "defense-monitor", "price-monitor", "reddit-monitor",
             "twitter-monitor", "politician-monitor"]


def _file_contains_naked_sell_post(file_path: Path) -> list[str]:
    """
    AST-walks `file_path` looking for `requests.post(URL, ..., json=payload, ...)`
    where URL contains "/v2/orders" AND payload has side in FORBIDDEN_SIDE_VALUES.

    Returns list of human-readable violation descriptions (line numbers + snippet).
    Empty list = clean.

    Heuristic: we look for the call signature. We cannot fully evaluate the
    payload dict at static-analysis time, so we flag any `requests.post`
    targeting /v2/orders unless the call is provably side='buy_to_open'
    style (legitimate BUY entry). Conservative: false positives are
    acceptable — they force the dev to either use safe_close OR allow-list.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    if "/v2/orders" not in source:
        return []

    violations: list[str] = []

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return [f"AST parse error in {file_path}"]

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match `requests.post(...)` or `_rq.post(...)` or `r.post(...)`
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == FORBIDDEN_METHOD):
            continue

        # First positional arg should be a URL string or f-string with /v2/orders
        if not node.args:
            continue
        url_arg = node.args[0]
        url_str = ""
        if isinstance(url_arg, ast.Constant) and isinstance(url_arg.value, str):
            url_str = url_arg.value
        elif isinstance(url_arg, ast.JoinedStr):  # f-string
            url_str = "".join(
                v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "<expr>"
                for v in url_arg.values
            )
        elif isinstance(url_arg, ast.BinOp):  # string concatenation
            url_str = ast.unparse(url_arg)
        else:
            try:
                url_str = ast.unparse(url_arg)
            except Exception:
                url_str = "<unparseable>"

        if not any(frag in url_str for frag in FORBIDDEN_URL_FRAGMENTS):
            continue

        # We have a /v2/orders POST. Check kwargs for json= payload + side field.
        payload_node = None
        for kw in node.keywords:
            if kw.arg == "json":
                payload_node = kw.value
                break

        is_sell_or_buy = False
        side_value = None
        if isinstance(payload_node, ast.Dict):
            for k, v in zip(payload_node.keys, payload_node.values):
                if isinstance(k, ast.Constant) and k.value == "side":
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        side_value = v.value
                        if v.value.lower() in FORBIDDEN_SIDE_VALUES:
                            is_sell_or_buy = True
                    elif isinstance(v, ast.Name) or isinstance(v, ast.Subscript):
                        # Variable: can't determine statically — flag conservatively
                        is_sell_or_buy = True
                        side_value = "<var>"
        elif isinstance(payload_node, ast.Name):
            # Payload built earlier as a variable — must flag (conservative)
            is_sell_or_buy = True
            side_value = "<var-payload>"

        # If we can prove side is "buy" but it's clearly a BUY ENTRY (not
        # buy_to_cover), we'd want to skip. But buy_to_cover from a short
        # position is ALSO a position-modifying call that needs pre-flight.
        # We choose: flag ALL POST /v2/orders that we can't prove safe.
        # Allowance: payload with `order_class: bracket` (BUY entry with SL+TP)
        # is OK because bracket is by definition an entry order.
        is_bracket = False
        if isinstance(payload_node, ast.Dict):
            for k, v in zip(payload_node.keys, payload_node.values):
                if (isinstance(k, ast.Constant) and k.value == "order_class"
                        and isinstance(v, ast.Constant) and v.value == "bracket"):
                    is_bracket = True
                    break

        if is_bracket:
            continue  # BRACKET orders are entries, not closes

        if not is_sell_or_buy:
            continue

        violations.append(
            f"{file_path.relative_to(REPO_ROOT)}:{node.lineno} "
            f"— requests.post(/v2/orders, side={side_value!r}) — "
            f"use safe_close() instead"
        )

    return violations


class TestNoNakedSellPath(unittest.TestCase):
    """ARCHITECTURAL INVARIANT — every SELL/EXIT must go through safe_close()."""

    def test_no_direct_sell_post_outside_safe_close(self):
        """
        Scan every Python file in repo (except ALLOWED_FILES + tests).
        ZERO files may call `requests.post(/v2/orders, side='sell'|'buy')`
        directly. The single allowed path is `alpaca_orders.safe_close`.

        If this fails:
        1. Look at the violation file/line.
        2. Refactor that callsite to call `safe_close(symbol, qty, ...)` instead.
        3. See `shared/alpaca_orders.py::safe_close` for the API.
        4. If your callsite is a special case (DELETE-based, idempotent,
           test mock, etc.), add to ALLOWED_FILES with comment explaining why.
        """
        violations: list[str] = []
        for scan_dir in SCAN_DIRS:
            d = REPO_ROOT / scan_dir
            if not d.is_dir():
                continue
            for py_file in d.rglob("*.py"):
                # Skip tests
                if "test_" in py_file.name or "/tests/" in str(py_file):
                    continue
                # Skip allowed
                rel = py_file.relative_to(REPO_ROOT).as_posix()
                if rel in ALLOWED_FILES:
                    continue
                # Skip __pycache__
                if "__pycache__" in str(py_file):
                    continue
                violations.extend(_file_contains_naked_sell_post(py_file))

        if violations:
            msg = (
                f"\n{len(violations)} naked SELL/BUY-TO-COVER POST(s) found "
                f"outside safe_close():\n  - "
                + "\n  - ".join(violations)
                + "\n\nRefactor to use shared.alpaca_orders.safe_close() — see "
                "docs/INCIDENT-2026-05-22-positions-closed.md for context."
            )
            self.fail(msg)

    def test_safe_close_exists_in_source(self):
        """Smoke check: safe_close must be defined in alpaca_orders.py.

        Source-level check (not import) because alpaca_orders.py uses PEP 604
        `dict | None` syntax requiring Python 3.10+. CI runs 3.11; local dev
        may have 3.9. This test must pass on both."""
        src_path = REPO_ROOT / "shared" / "alpaca_orders.py"
        src = src_path.read_text(encoding="utf-8")
        self.assertIn("def safe_close(", src, "safe_close not found in alpaca_orders.py")
        self.assertIn("intent_qty", src, "safe_close signature missing intent_qty")
        self.assertIn("_fetch_single_position", src, "safe_close must call _fetch_single_position")


if __name__ == "__main__":
    unittest.main()
