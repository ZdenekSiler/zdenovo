"""Zdenovo FastAPI blog application.

Main entry point with lifespan management, HTML page routes, and middleware setup.
Admin APIs and SEO routes are extracted to dedicated modules for clarity.
"""

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import mistune
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from slowapi.errors import RateLimitExceeded
from sanitize import safe_markdown
from rate_limit import limiter

load_dotenv()  # no-op if .env absent; prod uses file secrets

from code_validator import validate_content
from config import read_secret
from data.analytics import refresh_popular_posts
from data.drafts import get_draft_status_counts, get_drafts_grouped
from data.posts import get_all_posts, get_all_tags, get_category_counts, get_popular_posts, get_post_by_slug, get_posts_page, get_related_posts, get_series, get_series_list, get_series_siblings, search_posts, total_pages
from data.projects import get_all_projects
from db import comment_row_to_dict, deploy_row_to_dict, draft_row_to_dict, get_conn, init_db
from middleware.csrf import CSRFMiddleware
from routers.comments_api import generate_pending_comments, router as comments_router
from routers.drafts_api import _regenerate_draft, generate_daily_drafts, generate_single_topic, router as drafts_router
from routers.generate_api import router as generate_router
from routers.posts_api import router as posts_router
from routers.series_api import router as series_router
from routers.topics_api import _enrich_topics, _load_topics, _save_topics, _slugify, category_balance, create_topics, list_topics_for_admin, router as topics_router
from routers.auth import AdminRequired, _is_admin, require_admin, validate_redirect_url, verify_admin_password
from routers.deploys_api import router as deploys_router
from routers.seo import router as seo_router

BASE_DIR = Path(__file__).parent.parent  # zdenovo/

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)


