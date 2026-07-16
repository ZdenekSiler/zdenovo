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
# Drafts pass the slop review on the first attempt almost always (observed avg 8.29/10,
# 100% >= 6), so a 3rd retry rarely fires — 2 attempts keeps the review loop's safety net
# at ~⅔ the worst-case cost. The loop still keeps the best-scoring attempt.
MAX_GENERATION_ATTEMPTS = 2
SERIES_GENERATION_ATTEMPTS = 2

# USD per MILLION tokens (input / output). Cache reads bill at 0.1x input, cache writes at 1.25x.
# Update these if Anthropic pricing changes; the Console remains the source of truth for billing.
MODEL_PRICING = {
  # Sonnet 5 intro pricing through 2026-08-31; revert to 3.0/15.0 after that date.
  "claude-sonnet-5": {"in": 2.0, "out": 10.0},
  "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
  "claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0},
}
_DEFAULT_PRICING = {"in": 1.0, "out": 5.0}
WEB_SEARCH_USD = 0.01  # per web search request


def _as_int(v) -> int:
  """Coerce usage fields to int; non-ints (e.g. test MagicMocks) count as 0."""
  return v if isinstance(v, int) else 0


def _compute_cost(model: str, inp: int, out: int, cache_read: int, cache_write: int, searches: int) -> float:
  p = MODEL_PRICING.get(model, _DEFAULT_PRICING)
  token_cost = (
    inp * p["in"]
    + cache_read * p["in"] * 0.1
    + cache_write * p["in"] * 1.25
    + out * p["out"]
  ) / 1_000_000
  return round(token_cost + searches * WEB_SEARCH_USD, 6)


# ─── Schemas ──────────────────────────────────────────────────────────────────

class PostBrief(BaseModel):
  id: str
  title_hint: str = Field(..., max_length=300)
  description: str = Field(..., max_length=1500)
  audience: str = Field(..., max_length=300)
  tone: str = Field(..., max_length=300)
  tags: list[str] = Field(default_factory=list, max_length=10)
  outline: list[str] = Field(default_factory=list, max_length=20)


class GenerateIn(BaseModel):
  description: str = Field(..., min_length=10)
  tags: list[str] = Field(default_factory=list)


class SeriesPart(BaseModel):
  part_number: int
  title: str
  angle: str
  key_points: list[str] = Field(default_factory=list)
  suggested_tags: list[str] = Field(default_factory=list)


class SeriesPlan(BaseModel):
  series_title: str
  series_description: str
  parts: list[SeriesPart]


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
  series_id: str | None = None
  series_order: int | None = None
  gen_cost_usd: float | None = None


# ─── Blog generation client ─────────────────────────────────────────────────


