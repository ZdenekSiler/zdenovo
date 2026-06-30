"""REST API for post series/collections."""

import logging
import re
from datetime import datetime, timezone
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from db import get_conn, row_to_dict

logger = logging.getLogger(__name__)


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
def create_series(body: SeriesIn, _: None = Depends(_get_require_admin)) -> SeriesOut:
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


@router.delete("/{series_id}", status_code=204)
def delete_series(series_id: str, _: None = Depends(_get_require_admin)) -> None:
    """Delete a series and clear it from any referencing posts (admin only)."""
    with get_conn() as conn:
        result = conn.execute("DELETE FROM series WHERE id = ?", (series_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Series not found")
        conn.execute(
            "UPDATE posts SET series_id = NULL, series_order = NULL WHERE series_id = ?",
            (series_id,),
        )
