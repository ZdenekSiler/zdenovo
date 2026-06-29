"""Admin pages for managing blog posts."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from data.posts import get_all_posts
from db import get_conn
from routers.auth import require_admin


BASE_DIR = Path(__file__).parent.parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "frontend" / "templates")

router = APIRouter(tags=["admin:posts"])


@router.get("/admin/posts", response_class=HTMLResponse)
async def admin_posts(request: Request, _: None = Depends(require_admin)) -> str:
    """Admin page listing all published posts."""
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