class BlogGenerator:
  """Encapsulates all Claude API interactions for blog post generation, review, and source finding.

  Reuses a single Anthropic client for connection pooling. Loads prompt templates
  once and marks them with cache_control for Anthropic's prompt caching (90% input
  token discount on cache hits within the 5-minute TTL).
  """

  def __init__(self) -> None:
    self._client: anthropic.Anthropic | None = None
    self._run_cost = 0.0          # accumulates cost within one generate_with_review run
    self.last_run_cost = 0.0      # cost of the most recent completed run (read by _insert_draft)
    self._prompts_loaded = False
    self._system_prompt = ""
    self._post_tool: dict = {}
    self._review_system_prompt = ""
    self._review_tool: dict = {}
    self._sources_system_prompt = ""
    self._sources_tool: dict = {}
    self._trending_topics_system_prompt = ""
    self._trending_topics_tool: dict = {}
    self._series_plan_system_prompt = ""
    self._series_plan_tool: dict = {}
    self._series_system_prompt = ""
    self._series_post_tool: dict = {}

  def _ensure_prompts(self) -> None:
    if self._prompts_loaded:
      return
    self._system_prompt = (PROMPTS_DIR / "blog_system.md").read_text(encoding="utf-8")
    self._post_tool = json.loads((PROMPTS_DIR / "blog_tool.json").read_text(encoding="utf-8"))
    self._review_system_prompt = (PROMPTS_DIR / "blog_review.md").read_text(encoding="utf-8")
    self._review_tool = json.loads((PROMPTS_DIR / "review_tool.json").read_text(encoding="utf-8"))
    self._sources_system_prompt = (PROMPTS_DIR / "sources_system.md").read_text(encoding="utf-8")
    self._sources_tool = json.loads((PROMPTS_DIR / "sources_tool.json").read_text(encoding="utf-8"))
    self._trending_topics_system_prompt = (PROMPTS_DIR / "trending_topics_system.md").read_text(encoding="utf-8")
    self._trending_topics_tool = json.loads((PROMPTS_DIR / "trending_topics_tool.json").read_text(encoding="utf-8"))
    self._series_plan_system_prompt = (PROMPTS_DIR / "series_plan_system.md").read_text(encoding="utf-8")
    self._series_plan_tool = json.loads((PROMPTS_DIR / "series_plan_tool.json").read_text(encoding="utf-8"))
    self._series_system_prompt = (PROMPTS_DIR / "blog_series_system.md").read_text(encoding="utf-8")
    self._series_post_tool = json.loads((PROMPTS_DIR / "blog_series_tool.json").read_text(encoding="utf-8"))
    self._prompts_loaded = True

  def _get_client(self) -> anthropic.Anthropic:
    if self._client is None:
      api_key = read_secret("anthropic_api_key", "ANTHROPIC_API_KEY")
      if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")
      self._client = anthropic.Anthropic(api_key=api_key)
    return self._client

  def _log_usage(self, label: str, message: anthropic.types.Message,
                 ref_kind: str | None = None, ref_id: str | None = None) -> float:
    """Log tokens, compute cost, persist a row to api_costs, and add to the current run total.
    Returns the call's cost in USD. Fail-soft: a recording error never breaks generation."""
    usage = message.usage
    inp = _as_int(getattr(usage, "input_tokens", 0))
    out = _as_int(getattr(usage, "output_tokens", 0))
    cache_read = _as_int(getattr(usage, "cache_read_input_tokens", 0))
    cache_create = _as_int(getattr(usage, "cache_creation_input_tokens", 0))
    stu = getattr(usage, "server_tool_use", None)
    searches = _as_int(getattr(stu, "web_search_requests", 0)) if stu is not None else 0
    model = str(getattr(message, "model", "") or "")
    cost = _compute_cost(model, inp, out, cache_read, cache_create, searches)
    log.info(
      "%s: %d input, %d output, %d cache_read, %d cache_create, %d searches -> $%.4f",
      label, inp, out, cache_read, cache_create, searches, cost,
    )
    self._run_cost += cost
    try:
      with get_conn() as conn:
        conn.execute(
          """INSERT INTO api_costs
             (id, created_at, step, model, input_tokens, output_tokens, cache_read, cache_write,
              web_searches, cost_usd, ref_kind, ref_id)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
          (str(uuid.uuid4()), datetime.now(timezone.utc).isoformat(), label, model,
           inp, out, cache_read, cache_create, searches, cost,
           ref_kind, ref_id),
        )
    except Exception as exc:
      log.warning("api_costs record failed for %s: %s", label, exc)
    return cost

  def generate_post(self, user_message: str, series: bool = False) -> PostOut:
    self._ensure_prompts()
    # Series parts use a distinct system prompt + tool (chapter structure, no Mermaid,
    # comparison-only tables) so they read differently from standalone posts.
    base_prompt = self._series_system_prompt if series else self._system_prompt
    post_tool = self._series_post_tool if series else self._post_tool
    # The existing-posts corpus is identical across every generation within a run (it's the
    # published `posts` table, unchanged while drafts accumulate). Sending it as its own
    # cached system block — rather than appending it to the per-call user message — lets
    # back-to-back generations (e.g. the parts of a series) reuse it at the ~90% cache
    # discount instead of paying full price on every call and retry.
    system_blocks = [
      {"type": "text", "text": base_prompt, "cache_control": {"type": "ephemeral"}},
    ]
    corpus = _project_corpus_for_prompt()
    if corpus:
      corpus_xml = "\n".join(
        f'<post slug="{p["slug"]}"><title>{p["title"]}</title><summary>{p["summary"]}</summary></post>'
        for p in corpus
      )
      system_blocks.append({
        "type": "text",
        "text": f"<existing_posts>\n{corpus_xml}\n</existing_posts>",
        "cache_control": {"type": "ephemeral"},
      })
    try:
      message = self._get_client().messages.create(
        model="claude-sonnet-5",
        max_tokens=8192,
        system=system_blocks,
        tools=[{**post_tool, "cache_control": {"type": "ephemeral"}}],
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
      f"<post>\n"
      f"<title>{post.title}</title>\n"
      f"<summary>{post.summary}</summary>\n\n"
      f"<content>\n{post.content}\n</content>\n"
      f"</post>"
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
      f"<post>\n"
      f"<title>{post.title}</title>\n"
      f"<tags>{', '.join(post.tags)}</tags>\n"
      f"<summary>{post.summary}</summary>\n"
      f"</post>"
    )
    try:
      message = self._get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=[
          {"type": "text", "text": self._sources_system_prompt, "cache_control": {"type": "ephemeral"}},
        ],
        tools=[
          # 1 search (was 5, then 2): each web search injects a large (~30-45k token) result
          # payload — the dominant cost of the sources step. One search returns enough results
          # to extract 3-5 references; sources are a nice-to-have, not worth paying for breadth.
          {"type": "web_search_20250305", "name": "web_search", "max_uses": 1},
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

  def discover_trending_topics(self, category: dict, existing_topics: list[PostBrief]) -> list[dict]:
    """Search the web for 3-5 fresh topic candidates in the given category. Fail-soft:
    this is a pool-replenishment augmentation, never a blocking dependency."""
    self._ensure_prompts()
    corpus = _project_corpus_for_prompt()
    topics_projection = _project_topics_for_prompt(existing_topics)
    corpus_xml = "\n".join(
      f'<post slug="{p["slug"]}"><title>{p["title"]}</title><summary>{p["summary"]}</summary></post>'
      for p in corpus
    )
    topics_xml = "\n".join(
      f'<topic><title_hint>{t["title_hint"]}</title_hint><tags>{", ".join(t["tags"])}</tags></topic>'
      for t in topics_projection
    )
    prompt = (
      f"Find fresh topic candidates in this category:\n\n"
      f"<category>\n<label>{category['label']}</label>\n<search_hint>{category['search_hint']}</search_hint>\n</category>\n\n"
      f"<existing_posts>\n{corpus_xml}\n</existing_posts>\n\n"
      f"<existing_topics>\n{topics_xml}\n</existing_topics>"
    )
    try:
      message = self._get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        # Up to 5 web searches inject their results into the output stream *and* the model
        # must emit 3-5 full topic briefs afterward. 2048 was exhausted by the searches
        # before the suggest_topics call, truncating it to empty input (stop_reason=max_tokens).
        max_tokens=8192,
        system=[
          {"type": "text", "text": self._trending_topics_system_prompt, "cache_control": {"type": "ephemeral"}},
        ],
        tools=[
          {"type": "web_search_20250305", "name": "web_search", "max_uses": 5},
          {**self._trending_topics_tool, "cache_control": {"type": "ephemeral"}},
        ],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": prompt}],
      )
    except anthropic.APIError as exc:
      log.warning("Topic discovery failed: %s", exc)
      return []

    self._log_usage("discover_topics", message)

    tool_block = next((b for b in message.content if b.type == "tool_use" and b.name == "suggest_topics"), None)
    if tool_block is None:
      log.warning("Topic discovery returned no suggest_topics tool call (stop_reason=%s)", message.stop_reason)
      return []
    topics = tool_block.input.get("topics", [])
    if not topics:
      # Empty input usually means the tool call was truncated mid-JSON by the token limit.
      log.warning("Topic discovery produced 0 topics (stop_reason=%s) — likely max_tokens truncation", message.stop_reason)
    return topics

  def generate_with_review(
    self, user_message: str, max_attempts: int = MAX_GENERATION_ATTEMPTS,
    series: bool = False, with_sources: bool = True,
  ) -> tuple[PostOut, ReviewResult]:
    """Generate a post and review it. Retry up to `max_attempts`, feeding review feedback into retries.
    Set with_sources=False to skip the (expensive) web-search sources step — series runs it once
    for the whole series instead of once per part."""
    best_post = None
    best_review = None
    prompt = user_message
    self._run_cost = 0.0  # accumulate this run's cost across generate + review (+ sources)
    for attempt in range(max_attempts):
      post = self.generate_post(prompt, series=series)
      review = self.review_post(post)
      if best_review is None or review.score > best_review.score:
        best_post = post
        best_review = review
      if review.verdict == "pass":
        break
      if attempt < max_attempts - 1:
        prompt = (
          f"{user_message}\n\n"
          f"--- Previous attempt was rejected (score {review.score}/10) ---\n"
          f"Issues found: {'; '.join(review.issues)}\n"
          f"Fix these specific issues in your next attempt."
        )
    if with_sources:
      best_post.sources = self.find_sources(best_post)
    self.last_run_cost = round(self._run_cost, 6)
    return best_post, best_review

  def plan_series(self, topic: str, series_type: dict, count: int, extra_guidance: str = "") -> SeriesPlan:
    """Expand one topic + a series spec into an ordered outline of `count` parts.

    Cheap structured-outlining task — uses Haiku per the cost rules in docs/architecture.md.
    """
    self._ensure_prompts()
    corpus = _project_corpus_for_prompt()
    corpus_xml = "\n".join(
      f'<post slug="{p["slug"]}"><title>{p["title"]}</title><summary>{p["summary"]}</summary></post>'
      for p in corpus
    )
    spec_lines = [
      "<series_spec>",
      f"<topic>{topic}</topic>",
      f"<shape>{series_type['label']}</shape>",
      f"<number_of_parts>{count}</number_of_parts>",
      f"<arc_guidance>{series_type['arc_guidance']}</arc_guidance>",
      f"<part_guidance>{series_type['part_guidance']}</part_guidance>",
    ]
    if extra_guidance:
      spec_lines.append(f"<extra_guidance>{extra_guidance}</extra_guidance>")
    spec_lines.append("</series_spec>")
    prompt = "\n".join(spec_lines) + f"\n\n<existing_posts>\n{corpus_xml}\n</existing_posts>"

    try:
      message = self._get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=[
          {"type": "text", "text": self._series_plan_system_prompt, "cache_control": {"type": "ephemeral"}},
        ],
        tools=[{**self._series_plan_tool, "cache_control": {"type": "ephemeral"}}],
        tool_choice={"type": "tool", "name": "plan_series"},
        messages=[{"role": "user", "content": prompt}],
      )
    except anthropic.APIError as exc:
      raise HTTPException(status_code=502, detail=f"Claude API error: {exc}") from exc

    self._log_usage("plan_series", message)

    tool_block = next((b for b in message.content if b.type == "tool_use"), None)
    if tool_block is None:
      raise HTTPException(status_code=422, detail="Claude did not call plan_series tool")
    data = tool_block.input
    parts = data.get("parts", [])
    if not parts:
      raise HTTPException(status_code=422, detail="Series planning produced no parts (max_tokens hit?)")
    # Normalize ordering: trust sequence over the model's part_number field, and cap to `count`.
    plan_parts = [
      SeriesPart(
        part_number=i + 1,
        title=p["title"],
        angle=p.get("angle", ""),
        key_points=p.get("key_points", []),
        suggested_tags=p.get("suggested_tags", []),
      )
      for i, p in enumerate(parts[:count])
    ]
    return SeriesPlan(
      series_title=data.get("series_title", topic),
      series_description=data.get("series_description", ""),
      parts=plan_parts,
    )


blog_generator = BlogGenerator()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _project_corpus_for_prompt() -> list[dict]:
  """Slug/title/summary/tags only — never full content — to keep the prompt small and cache-friendly."""
  from data.posts import get_all_posts
  return [
    {"slug": p["slug"], "title": p["title"], "summary": p["summary"], "tags": p["tags"]}
    for p in get_all_posts()
  ]


def _project_topics_for_prompt(topics: list[PostBrief]) -> list[dict]:
  """title_hint/tags only, to keep the discovery prompt small and cache-friendly."""
  return [{"title_hint": t.title_hint, "tags": t.tags} for t in topics]


def _load_briefs() -> list[PostBrief]:
  raw = json.loads(BRIEFS_PATH.read_text())
  return [PostBrief(**item) for item in raw]


def _build_brief_message(brief: PostBrief) -> str:
  parts = [
    f"Today's date: {Date.today().isoformat()}",
    "<brief>",
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
  parts.append("</brief>")
  return "\n".join(parts)


def _build_series_part_message(series_title: str, part: SeriesPart, outline: list[SeriesPart]) -> str:
  """Brief message for one series part, with cross-part context so the writer stays in lane."""
  total = len(outline)
  outline_lines = "\n".join(
    f"  {p.part_number}. {p.title}" + (" (this part)" if p.part_number == part.part_number else "")
    for p in outline
  )
  lines = [
    f"Today's date: {Date.today().isoformat()}",
    "<brief>",
    f"This is Part {part.part_number} of {total} in the series \"{series_title}\".",
    "Full series outline (for context — write ONLY this part):",
    outline_lines,
    f"Title hint: {part.title}",
    f"This part's angle: {part.angle}",
  ]
  if part.key_points:
    points = "\n".join(f"  - {kp}" for kp in part.key_points)
    lines.append(f"Required points to cover:\n{points}")
  if part.suggested_tags:
    lines.append(f"Suggested tags: {', '.join(part.suggested_tags)}")
  lines.append(
    "Assume the reader has read the earlier parts — do not re-explain what they covered. "
    "You may mention what other parts cover, but keep this post focused on its own angle."
  )
  lines.append("</brief>")
  return "\n".join(lines)


def generate_series(series_id: str, series_title: str, parts: list[SeriesPart]) -> None:
  """Generate one draft per part, assigning each to the series. Runs in the background
  (off the event loop). Each part is isolated so one failure doesn't abort the rest.

  Sources are found ONCE for the whole series (not per part) — the web-search step is the
  single most expensive part of generation, so a series shares one set of references across
  its parts rather than paying for it N times."""
  first_post: PostOut | None = None
  for part in parts:
    try:
      user_message = _build_series_part_message(series_title, part, parts)
      post, review = blog_generator.generate_with_review(
        user_message, max_attempts=SERIES_GENERATION_ATTEMPTS, series=True, with_sources=False,
      )
      _insert_draft(
        post,
        topic_id=f"series:{series_id}",
        review=review,
        series_id=series_id,
        series_order=part.part_number,
      )
      if first_post is None:
        first_post = post
      log.info("Series %s: generated part %d/%d (%r)", series_id, part.part_number, len(parts), post.slug)
    except Exception as exc:
      log.warning("Series %s: part %d failed: %s", series_id, part.part_number, exc)

  # One sources call for the whole series, applied to every part's draft.
  if first_post is not None:
    try:
      sources = blog_generator.find_sources(first_post)
      if sources:
        sources_json = json.dumps([s.model_dump() for s in sources])
        with get_conn() as conn:
          conn.execute("UPDATE drafts SET sources = ? WHERE series_id = ? AND status = 'pending'",
                       (sources_json, series_id))
        log.info("Series %s: attached %d shared sources to its drafts", series_id, len(sources))
    except Exception as exc:
      log.warning("Series %s: shared source search failed: %s", series_id, exc)


def _existing_series_sources(series_id: str) -> str | None:
  """Reuse a sibling's sources (published post or pending draft) so regenerating one part
  costs no extra web search. Returns a JSON sources string, or None."""
  with get_conn() as conn:
    row = conn.execute(
      "SELECT sources FROM posts WHERE series_id = ? AND sources IS NOT NULL AND sources != '[]' LIMIT 1",
      (series_id,),
    ).fetchone()
    if row and row["sources"]:
      return row["sources"]
    row = conn.execute(
      "SELECT sources FROM drafts WHERE series_id = ? AND sources IS NOT NULL AND sources != '[]' LIMIT 1",
      (series_id,),
    ).fetchone()
    if row and row["sources"]:
      return row["sources"]
  return None


def generate_series_part(series_id: str, series_title: str, parts: list[SeriesPart], part_number: int) -> None:
  """(Re)generate a single series part from its stored brief — for filling a part that failed
  to generate, without rebuilding the whole series. Reuses siblings' sources (no extra search)."""
  target = next((p for p in parts if p.part_number == part_number), None)
  if target is None:
    log.warning("Series %s: part %d not in outline; nothing to generate", series_id, part_number)
    return
  try:
    user_message = _build_series_part_message(series_title, target, parts)
    post, review = blog_generator.generate_with_review(
      user_message, max_attempts=SERIES_GENERATION_ATTEMPTS, series=True, with_sources=False,
    )
    with get_conn() as conn:
      # Drop any existing pending draft for this slot so we don't create a duplicate.
      conn.execute("DELETE FROM drafts WHERE series_id = ? AND series_order = ? AND status = 'pending'",
                   (series_id, part_number))
    _insert_draft(post, topic_id=f"series:{series_id}", review=review,
                  series_id=series_id, series_order=part_number)
    reuse = _existing_series_sources(series_id)
    if reuse:
      with get_conn() as conn:
        conn.execute("UPDATE drafts SET sources = ? WHERE series_id = ? AND series_order = ? AND status = 'pending'",
                     (reuse, series_id, part_number))
    log.info("Series %s: regenerated part %d (%r)", series_id, part_number, post.slug)
  except Exception as exc:
    log.warning("Series %s: regenerating part %d failed: %s", series_id, part_number, exc)


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


def _insert_draft(
  post: PostOut,
  topic_id: str,
  review: ReviewResult | None = None,
  series_id: str | None = None,
  series_order: int | None = None,
  cost_usd: float | None = None,
) -> DraftOut:
  now = datetime.now(timezone.utc)
  draft_id = str(uuid.uuid4())
  # Default to the cost of the run that just produced this post.
  if cost_usd is None:
    cost_usd = blog_generator.last_run_cost
  q_score = review.score if review else None
  q_issues = json.dumps(review.issues) if review else "[]"
  q_strengths = json.dumps(review.strengths) if review else "[]"
  sources_json = json.dumps([s.model_dump() for s in post.sources])
  with get_conn() as conn:
    conn.execute(
      """INSERT INTO drafts
         (id, slug, title, date, summary, tags, content, image, generated_at, topic_id, status,
          quality_score, quality_issues, quality_strengths, sources, series_id, series_order, gen_cost_usd)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)""",
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
        series_id,
        series_order,
        cost_usd,
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
    series_id=series_id,
    series_order=series_order,
    gen_cost_usd=cost_usd,
  )


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/briefs", response_model=list[PostBrief])
def list_briefs():
  return _load_briefs()


@router.post("/generate", response_model=DraftOut, status_code=201)
def generate_post_route(body: GenerateIn, _: None = Depends(_get_require_admin())):
  user_message = f"Today's date: {Date.today().isoformat()}\nDescription: {body.description}"
  if body.tags:
    user_message += f"\nSuggested tags: {', '.join(body.tags)}"
  post, review = _generate_with_review(user_message)
  return _insert_draft(post, topic_id="freeform", review=review)


@router.post("/generate/{brief_id}", response_model=DraftOut, status_code=201)
def generate_from_brief(brief_id: str, _: None = Depends(_get_require_admin())):
  briefs = _load_briefs()
  brief = next((b for b in briefs if b.id == brief_id), None)
  if brief is None:
    raise HTTPException(status_code=404, detail=f"Brief '{brief_id}' not found")
  post, review = _generate_with_review(_build_brief_message(brief))
  return _insert_draft(post, topic_id=brief.id, review=review)
