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

def test_manual_trigger_generates_drafts(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = admin_client.post("/api/drafts/generate")
  assert resp.status_code == 201
  assert resp.json()["generated"] == 1


def test_generate_specific_topic(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = admin_client.post("/api/drafts/generate/solo-developer-ai-era")
  assert resp.status_code == 201
  data = resp.json()
  assert data["topic_id"] == "solo-developer-ai-era"
  assert data["status"] == "pending"


def test_generate_specific_topic_not_found(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  resp = admin_client.post("/api/drafts/generate/nonexistent-topic")
  assert resp.status_code == 404


def test_manual_trigger_requires_admin(client):
  resp = client.post("/api/drafts/generate", follow_redirects=False)
  assert resp.status_code == 303


def test_generated_drafts_have_pending_status(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    admin_client.post("/api/drafts/generate")
  drafts = admin_client.get("/api/drafts").json()
  assert all(d["status"] == "pending" for d in drafts)


def test_generated_drafts_not_in_posts(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    admin_client.post("/api/drafts/generate")
  draft_slugs = {d["slug"] for d in admin_client.get("/api/drafts").json()}
  post_slugs = {p["slug"] for p in admin_client.get("/api/posts").json()}
  assert draft_slugs.isdisjoint(post_slugs)


# ─── List & get ───────────────────────────────────────────────────────────────

def test_list_drafts_empty(client):
  resp = client.get("/api/drafts")
  assert resp.status_code == 200
  assert resp.json() == []


def test_list_drafts_returns_all(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  resp = admin_client.get("/api/drafts")
  assert resp.status_code == 200
  assert len(resp.json()) == 1


def test_get_draft_by_id(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  resp = admin_client.get(f"/api/drafts/{draft_id}")
  assert resp.status_code == 200
  data = resp.json()
  assert data["id"] == draft_id
  assert data["title"]
  assert data["reading_time"] >= 1


def test_get_draft_not_found(client):
  resp = client.get("/api/drafts/nonexistent-id")
  assert resp.status_code == 404


# ─── Approve ──────────────────────────────────────────────────────────────────

def test_approve_draft_publishes_to_posts(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  draft = admin_client.get(f"/api/drafts/{draft_id}").json()

  resp = admin_client.post(f"/api/drafts/{draft_id}/approve")
  assert resp.status_code == 201
  published = resp.json()
  assert published["slug"] == draft["slug"]
  assert published["title"] == draft["title"]

  # Post now appears in live blog
  post_slugs = [p["slug"] for p in admin_client.get("/api/posts").json()]
  assert draft["slug"] in post_slugs


def test_approve_draft_sets_status_approved(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  admin_client.post(f"/api/drafts/{draft_id}/approve")
  draft = admin_client.get(f"/api/drafts/{draft_id}").json()
  assert draft["status"] == "approved"


def test_approve_draft_not_found(admin_client):
  resp = admin_client.post("/api/drafts/nonexistent-id/approve")
  assert resp.status_code == 404


def test_approve_duplicate_slug_returns_409(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  admin_client.post(f"/api/drafts/{draft_id}/approve")
  # Approving the same draft again → slug already in posts
  resp = admin_client.post(f"/api/drafts/{draft_id}/approve")
  assert resp.status_code == 409


# ─── Patch ────────────────────────────────────────────────────────────────────

def test_patch_draft_title(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  resp = admin_client.patch(f"/api/drafts/{draft_id}", json={"title": "Updated Title"})
  assert resp.status_code == 200
  assert resp.json()["title"] == "Updated Title"


def test_patch_draft_content_updates_reading_time(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  long_content = "word " * 500
  resp = admin_client.patch(f"/api/drafts/{draft_id}", json={"content": long_content})
  assert resp.status_code == 200
  assert resp.json()["reading_time"] >= 2


def test_patch_draft_partial_keeps_other_fields(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  original = admin_client.get(f"/api/drafts/{draft_id}").json()
  resp = admin_client.patch(f"/api/drafts/{draft_id}", json={"title": "New Title"})
  assert resp.status_code == 200
  data = resp.json()
  assert data["summary"] == original["summary"]
  assert data["content"] == original["content"]
  assert data["tags"] == original["tags"]


def test_patch_draft_not_found(admin_client):
  resp = admin_client.patch("/api/drafts/nonexistent-id", json={"title": "X"})
  assert resp.status_code == 404


# ─── Delete ───────────────────────────────────────────────────────────────────

def test_delete_draft(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  resp = admin_client.delete(f"/api/drafts/{draft_id}")
  assert resp.status_code == 204
  assert admin_client.get(f"/api/drafts/{draft_id}").status_code == 404


def test_delete_draft_not_found(admin_client):
  resp = admin_client.delete("/api/drafts/nonexistent-id")
  assert resp.status_code == 404


# ─── Admin HTML pages ─────────────────────────────────────────────────────────

def test_admin_drafts_page_returns_200(admin_client):
  resp = admin_client.get("/admin/drafts")
  assert resp.status_code == 200
  assert b"Draft Posts" in resp.content


def test_admin_draft_preview_returns_200(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  resp = admin_client.get(f"/admin/drafts/{draft_id}")
  assert resp.status_code == 200
  assert b"Draft Preview" in resp.content


def test_admin_draft_preview_not_found(admin_client):
  resp = admin_client.get("/admin/drafts/nonexistent-id")
  assert resp.status_code == 404


# ─── Code validation ────────────────────────────────────────────────────────

def test_validate_draft_code_returns_summary(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  resp = admin_client.post(f"/api/drafts/{draft_id}/validate")
  assert resp.status_code == 200
  data = resp.json()
  assert "total" in data
  assert "results" in data
  assert data["total"] >= 0


def test_validate_draft_not_found(admin_client):
  resp = admin_client.post("/api/drafts/nonexistent-id/validate")
  assert resp.status_code == 404


def test_validate_draft_finds_code_blocks(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  admin_client.patch(f"/api/drafts/{draft_id}", json={
    "content": "# Post\n\n```python\nx = 1\n```\n\n```json\n{}\n```"
  })
  resp = admin_client.post(f"/api/drafts/{draft_id}/validate")
  data = resp.json()
  assert data["total"] == 2
  assert data["valid"] == 2


def test_draft_preview_includes_inline_validation(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  resp = admin_client.get(f"/admin/drafts/{draft_id}")
  assert resp.status_code == 200
  assert b"__codeValidation" in resp.content


def test_draft_preview_shows_validation_summary(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  admin_client.patch(f"/api/drafts/{draft_id}", json={
    "content": "# Post\n\n```python\nx = 1\n```\n\nSome text."
  })
  resp = admin_client.get(f"/admin/drafts/{draft_id}")
  assert resp.status_code == 200
  assert b"Code Validation" in resp.content
  assert b"1 block" in resp.content


# ─── Sources ─────────────────────────────────────────────────────────────────

def test_draft_has_sources_field(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  resp = admin_client.get(f"/api/drafts/{draft_id}")
  data = resp.json()
  assert "sources" in data
  assert isinstance(data["sources"], list)


def test_approved_draft_copies_sources(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  resp = admin_client.post(f"/api/drafts/{draft_id}/approve")
  assert resp.status_code == 201
  post = resp.json()
  assert "sources" in post
  assert isinstance(post["sources"], list)


# ─── Trending topic discovery ─────────────────────────────────────────────────

import json as _json

from pydantic import ValidationError


def _tool_message(name, input_data):
  block = MagicMock()
  block.type = "tool_use"
  block.name = name
  block.input = input_data
  msg = MagicMock()
  msg.content = [block]
  return msg


def _make_discovery_mock_client(topics: list[dict] = None):
  default_topics = [{
    "title_hint": "Something New in Python 3.14",
    "description": "A look at a recent Python release note.",
    "audience": "Python developers",
    "tone": "sarcastic, informational",
    "tags": ["python"],
    "outline": ["What changed", "Why it matters"],
    "source_note": "Found via web search of python.org changelog.",
  }]
  mock_client = MagicMock()
  mock_client.messages.create.return_value = _tool_message("suggest_topics", {"topics": topics if topics is not None else default_topics})
  return mock_client


@pytest.fixture()
def small_topics_file(tmp_path, monkeypatch):
  """A pool of 2 topics (below POOL_MIN_THRESHOLD=5) to exercise automatic discovery."""
  topics = [
    {"id": "small-one", "title_hint": "Small Topic One", "description": "d", "audience": "a", "tone": "t", "tags": ["python"], "outline": []},
    {"id": "small-two", "title_hint": "Small Topic Two", "description": "d", "audience": "a", "tone": "t", "tags": ["docker"], "outline": []},
  ]
  path = tmp_path / "daily_topics.json"
  path.write_text(_json.dumps(topics))
  from routers import topics_api
  monkeypatch.setattr(topics_api, "DAILY_TOPICS_PATH", path)
  return path


@pytest.fixture()
def healthy_topics_file(tmp_path, monkeypatch):
  """A pool of 6 topics (>= POOL_MIN_THRESHOLD=5) — discovery must NOT fire."""
  topics = [
    {"id": f"healthy-{i}", "title_hint": f"Healthy Topic {i}", "description": "d", "audience": "a", "tone": "t", "tags": ["python"], "outline": []}
    for i in range(6)
  ]
  path = tmp_path / "daily_topics.json"
  path.write_text(_json.dumps(topics))
  from routers import topics_api
  monkeypatch.setattr(topics_api, "DAILY_TOPICS_PATH", path)
  return path


@pytest.fixture()
def empty_topics_file(tmp_path, monkeypatch):
  path = tmp_path / "daily_topics.json"
  path.write_text("[]")
  from routers import topics_api
  monkeypatch.setattr(topics_api, "DAILY_TOPICS_PATH", path)
  return path


def test_discover_trending_topics_returns_candidates(client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.generate_api import blog_generator
  mock_client = _make_discovery_mock_client()
  category = {"id": "python-backend", "label": "Python & Backend Engineering", "tags": ["python"], "search_hint": "hint"}
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    candidates = blog_generator.discover_trending_topics(category, existing_topics=[])
  assert len(candidates) == 1
  assert candidates[0]["title_hint"] == "Something New in Python 3.14"


def test_discover_trending_topics_fails_soft_on_api_error(client, monkeypatch):
  import anthropic as anthropic_lib
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.generate_api import blog_generator
  mock_client = MagicMock()
  mock_client.messages.create.side_effect = anthropic_lib.APIStatusError(
    "rate limit", response=MagicMock(status_code=429), body={}
  )
  category = {"id": "python-backend", "label": "Python & Backend Engineering", "tags": ["python"], "search_hint": "hint"}
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    candidates = blog_generator.discover_trending_topics(category, existing_topics=[])
  assert candidates == []


def test_pick_understocked_category_favors_least_represented():
  from routers.generate_api import PostBrief
  from routers.drafts_api import _pick_understocked_category
  topics = [
    PostBrief(id="t1", title_hint="AI Agents Rule", description="d", audience="a", tone="t", tags=["ai", "agents"], outline=[]),
    PostBrief(id="t2", title_hint="More AI Stuff", description="d", audience="a", tone="t", tags=["ai", "llm"], outline=[]),
  ]
  category = _pick_understocked_category(topics)
  assert category["id"] == "python-backend"


def test_is_duplicate_candidate_detects_title_overlap():
  from routers.drafts_api import _is_duplicate_candidate
  existing = [{"title_hint": "FastAPI Dependency Injection Guide", "tags": ["fastapi"]}]
  candidate = {"title_hint": "FastAPI Dependency Injection Explained", "tags": ["python"]}
  assert _is_duplicate_candidate(candidate, existing) is True


def test_is_duplicate_candidate_detects_tag_overlap():
  from routers.drafts_api import _is_duplicate_candidate
  existing = [{"title_hint": "Something Else Entirely", "tags": ["docker", "deployment", "production"]}]
  candidate = {"title_hint": "A Totally Different Headline", "tags": ["docker", "deployment", "production"]}
  assert _is_duplicate_candidate(candidate, existing) is True


def test_is_duplicate_candidate_allows_distinct_topic():
  from routers.drafts_api import _is_duplicate_candidate
  existing = [{"title_hint": "Docker Compose for Local Dev", "tags": ["docker"]}]
  candidate = {"title_hint": "Why Solo Consultants Should Automate Invoicing", "tags": ["consulting"]}
  assert _is_duplicate_candidate(candidate, existing) is False


def test_validate_candidate_accepts_valid_dict_and_strips_source_note():
  from routers.drafts_api import _validate_candidate
  raw = {
    "title_hint": "Valid Topic",
    "description": "A valid description.",
    "audience": "Developers",
    "tone": "dry",
    "tags": ["python"],
    "outline": ["Point one"],
    "source_note": "Found via search.",
  }
  result = _validate_candidate(raw)
  assert result is not None
  assert result["title_hint"] == "Valid Topic"
  assert "source_note" not in result


def test_validate_candidate_rejects_oversized_title():
  from routers.drafts_api import _validate_candidate
  raw = {
    "title_hint": "x" * 400,
    "description": "d",
    "audience": "a",
    "tone": "t",
    "tags": [],
    "outline": [],
  }
  assert _validate_candidate(raw) is None


def test_discover_and_replenish_topics_adds_valid_candidates(client, small_topics_file, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_discovery_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    from routers.drafts_api import discover_and_replenish_topics
    result = discover_and_replenish_topics()
  assert result["added"] == 1
  topics = _json.loads(small_topics_file.read_text())
  assert len(topics) == 3
  assert "source_note" not in topics[-1]


def test_discover_and_replenish_topics_filters_duplicate(client, small_topics_file, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_discovery_mock_client(topics=[{
    "title_hint": "Small Topic One", "description": "d", "audience": "a", "tone": "t",
    "tags": ["python"], "outline": [], "source_note": "dup",
  }])
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    from routers.drafts_api import discover_and_replenish_topics
    result = discover_and_replenish_topics()
  assert result["added"] == 0
  assert result["filtered"] == 1


def test_discover_and_replenish_topics_reports_zero_on_api_failure(client, small_topics_file, monkeypatch):
  import anthropic as anthropic_lib
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = MagicMock()
  mock_client.messages.create.side_effect = anthropic_lib.APIStatusError(
    "rate limit", response=MagicMock(status_code=429), body={}
  )
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    from routers.drafts_api import discover_and_replenish_topics
    result = discover_and_replenish_topics()
  assert result["candidates"] == 0
  assert result["filtered"] == 0
  assert result["added"] == 0


def test_generate_daily_drafts_triggers_discovery_when_pool_low(admin_client, small_topics_file, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  messages = [
    _tool_message("suggest_topics", {"topics": [{
      "title_hint": "A Brand New Discovered Topic",
      "description": "d", "audience": "a", "tone": "t",
      "tags": ["ai"], "outline": [], "source_note": "found via search",
    }]}),
    _tool_message("write_post", MOCK_POST_DATA),
    _tool_message("review_post", {"score": 8, "issues": [], "strengths": ["solid"]}),
    _tool_message("suggest_sources", {"sources": []}),
  ]
  mock_client = MagicMock()
  mock_client.messages.create.side_effect = messages
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = admin_client.post("/api/drafts/generate")
  assert resp.status_code == 201
  assert resp.json()["generated"] == 1
  topics = _json.loads(small_topics_file.read_text())
  assert len(topics) == 3


def test_generate_daily_drafts_skips_discovery_when_pool_healthy(admin_client, healthy_topics_file, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  messages = [
    _tool_message("write_post", MOCK_POST_DATA),
    _tool_message("review_post", {"score": 8, "issues": [], "strengths": ["solid"]}),
    _tool_message("suggest_sources", {"sources": []}),
  ]
  mock_client = MagicMock()
  mock_client.messages.create.side_effect = messages
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = admin_client.post("/api/drafts/generate")
  assert resp.status_code == 201
  assert resp.json()["generated"] == 1
  assert mock_client.messages.create.call_count == 3


def test_generate_daily_drafts_degrades_gracefully_when_pool_exhausted(admin_client, empty_topics_file, monkeypatch):
  import anthropic as anthropic_lib
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = MagicMock()
  mock_client.messages.create.side_effect = anthropic_lib.APIStatusError(
    "rate limit", response=MagicMock(status_code=429), body={}
  )
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = admin_client.post("/api/drafts/generate")
  assert resp.status_code == 201
  assert resp.json()["generated"] == 0
