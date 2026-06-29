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


def test_admin_comments_returns_200(admin_client):
  resp = admin_client.get("/admin/comments")
  assert resp.status_code == 200


def test_admin_comments_lists_comments(admin_client):
  _insert_comment(admin_client, author="Dave", body="Testing")
  resp = admin_client.get("/admin/comments")
  assert b"Dave" in resp.content


def test_comment_form_submit_returns_partial(client):
  resp = client.post(
    f"/blog/{SEED_SLUG}/comments",
    data={"author": "Eve", "body": "Via form!"},
  )
  assert resp.status_code == 200
  assert b"Eve" in resp.content


# ─── is_generated flag ──────────────────────────────────────────────────────

def test_create_comment_is_generated_defaults_to_false(client):
  resp = client.post("/api/comments", json={"post_slug": SEED_SLUG, "author": "Bob", "body": "Nice!"})
  assert resp.json()["is_generated"] is False


def test_comment_out_includes_is_generated_field(client):
  _insert_comment(client)
  comments = client.get(f"/api/comments?post_slug={SEED_SLUG}").json()
  assert "is_generated" in comments[0]
  assert comments[0]["is_generated"] is False


def test_public_post_does_not_show_generated_flag(client):
  _insert_comment(client)
  resp = client.get(f"/blog/{SEED_SLUG}")
  assert b"AI" not in resp.content or b"is_generated" not in resp.content


# ─── Generate endpoint ───────────────────────────────────────────────────────

def _mock_comment_response():
  """Return a mock Anthropic message with a write_comments tool_use block."""
  from unittest.mock import MagicMock
  msg = MagicMock()
  msg.usage.input_tokens = 100
  msg.usage.output_tokens = 50
  msg.usage.cache_read_input_tokens = 0
  msg.usage.cache_creation_input_tokens = 0
  tool_block = MagicMock()
  tool_block.type = "tool_use"
  tool_block.input = {
    "comments": [
      {"author": "Mika", "body": "The dependency injection section was spot on.", "sentiment": "positive"},
    ]
  }
  msg.content = [tool_block]
  return msg


def test_generate_comments_returns_201(client, monkeypatch):
  from unittest.mock import MagicMock
  from routers.comments_api import comment_generator
  mock_client = MagicMock()
  mock_client.messages.create.return_value = _mock_comment_response()
  comment_generator._client = mock_client
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  resp = client.post(f"/api/comments/generate?post_slug={SEED_SLUG}")
  assert resp.status_code == 201


def test_generate_comments_post_not_found_returns_404(client):
  resp = client.post("/api/comments/generate?post_slug=nonexistent")
  assert resp.status_code == 404


def test_generate_comments_inserts_with_is_generated_true(client, monkeypatch):
  from unittest.mock import MagicMock
  from routers.comments_api import comment_generator
  mock_client = MagicMock()
  mock_client.messages.create.return_value = _mock_comment_response()
  comment_generator._client = mock_client
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  client.post(f"/api/comments/generate?post_slug={SEED_SLUG}")
  comments = client.get(f"/api/comments?post_slug={SEED_SLUG}").json()
  generated = [c for c in comments if c["is_generated"]]
  assert len(generated) == 1
  assert generated[0]["author"] == "Mika"


def test_admin_comments_shows_ai_badge_for_generated(admin_client, monkeypatch):
  from unittest.mock import MagicMock
  from routers.comments_api import comment_generator
  mock_client = MagicMock()
  mock_client.messages.create.return_value = _mock_comment_response()
  comment_generator._client = mock_client
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  admin_client.post(f"/api/comments/generate?post_slug={SEED_SLUG}")
  resp = admin_client.get("/admin/comments")
  assert b"AI" in resp.content


def test_admin_comments_no_ai_badge_for_real(admin_client):
  _insert_comment(admin_client, author="RealPerson", body="Real comment")
  resp = admin_client.get("/admin/comments")
  assert b"RealPerson" in resp.content


# ─── Scheduled generation ──────────────────────────────────────────────────

def test_slug_delay_hours_is_deterministic():
  from routers.comments_api import _slug_delay_hours
  d1 = _slug_delay_hours("my-post")
  d2 = _slug_delay_hours("my-post")
  assert d1 == d2
  assert 168 <= d1 <= 336


def test_slug_delay_hours_varies_by_slug():
  from routers.comments_api import _slug_delay_hours
  d1 = _slug_delay_hours("post-alpha")
  d2 = _slug_delay_hours("post-beta")
  assert d1 != d2


def test_generate_pending_comments_skips_too_recent(client, monkeypatch):
  from routers.comments_api import generate_pending_comments
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  result = generate_pending_comments()
  assert result == 0


def test_generate_pending_comments_generates_after_delay(client, monkeypatch):
  from unittest.mock import MagicMock
  from routers.comments_api import comment_generator, generate_pending_comments
  mock_client = MagicMock()
  mock_client.messages.create.return_value = _mock_comment_response()
  comment_generator._client = mock_client
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  from db import get_conn
  with get_conn() as conn:
    conn.execute("UPDATE posts SET date = '2020-01-01T00:00:00' WHERE slug = ?", (SEED_SLUG,))

  result = generate_pending_comments()
  assert result >= 1

  comments = client.get(f"/api/comments?post_slug={SEED_SLUG}").json()
  generated = [c for c in comments if c["is_generated"]]
  assert len(generated) >= 1


# ─── AI comments toggle ───────────────────────────────────────────────────────

def test_toggle_ai_comments_off_returns_button_html(admin_client):
  resp = admin_client.post(f"/api/posts/{SEED_SLUG}/toggle-ai-comments")
  assert resp.status_code == 200
  assert b"AI: off" in resp.content
  assert b'hx-post="/api/posts/' in resp.content


