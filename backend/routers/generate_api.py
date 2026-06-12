import json
import os
from datetime import date as Date
from pathlib import Path

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from routers.posts_api import PostOut, _slugify

router = APIRouter(prefix="/api/posts", tags=["generate"])

BRIEFS_PATH = Path(__file__).parent.parent / "data" / "post_briefs.json"

SYSTEM_PROMPT = "You are a technical blog post writer. Use the write_post tool to output the generated post."

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
  return PostOut(
    slug=_slugify(data["title"]),
    title=data["title"],
    summary=data["summary"],
    tags=data.get("tags", []),
    content=content,
    date=Date.today(),
    image=None,
    reading_time=max(1, len(content.split()) // 200),
  )


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/briefs", response_model=list[PostBrief])
def list_briefs():
  return _load_briefs()


@router.post("/generate", response_model=PostOut, status_code=201)
def generate_post(body: GenerateIn):
  user_message = f"Description: {body.description}"
  if body.tags:
    user_message += f"\nSuggested tags: {', '.join(body.tags)}"
  return _call_claude(user_message)


@router.post("/generate/{brief_id}", response_model=PostOut, status_code=201)
def generate_from_brief(brief_id: str):
  briefs = _load_briefs()
  brief = next((b for b in briefs if b.id == brief_id), None)
  if brief is None:
    raise HTTPException(status_code=404, detail=f"Brief '{brief_id}' not found")
  return _call_claude(_build_brief_message(brief))
