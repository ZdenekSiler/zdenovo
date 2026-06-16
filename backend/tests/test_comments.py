SEED_SLUG = "htmx-is-enough"


def _insert_comment(client, slug: str = SEED_SLUG, author: str = "Alice", body: str = "Great post!") -> str:
  resp = client.post("/api/comments", json={"post_slug": slug, "author": author, "body": body})
  assert resp.status_code == 201
  return resp.json()["id"]


# ─── List ─────────────────────────────────────────────────────────────────────

def test_list_comments_returns_200(client):
  resp = client.get(f"/api/comments?post_slug={SEED_SLUG}")
  assert resp.status_code == 200


def test_list_comments_empty_for_unknown_slug(client):
  resp = client.get("/api/comments?post_slug=nonexistent")
  assert resp.status_code == 200
  assert resp.json() == []


def test_list_comments_returns_existing_comments_oldest_first(client):
  _insert_comment(client, body="First")
  _insert_comment(client, body="Second")
  comments = client.get(f"/api/comments?post_slug={SEED_SLUG}").json()
  assert len(comments) == 2
  assert comments[0]["body"] == "First"
  assert comments[1]["body"] == "Second"


# ─── Create ───────────────────────────────────────────────────────────────────

def test_create_comment_returns_201(client):
  resp = client.post("/api/comments", json={"post_slug": SEED_SLUG, "author": "Bob", "body": "Nice!"})
  assert resp.status_code == 201


def test_create_comment_has_expected_fields(client):
  resp = client.post("/api/comments", json={"post_slug": SEED_SLUG, "author": "Bob", "body": "Nice!"})
  data = resp.json()
  assert data["author"] == "Bob"
  assert data["body"] == "Nice!"
  assert data["post_slug"] == SEED_SLUG
  assert data["id"]
  assert data["created_at"]


def test_create_comment_post_not_found_returns_404(client):
  resp = client.post("/api/comments", json={"post_slug": "no-such-post", "author": "Bob", "body": "Nice!"})
  assert resp.status_code == 404


def test_create_comment_empty_author_returns_422(client):
  resp = client.post("/api/comments", json={"post_slug": SEED_SLUG, "author": "", "body": "Nice!"})
  assert resp.status_code == 422


def test_create_comment_empty_body_returns_422(client):
  resp = client.post("/api/comments", json={"post_slug": SEED_SLUG, "author": "Bob", "body": ""})
  assert resp.status_code == 422


def test_create_comment_author_too_long_returns_422(client):
  resp = client.post("/api/comments", json={"post_slug": SEED_SLUG, "author": "x" * 81, "body": "Nice!"})
  assert resp.status_code == 422


def test_create_comment_appears_in_list(client):
  _insert_comment(client, author="Carol", body="Hello!")
  comments = client.get(f"/api/comments?post_slug={SEED_SLUG}").json()
  assert any(c["author"] == "Carol" for c in comments)


# ─── Delete ───────────────────────────────────────────────────────────────────

def test_delete_comment_returns_204(client):
  comment_id = _insert_comment(client)
  resp = client.delete(f"/api/comments/{comment_id}")
  assert resp.status_code == 204


def test_delete_comment_removes_it(client):
  comment_id = _insert_comment(client)
  client.delete(f"/api/comments/{comment_id}")
  comments = client.get(f"/api/comments?post_slug={SEED_SLUG}").json()
  assert not any(c["id"] == comment_id for c in comments)


def test_delete_comment_not_found_returns_404(client):
  resp = client.delete("/api/comments/nonexistent-id")
  assert resp.status_code == 404


# ─── Cascade delete ───────────────────────────────────────────────────────────

def test_delete_post_also_deletes_its_comments(client):
  _insert_comment(client)
  client.delete(f"/api/posts/{SEED_SLUG}")
  comments = client.get(f"/api/comments?post_slug={SEED_SLUG}").json()
  assert comments == []


# ─── HTML routes ──────────────────────────────────────────────────────────────

def test_post_detail_includes_comments_section(client):
  resp = client.get(f"/blog/{SEED_SLUG}")
  assert resp.status_code == 200
  assert b"comments-section" in resp.content


def test_admin_comments_returns_200(client):
  resp = client.get("/admin/comments")
  assert resp.status_code == 200


def test_admin_comments_lists_comments(client):
  _insert_comment(client, author="Dave", body="Testing")
  resp = client.get("/admin/comments")
  assert b"Dave" in resp.content


def test_comment_form_submit_returns_partial(client):
  resp = client.post(
    f"/blog/{SEED_SLUG}/comments",
    data={"author": "Eve", "body": "Via form!"},
  )
  assert resp.status_code == 200
  assert b"Eve" in resp.content
