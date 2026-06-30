"""REST API for blog posts CRUD operations."""

import json
import logging
import re
import uuid
from datetime import date as Date, datetime, timezone
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from db import get_conn, row_to_dict
from rate_limit import limiter

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/posts", tags=["posts"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class Source(BaseModel):
    """External reference for a blog post."""
    title: str
    url: str
    summary: str


class PostIn(BaseModel):
    """Request body for creating or updating a post."""
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    content: str = Field(..., min_length=1)
    date: Date = Field(default_factory=Date.today)
    image: str | None = None
    sources: list[Source] = Field(default_factory=list)


class PostOut(BaseModel):
    """Response body for a blog post."""
    slug: str
    title: str
    summary: str
    tags: list[str]
    content: str
    date: Date
    image: str | None = None
    reading_time: int | None = None
    sources: list[Source] = Field(default_factory=list)
    reactions: int = 0
    reactions_down: int = 0
    views: int = 0
    series_id: str | None = None
    series_order: int | None = None


class SeriesAssignIn(BaseModel):
    """Request body for assigning a post to a series."""
    series_id: str | None = None
    series_order: int | None = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _slugify(title: str) -> str:
    """Convert a title to a URL-safe slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:80]


def _get_require_admin() -> Callable:
    """Lazy-load require_admin to avoid circular imports."""
    from routers.auth import require_admin
    return require_admin


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[PostOut])
def list_posts() -> list[PostOut]:
    """List all published posts (newest first)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM posts ORDER BY date DESC"
        ).fetchall()
    return [row_to_dict(r) for r in rows]


@router.get("/search", response_model=list[PostOut])
def search_posts(q: str) -> list[PostOut]:
    """Full-text search over posts (title, summary, tags, content)."""
    if not q.strip():
        return []
    sanitized = re.sub(r'["*^():-]', "", q).strip()
    if not sanitized:
        return []
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT p.* FROM posts p
                   JOIN posts_fts f ON p.rowid = f.rowid
                   WHERE posts_fts MATCH ?
                   ORDER BY rank
                   LIMIT 10""",
                (sanitized,),
            ).fetchall()
        return [row_to_dict(r) for r in rows]
    except Exception:
        logger.warning("Post search failed for query %r", q, exc_info=True)
        return []


@router.get("/{slug}", response_model=PostOut)
def get_post(slug: str) -> PostOut:
    """Get a single post by slug."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM posts WHERE slug = ?", (slug,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return row_to_dict(row)


@router.post("", response_model=PostOut, status_code=201)
def create_post(body: PostIn, _: None = Depends(_get_require_admin)) -> PostOut:
    """Create a new post (admin only)."""
    slug = _slugify(body.title)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT slug FROM posts WHERE slug = ?", (slug,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Slug '{slug}' already exists")
        conn.execute(
            "INSERT INTO posts (slug, title, date, summary, tags, content, image, sources) VALUES (?,?,?,?,?,?,?,?)",
            (slug, body.title, body.date.isoformat(), body.summary, json.dumps(body.tags), body.content, body.image,
             json.dumps([s.model_dump() for s in body.sources])),
        )
    return {**body.model_dump(), "slug": slug}


@router.put("/{slug}", response_model=PostOut)
def update_post(slug: str, body: PostIn, _: None = Depends(_get_require_admin)) -> PostOut:
    """Update a post (admin only)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT slug FROM posts WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Post not found")
        conn.execute(
            """UPDATE posts
               SET title=?, date=?, summary=?, tags=?, content=?, image=?, sources=?
               WHERE slug=?""",
            (body.title, body.date.isoformat(), body.summary, json.dumps(body.tags), body.content, body.image,
             json.dumps([s.model_dump() for s in body.sources]), slug),
        )
    return {**body.model_dump(), "slug": slug}


@router.delete("/{slug}", status_code=204)
def delete_post(slug: str, _: None = Depends(_get_require_admin)) -> None:
    """Delete a post (admin only)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM comments WHERE post_slug = ?", (slug,))
        result = conn.execute("DELETE FROM posts WHERE slug = ?", (slug,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Post not found")


@router.post("/{slug}/unpublish", status_code=204)
def unpublish_post(slug: str, _: None = Depends(_get_require_admin)) -> None:
    """Move a published post back to drafts (admin only)."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM posts WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Post not found")
        post = row_to_dict(row)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO drafts (id, slug, title, date, summary, tags, content, image,
               generated_at, topic_id, status, sources)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', 'pending', ?)""",
            (str(uuid.uuid4()), post["slug"], post["title"], post["date"].isoformat(),
             post["summary"], json.dumps(post["tags"]), post["content"], post["image"], now,
             json.dumps(post.get("sources", []))),
        )
        conn.execute("DELETE FROM comments WHERE post_slug = ?", (slug,))
        conn.execute("DELETE FROM posts WHERE slug = ?", (slug,))


@router.post("/{slug}/react", response_class=HTMLResponse)
@limiter.limit("3/minute")
def react_to_post(slug: str, request: Request) -> HTMLResponse:
    """Thumbs-up reaction (rate limited, public). Returns updated count for HTMX swap."""
    with get_conn() as conn:
        row = conn.execute("SELECT slug FROM posts WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Post not found")
        conn.execute("UPDATE posts SET reactions = reactions + 1 WHERE slug = ?", (slug,))
        count = conn.execute(
            "SELECT reactions FROM posts WHERE slug = ?", (slug,)
        ).fetchone()["reactions"]
    return HTMLResponse(content=str(count))


@router.post("/{slug}/react-down", response_class=HTMLResponse)
@limiter.limit("3/minute")
def react_down_to_post(slug: str, request: Request) -> HTMLResponse:
    """Thumbs-down reaction (rate limited, public). Returns updated count for HTMX swap."""
    with get_conn() as conn:
        row = conn.execute("SELECT slug FROM posts WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Post not found")
        conn.execute("UPDATE posts SET reactions_down = reactions_down + 1 WHERE slug = ?", (slug,))
        count = conn.execute(
            "SELECT reactions_down FROM posts WHERE slug = ?", (slug,)
        ).fetchone()["reactions_down"]
    return HTMLResponse(content=str(count))


@router.patch("/{slug}/series", status_code=204)
def assign_post_series(
    slug: str, body: SeriesAssignIn, _: None = Depends(_get_require_admin)
) -> None:
    """Assign or unassign a post's series (admin only)."""
    with get_conn() as conn:
        post = conn.execute("SELECT slug FROM posts WHERE slug = ?", (slug,)).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="Post not found")
        if body.series_id is not None:
            series = conn.execute(
                "SELECT id FROM series WHERE id = ?", (body.series_id,)
            ).fetchone()
            if series is None:
                raise HTTPException(status_code=404, detail="Series not found")
        conn.execute(
            "UPDATE posts SET series_id = ?, series_order = ? WHERE slug = ?",
            (body.series_id, body.series_order, slug),
        )
