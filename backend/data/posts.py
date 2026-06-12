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
