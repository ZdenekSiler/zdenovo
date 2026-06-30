import pytest


# ── POST /api/series ──────────────────────────────────────────────────────────

_NEW_SERIES = {
    "title": "Learning Rust",
    "description": "A multi-part series on Rust fundamentals.",
}


def test_create_series_returns_201(client):
    r = client.post("/api/series", json=_NEW_SERIES)
    assert r.status_code == 201


def test_create_series_id_derived_from_title(client):
    r = client.post("/api/series", json=_NEW_SERIES)
    assert r.json()["id"] == "learning-rust"


def test_create_series_returns_zero_post_count(client):
    r = client.post("/api/series", json=_NEW_SERIES)
    assert r.json()["post_count"] == 0


def test_create_series_duplicate_returns_409(client):
    client.post("/api/series", json=_NEW_SERIES)
    r = client.post("/api/series", json=_NEW_SERIES)
    assert r.status_code == 409


def test_create_series_missing_title_returns_422(client):
    r = client.post("/api/series", json={"description": "x"})
    assert r.status_code == 422


# ── GET /api/series ───────────────────────────────────────────────────────────

def test_list_series_returns_list(client):
    client.post("/api/series", json=_NEW_SERIES)
    r = client.get("/api/series")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 1


def test_list_series_sorted_newest_first(client):
    client.post("/api/series", json={"title": "First Series"})
    client.post("/api/series", json={"title": "Second Series"})
    r = client.get("/api/series")
    ids = [s["id"] for s in r.json()]
    assert ids == ["second-series", "first-series"]


def test_list_series_includes_post_count(client):
    client.post("/api/series", json=_NEW_SERIES)
    r = client.get("/api/series")
    assert r.json()[0]["post_count"] == 0


# ── DELETE /api/series/{series_id} ────────────────────────────────────────────

def test_delete_series_returns_204(client):
    client.post("/api/series", json=_NEW_SERIES)
    r = client.delete("/api/series/learning-rust")
    assert r.status_code == 204


def test_delete_series_missing_returns_404(client):
    r = client.delete("/api/series/no-such-series")
    assert r.status_code == 404


def test_delete_series_removes_it(client):
    client.post("/api/series", json=_NEW_SERIES)
    client.delete("/api/series/learning-rust")
    r = client.get("/api/series")
    assert r.json() == []


def test_delete_series_clears_posts(client):
    client.post("/api/series", json=_NEW_SERIES)
    post = {
        "title": "Rust Part 1",
        "summary": "Intro to Rust.",
        "tags": ["rust"],
        "content": "Body content here.",
    }
    client.post("/api/posts", json=post)

    from db import get_conn
    with get_conn() as conn:
        conn.execute(
            "UPDATE posts SET series_id = ?, series_order = ? WHERE slug = ?",
            ("learning-rust", 1, "rust-part-1"),
        )

    r = client.delete("/api/series/learning-rust")
    assert r.status_code == 204

    with get_conn() as conn:
        row = conn.execute(
            "SELECT series_id, series_order FROM posts WHERE slug = ?", ("rust-part-1",)
        ).fetchone()
    assert row["series_id"] is None
    assert row["series_order"] is None
