import json
from pathlib import Path

CATEGORIES_PATH = Path(__file__).parent / "topic_categories.json"


def load_categories() -> list[dict]:
    return json.loads(CATEGORIES_PATH.read_text())


def categorize(tags: list[str], categories: list[dict] | None = None) -> str | None:
    """First category (from data/topic_categories.json) whose tags overlap `tags`, or
    None if there's no overlap. A tag-based heuristic, not a hard classifier — shared by
    topic-discovery category rotation, the topics admin dashboard, and post categorization."""
    categories = categories if categories is not None else load_categories()
    tag_set = set(tags)
    return next((c["id"] for c in categories if tag_set & set(c["tags"])), None)
