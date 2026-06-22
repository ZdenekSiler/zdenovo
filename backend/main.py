import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import mistune
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()  # no-op if .env absent; prod uses file secrets

from config import read_secret
from data.posts import get_all_posts, get_all_tags, get_post_by_slug, get_posts_page, total_pages
from data.projects import get_all_projects
from db import comment_row_to_dict, draft_row_to_dict, get_conn, init_db
from routers.comments_api import router as comments_router
from routers.drafts_api import _regenerate_draft, generate_daily_drafts, router as drafts_router
from routers.generate_api import router as generate_router
from routers.posts_api import router as posts_router

BASE_DIR = Path(__file__).parent.parent  # zdenovo/


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(generate_daily_drafts, "cron", hour=2, minute=0)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="zdenovo", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=read_secret("secret_key", "SECRET_KEY") or "dev-insecure-key-change-in-prod",
    session_cookie="zdenovo_session",
    max_age=60 * 60 * 24 * 7,  # 7 days
    https_only=False,           # set True in prod behind HTTPS
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend" / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "frontend" / "templates")

app.include_router(comments_router)
app.include_router(drafts_router)
app.include_router(generate_router)
app.include_router(posts_router)


def _fmt_date(d) -> str:
    """Cross-platform date format — %-d is Linux-only."""
    return f"{d.strftime('%b')} {d.day}, {d.year}"


templates.env.filters["dateformat"] = _fmt_date
templates.env.filters["markdown"] = mistune.html


# ─── Auth ─────────────────────────────────────────────────────────────────────

def _is_admin(request: Request) -> bool:
    return request.session.get("admin") is True


def require_admin(request: Request) -> None:
    if not _is_admin(request):
        raise _AdminRequired(next_url=str(request.url.path))


class _AdminRequired(Exception):
    def __init__(self, next_url: str = "/admin/posts"):
        self.next_url = next_url


@app.exception_handler(_AdminRequired)
async def _admin_required_handler(request: Request, exc: _AdminRequired):
    return RedirectResponse(f"/admin/login?next={exc.next_url}", status_code=303)


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, next: str = "/admin/posts"):
    if _is_admin(request):
        return RedirectResponse(next, status_code=303)
    return templates.TemplateResponse(request, "admin_login.html", {"next": next})


@app.post("/admin/login")
async def admin_login(
    request: Request,
    password: str = Form(...),
    next: str = Form("/admin/posts"),
):
    admin_password = read_secret("admin_password", "ADMIN_PASSWORD")
    if admin_password and secrets.compare_digest(password.encode(), admin_password.encode()):
        request.session["admin"] = True
        return RedirectResponse(next if next.startswith("/admin") else "/admin/posts", status_code=303)
    return templates.TemplateResponse(
        request, "admin_login.html", {"next": next, "error": "Wrong password."},
        status_code=401,
    )


@app.post("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


# ─── HTML pages ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    posts = get_all_posts()[:3]
    projects = [p for p in get_all_projects() if p["featured"]]
    tags = get_all_tags()
    return templates.TemplateResponse(request, "index.html", {
        "recent_posts": posts,
        "featured_projects": projects,
        "all_tags": tags,
    })


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    projects = [p for p in get_all_projects() if p["featured"]]
    tags = get_all_tags()
    return templates.TemplateResponse(request, "about.html", {
        "featured_projects": projects,
        "all_tags": tags,
    })


@app.get("/projects", response_class=HTMLResponse)
async def projects(request: Request):
    return templates.TemplateResponse(
        request, "projects.html", {"projects": get_all_projects()}
    )


@app.get("/blog", response_class=HTMLResponse)
async def blog(request: Request, tag: str | None = None, page: int = 1):
    posts, total = get_posts_page(page, tag=tag)
    n_pages = total_pages(total)
    return templates.TemplateResponse(
        request, "blog.html", {
            "posts": posts,
            "all_tags": get_all_tags(),
            "current_tag": tag,
            "page": page,
            "total_pages": n_pages,
        }
    )


@app.get("/blog/{slug}", response_class=HTMLResponse)
async def post(request: Request, slug: str):
    article = get_post_by_slug(slug)
    if article is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM comments WHERE post_slug = ? ORDER BY created_at ASC", (slug,)
        ).fetchall()
    comments = [comment_row_to_dict(r) for r in rows]
    return templates.TemplateResponse(request, "post.html", {"post": article, "comments": comments, "slug": slug})


@app.post("/blog/{slug}/comments", response_class=HTMLResponse)
async def submit_comment(request: Request, slug: str, author: str = Form(...), body: str = Form(...)):
    article = get_post_by_slug(slug)
    if article is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    if author.strip() and body.strip():
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO comments (id, post_slug, author, body, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), slug, author.strip()[:80], body.strip()[:2000], datetime.now(timezone.utc).isoformat()),
            )
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM comments WHERE post_slug = ? ORDER BY created_at ASC", (slug,)
        ).fetchall()
    comments = [comment_row_to_dict(r) for r in rows]
    return templates.TemplateResponse(request, "comments_section.html", {"comments": comments, "slug": slug})


# ─── Admin pages ──────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin_root(request: Request, _: None = Depends(require_admin)):
    return RedirectResponse("/admin/posts")


@app.get("/admin/posts", response_class=HTMLResponse)
async def admin_posts(request: Request, _: None = Depends(require_admin)):
    posts = get_all_posts()
    with get_conn() as conn:
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE status = 'pending'"
        ).fetchone()[0]
        comment_count = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    return templates.TemplateResponse(request, "admin_posts.html", {
        "posts": posts,
        "pending_count": pending_count,
        "comment_count": comment_count,
    })


@app.get("/admin/drafts", response_class=HTMLResponse)
async def admin_drafts(request: Request, _: None = Depends(require_admin)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM drafts ORDER BY generated_at DESC"
        ).fetchall()
    drafts = [draft_row_to_dict(r) for r in rows]
    return templates.TemplateResponse(request, "drafts_list.html", {"drafts": drafts})


@app.get("/admin/drafts/{draft_id}", response_class=HTMLResponse)
async def admin_draft_preview(request: Request, draft_id: str, _: None = Depends(require_admin)):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    draft = draft_row_to_dict(row)
    return templates.TemplateResponse(request, "draft_preview.html", {"draft": draft})


@app.get("/admin/comments", response_class=HTMLResponse)
async def admin_comments(request: Request, _: None = Depends(require_admin)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM comments ORDER BY created_at DESC"
        ).fetchall()
    comments = [comment_row_to_dict(r) for r in rows]
    return templates.TemplateResponse(request, "admin_comments.html", {"comments": comments})


@app.post("/admin/drafts/{draft_id}", response_class=HTMLResponse)
async def admin_draft_edit(
    request: Request,
    draft_id: str,
    title: str = Form(...),
    summary: str = Form(...),
    content: str = Form(...),
    tags: str = Form(""),
    _: None = Depends(require_admin),
):
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
    _regenerate_draft(draft_id, remarks)
    return RedirectResponse(f"/admin/drafts/{draft_id}", status_code=303)
