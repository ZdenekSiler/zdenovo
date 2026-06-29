# This file contains the updates to add to main.py for Phase 2
# Specifically for rate limiting and XSS sanitization

# 1. Add these imports after line 19 (after other imports from local modules):
"""
from middleware.ratelimit import limiter, LIMIT_COMMENT_SUBMIT, LIMIT_GENERATION
from sanitize import safe_markdown
from slowapi.errors import RateLimitExceeded
"""

# 2. Register rate limiter error handler (add after app initialization, around line 75):
"""
@app.exception_handler(RateLimitExceeded)
async def ratelimit_handler(request: Request, exc: RateLimitExceeded):
    return templates.TemplateResponse(
        request,
        "error.html",
        {"error": "Too many requests. Please try again later."},
        status_code=429,
    )
"""

# 3. Update markdown filter (replace line ~92):
"""
templates.env.filters["markdown"] = safe_markdown  # Changed from mistune.html
"""

# 4. Add rate limiting to comment submission (update submit_comment decorator):
"""
@app.post("/blog/{slug}/comments", response_class=HTMLResponse)
@limiter.limit(LIMIT_COMMENT_SUBMIT)
async def submit_comment(request: Request, slug: str, author: str = Form(...), body: str = Form(...)):
    # ... rest of function unchanged
"""

# 5. Register limiter with app (add after middleware setup, around line 75):
"""
app.state.limiter = limiter
"""

print("Phase 2 updates documented. Ready to implement.")
