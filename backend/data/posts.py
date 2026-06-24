import math

from db import get_conn, row_to_dict

PAGE_SIZE = 5


def get_all_posts() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM posts ORDER BY date DESC").fetchall()
    return [row_to_dict(r) for r in rows]


def get_post_by_slug(slug: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM posts WHERE slug = ?", (slug,)).fetchone()
    return row_to_dict(row) if row else None


def get_all_tags() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT value FROM posts, json_each(tags) ORDER BY value"
        ).fetchall()
    return [row[0] for row in rows]


def get_posts_page(page: int, tag: str | None = None) -> tuple[list[dict], int]:
    offset = (page - 1) * PAGE_SIZE
    with get_conn() as conn:
        if tag:
            total = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE EXISTS "
                "(SELECT 1 FROM json_each(tags) WHERE value = ?)",
                (tag,),
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT * FROM posts WHERE EXISTS "
                "(SELECT 1 FROM json_each(tags) WHERE value = ?) "
                "ORDER BY date DESC LIMIT ? OFFSET ?",
                (tag, PAGE_SIZE, offset),
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            rows = conn.execute(
                "SELECT * FROM posts ORDER BY date DESC LIMIT ? OFFSET ?",
                (PAGE_SIZE, offset),
            ).fetchall()
    return [row_to_dict(r) for r in rows], total


def total_pages(total: int) -> int:
    return max(1, math.ceil(total / PAGE_SIZE))


def get_popular_posts(limit: int = 5) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM posts ORDER BY views DESC, date DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_related_posts(slug: str, tags: list[str], limit: int = 3) -> list[dict]:
    all_posts = get_all_posts()
    scored = []
    tag_set = set(tags)
    for p in all_posts:
        if p["slug"] == slug:
            continue
        overlap = len(tag_set & set(p["tags"]))
        if overlap > 0:
            scored.append((overlap, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:limit]]
