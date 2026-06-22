import json
import logging
import os
import uuid
from datetime import date as Date, datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import anthropic
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

from db import get_conn
from routers.posts_api import PostOut, _slugify

router = APIRouter(prefix="/api/posts", tags=["generate"])

BRIEFS_PATH = Path(__file__).parent.parent / "data" / "post_briefs.json"

SYSTEM_PROMPT = (
  "You are writing for a personal technical blog run by Zdenek, a software engineer and consultant. "
  "The tone is dry, sarcastic, and self-deprecating — think deploy war stories, things that went wrong, "
  "and lessons earned the hard way. Avoid corporate language and buzzword-heavy intros. "
  "If there's a way to make a point with a deploy-fail-fix analogy or a dark joke about production, take it. "
  "Write like someone who has been paged at 3am and has opinions about it.\n\n"
  "FORMATTING RULES for visually rich posts:\n"
  "- Use ## for major sections and ### for subsections. Every section needs real content, not just bullets.\n"
  "- Use fenced code blocks with language tags (```python, ```bash, ```yaml) for any code or config.\n"
  "- Use Markdown tables when comparing options, tools, or tradeoffs.\n"
  "- Use horizontal rules (---) between major topic shifts.\n"
  "- Use callout blockquotes with emoji prefixes for tips, warnings, and key takeaways:\n"
  "  > 💡 Tip: ...\n  > ⚠️ Warning: ...\n  > ❌ Danger: ...\n  > ✅ Pro tip: ...\n"
  "- Include exactly one Mermaid diagram (no more than one) using a fenced code block with ```mermaid. "
  "Use flowchart TD, sequence diagrams, or mindmaps to illustrate architecture, decision trees, or workflows.\n"
  "- Write at least 800 words. Mix paragraphs, lists, code, tables, and callouts — "
  "never have more than 3 paragraphs in a row without a visual break (code, table, callout, diagram, or hr).\n"
  "- End with a punchy one-liner or dark joke, not a generic 'in conclusion' summary.\n"
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
        "description": "3-5 specific, descriptive lowercase tags. Include the core technology or topic (e.g. 'anthropic', 'ollama', 'kubernetes'), the domain (e.g. 'ai-regulation', 'devops', 'security'), and the angle (e.g. 'vendor-lock-in', 'self-hosting', 'incident-response'). Avoid vague tags like 'strategy' or 'tips'.",
      },
      "image_query": {
        "type": "string",
        "description": "A 2-4 word Unsplash search query for a hero photo that visually represents the post's core theme. Be concrete and visual — e.g. 'server room locked door' not 'ai risk'. Think about what photo would make someone click the article.",
      },
      "content": {
        "type": "string",
        "description": "Full post body in Markdown, at least 800 words. Must include: ## headings, fenced code blocks with language tags, at least one Markdown table, callout blockquotes (> 💡/⚠️/❌/✅ prefix), horizontal rules (---) between sections, and exactly one Mermaid diagram (```mermaid fenced block, no more than one). Mix visual elements so no more than 3 plain paragraphs appear in a row.",
      },
    },
    "required": ["title", "summary", "tags", "content"],
  },
}

REVIEW_SYSTEM_PROMPT = (
  "You are a ruthless blog post editor. Your job is to detect AI slop — generic, "
  "corporate, filler content that any LLM could have written. You are reviewing a post "
  "for a sarcastic, opinionated personal tech blog written by a real engineer. "
  "The bar is high: if it reads like a LinkedIn post, a press release, or a ChatGPT "
  "default, it fails. Use the review_post tool to output your verdict."
)

REVIEW_TOOL = {
  "name": "review_post",
  "description": "Output a structured quality review of a blog post.",
  "input_schema": {
    "type": "object",
    "properties": {
      "score": {
        "type": "integer",
        "description": "Quality score 1-10. 1-4 = reject (AI slop), 5-6 = borderline, 7-10 = publishable.",
      },
      "verdict": {
        "type": "string",
        "enum": ["pass", "fail"],
        "description": "'pass' if score >= 6, 'fail' otherwise.",
      },
      "issues": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Specific issues found: clichés, filler sentences, generic advice, missing concrete examples, AI-isms like 'delve/landscape/crucial/it\\'s important to note', corporate tone, etc.",
      },
      "strengths": {
        "type": "array",
        "items": {"type": "string"},
        "description": "What the post does well — specific voice, concrete examples, genuine opinions, etc.",
      },
    },
    "required": ["score", "verdict", "issues", "strengths"],
  },
}

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
  """Search Unsplash for a topic-relevant hero image. Returns URL or None."""
  access_key = os.environ.get("UNSPLASH_ACCESS_KEY")
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
  """Try Unsplash with image_query, then tags, then title. Fall back to picsum."""
  for query in [image_query, " ".join(tags[:3]), title]:
    if not query:
      continue
    url = _fetch_unsplash_image(query)
    if url:
      return url
  return f"https://picsum.photos/seed/{slug}/800/400"


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


