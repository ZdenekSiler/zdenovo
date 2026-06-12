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


def test_generate_returns_draft_post(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = client.post(
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
  assert data["image"] is None

  # Confirm post was NOT saved to DB
  list_resp = client.get("/api/posts")
  slugs = [p["slug"] for p in list_resp.json()]
  assert "python-type-hints-explained" not in slugs


def test_generate_with_tag_hints(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = client.post(
      "/api/posts/generate",
      json={
        "description": "A practical intro to Python type hints and why they matter",
        "tags": ["python", "mypy"],
      },
    )

  assert resp.status_code == 201
  # Verify the tag hints were forwarded to Claude
  call_kwargs = mock_client.messages.create.call_args
  user_content = call_kwargs.kwargs["messages"][0]["content"]
  assert "python" in user_content
  assert "mypy" in user_content


def test_generate_missing_api_key(client, monkeypatch):
  monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

  resp = client.post(
    "/api/posts/generate",
    json={"description": "A practical intro to Python type hints and why they matter"},
  )

  assert resp.status_code == 503
  assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


def test_generate_claude_api_error(client, monkeypatch):
  import anthropic as anthropic_lib

  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  mock_client = MagicMock()
  mock_client.messages.create.side_effect = anthropic_lib.APIStatusError(
    "rate limit", response=MagicMock(status_code=429), body={}
  )
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = client.post(
      "/api/posts/generate",
      json={"description": "A practical intro to Python type hints and why they matter"},
    )

  assert resp.status_code == 502


def test_generate_no_tool_block_returns_422(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  # Claude returns a text block instead of a tool_use block
  text_block = MagicMock()
  text_block.type = "text"
  mock_message = MagicMock()
  mock_message.content = [text_block]
  mock_client = MagicMock()
  mock_client.messages.create.return_value = mock_message

  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = client.post(
      "/api/posts/generate",
      json={"description": "A practical intro to Python type hints and why they matter"},
    )

  assert resp.status_code == 422


def test_generate_description_too_short(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  resp = client.post("/api/posts/generate", json={"description": "short"})

  assert resp.status_code == 422


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


def test_generate_from_brief_returns_draft_post(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = client.post("/api/posts/generate/claude-code-repo-best-practices")

  assert resp.status_code == 201
  data = resp.json()
  assert data["slug"]
  assert data["title"]
  assert data["content"]


def test_generate_from_brief_builds_rich_prompt(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    client.post("/api/posts/generate/claude-code-repo-best-practices")

  call_kwargs = mock_client.messages.create.call_args
  user_content = call_kwargs.kwargs["messages"][0]["content"]
  # Brief fields should all appear in the prompt
  assert "Title hint:" in user_content
  assert "Target audience:" in user_content
  assert "Tone:" in user_content
  assert "Required sections" in user_content


def test_generate_from_brief_not_found(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  resp = client.post("/api/posts/generate/nonexistent-brief-id")

  assert resp.status_code == 404
  assert "nonexistent-brief-id" in resp.json()["detail"]


def test_generate_from_brief_not_saved_to_db(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    client.post("/api/posts/generate/claude-code-repo-best-practices")

  list_resp = client.get("/api/posts")
  slugs = [p["slug"] for p in list_resp.json()]
  assert "python-type-hints-explained" not in slugs
