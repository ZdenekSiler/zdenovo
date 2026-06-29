import json
import logging
import uuid
from datetime import date as Date, datetime, timezone
from pathlib import Path

import anthropic
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import read_secret
from db import get_conn
from routers.posts_api import PostOut, Source, _slugify

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/posts", tags=["generate"])


BRIEFS_PATH = Path(__file__).parent.parent / "data" / "post_briefs.json"
PROMPTS_DIR = Path(__file__).parent.parent / "data" / "prompts"



# Import require_admin at usage time to avoid circular imports
def _get_require_admin():
    from routers.auth import require_admin
    return require_admin
MAX_GENERATION_ATTEMPTS = 3


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


class ReviewResult(BaseModel):
  score: int
  verdict: str
  issues: list[str]
  strengths: list[str]


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
  quality_score: int | None = None
  quality_issues: list[str] = Field(default_factory=list)
  quality_strengths: list[str] = Field(default_factory=list)
  admin_remarks: str | None = None
  sources: list[Source] = Field(default_factory=list)


# ─── Blog generation client ─────────────────────────────────────────────────


class BlogGenerator:
  """Encapsulates all Claude API interactions for blog post generation, review, and source finding.

  Reuses a single Anthropic client for connection pooling. Loads prompt templates
  once and marks them with cache_control for Anthropic's prompt caching (90% input
  token discount on cache hits within the 5-minute TTL).
  """

  def __init__(self) -> None:
    self._client: anthropic.Anthropic | None = None
    self._prompts_loaded = False
    self._system_prompt = ""
    self._post_tool: dict = {}
    self._review_system_prompt = ""
    self._review_tool: dict = {}
    self._sources_system_prompt = ""
    self._sources_tool: dict = {}

  def _ensure_prompts(self) -> None:
    if self._prompts_loaded:
      return
    self._system_prompt = (PROMPTS_DIR / "blog_system.md").read_text(encoding="utf-8")
    self._post_tool = json.loads((PROMPTS_DIR / "blog_tool.json").read_text(encoding="utf-8"))
    self._review_system_prompt = (PROMPTS_DIR / "blog_review.md").read_text(encoding="utf-8")
    self._review_tool = json.loads((PROMPTS_DIR / "review_tool.json").read_text(encoding="utf-8"))
    self._sources_system_prompt = (PROMPTS_DIR / "sources_system.md").read_text(encoding="utf-8")
    self._sources_tool = json.loads((PROMPTS_DIR / "sources_tool.json").read_text(encoding="utf-8"))
    self._prompts_loaded = True

  def _get_client(self) -> anthropic.Anthropic:
    if self._client is None:
      api_key = read_secret("anthropic_api_key", "ANTHROPIC_API_KEY")
      if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")
      self._client = anthropic.Anthropic(api_key=api_key)
    return self._client

  @staticmethod
  def _log_usage(label: str, message: anthropic.types.Message) -> None:
    usage = message.usage
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
    log.info(
      "%s: %d input, %d output, %d cache_read, %d cache_create tokens",
      label, usage.input_tokens, usage.output_tokens, cache_read, cache_create,
    )

  def generate_post(self, user_message: str) -> PostOut:
    self._ensure_prompts()
    try:
      message = self._get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=[
          {"type": "text", "text": self._system_prompt, "cache_control": {"type": "ephemeral"}},
        ],
        tools=[{**self._post_tool, "cache_control": {"type": "ephemeral"}}],
        tool_choice={"type": "tool", "name": "write_post"},
        messages=[{"role": "user", "content": user_message}],
      )
    except anthropic.APIError as exc:
      raise HTTPException(status_code=502, detail=f"Claude API error: {exc}") from exc

    self._log_usage("generate", message)

    tool_block = next((b for b in message.content if b.type == "tool_use"), None)
    if tool_block is None:
      raise HTTPException(status_code=422, detail="Claude did not call write_post tool")
    data = tool_block.input
    missing = [f for f in ("title", "summary", "tags", "content") if f not in data]
    if missing:
      raise HTTPException(status_code=422, detail=f"Claude omitted fields (max_tokens hit?): {missing}")

    content = data["content"]
    slug = _slugify(data["title"])
    tags = data.get("tags", [])
    image_query = data.get("image_query", "")
    return PostOut(
      slug=slug,
      title=data["title"],
      summary=data["summary"],
      tags=tags,
      content=content,
      date=Date.today(),
      image=_get_hero_image(image_query, data["title"], tags, slug),
      reading_time=max(1, len(content.split()) // 200),
    )

  def review_post(self, post: PostOut) -> ReviewResult:
    self._ensure_prompts()
    review_prompt = (
      f"Review this blog post for AI slop.\n\n"
      f"Title: {post.title}\n"
      f"Summary: {post.summary}\n\n"
      f"Content:\n{post.content}"
    )
    try:
      message = self._get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=[
          {"type": "text", "text": self._review_system_prompt, "cache_control": {"type": "ephemeral"}},
        ],
        tools=[{**self._review_tool, "cache_control": {"type": "ephemeral"}}],
        tool_choice={"type": "tool", "name": "review_post"},
        messages=[{"role": "user", "content": review_prompt}],
      )
    except anthropic.APIError:
      return ReviewResult(score=0, verdict="fail", issues=["Review API call failed"], strengths=[])

    self._log_usage("review", message)

    tool_block = next((b for b in message.content if b.type == "tool_use"), None)
    if tool_block is None:
      return ReviewResult(score=0, verdict="fail", issues=["Reviewer did not return structured output"], strengths=[])
    data = tool_block.input
    score = data.get("score", 0)
    return ReviewResult(
      score=score,
      verdict="pass" if score >= 6 else "fail",
      issues=data.get("issues", []),
      strengths=data.get("strengths", []),
    )

  def find_sources(self, post: PostOut) -> list[Source]:
    self._ensure_prompts()
    prompt = (
      f"Find sources for this blog post:\n\n"
      f"Title: {post.title}\n"
      f"Tags: {', '.join(post.tags)}\n"
      f"Summary: {post.summary}"
    )
    try:
      message = self._get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=[
          {"type": "text", "text": self._sources_system_prompt, "cache_control": {"type": "ephemeral"}},
        ],
        tools=[
          {"type": "web_search_20250305", "name": "web_search", "max_uses": 5},
          {**self._sources_tool, "cache_control": {"type": "ephemeral"}},
        ],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": prompt}],
      )
    except anthropic.APIError as exc:
      log.warning("Source search failed: %s", exc)
      return []

    self._log_usage("sources", message)

    tool_block = next((b for b in message.content if b.type == "tool_use" and b.name == "suggest_sources"), None)
    if tool_block is None:
      return []
    raw_sources = tool_block.input.get("sources", [])
    return [Source(title=s["title"], url=s["url"], summary=s["summary"]) for s in raw_sources if s.get("url")]

  def generate_with_review(self, user_message: str) -> tuple[PostOut, ReviewResult]:
    """Generate a post and review it. Retry up to MAX_GENERATION_ATTEMPTS, feeding review feedback into retries."""
    best_post = None
    best_review = None
    prompt = user_message
    for attempt in range(MAX_GENERATION_ATTEMPTS):
      post = self.generate_post(prompt)
      review = self.review_post(post)
      if best_review is None or review.score > best_review.score:
        best_post = post
        best_review = review
      if review.verdict == "pass":
        break
      if attempt < MAX_GENERATION_ATTEMPTS - 1:
        prompt = (
          f"{user_message}\n\n"
          f"--- Previous attempt was rejected (score {review.score}/10) ---\n"
          f"Issues found: {'; '.join(review.issues)}\n"
          f"Fix these specific issues in your next attempt."
        )
    best_post.sources = self.find_sources(best_post)
    return best_post, best_review


