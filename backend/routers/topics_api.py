import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from data.categories import categorize, load_categories
from db import get_conn, topic_row_to_dict

router = APIRouter(prefix="/api/topics", tags=["topics"])


# Import require_admin at usage time to avoid circular imports
def _get_require_admin():
    from routers.auth import require_admin
    return require_admin


# ─── Schemas ──────────────────────────────────────────────────────────────────

class TopicIn(BaseModel):
    title_hint: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., min_length=1, max_length=1500)
    audience: str = Field(..., min_length=1, max_length=300)
    tone: str = Field(..., min_length=1, max_length=300)
    tags: list[str] = Field(default_factory=list, max_length=10)
    outline: list[str] = Field(default_factory=list, max_length=20)


class TopicOut(TopicIn):
    id: str
    status: str = "available"
    draft_id: str | None = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_topics() -> list[dict]:
    """Return all topics as brief-shaped dicts (no `created_at`), in insertion order."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM topics ORDER BY rowid").fetchall()
    return [topic_row_to_dict(r) for r in rows]


def _save_topics(topics: list[dict]) -> None:
    """Full-table replace inside one transaction. Preserves each existing id's
    `created_at`; new ids get the current UTC timestamp. Row order follows the list."""
    with get_conn() as conn:
        existing = {
            row["id"]: row["created_at"]
            for row in conn.execute("SELECT id, created_at FROM topics")
        }
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("DELETE FROM topics")
        conn.executemany(
            "INSERT INTO topics (id, title_hint, description, audience, tone, tags, outline, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    t["id"],
                    t["title_hint"],
                    t["description"],
                    t["audience"],
                    t["tone"],
                    json.dumps(t.get("tags", [])),
                    json.dumps(t.get("outline", [])),
                    existing.get(t["id"], now),
                )
                for t in topics
            ],
        )


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


def category_balance(topics: list[dict]) -> list[dict]:
    """Available/used/total topic counts *and* the topics themselves, per fixed discovery
    category, for the admin category-balance dashboard. Topics that don't match any
    category tag are grouped under 'Uncategorized'."""
    categories = load_categories()
    buckets = {
        c["id"]: {"id": c["id"], "label": c["label"], "available": 0, "used": 0, "total": 0, "topics": []}
        for c in categories
    }
    uncategorized = {"id": "uncategorized", "label": "Uncategorized", "available": 0, "used": 0, "total": 0, "topics": []}
    for t in topics:
        cat_id = categorize(t.get("tags", []), categories) or "uncategorized"
        bucket = buckets.get(cat_id, uncategorized)
        bucket["total"] += 1
        if t.get("status") == "available":
            bucket["available"] += 1
        else:
            bucket["used"] += 1
        bucket["topics"].append({
            "id": t["id"],
            "title_hint": t["title_hint"],
            "status": t.get("status", "available"),
            "tags": t.get("tags", []),
            "draft_id": t.get("draft_id"),
        })
    result = list(buckets.values())
    if uncategorized["total"] > 0:
        result.append(uncategorized)
    return result


def create_topics(new_items: list[dict]) -> list[dict]:
    """Create one or more topics in a single load/save cycle. Shared by the REST create
    route, main.py's admin HTML create route, and automatic/manual topic discovery."""
    topics = _load_topics()
    created = []
    for data in new_items:
        topic_id = _slugify(data["title_hint"])
        if any(t["id"] == topic_id for t in topics):
            topic_id = f"{topic_id}-{len(topics)}"
        topic = {"id": topic_id, **data}
        topics.append(topic)
        created.append(topic)
    _save_topics(topics)
    return created


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
def create_topic(body: TopicIn, _: None = Depends(_get_require_admin())):
    return create_topics([body.model_dump()])[0]


@router.post("/discover", status_code=200)
def discover_topics_route(_: None = Depends(_get_require_admin())):
    """Manually trigger trending-topic discovery (also runs automatically when the pool is low)."""
    from routers.drafts_api import discover_and_replenish_topics
    return discover_and_replenish_topics()


@router.put("/{topic_id}", response_model=TopicOut)
def update_topic(topic_id: str, body: TopicIn, _: None = Depends(_get_require_admin())):
    topics = _load_topics()
    topic = next((t for t in topics if t["id"] == topic_id), None)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    topic.update(body.model_dump())
    _save_topics(topics)
    return topic


@router.delete("/{topic_id}", status_code=204)
def delete_topic(topic_id: str, _: None = Depends(_get_require_admin())):
    topics = _load_topics()
    filtered = [t for t in topics if t["id"] != topic_id]
    if len(filtered) == len(topics):
        raise HTTPException(status_code=404, detail="Topic not found")
    _save_topics(filtered)
