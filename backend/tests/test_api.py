import pytest


# ── GET /api/posts ────────────────────────────────────────────────────────────

def test_list_posts_returns_200(client):
    r = client.get("/api/posts")
    assert r.status_code == 200


def test_list_posts_returns_three_seed_posts(client):
    r = client.get("/api/posts")
    assert len(r.json()) == 3


def test_list_posts_sorted_newest_first(client):
    r = client.get("/api/posts")
    dates = [p["date"] for p in r.json()]
    assert dates == sorted(dates, reverse=True)


# ── GET /api/posts/{slug} ─────────────────────────────────────────────────────

def test_get_post_returns_correct_slug(client):
    r = client.get("/api/posts/htmx-is-enough")
    assert r.status_code == 200
    assert r.json()["slug"] == "htmx-is-enough"


def test_get_post_missing_returns_404(client):
    r = client.get("/api/posts/no-such-post")
    assert r.status_code == 404


# ── POST /api/posts ───────────────────────────────────────────────────────────

_NEW_POST = {
    "title": "Hello World",
    "summary": "A test post.",
    "tags": ["test"],
    "content": "Body content here.",
}


def test_post_response_includes_image_field(client):
    r = client.get("/api/posts/htmx-is-enough")
    assert "image" in r.json()


def test_seed_post_has_image(client):
    r = client.get("/api/posts/htmx-is-enough")
    assert r.json()["image"] is not None


def test_create_post_with_image(client):
    r = client.post("/api/posts", json={**_NEW_POST, "title": "Image Post", "image": "https://example.com/img.jpg"})
    assert r.status_code == 201
    assert r.json()["image"] == "https://example.com/img.jpg"


def test_create_post_without_image_defaults_null(client):
    r = client.post("/api/posts", json=_NEW_POST)
    assert r.status_code == 201
    assert r.json()["image"] is None


def test_update_post_sets_image(client):
    client.post("/api/posts", json=_NEW_POST)
    r = client.put("/api/posts/hello-world", json={**_NEW_POST, "image": "https://example.com/new.jpg"})
    assert r.status_code == 200
    assert r.json()["image"] == "https://example.com/new.jpg"


def test_create_post_returns_201(client):
    r = client.post("/api/posts", json=_NEW_POST)
    assert r.status_code == 201


def test_create_post_slug_derived_from_title(client):
    r = client.post("/api/posts", json=_NEW_POST)
    assert r.json()["slug"] == "hello-world"


def test_create_post_duplicate_returns_409(client):
    client.post("/api/posts", json=_NEW_POST)
    r = client.post("/api/posts", json=_NEW_POST)
    assert r.status_code == 409


def test_create_post_missing_title_returns_422(client):
    r = client.post("/api/posts", json={"summary": "x", "content": "x"})
    assert r.status_code == 422


# ── PUT /api/posts/{slug} ─────────────────────────────────────────────────────

def test_update_post_returns_200(client):
    client.post("/api/posts", json=_NEW_POST)
    r = client.put("/api/posts/hello-world", json={**_NEW_POST, "summary": "Updated."})
    assert r.status_code == 200
    assert r.json()["summary"] == "Updated."


def test_update_post_missing_returns_404(client):
    r = client.put("/api/posts/no-such-post", json=_NEW_POST)
    assert r.status_code == 404


# ── DELETE /api/posts/{slug} ──────────────────────────────────────────────────

def test_delete_post_returns_204(client):
    client.post("/api/posts", json=_NEW_POST)
    r = client.delete("/api/posts/hello-world")
    assert r.status_code == 204


def test_delete_post_removes_it(client):
    client.post("/api/posts", json=_NEW_POST)
    client.delete("/api/posts/hello-world")
    r = client.get("/api/posts/hello-world")
    assert r.status_code == 404


def test_delete_post_missing_returns_404(client):
    r = client.delete("/api/posts/no-such-post")
    assert r.status_code == 404
