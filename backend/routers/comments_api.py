import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import comment_row_to_dict, get_conn

router = APIRouter(prefix="/api/comments", tags=["comments"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class CommentIn(BaseModel):
  post_slug: str
  author: str = Field(..., min_length=1, max_length=80)
  body: str = Field(..., min_length=1, max_length=2000)


class CommentOut(BaseModel):
  id: str
  post_slug: str
  author: str
  body: str
  created_at: datetime


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[CommentOut])
def list_comments(post_slug: str) -> list[dict]:
  with get_conn() as conn:
    rows = conn.execute(
      "SELECT * FROM comments WHERE post_slug = ? ORDER BY created_at ASC",
      (post_slug,),
    ).fetchall()
  return [comment_row_to_dict(r) for r in rows]


@router.post("", response_model=CommentOut, status_code=201)
def create_comment(body: CommentIn) -> dict:
  with get_conn() as conn:
    post = conn.execute(
      "SELECT slug FROM posts WHERE slug = ?", (body.post_slug,)
    ).fetchone()
    if post is None:
      raise HTTPException(status_code=404, detail=f"Post '{body.post_slug}' not found")
    comment_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
      "INSERT INTO comments (id, post_slug, author, body, created_at) VALUES (?, ?, ?, ?, ?)",
      (comment_id, body.post_slug, body.author, body.body, now),
    )
  with get_conn() as conn:
    row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
  return comment_row_to_dict(row)


@router.delete("/{comment_id}", status_code=204)
def delete_comment(comment_id: str) -> None:
  with get_conn() as conn:
    result = conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
  if result.rowcount == 0:
    raise HTTPException(status_code=404, detail=f"Comment '{comment_id}' not found")
