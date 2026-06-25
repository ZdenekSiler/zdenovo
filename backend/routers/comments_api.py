import json
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import read_secret
from db import comment_row_to_dict, get_conn

router = APIRouter(prefix="/api/comments", tags=["comments"])
log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "data" / "prompts"


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
    is_generated: bool = False


# ─── CommentGenerator ────────────────────────────────────────────────────────

class CommentGenerator:
    """Generates realistic fake comments for blog posts using Claude Haiku."""

    def __init__(self) -> None:
        self._client: anthropic.Anthropic | None = None
        self._prompts_loaded = False
        self._system_prompt = ""
        self._comment_tool: dict = {}

    def _ensure_prompts(self) -> None:
        if self._prompts_loaded:
            return
        self._system_prompt = (PROMPTS_DIR / "comment_system.md").read_text(encoding="utf-8")
        self._comment_tool = json.loads((PROMPTS_DIR / "comment_tool.json").read_text(encoding="utf-8"))
        self._prompts_loaded = True

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            api_key = read_secret("anthropic_api_key", "ANTHROPIC_API_KEY")
            if not api_key:
                raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def generate_and_insert(self, post_slug: str, post_title: str, post_content: str, post_date: str) -> list[dict]:
        """Generate 1-2 fake comments and insert them into the database."""
        self._ensure_prompts()
        count = random.randint(1, 2)
        name_pool = [
            "Jake", "Amara", "Wei", "Sofia", "Tomás", "Kenji", "Fatima", "Liam",
            "Ayo", "Nina", "Raj", "Elena", "Dmitri", "Mei", "Carlos", "Ingrid",
            "Tariq", "Hana", "Oluwaseun", "Yuki", "Sven", "Aisha", "Marco", "Daria",
        ]
        suggested = random.sample(name_pool, count)
        user_message = (
            f"Write {count} comment{'s' if count > 1 else ''} for this blog post.\n"
            f"Use these names for the commenters: {', '.join(suggested)}.\n\n"
            f"Title: {post_title}\n\n"
            f"Content (first 1500 chars):\n{post_content[:1500]}"
        )

        try:
            message = self._get_client().messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=[
                    {"type": "text", "text": self._system_prompt, "cache_control": {"type": "ephemeral"}},
                ],
                tools=[{**self._comment_tool, "cache_control": {"type": "ephemeral"}}],
                tool_choice={"type": "tool", "name": "write_comments"},
                messages=[{"role": "user", "content": user_message}],
            )
        except anthropic.APIError as exc:
            raise HTTPException(status_code=502, detail=f"Claude API error: {exc}") from exc

        usage = message.usage
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
        log.info(
            "comment_gen: %d input, %d output, %d cache_read, %d cache_create tokens",
            usage.input_tokens, usage.output_tokens, cache_read, cache_create,
        )

        tool_block = next((b for b in message.content if b.type == "tool_use"), None)
        if not tool_block:
            raise HTTPException(status_code=422, detail="No tool_use block in response")

        comments_data = tool_block.input.get("comments", [])
        base_date = datetime.fromisoformat(post_date).replace(tzinfo=timezone.utc)
        offset = timedelta(hours=random.uniform(1, 72))
        inserted = []

        with get_conn() as conn:
            for item in comments_data:
                created_at = base_date + offset
                comment_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO comments (id, post_slug, author, body, created_at, is_generated) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (comment_id, post_slug, item["author"], item["body"], created_at.isoformat()),
                )
                inserted.append({
                    "id": comment_id,
                    "post_slug": post_slug,
                    "author": item["author"],
                    "body": item["body"],
                    "sentiment": item.get("sentiment", "neutral"),
                    "created_at": created_at.isoformat(),
                })
                offset += timedelta(minutes=random.uniform(30, 60 * 24))

        log.info("Generated %d comment(s) for post '%s'", len(inserted), post_slug)
        return inserted


comment_generator = CommentGenerator()


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
            "INSERT INTO comments (id, post_slug, author, body, created_at, is_generated) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (comment_id, body.post_slug, body.author, body.body, now),
        )
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone()
    return comment_row_to_dict(row)


@router.post("/generate", status_code=201)
def generate_fake_comments(post_slug: str) -> list[dict]:
    """Generate 1-2 AI comments for a post."""
    with get_conn() as conn:
        post = conn.execute(
            "SELECT slug, title, content, date FROM posts WHERE slug = ?", (post_slug,)
        ).fetchone()
    if post is None:
        raise HTTPException(status_code=404, detail=f"Post '{post_slug}' not found")
    return comment_generator.generate_and_insert(
        post["slug"], post["title"], post["content"], post["date"],
    )


@router.delete("/{comment_id}", status_code=204)
def delete_comment(comment_id: str) -> None:
    with get_conn() as conn:
        result = conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"Comment '{comment_id}' not found")
