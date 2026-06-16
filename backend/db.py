import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(os.getenv("DB_DIR", str(Path(__file__).parent))) / "blog.db"
SEED_PATH = Path(__file__).parent / "seed_posts.json"


def _load_seed() -> list[dict]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                slug    TEXT PRIMARY KEY,
                title   TEXT NOT NULL,
                date    TEXT NOT NULL,
                summary TEXT NOT NULL,
                tags    TEXT NOT NULL,
                content TEXT NOT NULL,
                image   TEXT
            )
        """)
        # Migrate: add image column to existing databases that predate this field
        cols = {row[1] for row in conn.execute("PRAGMA table_info(posts)")}
        if "image" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN image TEXT")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS drafts (
                id           TEXT PRIMARY KEY,
                slug         TEXT NOT NULL,
                title        TEXT NOT NULL,
                date         TEXT NOT NULL,
                summary      TEXT NOT NULL,
                tags         TEXT NOT NULL,
                content      TEXT NOT NULL,
                image        TEXT,
                generated_at TEXT NOT NULL,
                topic_id     TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending'
            )
        """)
        conn.execute(
            "UPDATE posts SET image = 'https://picsum.photos/seed/' || slug || '/800/400' WHERE image IS NULL"
        )
        if conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO posts (slug, title, date, summary, tags, content, image) VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        p["slug"],
                        p["title"],
                        p["date"],
                        p["summary"],
                        json.dumps(p["tags"]),
                        p["content"],
                        p.get("image"),
                    )
                    for p in _load_seed()
                ],
            )


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d["tags"])
    d["date"] = date.fromisoformat(d["date"])
    d["reading_time"] = max(1, len(d["content"].split()) // 200)
    return d


def draft_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d["tags"])
    d["date"] = date.fromisoformat(d["date"])
    d["generated_at"] = datetime.fromisoformat(d["generated_at"])
    d["reading_time"] = max(1, len(d["content"].split()) // 200)
    return d
