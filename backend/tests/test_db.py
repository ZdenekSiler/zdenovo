import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest


# ── _load_seed ────────────────────────────────────────────────────────────────

def test_load_seed_returns_list():
    import db
    seed = db._load_seed()
    assert isinstance(seed, list)
    assert len(seed) > 0


def test_load_seed_posts_have_required_keys():
    import db
    required = {"slug", "title", "date", "summary", "tags", "content"}
    for post in db._load_seed():
        assert required <= post.keys()


def test_load_seed_tags_are_lists():
    import db
    for post in db._load_seed():
        assert isinstance(post["tags"], list)


# ── init_db ───────────────────────────────────────────────────────────────────

def test_init_db_creates_posts_table(test_db):
    import db
    conn = sqlite3.connect(test_db)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='posts'"
    ).fetchone()
    conn.close()
    assert tables is not None


def test_init_db_seeds_all_posts(test_db):
    import db
    with db.get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    assert count == len(db._load_seed())


def test_init_db_is_idempotent(test_db):
    import db
    db.init_db()  # second call — must not raise or duplicate rows
    with db.get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    assert count == len(db._load_seed())


# ── get_conn ──────────────────────────────────────────────────────────────────

def test_get_conn_returns_row_factory(test_db):
    import db
    with db.get_conn() as conn:
        row = conn.execute("SELECT slug FROM posts LIMIT 1").fetchone()
    assert isinstance(row, sqlite3.Row)
    assert "slug" in row.keys()


# ── row_to_dict ───────────────────────────────────────────────────────────────

def test_row_to_dict_deserialises_tags(test_db):
    import db
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM posts LIMIT 1").fetchone()
    result = db.row_to_dict(row)
    assert isinstance(result["tags"], list)
    assert all(isinstance(t, str) for t in result["tags"])


def test_row_to_dict_converts_date(test_db):
    import db
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM posts LIMIT 1").fetchone()
    result = db.row_to_dict(row)
    assert isinstance(result["date"], date)


def test_row_to_dict_adds_reading_time(test_db):
    import db
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM posts LIMIT 1").fetchone()
    result = db.row_to_dict(row)
    assert "reading_time" in result
    assert result["reading_time"] >= 1


def test_row_to_dict_reading_time_minimum_one(test_db):
    import db
    with db.get_conn() as conn:
        # Insert a post with very short content
        conn.execute(
            "INSERT INTO posts (slug, title, date, summary, tags, content) VALUES (?,?,?,?,?,?)",
            ("tiny", "Tiny", "2026-01-01", "Sum", json.dumps(["x"]), "Hi"),
        )
        row = conn.execute("SELECT * FROM posts WHERE slug='tiny'").fetchone()
    result = db.row_to_dict(row)
    assert result["reading_time"] == 1


# ── FTS5 full-text search ──────────────────────────────────────────────────────

def test_init_db_creates_posts_fts_table(test_db):
    import sqlite3
    conn = sqlite3.connect(test_db)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='posts_fts'"
    ).fetchone()
    conn.close()
    assert row is not None


def test_init_db_backfills_existing_posts_into_fts(test_db):
    import db
    with db.get_conn() as conn:
        post_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM posts_fts").fetchone()[0]
    assert fts_count == post_count


def test_insert_post_syncs_to_fts_via_trigger(test_db):
    import db
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO posts (slug, title, date, summary, tags, content) VALUES (?,?,?,?,?,?)",
            ("fts-test", "FTS Unique Title", "2026-01-01", "Summary", json.dumps([]), "Content"),
        )
        row = conn.execute(
            "SELECT slug FROM posts_fts WHERE posts_fts MATCH 'FTS'",
        ).fetchone()
    assert row is not None
    assert row[0] == "fts-test"


def test_update_post_syncs_to_fts_via_trigger(test_db):
    import db
    # Use tokens that are guaranteed unique — absent from seed posts
    UNIQUE_OLD = "xyzzy7142oldtoken"
    UNIQUE_NEW = "xyzzy7142newtoken"
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO posts (slug, title, date, summary, tags, content) VALUES (?,?,?,?,?,?)",
            ("upd-test", UNIQUE_OLD, "2026-01-01", "Summary", json.dumps([]), "Content"),
        )
        conn.execute(f"UPDATE posts SET title = '{UNIQUE_NEW}' WHERE slug = 'upd-test'")
        old_match = conn.execute(
            "SELECT slug FROM posts_fts WHERE posts_fts MATCH ?", (UNIQUE_OLD,),
        ).fetchone()
        new_match = conn.execute(
            "SELECT slug FROM posts_fts WHERE posts_fts MATCH ?", (UNIQUE_NEW,),
        ).fetchone()
    assert old_match is None
    assert new_match is not None


def test_delete_post_removes_from_fts_via_trigger(test_db):
    import db
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO posts (slug, title, date, summary, tags, content) VALUES (?,?,?,?,?,?)",
            ("del-test", "Delete Me", "2026-01-01", "Summary", json.dumps([]), "Content"),
        )
        conn.execute("DELETE FROM posts WHERE slug = 'del-test'")
        row = conn.execute(
            "SELECT slug FROM posts_fts WHERE posts_fts MATCH 'Delete'",
        ).fetchone()
    assert row is None


def test_init_db_is_idempotent_does_not_duplicate_fts_rows(test_db):
    import db
    with db.get_conn() as conn:
        fts_before = conn.execute("SELECT COUNT(*) FROM posts_fts").fetchone()[0]
    db.init_db()  # second call
    with db.get_conn() as conn:
        fts_after = conn.execute("SELECT COUNT(*) FROM posts_fts").fetchone()[0]
    assert fts_after == fts_before
