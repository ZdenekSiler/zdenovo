import json
import random
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from code_validator import ValidationSummary, validate_content
from db import draft_row_to_dict, get_conn, row_to_dict
from routers.generate_api import (
  DraftOut,
  PostBrief,
  _build_brief_message,
  _call_claude,
  _generate_with_review,
  _insert_draft,
  _load_briefs,
  _review_post,
)

router = APIRouter(prefix="/api/drafts", tags=["drafts"])

DAILY_TOPICS_PATH = Path(__file__).parent.parent / "data" / "daily_topics.json"
DAILY_COUNT = 3


# ─── Schemas ──────────────────────────────────────────────────────────────────

class DraftPatch(BaseModel):
  title: str | None = None
  summary: str | None = None
  content: str | None = None
  tags: list[str] | None = None


class RegenerateIn(BaseModel):
  remarks: str = Field(..., min_length=1, max_length=2000)


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
    quality_score=d.get("quality_score"),
    quality_issues=d.get("quality_issues", []),
    quality_strengths=d.get("quality_strengths", []),
    admin_remarks=d.get("admin_remarks"),
    sources=d.get("sources", []),
  )


def _find_brief(topic_id: str) -> PostBrief | None:
  if topic_id in ("freeform", "manual"):
    return None
  for brief in _load_briefs():
    if brief.id == topic_id:
      return brief
  for brief in _load_daily_topics():
    if brief.id == topic_id:
      return brief
  return None


def _build_regenerate_message(draft: dict, remarks: str, brief: PostBrief | None) -> str:
  parts = ["You are regenerating an existing blog post based on editorial feedback.\n"]
  if brief:
    parts.append("--- Original Brief ---")
    parts.append(_build_brief_message(brief))
    parts.append("")
  parts.append("--- Current Post ---")
  parts.append(f"Title: {draft['title']}")
  parts.append(f"Summary: {draft['summary']}")
  parts.append(f"Tags: {', '.join(draft['tags'])}")
  parts.append(f"\nContent:\n{draft['content']}\n")
  parts.append("--- Editorial Feedback ---")
  parts.append(remarks)
  parts.append("\n---")
  parts.append(
    "IMPORTANT: Do NOT rewrite the entire post. Only modify the specific section(s) "
    "mentioned in the editorial feedback. Copy every other section, heading, code block, "
    "table, and diagram EXACTLY as-is — character for character. "
    "If the feedback says 'fix the intro', only rewrite the intro. "
    "If it says 'add a Docker section', insert it and leave everything else untouched. "
    "The output must be the full post with surgical edits, not a rewrite."
  )
  return "\n".join(parts)


def _regenerate_draft(draft_id: str, remarks: str) -> DraftOut:
  with get_conn() as conn:
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
  if row is None:
    raise HTTPException(status_code=404, detail=f"Draft '{draft_id}' not found")
  draft = draft_row_to_dict(row)

  brief = _find_brief(draft["topic_id"])
  prompt = _build_regenerate_message(draft, remarks, brief)

  post = _call_claude(prompt)
  review = _review_post(post)
  now = datetime.now(timezone.utc)

  with get_conn() as conn:
    conn.execute(
      """UPDATE drafts SET
         slug=?, title=?, summary=?, tags=?, content=?,
         generated_at=?, status='pending',
         quality_score=?, quality_issues=?, quality_strengths=?,
         admin_remarks=?
       WHERE id=?""",
      (
        post.slug,
        post.title,
        post.summary,
        json.dumps(post.tags),
        post.content,
        now.isoformat(),
        review.score,
        json.dumps(review.issues),
        json.dumps(review.strengths),
        remarks,
        draft_id,
      ),
    )

  with get_conn() as conn:
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
  return _draft_to_out(draft_row_to_dict(row))


def generate_daily_drafts() -> int:
  """Generate DAILY_COUNT drafts from random daily topics. Called by scheduler and manual trigger."""
  topics = _load_daily_topics()
  chosen = random.sample(topics, min(DAILY_COUNT, len(topics)))
  generated = 0
  for topic in chosen:
    post, review = _generate_with_review(_build_brief_message(topic))
    _insert_draft(post, topic_id=topic.id, review=review)
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


@router.patch("/{draft_id}", response_model=DraftOut)
def patch_draft(draft_id: str, body: DraftPatch):
  """Edit a draft's title, summary, content, or tags before approving."""
  with get_conn() as conn:
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
      raise HTTPException(status_code=404, detail=f"Draft '{draft_id}' not found")
    draft = draft_row_to_dict(row)

    title = body.title if body.title is not None else draft["title"]
    summary = body.summary if body.summary is not None else draft["summary"]
    content = body.content if body.content is not None else draft["content"]
    tags = body.tags if body.tags is not None else draft["tags"]

    conn.execute(
      "UPDATE drafts SET title=?, summary=?, content=?, tags=? WHERE id=?",
      (title, summary, content, json.dumps(tags), draft_id),
    )

  with get_conn() as conn:
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
  return _draft_to_out(draft_row_to_dict(row))


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
      """INSERT INTO posts (slug, title, date, summary, tags, content, image, sources)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
      (
        draft["slug"],
        draft["title"],
        draft["date"].isoformat(),
        draft["summary"],
        json.dumps(draft["tags"]),
        draft["content"],
        draft.get("image"),
        json.dumps(draft.get("sources", [])),
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


@router.post("/{draft_id}/regenerate", response_model=DraftOut)
def regenerate_draft(draft_id: str, body: RegenerateIn):
  return _regenerate_draft(draft_id, body.remarks)


@router.post("/{draft_id}/validate", response_model=ValidationSummary)
def validate_draft_code(draft_id: str):
  with get_conn() as conn:
    row = conn.execute("SELECT content FROM drafts WHERE id = ?", (draft_id,)).fetchone()
  if row is None:
    raise HTTPException(status_code=404, detail=f"Draft '{draft_id}' not found")
  return validate_content(row["content"])


@router.delete("/{draft_id}", status_code=204)
def delete_draft(draft_id: str):
  with get_conn() as conn:
    result = conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
  if result.rowcount == 0:
    raise HTTPException(status_code=404, detail=f"Draft '{draft_id}' not found")
