from unittest.mock import MagicMock, patch

import pytest


MOCK_POST_DATA = {
  "title": "FastAPI Dependency Injection Guide",
  "summary": "A practical guide to FastAPI's dependency injection system.",
  "tags": ["fastapi", "python"],
  "content": "## Introduction\n\nDependency injection is a core FastAPI feature.\n\n## How It Works\n\nUse `Depends()` to declare dependencies.\n\n## Testing\n\nOverride dependencies in tests easily.\n\n## Conclusion\n\nKeep your routes thin and your logic testable.",
}


def _make_mock_client(post_data: dict = None):
  tool_block = MagicMock()
  tool_block.type = "tool_use"
  tool_block.input = post_data or MOCK_POST_DATA
  mock_message = MagicMock()
  mock_message.content = [tool_block]
  mock_client = MagicMock()
  mock_client.messages.create.return_value = mock_message
  return mock_client


def _insert_draft(client, monkeypatch) -> str:
  """Helper: trigger generation and return the first draft id."""
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = client.post("/api/drafts/generate")
  assert resp.status_code == 201
  drafts = client.get("/api/drafts").json()
  assert drafts
  return drafts[0]["id"]


# ─── Generation ───────────────────────────────────────────────────────────────

def test_manual_trigger_generates_drafts(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = client.post("/api/drafts/generate")
  assert resp.status_code == 201
  assert resp.json()["generated"] == 3


def test_generated_drafts_have_pending_status(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    client.post("/api/drafts/generate")
  drafts = client.get("/api/drafts").json()
  assert all(d["status"] == "pending" for d in drafts)


def test_generated_drafts_not_in_posts(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    client.post("/api/drafts/generate")
  draft_slugs = {d["slug"] for d in client.get("/api/drafts").json()}
  post_slugs = {p["slug"] for p in client.get("/api/posts").json()}
  assert draft_slugs.isdisjoint(post_slugs)


# ─── List & get ───────────────────────────────────────────────────────────────

def test_list_drafts_empty(client):
  resp = client.get("/api/drafts")
  assert resp.status_code == 200
  assert resp.json() == []


def test_list_drafts_returns_all(client, monkeypatch):
  draft_id = _insert_draft(client, monkeypatch)
  resp = client.get("/api/drafts")
  assert resp.status_code == 200
  assert len(resp.json()) == 3


def test_get_draft_by_id(client, monkeypatch):
  draft_id = _insert_draft(client, monkeypatch)
  resp = client.get(f"/api/drafts/{draft_id}")
  assert resp.status_code == 200
  data = resp.json()
  assert data["id"] == draft_id
  assert data["title"]
  assert data["reading_time"] >= 1


def test_get_draft_not_found(client):
  resp = client.get("/api/drafts/nonexistent-id")
  assert resp.status_code == 404


# ─── Approve ──────────────────────────────────────────────────────────────────

def test_approve_draft_publishes_to_posts(client, monkeypatch):
  draft_id = _insert_draft(client, monkeypatch)
  draft = client.get(f"/api/drafts/{draft_id}").json()

  resp = client.post(f"/api/drafts/{draft_id}/approve")
  assert resp.status_code == 201
  published = resp.json()
  assert published["slug"] == draft["slug"]
  assert published["title"] == draft["title"]

  # Post now appears in live blog
  post_slugs = [p["slug"] for p in client.get("/api/posts").json()]
  assert draft["slug"] in post_slugs


def test_approve_draft_sets_status_approved(client, monkeypatch):
  draft_id = _insert_draft(client, monkeypatch)
  client.post(f"/api/drafts/{draft_id}/approve")
  draft = client.get(f"/api/drafts/{draft_id}").json()
  assert draft["status"] == "approved"


def test_approve_draft_not_found(client):
  resp = client.post("/api/drafts/nonexistent-id/approve")
  assert resp.status_code == 404


def test_approve_duplicate_slug_returns_409(client, monkeypatch):
  draft_id = _insert_draft(client, monkeypatch)
  client.post(f"/api/drafts/{draft_id}/approve")
  # Approving the same draft again → slug already in posts
  resp = client.post(f"/api/drafts/{draft_id}/approve")
  assert resp.status_code == 409


# ─── Delete ───────────────────────────────────────────────────────────────────

def test_delete_draft(client, monkeypatch):
  draft_id = _insert_draft(client, monkeypatch)
  resp = client.delete(f"/api/drafts/{draft_id}")
  assert resp.status_code == 204
  assert client.get(f"/api/drafts/{draft_id}").status_code == 404


def test_delete_draft_not_found(client):
  resp = client.delete("/api/drafts/nonexistent-id")
  assert resp.status_code == 404


# ─── Admin HTML pages ─────────────────────────────────────────────────────────

def test_admin_drafts_page_returns_200(client):
  resp = client.get("/admin/drafts")
  assert resp.status_code == 200
  assert b"Draft Posts" in resp.content


def test_admin_draft_preview_returns_200(client, monkeypatch):
  draft_id = _insert_draft(client, monkeypatch)
  resp = client.get(f"/admin/drafts/{draft_id}")
  assert resp.status_code == 200
  assert b"Draft Preview" in resp.content


def test_admin_draft_preview_not_found(client):
  resp = client.get("/admin/drafts/nonexistent-id")
  assert resp.status_code == 404
