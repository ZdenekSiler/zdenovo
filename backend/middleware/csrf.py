"""CSRF protection middleware using session-based tokens."""
import secrets
from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF protection middleware that:
    1. Generates a CSRF token on first request and stores in session
    2. Validates token on state-changing requests (POST, PUT, PATCH, DELETE)
    3. Skips validation for API routes (which rely on same-origin policy)
    """

    async def dispatch(self, request: Request, call_next):
        # Generate CSRF token if not in session
        if "csrf_token" not in request.session:
            request.session["csrf_token"] = secrets.token_urlsafe(32)

        # Validate CSRF token on state-changing HTML form requests
        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            # Skip validation for API routes (they use JSON, not forms, and rely on same-origin)
            # Skip validation for auth routes (login form is public, logout is safe)
            if not request.url.path.startswith("/api/") and not request.url.path.startswith("/admin/login"):
                # For HTML forms, get token from form data
                try:
                    form_data = await request.form()
                    token = form_data.get("csrf_token")
                except Exception:
                    # If not a form request, skip validation (e.g., JSON API requests)
                    response = await call_next(request)
                    return response

                session_token = request.session.get("csrf_token")
                if not token or token != session_token:
                    raise HTTPException(status_code=403, detail="CSRF token invalid or missing")

        response = await call_next(request)
        return response
