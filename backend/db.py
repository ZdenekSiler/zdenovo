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
        # ── posts column migrations ────────────────────────────────────────────
        cols = {row[1] for row in conn.execute("PRAGMA table_info(posts)")}
        if "image" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN image TEXT")
        if "sources" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN sources TEXT NOT NULL DEFAULT '[]'")
        if "views" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN views INTEGER NOT NULL DEFAULT 0")
        if "ai_comments" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN ai_comments INTEGER NOT NULL DEFAULT 1")
        if "reactions" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN reactions INTEGER NOT NULL DEFAULT 0")
        if "series_id" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN series_id TEXT REFERENCES series(id)")
        if "series_order" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN series_order INTEGER")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS drafts (
                id                TEXT PRIMARY KEY,
                slug              TEXT NOT NULL,
                title             TEXT NOT NULL,
                date              TEXT NOT NULL,
                summary           TEXT NOT NULL,
                tags              TEXT NOT NULL,
                content           TEXT NOT NULL,
                image             TEXT,
                generated_at      TEXT NOT NULL,
                topic_id          TEXT NOT NULL,
                status            TEXT NOT NULL DEFAULT 'pending',
                quality_score     INTEGER,
                quality_issues    TEXT NOT NULL DEFAULT '[]',
                quality_strengths TEXT NOT NULL DEFAULT '[]',
                admin_remarks     TEXT
            )
        """)
        draft_cols = {row[1] for row in conn.execute("PRAGMA table_info(drafts)")}
        if "quality_score" not in draft_cols:
            conn.execute("ALTER TABLE drafts ADD COLUMN quality_score INTEGER")
            conn.execute("ALTER TABLE drafts ADD COLUMN quality_issues TEXT DEFAULT '[]'")
            conn.execute("ALTER TABLE drafts ADD COLUMN quality_strengths TEXT DEFAULT '[]'")
        if "admin_remarks" not in draft_cols:
            conn.execute("ALTER TABLE drafts ADD COLUMN admin_remarks TEXT")
        if "sources" not in draft_cols:
            conn.execute("ALTER TABLE drafts ADD COLUMN sources TEXT NOT NULL DEFAULT '[]'")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id           TEXT PRIMARY KEY,
                post_slug    TEXT NOT NULL,
                author       TEXT NOT NULL,
                body         TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                is_generated INTEGER NOT NULL DEFAULT 0
            )
        """)
        comment_cols = {row[1] for row in conn.execute("PRAGMA table_info(comments)")}
        if "is_generated" not in comment_cols:
            conn.execute("ALTER TABLE comments ADD COLUMN is_generated INTEGER NOT NULL DEFAULT 0")
        if "status" not in comment_cols:
            conn.execute("ALTER TABLE comments ADD COLUMN status TEXT NOT NULL DEFAULT 'published'")
        if "parent_id" not in comment_cols:
            conn.execute("ALTER TABLE comments ADD COLUMN parent_id TEXT REFERENCES comments(id)")

        # ── series table ───────────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS series (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                description TEXT,
                created_at  TEXT NOT NULL
            )
        """)

        # ── FTS5 full-text search ──────────────────────────────────────────────
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
                slug UNINDEXED,
                title,
                summary,
                tags,
                content,
                content='posts',
                content_rowid='rowid'
            )
        """)
        # Triggers to keep posts_fts in sync with posts
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS posts_fts_insert
            AFTER INSERT ON posts BEGIN
                INSERT INTO posts_fts(rowid, slug, title, summary, tags, content)
                VALUES (new.rowid, new.slug, new.title, new.summary, new.tags, new.content);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS posts_fts_update
            AFTER UPDATE ON posts BEGIN
                INSERT INTO posts_fts(posts_fts, rowid, slug, title, summary, tags, content)
                VALUES ('delete', old.rowid, old.slug, old.title, old.summary, old.tags, old.content);
                INSERT INTO posts_fts(rowid, slug, title, summary, tags, content)
                VALUES (new.rowid, new.slug, new.title, new.summary, new.tags, new.content);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS posts_fts_delete
            AFTER DELETE ON posts BEGIN
                INSERT INTO posts_fts(posts_fts, rowid, slug, title, summary, tags, content)
                VALUES ('delete', old.rowid, old.slug, old.title, old.summary, old.tags, old.content);
            END
        """)
        # Backfill FTS5 table for existing posts (idempotent — INSERT OR IGNORE)
        conn.execute("""
            INSERT OR IGNORE INTO posts_fts(rowid, slug, title, summary, tags, content)
            SELECT rowid, slug, title, summary, tags, content FROM posts
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
    d["sources"] = json.loads(d.get("sources") or "[]")
    return d


def draft_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d["tags"])
    d["date"] = date.fromisoformat(d["date"])
    d["generated_at"] = datetime.fromisoformat(d["generated_at"])
    d["reading_time"] = max(1, len(d["content"].split()) // 200)
    d["quality_issues"] = json.loads(d.get("quality_issues") or "[]")
    d["quality_strengths"] = json.loads(d.get("quality_strengths") or "[]")
    d["sources"] = json.loads(d.get("sources") or "[]")
    return d


def comment_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["created_at"] = datetime.fromisoformat(d["created_at"])
    d["is_generated"] = bool(d.get("is_generated", 0))
    d["status"] = d.get("status", "published")
    d["parent_id"] = d.get("parent_id")
    return d