# ─── Lifespan & Scheduler ─────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and start scheduler on app startup."""
    init_db()
    refresh_popular_posts()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(generate_daily_drafts, "cron", hour=2, minute=0)
    scheduler.add_job(refresh_popular_posts, "cron", hour="6,14,22", minute=0)
    scheduler.add_job(generate_pending_comments, "interval", days=3)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Zdenovo API",
    description="Blog platform API — posts, drafts, comments, topics, and AI generation.",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def ratelimit_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded errors."""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again later."}
    )


# ─── Middleware ───────────────────────────────────────────────────────────────

secret_key = read_secret("secret_key", "SECRET_KEY")
if not secret_key:
    raise RuntimeError("SECRET_KEY not configured. Set /run/secrets/secret_key or SECRET_KEY env var.")

app.add_middleware(
    SessionMiddleware,
    secret_key=secret_key,
    session_cookie="zdenovo_session",
    max_age=60 * 60 * 24 * 7,  # 7 days
    https_only=os.getenv("HTTPS_ONLY", "False").lower() == "true",
    same_site="lax",  # CSRF defense
)

# Add CSRF middleware AFTER SessionMiddleware (middleware order is reversed)
app.add_middleware(CSRFMiddleware)

app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend" / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "frontend" / "templates")


def _fmt_date(d) -> str:
    """Cross-platform date format — %-d is Linux-only."""
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def _fmt_views(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


templates.env.filters["dateformat"] = _fmt_date
templates.env.filters["format_views"] = _fmt_views
templates.env.filters["markdown"] = safe_markdown

_commit_file = Path("/app/BUILD_COMMIT")
templates.env.globals["build_commit"] = _commit_file.read_text().strip() if _commit_file.exists() else "dev"
templates.env.globals["deploy_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# Include API routers
app.include_router(comments_router)
app.include_router(deploys_router)
app.include_router(drafts_router)
app.include_router(generate_router)
app.include_router(posts_router)
app.include_router(series_router)
app.include_router(topics_router)
app.include_router(seo_router)


# ─── Auth Exception Handler ────────────────────────────────────────────────────

@app.exception_handler(AdminRequired)
async def admin_required_handler(request: Request, exc: AdminRequired):
    """Redirect unauthenticated requests to login page."""
    return RedirectResponse(f"/admin/login?next={exc.next_url}", status_code=303)


# ─── Auth Routes ──────────────────────────────────────────────────────────────

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, next: str = "/admin/posts") -> str:
    """Display admin login page."""
    if _is_admin(request):
        return RedirectResponse(next, status_code=303)
    return templates.TemplateResponse(request, "admin_login.html", {"next": next})


@app.post("/admin/login")
async def admin_login(
    request: Request,
    password: str = Form(...),
    next: str = Form("/admin/posts"),
):
    """Handle admin login form submission."""
    if verify_admin_password(password):
        request.session["admin"] = True
        next_url = validate_redirect_url(next)
        return RedirectResponse(next_url, status_code=303)
    return templates.TemplateResponse(
        request, "admin_login.html", {"next": next, "error": "Wrong password."},
        status_code=401,
    )


@app.post("/admin/logout")
async def admin_logout(request: Request):
    """Handle admin logout."""
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


# ─── Public HTML Pages ────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> str:
    """Home page with featured projects and recent posts."""
    posts = get_all_posts()[:3]
    projects = [p for p in get_all_projects() if p["featured"]]
    tags = get_all_tags()
    return templates.TemplateResponse(request, "index.html", {
        "recent_posts": posts,
        "featured_projects": projects,
        "all_tags": tags,
    })


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request) -> str:
    """About page with featured projects."""
    projects = [p for p in get_all_projects() if p["featured"]]
    tags = get_all_tags()
    return templates.TemplateResponse(request, "about.html", {
        "featured_projects": projects,
        "all_tags": tags,
    })


@app.get("/projects", response_class=HTMLResponse)
async def projects(request: Request) -> str:
    """Projects showcase page."""
    return templates.TemplateResponse(
        request, "projects.html", {"projects": get_all_projects()}
    )


@app.get("/projects/fakturant", response_class=HTMLResponse)
async def project_fakturant(request: Request) -> str:
    """Fakturant project details page."""
    return templates.TemplateResponse(request, "fakturant.html", {})


_BOT_UA_PATTERNS = ("bot", "crawler", "spider", "googlebot", "bingbot", "slurp", "duckduckbot", "curl", "wget", "python-")


@app.get("/blog", response_class=HTMLResponse)
async def blog(request: Request, tag: str | None = None, page: int = 1) -> str:
    """Blog listing page with pagination and tag filtering."""
    posts, total = get_posts_page(page, tag=tag)
    n_pages = total_pages(total)
    if tag:
        page_title = f"{tag.capitalize()} posts"
        meta_description = f"Posts tagged with {tag} on Zdenovo."
        canonical_url = f"https://zdenovo.com/blog?tag={tag}"
    else:
        page_title = "Blog"
        meta_description = "Notes on software engineering, AI development, tooling, and lessons learned the hard way."
        canonical_url = "https://zdenovo.com/blog"
    return templates.TemplateResponse(request, "blog.html", {
        "posts": posts,
        "current_tag": tag,
        "page": page,
        "total_pages": n_pages,
        "popular_posts": get_popular_posts(),
        "page_title": page_title,
        "meta_description": meta_description,
        "canonical_url": canonical_url,
    })


@app.get("/blog/search", response_class=HTMLResponse)
async def blog_search(request: Request, q: str = "") -> str:
    """HTMX HTML fragment for inline search results dropdown."""
    results = search_posts(q)
    return templates.TemplateResponse(request, "search_results.html", {"results": results})


@app.get("/blog/{slug}", response_class=HTMLResponse)
async def post(request: Request, slug: str) -> str:
    """Individual blog post page with comments."""
    article = get_post_by_slug(slug)
    if article is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)

    ua = (request.headers.get("user-agent") or "").lower()
    if not any(p in ua for p in _BOT_UA_PATTERNS):
        with get_conn() as conn:
            conn.execute("UPDATE posts SET views = views + 1 WHERE slug = ?", (slug,))
        article["views"] = article.get("views", 0) + 1

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM comments WHERE post_slug = ? AND (status = 'published' OR is_generated = 0)"
            " ORDER BY created_at ASC",
            (slug,),
        ).fetchall()
    all_comments = [comment_row_to_dict(r) for r in rows]
    top_level = [c for c in all_comments if c["parent_id"] is None]
    replies_by_parent: dict[str, list] = {}
    for c in all_comments:
        if c["parent_id"]:
            replies_by_parent.setdefault(c["parent_id"], []).append(c)

    series_posts: list[dict] = []
    series_position: int | None = None
    series_title: str | None = None
    if article.get("series_id"):
        series_posts = get_series_siblings(article["series_id"])
        with get_conn() as conn:
            s_row = conn.execute("SELECT title FROM series WHERE id = ?", (article["series_id"],)).fetchone()
            series_title = s_row["title"] if s_row else None
        for i, sp in enumerate(series_posts):
            if sp["slug"] == slug:
                series_position = i + 1
                break

    related = get_related_posts(slug, article["tags"])
    return templates.TemplateResponse(request, "post.html", {
        "post": article,
        "comments": top_level,
        "replies_by_parent": replies_by_parent,
        "slug": slug,
        "related_posts": related,
        "series_posts": series_posts,
        "series_position": series_position,
        "series_title": series_title,
        "is_admin": False,
    })


@app.get("/series", response_class=HTMLResponse)
async def series_hub(request: Request) -> str:
    """Public hub listing all series that have at least one published post."""
    series = [s for s in get_series_list() if s["post_count"] > 0]
    return templates.TemplateResponse(request, "series_list.html", {
        "series": series,
        "page_title": "Series",
        "meta_description": "Multi-part series on Zdenovo — deep dives, overviews, and tutorials.",
        "canonical_url": "https://zdenovo.com/series",
    })


@app.get("/series/{series_id}", response_class=HTMLResponse)
async def series_detail(request: Request, series_id: str) -> str:
    """Public landing page for one series: description + ordered list of its published parts."""
    series = get_series(series_id)
    parts = get_series_siblings(series_id) if series else []
    if series is None or not parts:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return templates.TemplateResponse(request, "series_detail.html", {
        "series": series,
        "parts": parts,
        "page_title": series["title"],
        "meta_description": series.get("description") or f"The {series['title']} series on Zdenovo.",
        "canonical_url": f"https://zdenovo.com/series/{series_id}",
    })


@app.get("/blog/{slug}/comments/{comment_id}/reply-form", response_class=HTMLResponse)
async def comment_reply_form(request: Request, slug: str, comment_id: str) -> str:
    """Return inline reply form partial for HTMX."""
    return templates.TemplateResponse(request, "reply_form.html", {"slug": slug, "parent_id": comment_id})


@app.post("/blog/{slug}/comments", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def submit_comment(
    request: Request,
    slug: str,
    author: str = Form(...),
    body: str = Form(...),
    parent_id: str = Form(""),
) -> str:
    """Submit a comment on a blog post (rate limited)."""
    article = get_post_by_slug(slug)
    if article is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)

    author = author.strip()
    body = body.strip()
    if not (1 <= len(author) <= 80):
        raise HTTPException(status_code=400, detail="Author must be 1-80 characters")
    if not (1 <= len(body) <= 2000):
        raise HTTPException(status_code=400, detail="Body must be 1-2000 characters")

    pid = parent_id.strip() or None
    if pid:
        with get_conn() as conn:
            parent_row = conn.execute("SELECT parent_id FROM comments WHERE id = ?", (pid,)).fetchone()
        if parent_row is None:
            raise HTTPException(status_code=404, detail="Parent comment not found")
        if parent_row["parent_id"] is not None:
            raise HTTPException(status_code=422, detail="Cannot reply to a reply (max 1 level of threading)")

    if author and body:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO comments (id, post_slug, author, body, created_at, is_generated, parent_id) VALUES (?, ?, ?, ?, ?, 0, ?)",
                (str(uuid.uuid4()), slug, author[:80], body[:2000], datetime.now(timezone.utc).isoformat(), pid),
            )
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM comments WHERE post_slug = ? AND (status = 'published' OR is_generated = 0)"
            " ORDER BY created_at ASC",
            (slug,),
        ).fetchall()
    all_comments = [comment_row_to_dict(r) for r in rows]
    top_level = [c for c in all_comments if c["parent_id"] is None]
    replies_by_parent: dict[str, list] = {}
    for c in all_comments:
        if c["parent_id"]:
            replies_by_parent.setdefault(c["parent_id"], []).append(c)
    return templates.TemplateResponse(
        request, "comments_section.html",
        {"comments": top_level, "replies_by_parent": replies_by_parent, "slug": slug, "is_admin": False},
    )


# ─── Admin Dashboard & Posts ──────────────────────────────────────────────────

@app.get("/admin/", response_class=HTMLResponse)
@app.get("/admin", response_class=HTMLResponse)
async def admin_root(request: Request, _: None = Depends(require_admin)) -> str:
    """Admin dashboard with statistics."""
    posts = get_all_posts()
    with get_conn() as conn:
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE status = 'pending'"
        ).fetchone()[0]
        comment_count = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        generated_comment_count = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE is_generated = 1"
        ).fetchone()[0]
        comment_pending_count = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE status IN ('generated', 'approved')"
        ).fetchone()[0]
        last_deploy_row = conn.execute(
            "SELECT commit_hash, status FROM deploys ORDER BY deployed_at DESC LIMIT 1"
        ).fetchone()
    real_comment_count = comment_count - generated_comment_count
    topic_count = len(_load_topics())
    series_count = len(get_series_list())
    return templates.TemplateResponse(request, "admin_hub.html", {
        "post_count": len(posts),
        "pending_count": pending_count,
        "comment_count": comment_count,
        "real_comment_count": real_comment_count,
        "generated_comment_count": generated_comment_count,
        "comment_pending_count": comment_pending_count,
        "topic_count": topic_count,
        "series_count": series_count,
        "last_deploy_commit": last_deploy_row["commit_hash"] if last_deploy_row else None,
        "last_deploy_status": last_deploy_row["status"] if last_deploy_row else None,
    })


@app.get("/admin/deploys", response_class=HTMLResponse)
async def admin_deploys(request: Request, _: None = Depends(require_admin)) -> str:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM deploys ORDER BY deployed_at DESC LIMIT 50"
        ).fetchall()
    deploys = [deploy_row_to_dict(r) for r in rows]
    return templates.TemplateResponse(request, "admin_deploys.html", {"deploys": deploys})


@app.get("/admin/posts", response_class=HTMLResponse)
async def admin_posts(request: Request, category: str | None = None, _: None = Depends(require_admin)) -> str:
    """Admin page listing all published posts, optionally filtered by category."""
    from data.categories import load_categories
    posts = get_all_posts(category=category)
    with get_conn() as conn:
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE status = 'pending'"
        ).fetchone()[0]
        comment_count = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    return templates.TemplateResponse(request, "admin_posts.html", {
        "posts": posts,
        "pending_count": pending_count,
        "comment_count": comment_count,
        "category_counts": get_category_counts(),
        "current_category": category,
        "categories": load_categories(),
    })


def _category_picker_html(slug: str, current: str | None) -> str:
    """HTML for the inline category-picker <select> on /admin/posts (mirrors _ai_toggle_btn's
    pattern of building a small swappable fragment for HTMX partial updates)."""
    from data.categories import load_categories
    options = [f'<option value=""{" selected" if current is None else ""}>Uncategorized</option>']
    for c in load_categories():
        selected = " selected" if c["id"] == current else ""
        options.append(f'<option value="{c["id"]}"{selected}>{c["label"]}</option>')
    return (
        f'<select name="category" hx-post="/admin/posts/{slug}/category" '
        f'hx-trigger="change" hx-target="this" hx-swap="outerHTML" '
        f'class="category-picker text-[11px] bg-zinc-950 border border-zinc-800 rounded px-1.5 py-1 text-zinc-400">'
        + "".join(options) +
        "</select>"
    )


@app.post("/admin/posts/{slug}/category", response_class=HTMLResponse)
async def admin_set_post_category(
    request: Request, slug: str, category: str = Form(""), _: None = Depends(require_admin)
) -> str:
    """Set or clear a post's category from the admin inline picker."""
    from data.categories import load_categories
    value = category.strip() or None
    if value is not None and value not in {c["id"] for c in load_categories()}:
        raise HTTPException(status_code=422, detail=f"Unknown category '{value}'")
    with get_conn() as conn:
        row = conn.execute("SELECT slug FROM posts WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Post not found")
        conn.execute("UPDATE posts SET category = ? WHERE slug = ?", (value, slug))
    return _category_picker_html(slug, value)