def _review_post(post: PostOut) -> ReviewResult:
  api_key = os.environ.get("ANTHROPIC_API_KEY")
  if not api_key:
    return ReviewResult(score=0, verdict="fail", issues=["No API key — review skipped"], strengths=[])
  review_prompt = (
    f"Review this blog post for AI slop.\n\n"
    f"Title: {post.title}\n"
    f"Summary: {post.summary}\n\n"
    f"Content:\n{post.content}\n\n"
    f"Check for:\n"
    f"- AI cliché words: delve, landscape, crucial, leverage, foster, comprehensive, robust, "
    f"seamless, cutting-edge, game-changer, it's important to note, in today's world\n"
    f"- Corporate/LinkedIn tone vs the expected sarcastic, opinionated engineer voice\n"
    f"- Generic advice that could apply to anything vs specific, concrete examples\n"
    f"- Filler paragraphs that say nothing\n"
    f"- Excessive bullet lists used as padding\n"
    f"- Missing personal voice, war stories, or genuine opinions\n"
    f"- Over-hedging ('it depends', 'there's no one-size-fits-all') without taking a stance\n"
    f"- Suspiciously balanced 'on one hand / on the other hand' structure\n"
    f"Be harsh. The bar is: would a real engineer with opinions write this, or did an AI?"
  )
  try:
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
      model="claude-sonnet-4-6",
      max_tokens=2048,
      system=REVIEW_SYSTEM_PROMPT,
      tools=[REVIEW_TOOL],
      tool_choice={"type": "tool", "name": "review_post"},
      messages=[{"role": "user", "content": review_prompt}],
    )
  except anthropic.APIError:
    return ReviewResult(score=0, verdict="fail", issues=["Review API call failed"], strengths=[])

  tool_block = next((b for b in message.content if b.type == "tool_use"), None)
  if tool_block is None:
    return ReviewResult(score=0, verdict="fail", issues=["Reviewer did not return structured output"], strengths=[])
  data = tool_block.input
  return ReviewResult(
    score=data.get("score", 0),
    verdict=data.get("verdict", "fail"),
    issues=data.get("issues", []),
    strengths=data.get("strengths", []),
  )


def _generate_with_review(user_message: str) -> tuple[PostOut, ReviewResult]:
  """Generate a post and review it. Retry up to MAX_GENERATION_ATTEMPTS if it fails review."""
  best_post = None
  best_review = None
  for attempt in range(MAX_GENERATION_ATTEMPTS):
    post = _call_claude(user_message)
    review = _review_post(post)
    if best_review is None or review.score > best_review.score:
      best_post = post
      best_review = review
    if review.verdict == "pass":
      break
  return best_post, best_review


def _insert_draft(post: PostOut, topic_id: str, review: ReviewResult | None = None) -> DraftOut:
  """Save a generated post to the drafts table and return the draft."""
  now = datetime.now(timezone.utc)
  draft_id = str(uuid.uuid4())
  q_score = review.score if review else None
  q_issues = json.dumps(review.issues) if review else "[]"
  q_strengths = json.dumps(review.strengths) if review else "[]"
  with get_conn() as conn:
    conn.execute(
      """INSERT INTO drafts
         (id, slug, title, date, summary, tags, content, image, generated_at, topic_id, status,
          quality_score, quality_issues, quality_strengths)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
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
  post, review = _generate_with_review(user_message)
  return _insert_draft(post, topic_id="freeform", review=review)


@router.post("/generate/{brief_id}", response_model=DraftOut, status_code=201)
def generate_from_brief(brief_id: str):
  briefs = _load_briefs()
  brief = next((b for b in briefs if b.id == brief_id), None)
  if brief is None:
    raise HTTPException(status_code=404, detail=f"Brief '{brief_id}' not found")
  post, review = _generate_with_review(_build_brief_message(brief))
  return _insert_draft(post, topic_id=brief.id, review=review)
