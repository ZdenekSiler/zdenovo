import json
import re
from datetime import date as Date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import get_conn, row_to_dict

router = APIRouter(prefix="/api/posts", tags=["posts"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class PostIn(BaseModel):
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    content: str = Field(..., min_length=1)
    date: Date = Field(default_factory=Date.today)
    image: str | None = None


class PostOut(BaseModel):
    slug: str
    title: str
    summary: str
    tags: list[str]
    content: str
    date: Date
    image: str | None = None
    reading_time: int | None = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _slugify(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:80]


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[PostOut])
def list_posts():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM posts ORDER BY date DESC"
        ).fetchall()
    return [row_to_dict(r) for r in rows]


@router.get("/{slug}", response_model=PostOut)
def get_post(slug: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM posts WHERE slug = ?", (slug,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return row_to_dict(row)


@router.post("", response_model=PostOut, status_code=201)
def create_post(body: PostIn):
    slug = _slugify(body.title)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT slug FROM posts WHERE slug = ?", (slug,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Slug '{slug}' already exists")
        conn.execute(
            "INSERT INTO posts (slug, title, date, summary, tags, content, image) VALUES (?,?,?,?,?,?,?)",
            (slug, body.title, body.date.isoformat(), body.summary, json.dumps(body.tags), body.content, body.image),
        )
    return {**body.model_dump(), "slug": slug}


@router.put("/{slug}", response_model=PostOut)
def update_post(slug: str, body: PostIn):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT slug FROM posts WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Post not found")
        conn.execute(
            """UPDATE posts
               SET title=?, date=?, summary=?, tags=?, content=?, image=?
               WHERE slug=?""",
            (body.title, body.date.isoformat(), body.summary, json.dumps(body.tags), body.content, body.image, slug),
        )
    return {**body.model_dump(), "slug": slug}


@router.delete("/{slug}", status_code=204)
def delete_post(slug: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM comments WHERE post_slug = ?", (slug,))
        result = conn.execute(
            "DELETE FROM posts WHERE slug = ?", (slug,)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Post not found")
