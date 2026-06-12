import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import draft_row_to_dict, get_conn, row_to_dict
from routers.generate_api import PostBrief, _build_brief_message, _call_claude

router = APIRouter(prefix="/api/drafts", tags=["drafts"])

DAILY_TOPICS_PATH = Path(__file__).parent.parent / "data" / "daily_topics.json"
DAILY_COUNT = 3


# ─── Schemas ──────────────────────────────────────────────────────────────────

class DraftOut(BaseModel):
  id: str
  slug: str
  title: str
  summary: str
  tags: list[str]
  content: str
  date: str
  image: str | None = None
  generated_at: str
  topic_id: str
  status: str
  reading_time: int


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_daily_topics() -> list[PostBrief]:
  raw = json.loads(DAILY_TOPICS_PATH.read_text())
  return [PostBrief(**item) for item in raw]


def _draft_to_out(d: dict) -> DraftOut:
  return DraftOut(
    id=d["id"],
    slug=d["slug"],
    title=d["title"],
    summary=d["summary"],
    tags=d["tags"],
    content=d["content"],
    date=d["date"].isoformat(),
    image=d.get("image"),
    generated_at=d["generated_at"].isoformat(),
    topic_id=d["topic_id"],
    status=d["status"],
    reading_time=d["reading_time"],
  )


def generate_daily_drafts() -> int:
  """Generate DAILY_COUNT drafts from random daily topics. Called by scheduler and manual trigger."""
  topics = _load_daily_topics()
  chosen = random.sample(topics, min(DAILY_COUNT, len(topics)))
  generated = 0
  for topic in chosen:
    post = _call_claude(_build_brief_message(topic))
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
      conn.execute(
        """INSERT INTO drafts
           (id, slug, title, date, summary, tags, content, image, generated_at, topic_id, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (
          str(uuid.uuid4()),
          post.slug,
          post.title,
          post.date.isoformat(),
          post.summary,
          json.dumps(post.tags),
          post.content,
          post.image,
          now,
          topic.id,
        ),
      )
    generated += 1
  return generated


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[DraftOut])
def list_drafts():
  with get_conn() as conn:
    rows = conn.execute(
      "SELECT * FROM drafts ORDER BY generated_at DESC"
    ).fetchall()
  return [_draft_to_out(draft_row_to_dict(r)) for r in rows]


@router.get("/{draft_id}", response_model=DraftOut)
def get_draft(draft_id: str):
  with get_conn() as conn:
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
  if row is None:
    raise HTTPException(status_code=404, detail=f"Draft '{draft_id}' not found")
  return _draft_to_out(draft_row_to_dict(row))


@router.post("/generate", status_code=201)
def trigger_daily_generation():
  """Manually trigger daily draft generation (also called by the scheduler)."""
  count = generate_daily_drafts()
  return {"generated": count}


@router.post("/{draft_id}/approve", status_code=201)
def approve_draft(draft_id: str):
  """Publish a draft to the live blog. Returns the published post slug."""
  with get_conn() as conn:
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
      raise HTTPException(status_code=404, detail=f"Draft '{draft_id}' not found")
    draft = draft_row_to_dict(row)

    existing = conn.execute(
      "SELECT slug FROM posts WHERE slug = ?", (draft["slug"],)
    ).fetchone()
    if existing:
      raise HTTPException(
        status_code=409, detail=f"A post with slug '{draft['slug']}' already exists"
      )

    conn.execute(
      """INSERT INTO posts (slug, title, date, summary, tags, content, image)
         VALUES (?, ?, ?, ?, ?, ?, ?)""",
      (
        draft["slug"],
        draft["title"],
        draft["date"].isoformat(),
        draft["summary"],
        json.dumps(draft["tags"]),
        draft["content"],
        draft.get("image"),
      ),
    )
    conn.execute(
      "UPDATE drafts SET status = 'approved' WHERE id = ?", (draft_id,)
    )

  with get_conn() as conn:
    post_row = conn.execute(
      "SELECT * FROM posts WHERE slug = ?", (draft["slug"],)
    ).fetchone()
  return row_to_dict(post_row)


@router.delete("/{draft_id}", status_code=204)
def delete_draft(draft_id: str):
  with get_conn() as conn:
    result = conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
  if result.rowcount == 0:
    raise HTTPException(status_code=404, detail=f"Draft '{draft_id}' not found")
