#!/usr/bin/env python3
"""Route auth audit — Layer 2 security gate.

Scans backend/routers/*.py for state-changing endpoints (POST/PATCH/DELETE/PUT)
and verifies each one is protected by `require_admin`, either:

  1. As a FastAPI dependency in the function signature, e.g.
     `_: None = Depends(require_admin)` or `Depends(_get_require_admin)`, or
  2. As a direct call inside the function body.

Endpoints not protected this way must be explicitly whitelisted below as
known-public (intentionally unauthenticated) routes. Anything else fails the
audit.

Usage:
    uv run python scripts/route-auth-audit.py

Exit code 0 = all state-changing routes are protected or whitelisted.
Exit code 1 = at least one unprotected, non-whitelisted route was found.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTERS_DIR = REPO_ROOT / "backend" / "routers"

STATE_CHANGING_METHODS = {"post", "patch", "delete", "put"}

# Known-public endpoints: intentionally unauthenticated by design.
# Keyed by (filename, function_name). Document *why* here, not just *what*.
PUBLIC_WHITELIST: dict[tuple[str, str], str] = {
    ("comments_api.py", "create_comment"): (
        "POST /api/comments — reader-submitted comments (JSON API)."
    ),
    # POST /blog/{slug}/comments (the HTML form equivalent) lives in main.py,
    # not in routers/, so it is outside this script's scan scope by design.
    ("posts_api.py", "react_to_post"): (
        "POST /{slug}/react — public thumbs-up reaction, rate-limited via slowapi."
    ),
    ("posts_api.py", "react_down_to_post"): (
        "POST /{slug}/react-down — public thumbs-down reaction, rate-limited via slowapi."
    ),
    ("deploys_api.py", "create_deploy"): (
        "POST /api/deploys — machine-to-machine endpoint protected by X-Deploy-Token "
        "shared secret (_verify_deploy_token), not admin session. Called by Makefile "
        "via scripts/record-deploy.sh after each prod deploy."
    ),
}


@dataclass
class Endpoint:
    file: str
    function: str
    method: str
    path: str
    line: int
    protected: bool
    whitelisted: bool


def _decorator_route_info(decorator: ast.expr) -> tuple[str, str] | None:
    """Return (http_method, path) if `decorator` is a @router.<method>(...) call."""
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return None
    method = func.attr.lower()
    if method not in STATE_CHANGING_METHODS:
        return None
    # First positional arg is the path, e.g. @router.post("/{id}")
    path = "<unknown>"
    if decorator.args and isinstance(decorator.args[0], ast.Constant):
        if isinstance(decorator.args[0].value, str):
            path = decorator.args[0].value
    return method, path


# Helper function names that may wrap `require_admin` (e.g. to dodge
# circular imports). Only counted as real protection once verified by
# `_is_genuine_require_admin_wrapper` to actually return the real thing.
REQUIRE_ADMIN_NAMES = {"require_admin", "_get_require_admin"}


def _calls_require_admin(node: ast.AST, verified_names: set[str]) -> bool:
    """True if a verified `require_admin` reference appears anywhere in the
    function's subtree — either as a Depends(...) default in the signature
    or a direct call in the body."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in verified_names:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in verified_names:
            return True
    return False


def _is_genuine_require_admin_wrapper(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A `_get_require_admin`-style helper only counts as protection if it
    actually imports and returns the real `require_admin` from
    `routers.auth` — guards against a same-named decoy short-circuiting
    the audit."""
    imports_it = any(
        isinstance(sub, ast.ImportFrom)
        and sub.module == "routers.auth"
        and any(alias.name == "require_admin" for alias in sub.names)
        for sub in ast.walk(func)
    )
    returns_it = any(
        isinstance(sub, ast.Return)
        and isinstance(sub.value, ast.Name)
        and sub.value.id == "require_admin"
        for sub in ast.walk(func)
    )
    return imports_it and returns_it


def _verified_require_admin_names(tree: ast.Module) -> set[str]:
    """Names in this module that resolve to the real `require_admin`:
    the name itself (if imported directly) plus any verified lazy-loader
    wrapper functions."""
    names = {"require_admin"}
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in REQUIRE_ADMIN_NAMES
            and _is_genuine_require_admin_wrapper(node)
        ):
            names.add(node.name)
    return names


def _scan_file(path: Path) -> list[Endpoint]:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    endpoints: list[Endpoint] = []
    verified_names = _verified_require_admin_names(tree)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            info = _decorator_route_info(decorator)
            if info is None:
                continue
            method, route_path = info
            protected = _calls_require_admin(node, verified_names)
            whitelist_key = (path.name, node.name)
            whitelisted = whitelist_key in PUBLIC_WHITELIST
            endpoints.append(
                Endpoint(
                    file=path.name,
                    function=node.name,
                    method=method.upper(),
                    path=route_path,
                    line=node.lineno,
                    protected=protected,
                    whitelisted=whitelisted,
                )
            )
    return endpoints


def main() -> int:
    if not ROUTERS_DIR.is_dir():
        print(f"ERROR: routers directory not found at {ROUTERS_DIR}")
        return 1

    router_files = sorted(ROUTERS_DIR.glob("*.py"))
    router_files = [f for f in router_files if f.name != "__init__.py"]

    all_endpoints: list[Endpoint] = []
    for f in router_files:
        all_endpoints.extend(_scan_file(f))

    if not all_endpoints:
        print("No state-changing endpoints found — nothing to audit.")
        return 0

    failures: list[Endpoint] = []

    print("=== Route auth audit ===")
    for ep in sorted(all_endpoints, key=lambda e: (e.file, e.line)):
        if ep.protected:
            status = "PASS (require_admin)"
        elif ep.whitelisted:
            reason = PUBLIC_WHITELIST[(ep.file, ep.function)]
            status = f"PASS (whitelisted: {reason})"
        else:
            status = "FAIL (no require_admin, not whitelisted)"
            failures.append(ep)

        print(f"  [{status}] {ep.method:6s} {ep.path:30s} {ep.file}:{ep.line} ({ep.function})")

    # Flag stale whitelist entries (functions that no longer exist or are
    # no longer state-changing routes) — not a failure, just a warning.
    seen = {(e.file, e.function) for e in all_endpoints}
    stale = [key for key in PUBLIC_WHITELIST if key not in seen]
    for file_name, func_name in stale:
        print(f"  [WARN] Whitelist entry {file_name}:{func_name} did not match any scanned route.")

    print()
    if failures:
        print(f"FAILED: {len(failures)} unprotected endpoint(s) found:")
        for ep in failures:
            print(f"  - {ep.method} {ep.path} in {ep.file}:{ep.line} ({ep.function})")
        return 1

    print(f"All {len(all_endpoints)} state-changing endpoint(s) are protected or whitelisted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
