from unittest.mock import MagicMock, patch

import pytest


MOCK_POST_DATA = {
  "title": "Python Type Hints Explained",
  "summary": "A practical introduction to Python type hints and why they improve code quality.",
  "tags": ["python", "typing"],
  "content": "## Introduction\n\nType hints improve readability.\n\n## Basic Syntax\n\n```python\ndef greet(name: str) -> str:\n    return f'Hello, {name}'\n```\n\n## Conclusion\n\nHighly recommended for larger codebases.",
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


def test_generate_saves_to_drafts(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = admin_client.post(
      "/api/posts/generate",
      json={"description": "A practical intro to Python type hints and why they matter"},
    )

  assert resp.status_code == 201
  data = resp.json()
  assert data["title"] == "Python Type Hints Explained"
  assert data["slug"] == "python-type-hints-explained"
  assert data["summary"]
  assert isinstance(data["tags"], list)
  assert data["content"]
  assert data["date"]
  assert data["image"] and data["image"].startswith("https://")
  assert data["status"] == "pending"
  assert data["topic_id"] == "freeform"
  assert data["id"]

  # Saved to drafts, not posts
  drafts = admin_client.get("/api/drafts").json()
  assert any(d["slug"] == "python-type-hints-explained" for d in drafts)
  posts = admin_client.get("/api/posts").json()
  assert not any(p["slug"] == "python-type-hints-explained" for p in posts)


def test_generate_with_tag_hints(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = admin_client.post(
      "/api/posts/generate",
      json={
        "description": "A practical intro to Python type hints and why they matter",
        "tags": ["python", "mypy"],
      },
    )

  assert resp.status_code == 201
  generation_call = mock_client.messages.create.call_args_list[0]
  user_content = generation_call.kwargs["messages"][0]["content"]
  assert "python" in user_content
  assert "mypy" in user_content


def test_generate_missing_api_key(admin_client, monkeypatch):
  monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

  resp = admin_client.post(
    "/api/posts/generate",
    json={"description": "A practical intro to Python type hints and why they matter"},
  )

  assert resp.status_code == 503
  assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


def test_generate_claude_api_error(admin_client, monkeypatch):
  import anthropic as anthropic_lib

  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  mock_client = MagicMock()
  mock_client.messages.create.side_effect = anthropic_lib.APIStatusError(
    "rate limit", response=MagicMock(status_code=429), body={}
  )
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = admin_client.post(
      "/api/posts/generate",
      json={"description": "A practical intro to Python type hints and why they matter"},
    )

  assert resp.status_code == 502


def test_generate_no_tool_block_returns_422(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  text_block = MagicMock()
  text_block.type = "text"
  mock_message = MagicMock()
  mock_message.content = [text_block]
  mock_client = MagicMock()
  mock_client.messages.create.return_value = mock_message

  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = admin_client.post(
      "/api/posts/generate",
      json={"description": "A practical intro to Python type hints and why they matter"},
    )

  assert resp.status_code == 422


def test_generate_description_too_short(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  resp = admin_client.post("/api/posts/generate", json={"description": "short"})

  assert resp.status_code == 422


def test_generate_post_requires_admin(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  resp = client.post(
    "/api/posts/generate",
    json={"description": "A practical intro to Python type hints and why they matter"},
    follow_redirects=False,
  )
  assert resp.status_code == 303


# ─── Brief routes ─────────────────────────────────────────────────────────────

def test_list_briefs_returns_200(client):
  resp = client.get("/api/posts/briefs")
  assert resp.status_code == 200


def test_list_briefs_returns_list(client):
  resp = client.get("/api/posts/briefs")
  data = resp.json()
  assert isinstance(data, list)
  assert len(data) >= 1


def test_list_briefs_entry_has_required_fields(client):
  resp = client.get("/api/posts/briefs")
  brief = resp.json()[0]
  for field in ("id", "title_hint", "description", "audience", "tone", "tags", "outline"):
    assert field in brief, f"missing field: {field}"


def test_list_briefs_claude_code_entry_exists(client):
  resp = client.get("/api/posts/briefs")
  ids = [b["id"] for b in resp.json()]
  assert "claude-code-repo-best-practices" in ids


def test_generate_from_brief_saves_to_drafts(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = admin_client.post("/api/posts/generate/claude-code-repo-best-practices")

  assert resp.status_code == 201
  data = resp.json()
  assert data["slug"]
  assert data["title"]
  assert data["content"]
  assert data["status"] == "pending"
  assert data["topic_id"] == "claude-code-repo-best-practices"
  assert data["id"]

  # Saved to drafts, not posts
  drafts = admin_client.get("/api/drafts").json()
  assert any(d["id"] == data["id"] for d in drafts)
  posts = admin_client.get("/api/posts").json()
  assert not any(p["slug"] == data["slug"] for p in posts)


def test_generate_from_brief_builds_rich_prompt(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    admin_client.post("/api/posts/generate/claude-code-repo-best-practices")

  generation_call = mock_client.messages.create.call_args_list[0]
  user_content = generation_call.kwargs["messages"][0]["content"]
  assert "Title hint:" in user_content
  assert "Target audience:" in user_content
  assert "Tone:" in user_content
  assert "Required sections" in user_content


def test_generate_from_brief_not_found(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  resp = admin_client.post("/api/posts/generate/nonexistent-brief-id")

  assert resp.status_code == 404
  assert "nonexistent-brief-id" in resp.json()["detail"]


# ─── Existing-posts corpus (inline cross-post linking) ─────────────────────────

def test_generate_prompt_includes_existing_posts_corpus(admin_client, monkeypatch):
  """The seeded posts should be listed in the prompt so Claude can link to them inline."""
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    admin_client.post(
      "/api/posts/generate",
      json={"description": "A practical intro to Python type hints and why they matter"},
    )

  generation_call = mock_client.messages.create.call_args_list[0]
  user_content = generation_call.kwargs["messages"][0]["content"]
  assert "<existing_posts>" in user_content
  assert "htmx-is-enough" in user_content


def test_generate_prompt_omits_existing_posts_tag_when_no_posts(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  import db
  with db.get_conn() as conn:
    conn.execute("DELETE FROM posts")

  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    admin_client.post(
      "/api/posts/generate",
      json={"description": "A practical intro to Python type hints and why they matter"},
    )

  generation_call = mock_client.messages.create.call_args_list[0]
  user_content = generation_call.kwargs["messages"][0]["content"]
  assert "<existing_posts>" not in user_content