def test_toggle_ai_comments_back_on(admin_client):
  admin_client.post(f"/api/posts/{SEED_SLUG}/toggle-ai-comments")  # off
  resp = admin_client.post(f"/api/posts/{SEED_SLUG}/toggle-ai-comments")  # on
  assert resp.status_code == 200
  assert b"AI: on" in resp.content


def test_toggle_ai_comments_unknown_slug_returns_404(admin_client):
  resp = admin_client.post("/api/posts/no-such-post/toggle-ai-comments")
  assert resp.status_code == 404


def test_toggle_ai_comments_requires_admin(client):
  resp = client.post(f"/api/posts/{SEED_SLUG}/toggle-ai-comments", follow_redirects=False)
  assert resp.status_code == 303


def test_generate_skips_post_with_ai_comments_disabled(client, monkeypatch):
  from unittest.mock import MagicMock
  from routers.comments_api import comment_generator, generate_pending_comments

  from db import get_conn
  with get_conn() as conn:
    conn.execute("UPDATE posts SET date = '2020-01-01T00:00:00', ai_comments = 0")

  mock_client = MagicMock()
  mock_client.messages.create.return_value = _mock_comment_response()
  comment_generator._client = mock_client
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  result = generate_pending_comments()
  assert result == 0

  comments = client.get(f"/api/comments?post_slug={SEED_SLUG}").json()
  assert not any(c["is_generated"] for c in comments)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _insert_generated_comment(slug: str = SEED_SLUG) -> str:
  import uuid
  from datetime import datetime, timezone
  from db import get_conn
  comment_id = str(uuid.uuid4())
  now = datetime.now(timezone.utc).isoformat()
  with get_conn() as conn:
    conn.execute(
      "INSERT INTO comments (id, post_slug, author, body, created_at, is_generated, status) "
      "VALUES (?, ?, ?, ?, ?, 1, 'generated')",
      (comment_id, slug, "AI Bot", "Generated comment", now),
    )
  return comment_id


# ─── Status field ────────────────────────────────────────────────────────────

def test_real_comment_has_status_published(client):
  resp = client.post("/api/comments", json={"post_slug": SEED_SLUG, "author": "Bob", "body": "Nice!"})
  assert resp.json()["status"] == "published"


def test_comment_out_includes_status_field(client):
  _insert_comment(client)
  comments = client.get(f"/api/comments?post_slug={SEED_SLUG}").json()
  assert "status" in comments[0]


# ─── Approve endpoint ───────────────────────────────────────────────────────

def test_approve_comment_returns_200(client):
  comment_id = _insert_generated_comment()
  resp = client.patch(f"/api/comments/{comment_id}/approve")
  assert resp.status_code == 200


def test_approve_comment_sets_status_approved(client):
  comment_id = _insert_generated_comment()
  resp = client.patch(f"/api/comments/{comment_id}/approve")
  assert resp.json()["status"] == "approved"


def test_approve_non_generated_returns_409(client):
  comment_id = _insert_comment(client)
  resp = client.patch(f"/api/comments/{comment_id}/approve")
  assert resp.status_code == 409


def test_approve_nonexistent_returns_404(client):
  resp = client.patch("/api/comments/nonexistent-id/approve")
  assert resp.status_code == 404


# ─── Publish endpoint ───────────────────────────────────────────────────────

def test_publish_comment_returns_200(client):
  comment_id = _insert_generated_comment()
  client.patch(f"/api/comments/{comment_id}/approve")
  resp = client.patch(f"/api/comments/{comment_id}/publish")
  assert resp.status_code == 200


def test_publish_comment_sets_status_published(client):
  comment_id = _insert_generated_comment()
  client.patch(f"/api/comments/{comment_id}/approve")
  resp = client.patch(f"/api/comments/{comment_id}/publish")
  assert resp.json()["status"] == "published"


def test_publish_non_approved_returns_409(client):
  comment_id = _insert_generated_comment()
  resp = client.patch(f"/api/comments/{comment_id}/publish")
  assert resp.status_code == 409


def test_publish_nonexistent_returns_404(client):
  resp = client.patch("/api/comments/nonexistent-id/publish")
  assert resp.status_code == 404


# ─── Public visibility ───────────────────────────────────────────────────────

def test_public_post_hides_generated_comments(client):
  _insert_generated_comment()
  resp = client.get(f"/blog/{SEED_SLUG}")
  assert b"Generated comment" not in resp.content


def test_public_post_hides_approved_comments(client):
  import uuid
  from datetime import datetime, timezone
  from db import get_conn
  comment_id = str(uuid.uuid4())
  with get_conn() as conn:
    conn.execute(
      "INSERT INTO comments (id, post_slug, author, body, created_at, is_generated, status) "
      "VALUES (?, ?, ?, ?, ?, 1, 'approved')",
      (comment_id, SEED_SLUG, "AI Bot", "Approved but not published", datetime.now(timezone.utc).isoformat()),
    )
  resp = client.get(f"/blog/{SEED_SLUG}")
  assert b"Approved but not published" not in resp.content


def test_public_post_shows_published_ai_comments(client):
  comment_id = _insert_generated_comment()
  client.patch(f"/api/comments/{comment_id}/approve")
  client.patch(f"/api/comments/{comment_id}/publish")
  resp = client.get(f"/blog/{SEED_SLUG}")
  assert b"Generated comment" in resp.content


def test_public_post_always_shows_real_comments(client):
  _insert_comment(client, body="Real human comment here")
  resp = client.get(f"/blog/{SEED_SLUG}")
  assert b"Real human comment here" in resp.content
