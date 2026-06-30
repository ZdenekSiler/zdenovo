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


# ── POST /api/posts/{slug}/unpublish ─────────────────────────────────────────

def test_unpublish_returns_204(client):
    client.post("/api/posts", json=_NEW_POST)
    r = client.post("/api/posts/hello-world/unpublish")
    assert r.status_code == 204


def test_unpublish_removes_from_posts(client):
    client.post("/api/posts", json=_NEW_POST)
    client.post("/api/posts/hello-world/unpublish")
    r = client.get("/api/posts/hello-world")
    assert r.status_code == 404


def test_unpublish_creates_pending_draft(client):
    client.post("/api/posts", json=_NEW_POST)
    client.post("/api/posts/hello-world/unpublish")
    drafts = client.get("/api/drafts").json()
    assert any(d["slug"] == "hello-world" and d["status"] == "pending" for d in drafts)


def test_unpublish_preserves_title_and_content(client):
    client.post("/api/posts", json=_NEW_POST)
    client.post("/api/posts/hello-world/unpublish")
    drafts = client.get("/api/drafts").json()
    draft = next(d for d in drafts if d["slug"] == "hello-world")
    assert draft["title"] == _NEW_POST["title"]
    assert draft["content"] == _NEW_POST["content"]


def test_unpublish_removes_comments(client):
    client.post("/api/posts", json=_NEW_POST)
    client.post("/api/comments", json={"post_slug": "hello-world", "author": "X", "body": "hi"})
    client.post("/api/posts/hello-world/unpublish")
    comments = client.get("/api/comments?post_slug=hello-world").json()
    assert comments == []


def test_unpublish_not_found_returns_404(client):
    r = client.post("/api/posts/no-such-post/unpublish")
    assert r.status_code == 404


# ── Reactions ─────────────────────────────────────────────────────────────────

def test_react_up_increments_count(client):
    r = client.post("/api/posts/htmx-is-enough/react")
    assert r.status_code == 200
    assert r.text == "1"

def test_react_up_returns_plain_text_not_json(client):
    r = client.post("/api/posts/htmx-is-enough/react")
    assert r.headers["content-type"].startswith("text/html")
    assert r.text.strip().isdigit()

def test_react_up_missing_post_returns_404(client):
    r = client.post("/api/posts/no-such/react")
    assert r.status_code == 404

def test_react_down_increments_count(client):
    r = client.post("/api/posts/htmx-is-enough/react-down")
    assert r.status_code == 200
    assert r.text == "1"

def test_react_down_returns_plain_text_not_json(client):
    r = client.post("/api/posts/htmx-is-enough/react-down")
    assert r.headers["content-type"].startswith("text/html")
    assert r.text.strip().isdigit()

def test_react_down_missing_post_returns_404(client):
    r = client.post("/api/posts/no-such/react-down")
    assert r.status_code == 404

def test_react_up_and_down_are_independent(client):
    # Up and down counters must not affect each other
    up = int(client.post("/api/posts/htmx-is-enough/react").text)
    down = int(client.post("/api/posts/htmx-is-enough/react-down").text)
    assert up == 1
    assert down == 1


# ── GET /api/posts/search ─────────────────────────────────────────────────────

def test_search_returns_matching_posts_by_title(client):
    r = client.get("/api/posts/search?q=HTMX")
    assert r.status_code == 200
    slugs = [p["slug"] for p in r.json()]
    assert "htmx-is-enough" in slugs

def test_search_returns_matching_posts_by_content(client):
    r = client.get("/api/posts/search?q=python")
    assert r.status_code == 200
    assert len(r.json()) > 0

def test_search_returns_matching_posts_by_tag(client):
    r = client.get("/api/posts/search?q=tooling")
    assert r.status_code == 200
    # "tooling" is a tag on the type-hints seed post
    assert any(p["slug"] == "why-i-switched-to-type-hints" for p in r.json())

def test_search_empty_query_returns_empty_list(client):
    r = client.get("/api/posts/search?q=")
    assert r.status_code == 200
    assert r.json() == []

def test_search_whitespace_query_returns_empty_list(client):
    r = client.get("/api/posts/search?q=   ")
    assert r.status_code == 200
    assert r.json() == []

def test_search_sanitizes_fts5_special_characters(client):
    # A query with FTS5 operator chars should not crash the endpoint
    r = client.get('/api/posts/search?q=python"*^()')
    assert r.status_code == 200

def test_search_respects_limit_of_10(client):
    import json
    from db import get_conn
    # Insert 15 posts all matching "uniqueterm"
    with get_conn() as conn:
        for i in range(15):
            conn.execute(
                "INSERT INTO posts (slug, title, date, summary, tags, content) VALUES (?,?,?,?,?,?)",
                (f"limit-test-{i}", f"Title {i}", "2026-01-01", "Sum", json.dumps([]), "uniqueterm content"),
            )
    r = client.get("/api/posts/search?q=uniqueterm")
    assert r.status_code == 200
    assert len(r.json()) <= 10

def test_search_results_are_json_post_objects(client):
    r = client.get("/api/posts/search?q=HTMX")
    assert r.status_code == 200
    results = r.json()
    assert len(results) > 0
    assert "slug" in results[0]
    assert "title" in results[0]
    assert "date" in results[0]
