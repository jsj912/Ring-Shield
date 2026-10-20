from __future__ import annotations

import ast
from pathlib import Path


APP_FILE = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"


def test_dashboard_does_not_do_arithmetic_on_api_values():
    tree = ast.parse(APP_FILE.read_text(encoding="utf-8"), filename=str(APP_FILE))
    arithmetic_operators = (ast.Add, ast.Sub, ast.Mult, ast.Div)

    # These exact page-counter expressions are the complete arithmetic allow-list.
    # A new expression, including one using a cursor-derived value, fails the check.
    allowed_page_navigation = {
        "page + 1",
        "page - 1",
    }
    # pathlib's overloaded slash joins the repository root to a config filename; it
    # does not calculate with API data and is the sole non-navigation BinOp exception.
    allowed_path_join = ("REPO_ROOT", ".env")

    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, arithmetic_operators):
            expression = ast.unparse(node)
            is_path_join = (
                isinstance(node.op, ast.Div)
                and isinstance(node.left, ast.Name)
                and node.left.id == allowed_path_join[0]
                and isinstance(node.right, ast.Constant)
                and node.right.value == allowed_path_join[1]
            )
            assert expression in allowed_page_navigation or is_path_join, (
                f"Unexpected arithmetic expression in dashboard: {expression}"
            )
            if expression in allowed_page_navigation:
                assert isinstance(node.left, ast.Name) and node.left.id == "page"
                assert isinstance(node.right, ast.Constant) and type(node.right.value) is int
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, arithmetic_operators):
            raise AssertionError(
                f"Unexpected augmented arithmetic in dashboard: {ast.unparse(node)}"
            )
        elif isinstance(node, ast.Call):
            function_name = ast.unparse(node.func).lower()
            leaf_name = function_name.rsplit(".", 1)[-1]
            assert leaf_name not in {"sum", "sums", "average", "median"} and not (
                "mean" in leaf_name
            ), f"Unexpected aggregate arithmetic call: {function_name}"
