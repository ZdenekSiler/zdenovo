"""REST API for post series/collections."""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from db import get_conn, row_to_dict

logger = logging.getLogger(__name__)

SERIES_TYPES_PATH = Path(__file__).parent.parent / "data" / "series_types.json"


def load_series_types() -> list[dict]:
    """Spec templates that shape a generated series (deep-dive, overview, tutorial)."""
    return json.loads(SERIES_TYPES_PATH.read_text(encoding="utf-8"))


router = APIRouter(prefix="/api/series", tags=["series"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class SeriesIn(BaseModel):
    """Request body for creating a series."""
    title: str = Field(..., min_length=1)
    description: str | None = None


class SeriesOut(BaseModel):
    """Response body for a series."""
    id: str
    title: str
    description: str | None = None
    created_at: datetime
    post_count: int = 0


class SeriesGenerateIn(BaseModel):
    """Request body for generating a whole series from one topic + a spec type."""
    topic: str = Field(..., min_length=1, max_length=300)
    series_type: str = Field(..., min_length=1)     # one of series_types.json ids
    parts: int | None = Field(default=None, ge=2, le=8)
    guidance: str | None = Field(default=None, max_length=1000)


class SeriesGenerateOut(BaseModel):
    """202 response: the series was created and its parts are generating in the background."""
    series_id: str
    series_title: str
    series_description: str | None = None
    parts: list[dict]


class SeriesProgressPart(BaseModel):
    series_order: int | None = None
    title: str
    status: str          # "pending" (draft awaiting review) or "published" (live post)
    ref: str             # /admin/drafts/{id} or /blog/{slug}


class SeriesProgressOut(BaseModel):
    """How many parts of a generating series exist so far (drafts + published posts)."""
    series_id: str
    parts: list[SeriesProgressPart]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _slugify(title: str) -> str:
    """Convert a title to a URL-safe slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:80]


def _unique_series_id(conn, title: str) -> str:
    """Slug from title, suffixed (-2, -3, …) if that id already exists."""
    base = _slugify(title)
    series_id = base
    n = 2
    while conn.execute("SELECT id FROM series WHERE id = ?", (series_id,)).fetchone():
        series_id = f"{base}-{n}"
        n += 1
    return series_id


def _get_require_admin() -> Callable:
    """Lazy-load require_admin to avoid circular imports."""
    from routers.auth import require_admin
    return require_admin


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[SeriesOut])
def list_series() -> list[SeriesOut]:
    """List all series (newest first), with post counts."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT s.*, COUNT(p.slug) as post_count
               FROM series s
               LEFT JOIN posts p ON p.series_id = s.id
               GROUP BY s.id
               ORDER BY s.created_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("", response_model=SeriesOut, status_code=201)
def create_series(body: SeriesIn, _: None = Depends(_get_require_admin())) -> SeriesOut:
    """Create a new series (admin only)."""
    series_id = _slugify(body.title)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM series WHERE id = ?", (series_id,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Series '{series_id}' already exists")
        created_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO series (id, title, description, created_at) VALUES (?,?,?,?)",
            (series_id, body.title, body.description, created_at),
        )
    return {
        "id": series_id,
        "title": body.title,
        "description": body.description,
        "created_at": created_at,
        "post_count": 0,
    }


@router.post("/generate", response_model=SeriesGenerateOut, status_code=202)
async def generate_series_route(
    body: SeriesGenerateIn, _: None = Depends(_get_require_admin())
) -> SeriesGenerateOut:
    """Plan a multi-part series from a topic + spec, create the series row, and generate
    each part into `drafts` in the background (admin only). Returns 202 with the outline.

    Generation reuses the single-post engine in generate_api; imported lazily here (route-time
    only) to keep this router free of module-level cross-router imports — the same pattern
    topics_api uses to reach drafts_api (see .claude/rules/architecture.md)."""
    # Lazy import: route-time only, avoids a module-level series_api → generate_api dependency.
    from routers.generate_api import blog_generator, generate_series

    series_type = next((t for t in load_series_types() if t["id"] == body.series_type), None)
    if series_type is None:
        valid = ", ".join(t["id"] for t in load_series_types())
        raise HTTPException(status_code=400, detail=f"Unknown series_type. Valid types: {valid}")

    count = body.parts or series_type.get("default_parts", 4)
    # Planning is one blocking Haiku call — run off the event loop.
    plan = await asyncio.to_thread(
        blog_generator.plan_series, body.topic, series_type, count, body.guidance or ""
    )

    created_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        # Short, shareable id from the topic + spec type (e.g. "langchain-deep-dive"),
        # not the planner's verbose title — the title is kept for display.
        series_id = _unique_series_id(conn, f"{body.topic}-{series_type['id']}")
        conn.execute(
            "INSERT INTO series (id, title, description, created_at) VALUES (?,?,?,?)",
            (series_id, plan.series_title, plan.series_description, created_at),
        )

    # Fire-and-forget: parts generate off the event loop and land in /admin/drafts as they finish.
    asyncio.create_task(
        asyncio.to_thread(generate_series, series_id, plan.series_title, plan.parts)
    )

    return SeriesGenerateOut(
        series_id=series_id,
        series_title=plan.series_title,
        series_description=plan.series_description,
        parts=[p.model_dump() for p in plan.parts],
    )


@router.get("/{series_id}/progress", response_model=SeriesProgressOut)
def series_progress(series_id: str, _: None = Depends(_get_require_admin())) -> SeriesProgressOut:
    """Parts of a series that exist so far — pending drafts + published posts. Polled by the
    admin generate form to show live progress while parts generate in the background."""
    with get_conn() as conn:
        draft_rows = conn.execute(
            "SELECT id, title, series_order FROM drafts"
            " WHERE series_id = ? AND status = 'pending' ORDER BY series_order ASC",
            (series_id,),
        ).fetchall()
        post_rows = conn.execute(
            "SELECT slug, title, series_order FROM posts WHERE series_id = ? ORDER BY series_order ASC",
            (series_id,),
        ).fetchall()
    parts = [
        SeriesProgressPart(series_order=d["series_order"], title=d["title"],
                           status="pending", ref=f"/admin/drafts/{d['id']}")
        for d in draft_rows
    ] + [
        SeriesProgressPart(series_order=p["series_order"], title=p["title"],
                           status="published", ref=f"/blog/{p['slug']}")
        for p in post_rows
    ]
    parts.sort(key=lambda x: (x.series_order is None, x.series_order or 0))
    return SeriesProgressOut(series_id=series_id, parts=parts)


@router.delete("/{series_id}", status_code=204)
def delete_series(series_id: str, _: None = Depends(_get_require_admin())) -> None:
    """Delete a series and clear it from any referencing posts (admin only)."""
    with get_conn() as conn:
        result = conn.execute("DELETE FROM series WHERE id = ?", (series_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Series not found")
        conn.execute(
            "UPDATE posts SET series_id = NULL, series_order = NULL WHERE series_id = ?",
            (series_id,),
        )
