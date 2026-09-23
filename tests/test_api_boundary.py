"""Tests ensuring that all router API communication is delegated to gli4py.

Home Assistant integration code in custom_components/glinet must never make direct
HTTP/JSON-RPC requests to the router. All device interactions must be routed
through the gli4py client library.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parent.parent / "custom_components" / "glinet"

FORBIDDEN_IMPORT_MODULES = frozenset(
    {"requests", "httpx", "urllib.request", "http.client"}
)
FORBIDDEN_HTTP_METHODS = frozenset(
    {"get", "post", "put", "delete", "patch", "request", "head", "options"}
)


def _check_source_for_direct_api_calls(
    source_code: str, filename: str = "module.py"
) -> list[str]:
    """Scan Python source code for direct HTTP calls or raw RPC interactions."""
    violations: list[str] = []
    tree = ast.parse(source_code, filename=filename)

    for node in ast.walk(tree):
        # 1. Prohibit raw HTTP library imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split(".")[0]
                if root_module in FORBIDDEN_IMPORT_MODULES:
                    violations.append(
                        f"{filename}:{node.lineno} Prohibited import '{alias.name}'. "
                        "All network communication must go through gli4py."
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in FORBIDDEN_IMPORT_MODULES:
                violations.append(
                    f"{filename}:{node.lineno} Prohibited from-import '{node.module}'. "
                    "All network communication must go through gli4py."
                )

        # 2. Prohibit direct HTTP calls on sessions/clients (e.g. session.post, session.get, client.request)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                method_name = node.func.attr.lower()
                target = node.func.value
                target_name = ""
                if isinstance(target, ast.Name):
                    target_name = target.id.lower()
                elif isinstance(target, ast.Attribute):
                    target_name = target.attr.lower()

                # Always flag HTTP-only mutating verbs (post, put, delete, patch, request)
                # on variables representing network sessions/clients
                is_http_verb = method_name in {
                    "post",
                    "put",
                    "delete",
                    "patch",
                    "request",
                    "head",
                    "options",
                }
                # For 'get', distinguish from dict.get() by checking if target is explicitly
                # a session or if HTTP keyword arguments (url, headers, timeout, params) are passed
                has_http_kwargs = any(
                    kw.arg
                    in {"url", "headers", "timeout", "params", "json", "data", "ssl"}
                    for kw in node.keywords
                    if kw.arg
                )
                is_session_target = target_name in {
                    "session",
                    "client_session",
                    "http_session",
                    "aiohttp_session",
                    "_session",
                }
                is_direct_http_call = False

                if (
                    is_session_target
                    and (is_http_verb or method_name == "get" or has_http_kwargs)
                    or is_http_verb
                    and any(kw in target_name for kw in ("client", "http", "conn"))
                ):
                    is_direct_http_call = True

                if is_direct_http_call:
                    violations.append(
                        f"{filename}:{node.lineno} Direct HTTP call '{target_name}.{method_name}()' detected. "
                        "Direct HTTP communication with the router is not permitted; "
                        "implement the endpoint in gli4py and call it via self._api.<method>()."
                    )

        # 3. Prohibit hardcoded RPC path endpoints outside const.py
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and filename != "const.py"
            and node.value in ("/rpc", "/cgi-bin/luci/rpc")
        ):
            violations.append(
                f"{filename}:{node.lineno} Hardcoded RPC path '{node.value}' detected. "
                "All RPC communication must be encapsulated in gli4py."
            )

    return violations


def test_no_direct_api_interactions_in_component() -> None:
    """Ensure no custom_components/glinet module bypasses gli4py with direct HTTP calls."""
    all_violations: list[str] = []

    py_files = sorted(PACKAGE_ROOT.glob("**/*.py"))
    assert len(py_files) > 0, "No python source files found to check"

    for py_file in py_files:
        code = py_file.read_text(encoding="utf-8")
        all_violations.extend(_check_source_for_direct_api_calls(code, py_file.name))

    assert not all_violations, (
        "Direct API / HTTP interactions detected in integration code:\n"
        + "\n".join(f"  - {v}" for v in all_violations)
        + "\n\nAll router communication must be handled by the upstream 'gli4py' library.\n"
        + "If you need a new API endpoint, open a PR in HarvsG/gli4py and link it in "
        + "your PR using 'Depends-on: HarvsG/gli4py#<PR_NUMBER>'."
    )


def test_boundary_checker_detects_violations() -> None:
    """Verify that the boundary checker catches prohibited HTTP patterns."""
    bad_snippets = [
        "import requests",
        "from httpx import post",
        "async def bad(session): await session.post('http://router/rpc')",
        "async def bad(session): await session.get('http://router/status')",
        "def bad(client): client.request('POST', '/api')",
        "RPC_URL = '/rpc'",
    ]

    for snippet in bad_snippets:
        violations = _check_source_for_direct_api_calls(snippet, "bad_example.py")
        assert len(violations) > 0, f"Expected violation for snippet: {snippet}"
