from contextlib import asynccontextmanager
from pathlib import Path

import mistune
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv()  # no-op if .env absent; prod uses system env vars
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from data.posts import get_all_tags, get_post_by_slug, get_posts_page, total_pages
from data.projects import get_all_projects
from db import draft_row_to_dict, get_conn, init_db
from routers.drafts_api import generate_daily_drafts, router as drafts_router
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

app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend" / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "frontend" / "templates")

app.include_router(drafts_router)
app.include_router(generate_router)
app.include_router(posts_router)


def _fmt_date(d) -> str:
    """Cross-platform date format — %-d is Linux-only."""
    return f"{d.strftime('%b')} {d.day}, {d.year}"


templates.env.filters["dateformat"] = _fmt_date
templates.env.filters["markdown"] = mistune.html


# ─── HTML pages ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse(request, "about.html")


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
    return templates.TemplateResponse(request, "post.html", {"post": article})


# ─── Admin pages ──────────────────────────────────────────────────────────────

@app.get("/admin/drafts", response_class=HTMLResponse)
async def admin_drafts(request: Request):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM drafts ORDER BY generated_at DESC"
        ).fetchall()
    drafts = [draft_row_to_dict(r) for r in rows]
    return templates.TemplateResponse(request, "drafts_list.html", {"drafts": drafts})


@app.get("/admin/drafts/{draft_id}", response_class=HTMLResponse)
async def admin_draft_preview(request: Request, draft_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    draft = draft_row_to_dict(row)
    return templates.TemplateResponse(request, "draft_preview.html", {"draft": draft})
