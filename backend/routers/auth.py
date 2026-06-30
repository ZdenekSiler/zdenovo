"""Authentication and authorization for admin pages."""

import secrets
from typing import Callable

from fastapi import Request
from fastapi.responses import RedirectResponse

from config import read_secret


# ─── Auth Guards ──────────────────────────────────────────────────────────────

def _is_admin(request: Request) -> bool:
    """Check if the request session has admin privileges."""
    return request.session.get("admin") is True


class AdminRequired(Exception):
    """Raised when admin auth is required but not present."""

    def __init__(self, next_url: str = "/admin/posts"):
        self.next_url = next_url


def require_admin(request: Request) -> None:
    """Dependency that enforces admin authentication.
    
    Raises AdminRequired if the request is not authenticated as admin.
    The exception is caught by the admin_required_handler in main.py.
    """
    if not _is_admin(request):
        raise AdminRequired(next_url=str(request.url.path))


# ─── Session & Redirect Validation ────────────────────────────────────────────

SAFE_REDIRECTS = {"/admin", "/admin/posts", "/admin/drafts", "/admin/comments", "/admin/topics", "/admin/stats", "/admin/deploys"}


def validate_redirect_url(url: str) -> str:
    """Ensure redirect URL is in the safe list. Defaults to /admin/posts."""
    return url if url in SAFE_REDIRECTS else "/admin/posts"


def verify_admin_password(password: str) -> bool:
    """Check password against configured admin secret."""
    admin_password = read_secret("admin_password", "ADMIN_PASSWORD")
    if not admin_password:
        return False
    return secrets.compare_digest(password.encode(), admin_password.encode())