@app.post("/api/posts/{slug}/toggle-ai-comments", response_class=HTMLResponse)
async def toggle_ai_comments(slug: str, _: None = Depends(require_admin)) -> str:
    """Toggle AI comment generation for a post."""
    with get_conn() as conn:
        row = conn.execute("SELECT ai_comments FROM posts WHERE slug = ?", (slug,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Post not found")
        new_val = 0 if row["ai_comments"] else 1
        conn.execute("UPDATE posts SET ai_comments = ? WHERE slug = ?", (new_val, slug))
    return _ai_toggle_btn(slug, bool(new_val))


def _ai_toggle_btn(slug: str, enabled: bool) -> str:
    """HTML for AI toggle button."""
    label = "AI: on" if enabled else "AI: off"
    cls = "text-emerald-400 border-emerald-900/40 hover:border-emerald-700/60" if enabled else "text-zinc-500"
    return (
        f'<button hx-post="/api/posts/{slug}/toggle-ai-comments" '
        f'hx-target="this" hx-swap="outerHTML" '
        f'class="btn-ghost text-xs {cls}">'
        f'{label}</button>'
    )


# ─── Admin Series ─────────────────────────────────────────────────────────────

@app.get("/admin/series", response_class=HTMLResponse)
async def admin_series(request: Request, _: None = Depends(require_admin)) -> str:
    """List all post series, each with its parts (pending drafts + published posts)."""
    series = get_series_list()
    for s in series:
        with get_conn() as conn:
            draft_rows = conn.execute(
                "SELECT id, title, series_order, quality_score FROM drafts"
                " WHERE series_id = ? AND status = 'pending' ORDER BY series_order ASC",
                (s["id"],),
            ).fetchall()
        parts = [
            {"kind": "draft", "order": d["series_order"], "title": d["title"],
             "ref": f"/admin/drafts/{d['id']}", "score": d["quality_score"]}
            for d in draft_rows
        ] + [
            {"kind": "post", "order": p["series_order"], "title": p["title"],
             "ref": f"/blog/{p['slug']}"}
            for p in get_series_siblings(s["id"])
        ]
        parts.sort(key=lambda x: (x["order"] is None, x["order"] or 0))
        s["parts"] = parts
        # Outline parts that have neither a published post nor a pending draft — offer to (re)generate.
        present = {p["order"] for p in parts}
        missing = []
        if s.get("outline"):
            for op in json.loads(s["outline"]).get("parts", []):
                if op["part_number"] not in present:
                    missing.append({"order": op["part_number"], "title": op["title"]})
        s["missing"] = sorted(missing, key=lambda m: m["order"])
    from routers.series_api import load_series_types
    return templates.TemplateResponse(
        request, "admin_series.html", {"series": series, "series_types": load_series_types()}
    )


@app.post("/admin/series", response_class=HTMLResponse)
async def admin_series_create(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    _: None = Depends(require_admin),
) -> RedirectResponse:
    """Create a new series."""
    import re
    series_id = re.sub(r"[^\w\s-]", "", title.lower().strip())
    series_id = re.sub(r"[\s_]+", "-", series_id)[:80]
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM series WHERE id = ?", (series_id,)).fetchone()
        if existing:
            series_id = f"{series_id}-{int(now[-6:].replace(':', ''))}"
        conn.execute(
            "INSERT INTO series (id, title, description, created_at) VALUES (?, ?, ?, ?)",
            (series_id, title.strip(), description.strip() or None, now),
        )
    return RedirectResponse("/admin/series", status_code=303)


@app.post("/admin/series/{series_id}/delete", response_class=HTMLResponse)
async def admin_series_delete(
    request: Request,
    series_id: str,
    _: None = Depends(require_admin),
) -> RedirectResponse:
    """Delete a series (clears assignment on posts)."""
    with get_conn() as conn:
        conn.execute("UPDATE posts SET series_id = NULL, series_order = NULL WHERE series_id = ?", (series_id,))
        conn.execute("DELETE FROM series WHERE id = ?", (series_id,))
    return RedirectResponse("/admin/series", status_code=303)


# ─── Admin Drafts ─────────────────────────────────────────────────────────────

@app.get("/admin/drafts", response_class=HTMLResponse)
async def admin_drafts(
    request: Request, status: str | None = None, _: None = Depends(require_admin)
) -> str:
    """List drafts, filtered by status. Defaults to pending-only (the actionable
    review queue) when no ?status= is given; ?status=all shows everything."""
    effective_status = status or "pending"
    grouped = get_drafts_grouped(None if effective_status == "all" else effective_status)
    return templates.TemplateResponse(request, "drafts_list.html", {
        "series_groups": grouped["series_groups"],
        "standalone": grouped["standalone"],
        "status_counts": get_draft_status_counts(),
        "current_status": effective_status,
    })


@app.get("/admin/drafts/{draft_id}", response_class=HTMLResponse)
async def admin_draft_preview(request: Request, draft_id: str, _: None = Depends(require_admin)) -> str:
    """View and edit a draft."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    draft = draft_row_to_dict(row)
    summary = validate_content(draft["content"])
    validation_json = json.dumps([r.model_dump() for r in summary.results])
    return templates.TemplateResponse(request, "draft_preview.html", {
        "draft": draft,
        "validation": summary,
        "validation_json": validation_json,
    })


@app.post("/admin/drafts/{draft_id}", response_class=HTMLResponse)
async def admin_draft_edit(
    request: Request,
    draft_id: str,
    title: str = Form(...),
    summary: str = Form(...),
    content: str = Form(...),
    tags: str = Form(""),
    _: None = Depends(require_admin),
) -> RedirectResponse:
    """Update a draft's content."""
    tags_list = [t.strip() for t in tags.split(",") if t.strip()]
    with get_conn() as conn:
        conn.execute(
            "UPDATE drafts SET title=?, summary=?, content=?, tags=? WHERE id=?",
            (title, summary, content, json.dumps(tags_list), draft_id),
        )
    return RedirectResponse(f"/admin/drafts/{draft_id}", status_code=303)


@app.post("/admin/drafts/{draft_id}/regenerate", response_class=HTMLResponse)
async def admin_draft_regenerate(
    request: Request,
    draft_id: str,
    remarks: str = Form(...),
    _: None = Depends(require_admin),
):
    """Regenerate a draft based on editorial feedback."""
    _regenerate_draft(draft_id, remarks)
    if request.headers.get("HX-Request"):
        from fastapi.responses import Response
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = f"/admin/drafts/{draft_id}"
        return response
    return RedirectResponse(f"/admin/drafts/{draft_id}", status_code=303)


# ─── Admin Comments ───────────────────────────────────────────────────────────

@app.get("/admin/comments", response_class=HTMLResponse)
async def admin_comments(request: Request, _: None = Depends(require_admin)) -> str:
    """List all comments."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM comments ORDER BY created_at DESC"
        ).fetchall()
        generated_count = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE is_generated = 1"
        ).fetchone()[0]
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE status = 'generated'"
        ).fetchone()[0]
        approved_count = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE status = 'approved'"
        ).fetchone()[0]
    comments = [comment_row_to_dict(r) for r in rows]
    real_count = len(comments) - generated_count
    return templates.TemplateResponse(request, "admin_comments.html", {
        "comments": comments,
        "real_count": real_count,
        "generated_count": generated_count,
        "pending_count": pending_count,
        "approved_count": approved_count,
    })


# ─── Admin Stats ──────────────────────────────────────────────────────────────

def _api_cost_summary() -> dict:
    """Aggregate api_costs for the admin cost panel: totals + breakdown by model/step/day."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    d7 = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    d30 = (now - timedelta(days=29)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        def since(day: str) -> float:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM api_costs WHERE substr(created_at, 1, 10) >= ?", (day,)
            ).fetchone()
            return round(row[0], 4)
        today_cost = round(conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM api_costs WHERE substr(created_at, 1, 10) = ?", (today,)
        ).fetchone()[0], 4)
        by_model = [dict(r) for r in conn.execute(
            "SELECT model, COUNT(*) AS calls, ROUND(SUM(cost_usd), 4) AS cost FROM api_costs GROUP BY model ORDER BY cost DESC")]
        by_step = [dict(r) for r in conn.execute(
            "SELECT step, COUNT(*) AS calls, ROUND(SUM(cost_usd), 4) AS cost FROM api_costs GROUP BY step ORDER BY cost DESC")]
        recent_days = [dict(r) for r in conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, ROUND(SUM(cost_usd), 4) AS cost, COUNT(*) AS calls"
            " FROM api_costs GROUP BY day ORDER BY day DESC LIMIT 14")]
        n_calls = conn.execute("SELECT COUNT(*) FROM api_costs").fetchone()[0]
    return {
        "today": today_cost, "last7": since(d7), "last30": since(d30),
        "all_total": since("0000"), "calls": n_calls,
        "by_model": by_model, "by_step": by_step, "recent_days": recent_days,
    }


