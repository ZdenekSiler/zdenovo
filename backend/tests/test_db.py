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
