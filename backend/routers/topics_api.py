import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from db import get_conn

router = APIRouter(prefix="/api/topics", tags=["topics"])

DAILY_TOPICS_PATH = Path(__file__).resolve().parent.parent / "data" / "daily_topics.json"


# Import require_admin at usage time to avoid circular imports
def _get_require_admin():
    from routers.auth import require_admin
    return require_admin


# ─── Schemas ──────────────────────────────────────────────────────────────────

class TopicIn(BaseModel):
    title_hint: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    audience: str = Field(..., min_length=1)
    tone: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    outline: list[str] = Field(default_factory=list)


class TopicOut(TopicIn):
    id: str
    status: str = "available"
    draft_id: str | None = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_topics() -> list[dict]:
    return json.loads(DAILY_TOPICS_PATH.read_text())


def _save_topics(topics: list[dict]) -> None:
    DAILY_TOPICS_PATH.write_text(json.dumps(topics, indent=2) + "\n")


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _get_topic_draft_map() -> dict[str, dict]:
    """Return {topic_id: {"status": ..., "draft_id": ...}} for topics with existing drafts."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT topic_id, id, status FROM drafts ORDER BY generated_at DESC"
        ).fetchall()
    result: dict[str, dict] = {}
    for row in rows:
        tid = row["topic_id"]
        if tid in result:
            continue
        draft_status = "published" if row["status"] == "approved" else "draft_pending"
        result[tid] = {"status": draft_status, "draft_id": row["id"]}
    return result


def _enrich_topics(topics: list[dict]) -> list[dict]:
    """Attach status and draft_id to each topic based on draft existence."""
    draft_map = _get_topic_draft_map()
    enriched = []
    for t in topics:
        info = draft_map.get(t["id"])
        enriched.append({
            **t,
            "status": info["status"] if info else "available",
            "draft_id": info["draft_id"] if info else None,
        })
    return enriched


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[TopicOut])
def list_topics():
    return _enrich_topics(_load_topics())


@router.get("/{topic_id}", response_model=TopicOut)
def get_topic(topic_id: str):
    topics = _enrich_topics(_load_topics())
    topic = next((t for t in topics if t["id"] == topic_id), None)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.post("", response_model=TopicOut, status_code=201)
def create_topic(body: TopicIn, _: None = Depends(_get_require_admin)):
    topics = _load_topics()
    topic_id = _slugify(body.title_hint)
    if any(t["id"] == topic_id for t in topics):
        topic_id = f"{topic_id}-{len(topics)}"
    topic = {"id": topic_id, **body.model_dump()}
    topics.append(topic)
    _save_topics(topics)
    return topic


@router.put("/{topic_id}", response_model=TopicOut)
def update_topic(topic_id: str, body: TopicIn, _: None = Depends(_get_require_admin)):
    topics = _load_topics()
    topic = next((t for t in topics if t["id"] == topic_id), None)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    topic.update(body.model_dump())
    _save_topics(topics)
    return topic


@router.delete("/{topic_id}", status_code=204)
def delete_topic(topic_id: str, _: None = Depends(_get_require_admin)):
    topics = _load_topics()
    filtered = [t for t in topics if t["id"] != topic_id]
    if len(filtered) == len(topics):
        raise HTTPException(status_code=404, detail="Topic not found")
    _save_topics(filtered)