blog_generator = BlogGenerator()


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


def _fetch_unsplash_image(query: str) -> str | None:
  access_key = read_secret("unsplash_access_key", "UNSPLASH_ACCESS_KEY")
  if not access_key:
    return None
  try:
    resp = httpx.get(
      "https://api.unsplash.com/search/photos",
      params={
        "query": query,
        "per_page": 1,
        "orientation": "landscape",
        "content_filter": "high",
      },
      headers={"Authorization": f"Client-ID {access_key}"},
      timeout=10.0,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
      return None
    photo = results[0]
    raw_url = photo["urls"]["raw"]
    return f"{raw_url}&w=800&h=400&fit=crop&q=80"
  except Exception as exc:
    log.warning("Unsplash search failed for %r: %s", query, exc)
    return None


def _get_hero_image(image_query: str, title: str, tags: list[str], slug: str) -> str:
  for query in [image_query, " ".join(tags[:3]), title]:
    if not query:
      continue
    url = _fetch_unsplash_image(query)
    if url:
      return url
  return f"https://picsum.photos/seed/{slug}/800/400"


def _generate_with_review(user_message: str) -> tuple[PostOut, ReviewResult]:
  return blog_generator.generate_with_review(user_message)


def _call_claude(user_message: str) -> PostOut:
  return blog_generator.generate_post(user_message)


def _review_post(post: PostOut) -> ReviewResult:
  return blog_generator.review_post(post)


def _find_sources(post: PostOut) -> list[Source]:
  return blog_generator.find_sources(post)


def _insert_draft(post: PostOut, topic_id: str, review: ReviewResult | None = None) -> DraftOut:
  now = datetime.now(timezone.utc)
  draft_id = str(uuid.uuid4())
  q_score = review.score if review else None
  q_issues = json.dumps(review.issues) if review else "[]"
  q_strengths = json.dumps(review.strengths) if review else "[]"
  sources_json = json.dumps([s.model_dump() for s in post.sources])
  with get_conn() as conn:
    conn.execute(
      """INSERT INTO drafts
         (id, slug, title, date, summary, tags, content, image, generated_at, topic_id, status,
          quality_score, quality_issues, quality_strengths, sources)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
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
        q_score,
        q_issues,
        q_strengths,
        sources_json,
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
    quality_score=q_score,
    quality_issues=review.issues if review else [],
    quality_strengths=review.strengths if review else [],
    sources=post.sources,
  )


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/briefs", response_model=list[PostBrief])
def list_briefs():
  return _load_briefs()


@router.post("/generate", response_model=DraftOut, status_code=201)
def generate_post_route(body: GenerateIn, _: None = Depends(_get_require_admin)):
  user_message = f"Description: {body.description}"
  if body.tags:
    user_message += f"\nSuggested tags: {', '.join(body.tags)}"
  post, review = _generate_with_review(user_message)
  return _insert_draft(post, topic_id="freeform", review=review)


@router.post("/generate/{brief_id}", response_model=DraftOut, status_code=201)
def generate_from_brief(brief_id: str, _: None = Depends(_get_require_admin)):
  briefs = _load_briefs()
  brief = next((b for b in briefs if b.id == brief_id), None)
  if brief is None:
    raise HTTPException(status_code=404, detail=f"Brief '{brief_id}' not found")
  post, review = _generate_with_review(_build_brief_message(brief))
  return _insert_draft(post, topic_id=brief.id, review=review)
