import json
import os
import uuid
from datetime import date as Date, datetime, timezone
from pathlib import Path

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import get_conn
from routers.posts_api import PostOut, _slugify

router = APIRouter(prefix="/api/posts", tags=["generate"])

BRIEFS_PATH = Path(__file__).parent.parent / "data" / "post_briefs.json"

SYSTEM_PROMPT = (
  "You are writing for a personal technical blog run by Zdenek, a software engineer and consultant. "
  "The tone is dry, sarcastic, and self-deprecating — think deploy war stories, things that went wrong, "
  "and lessons earned the hard way. Avoid corporate language and buzzword-heavy intros. "
  "If there's a way to make a point with a deploy-fail-fix analogy or a dark joke about production, take it. "
  "Write like someone who has been paged at 3am and has opinions about it. "
  "Use the write_post tool to output the generated post."
)

POST_TOOL = {
  "name": "write_post",
  "description": "Output a complete blog post.",
  "input_schema": {
    "type": "object",
    "properties": {
      "title": {"type": "string", "description": "Concise, engaging post title"},
      "summary": {"type": "string", "description": "One or two sentence description"},
      "tags": {
        "type": "array",
        "items": {"type": "string"},
        "description": "2-4 lowercase single-word or hyphenated tags",
      },
      "content": {
        "type": "string",
        "description": "Full post body in Markdown, at least 300 words, with headings, code blocks, and lists as appropriate",
      },
    },
    "required": ["title", "summary", "tags", "content"],
  },
}


# ─── Schemas ──────────────────────────────────────────────────────────────────

class PostBrief(BaseModel):
  id: str
  title_hint: str
  description: str
  audience: str
  tone: str
  tags: list[str] = Field(default_factory=list)
  outline: list[str] = Field(default_factory=list)


class GenerateIn(BaseModel):
  description: str = Field(..., min_length=10)
  tags: list[str] = Field(default_factory=list)


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

def _load_briefs() -> list[PostBrief]:
  raw = json.loads(BRIEFS_PATH.read_text())
  return [PostBrief(**item) for item in raw]


def _build_brief_message(brief: PostBrief) -> str:
  parts = [
    f"Title hint: {brief.title_hint}",
    f"Description: {brief.description}",
    f"Target audience: {brief.audience}",
    f"Tone: {brief.tone}",
  ]
  if brief.tags:
    parts.append(f"Suggested tags: {', '.join(brief.tags)}")
  if brief.outline:
    sections = "\n".join(f"  - {point}" for point in brief.outline)
    parts.append(f"Required sections to cover:\n{sections}")
  return "\n".join(parts)


def _call_claude(user_message: str) -> PostOut:
  api_key = os.environ.get("ANTHROPIC_API_KEY")
  if not api_key:
    raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")
  try:
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
      model="claude-sonnet-4-6",
      max_tokens=8192,
      system=SYSTEM_PROMPT,
      tools=[POST_TOOL],
      tool_choice={"type": "tool", "name": "write_post"},
      messages=[{"role": "user", "content": user_message}],
    )
  except anthropic.APIError as exc:
    raise HTTPException(status_code=502, detail=f"Claude API error: {exc}") from exc

  tool_block = next((b for b in message.content if b.type == "tool_use"), None)
  if tool_block is None:
    raise HTTPException(status_code=422, detail="Claude did not call write_post tool")
  data = tool_block.input
  missing = [f for f in ("title", "summary", "tags", "content") if f not in data]
  if missing:
    raise HTTPException(status_code=422, detail=f"Claude omitted fields (max_tokens hit?): {missing}")

  content = data["content"]
  slug = _slugify(data["title"])
  return PostOut(
    slug=slug,
    title=data["title"],
    summary=data["summary"],
    tags=data.get("tags", []),
    content=content,
    date=Date.today(),
    image=f"https://picsum.photos/seed/{slug}/800/400",
    reading_time=max(1, len(content.split()) // 200),
  )


def _insert_draft(post: PostOut, topic_id: str) -> DraftOut:
  """Save a generated post to the drafts table and return the draft."""
  now = datetime.now(timezone.utc)
  draft_id = str(uuid.uuid4())
  with get_conn() as conn:
    conn.execute(
      """INSERT INTO drafts
         (id, slug, title, date, summary, tags, content, image, generated_at, topic_id, status)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
      (
        draft_id,
        post.slug,
        post.title,
        post.date.isoformat(),
        post.summary,
        json.dumps(post.tags),
        post.content,
        post.image,
        now.isoformat(),
        topic_id,
      ),
    )
  return DraftOut(
    id=draft_id,
    slug=post.slug,
    title=post.title,
    summary=post.summary,
    tags=post.tags,
    content=post.content,
    date=post.date.isoformat(),
    image=post.image,
    generated_at=now.isoformat(),
    topic_id=topic_id,
    status="pending",
    reading_time=max(1, len(post.content.split()) // 200),
  )


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/briefs", response_model=list[PostBrief])
def list_briefs():
  return _load_briefs()


@router.post("/generate", response_model=DraftOut, status_code=201)
def generate_post(body: GenerateIn):
  user_message = f"Description: {body.description}"
  if body.tags:
    user_message += f"\nSuggested tags: {', '.join(body.tags)}"
  post = _call_claude(user_message)
  return _insert_draft(post, topic_id="freeform")


@router.post("/generate/{brief_id}", response_model=DraftOut, status_code=201)
def generate_from_brief(brief_id: str):
  briefs = _load_briefs()
  brief = next((b for b in briefs if b.id == brief_id), None)
  if brief is None:
    raise HTTPException(status_code=404, detail=f"Brief '{brief_id}' not found")
  post = _call_claude(_build_brief_message(brief))
  return _insert_draft(post, topic_id=brief.id)