@app.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats(request: Request, _: None = Depends(require_admin)) -> str:
    """Display analytics from Cloudflare + Anthropic API cost tracking."""
    import urllib.request
    from datetime import timedelta

    cost = _api_cost_summary()

    cf_token = read_secret("cloudflare_api_token", "CLOUDFLARE_API_TOKEN")
    zone_id = os.environ.get("CF_ZONE_ID", "")

    if not cf_token or not zone_id:
        return templates.TemplateResponse(request, "admin_stats.html", {"cost": cost, "error": "Analytics not configured. Set CLOUDFLARE_API_TOKEN and CF_ZONE_ID."})

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y-%m-%d")

    # httpRequests1dGroups supports up to 30 days.
    # httpRequestsAdaptiveGroups is limited to a 1-day range — use today only.
    query = """
    query($zoneTag: String!, $dateGt: String!, $dateLe: String!, $dateToday: String!) {
      viewer {
        zones(filter: {zoneTag: $zoneTag}) {
          daily: httpRequests1dGroups(
            limit: 7
            filter: {date_geq: $dateGt, date_leq: $dateLe}
          ) {
            dimensions { date }
            sum { requests pageViews }
            uniq { uniques }
          }
          topPaths: httpRequestsAdaptiveGroups(
            limit: 10
            filter: {date_geq: $dateToday, date_leq: $dateToday, requestSource: "eyeball"}
            orderBy: [count_DESC]
          ) {
            dimensions { clientRequestPath }
            count
          }
          topCountries: httpRequestsAdaptiveGroups(
            limit: 10
            filter: {date_geq: $dateToday, date_leq: $dateToday, requestSource: "eyeball"}
            orderBy: [count_DESC]
          ) {
            dimensions { clientCountryName }
            count
          }
          topBrowsers: httpRequestsAdaptiveGroups(
            limit: 5
            filter: {date_geq: $dateToday, date_leq: $dateToday, requestSource: "eyeball"}
            orderBy: [count_DESC]
          ) {
            dimensions { userAgent }
            count
          }
        }
      }
    }
    """

    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4/graphql",
        data=json.dumps({
            "query": query,
            "variables": {
                "zoneTag": zone_id,
                "dateGt": week_ago,
                "dateLe": today,
                "dateToday": today,
            }
        }).encode(),
        headers={"Authorization": f"Bearer {cf_token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 — URL is Cloudflare API endpoint, not user input
            data = json.loads(resp.read())
    except Exception as exc:
        log.error("Cloudflare API request failed: %s", exc, exc_info=True)
        return templates.TemplateResponse(
            request, "admin_stats.html",
            {"cost": cost, "error": "Failed to fetch analytics from Cloudflare."}
        )

    if data.get("errors") or not data.get("data"):
        msg = data.get("errors", [{}])[0].get("message", "Unknown error") if data.get("errors") else "Empty response"
        return templates.TemplateResponse(request, "admin_stats.html", {"cost": cost, "error": f"Cloudflare API error: {msg}"})

    zones = data["data"].get("viewer", {}).get("zones", [{}])
    zone = zones[0] if zones else {}

    daily_raw = zone.get("daily", [])
    daily = sorted(
        [
            {
                "date": d["dimensions"]["date"],
                "page_views": d["sum"]["pageViews"],
                "requests": d["sum"]["requests"],
                "uniques": d["uniq"]["uniques"],
            }
            for d in daily_raw
        ],
        key=lambda d: d["date"],
    )
    max_views = max((d["page_views"] for d in daily), default=1) or 1
    max_uniques = max((d["uniques"] for d in daily), default=1) or 1
    for d in daily:
        d["views_pct"] = round(d["page_views"] / max_views * 100)
        d["uniques_pct"] = round(d["uniques"] / max_uniques * 100)
        dt = datetime.strptime(d["date"], "%Y-%m-%d")
        d["day_label"] = dt.strftime("%a")
        d["date_label"] = dt.strftime("%b %d")

    totals = {
        "page_views": sum(d["page_views"] for d in daily),
        "uniques": sum(d["uniques"] for d in daily),
        "requests": sum(d["requests"] for d in daily),
    }

    top_pages = [{"path": r["dimensions"]["clientRequestPath"], "count": r["count"]} for r in zone.get("topPaths", [])]
    top_countries = [{"country": r["dimensions"]["clientCountryName"], "count": r["count"]} for r in zone.get("topCountries", [])]
    top_browsers = [{"browser": r["dimensions"]["userAgent"], "count": r["count"]} for r in zone.get("topBrowsers", [])]

    return templates.TemplateResponse(request, "admin_stats.html", {
        "cost": cost,
        "daily": daily,
        "totals": totals,
        "top_pages": top_pages,
        "top_countries": top_countries,
        "top_browsers": top_browsers,
    })


@app.get("/api/costs/summary")
async def api_costs_summary(request: Request, _: None = Depends(require_admin)):
    """JSON snapshot of API spend + an internal quality signal, for the /cost-review skill.
    Admin only. Spend comes from the api_costs table; quality from draft review scores."""
    from fastapi.responses import JSONResponse
    data = _api_cost_summary()
    with get_conn() as conn:
        q = conn.execute(
            "SELECT COUNT(*) AS n, AVG(quality_score) AS avg,"
            " SUM(CASE WHEN quality_score >= 6 THEN 1 ELSE 0 END) AS passing"
            " FROM drafts WHERE quality_score IS NOT NULL"
        ).fetchone()
    data["quality"] = {
        "drafts_scored": q["n"],
        "avg_review_score": round(q["avg"], 2) if q["avg"] is not None else None,
        "passing_ge6": q["passing"] or 0,
    }
    return JSONResponse(data)


# ─── Admin Topics ─────────────────────────────────────────────────────────────

@app.get("/admin/topics", response_class=HTMLResponse)
async def admin_topics(request: Request, _: None = Depends(require_admin)) -> str:
    """List all generation topics."""
    topics = list_topics_for_admin()
    available_count = sum(1 for t in topics if t["status"] == "available")
    return templates.TemplateResponse(request, "admin_topics.html", {
        "topics": topics,
        "available_count": available_count,
    })


@app.get("/admin/topics/categories", response_class=HTMLResponse)
async def admin_topic_categories(request: Request, _: None = Depends(require_admin)) -> str:
    """Category balance dashboard — shows how the topic pool is distributed across
    the fixed discovery categories, so rotation balance is visible at a glance."""
    categories = category_balance(_enrich_topics(_load_topics()))
    return templates.TemplateResponse(request, "admin_topic_categories.html", {"categories": categories})


@app.get("/admin/topics/new", response_class=HTMLResponse)
async def admin_topic_new(request: Request, _: None = Depends(require_admin)) -> str:
    """New topic creation form."""
    return templates.TemplateResponse(request, "admin_topic_edit.html", {"topic": None})


@app.get("/admin/topics/{topic_id}/edit", response_class=HTMLResponse)
async def admin_topic_edit(request: Request, topic_id: str, _: None = Depends(require_admin)) -> str:
    """Edit topic form."""
    topics = _load_topics()
    topic = next((t for t in topics if t["id"] == topic_id), None)
    if topic is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return templates.TemplateResponse(request, "admin_topic_edit.html", {"topic": topic})


@app.post("/admin/topics", response_class=HTMLResponse)
async def admin_topic_create(
    request: Request,
    title_hint: str = Form(...),
    description: str = Form(...),
    audience: str = Form(...),
    tone: str = Form(...),
    tags: str = Form(""),
    outline: str = Form(""),
    _: None = Depends(require_admin),
) -> RedirectResponse:
    """Create a new topic."""
    data = {
        "title_hint": title_hint.strip(),
        "description": description.strip(),
        "audience": audience.strip(),
        "tone": tone.strip(),
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "outline": [line.strip() for line in outline.splitlines() if line.strip()],
    }
    create_topics([data])
    return RedirectResponse("/admin/topics", status_code=303)


@app.post("/admin/topics/{topic_id}", response_class=HTMLResponse)
async def admin_topic_update(
    request: Request,
    topic_id: str,
    title_hint: str = Form(...),
    description: str = Form(...),
    audience: str = Form(...),
    tone: str = Form(...),
    tags: str = Form(""),
    outline: str = Form(""),
    _: None = Depends(require_admin),
) -> RedirectResponse:
    """Update a topic."""
    topics = _load_topics()
    topic = next((t for t in topics if t["id"] == topic_id), None)
    if topic is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    topic["title_hint"] = title_hint.strip()
    topic["description"] = description.strip()
    topic["audience"] = audience.strip()
    topic["tone"] = tone.strip()
    topic["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    topic["outline"] = [line.strip() for line in outline.splitlines() if line.strip()]
    _save_topics(topics)
    return RedirectResponse("/admin/topics", status_code=303)


@app.post("/admin/topics/{topic_id}/generate", response_class=HTMLResponse)
async def admin_topic_generate(request: Request, topic_id: str, _: None = Depends(require_admin)) -> RedirectResponse:
    """Generate a draft from a topic."""
    draft = generate_single_topic(topic_id)
    return RedirectResponse(f"/admin/drafts/{draft.id}", status_code=303)


@app.post("/admin/topics/{topic_id}/delete", response_class=HTMLResponse)
async def admin_topic_delete(request: Request, topic_id: str, _: None = Depends(require_admin)) -> RedirectResponse:
    """Delete a topic."""
    topics = _load_topics()
    topics = [t for t in topics if t["id"] != topic_id]
    _save_topics(topics)
    return RedirectResponse("/admin/topics", status_code=303)
