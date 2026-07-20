import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from db import get_conn


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


# ─── data/drafts.py ────────────────────────────────────────────────────────────

def test_get_drafts_no_filter_returns_all(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  admin_client.post(f"/api/drafts/{draft_id}/approve")
  from data.drafts import get_drafts
  assert len(get_drafts()) == 1


def test_get_drafts_filtered_by_status(admin_client, monkeypatch):
  draft_id = _insert_draft(admin_client, monkeypatch)
  admin_client.post(f"/api/drafts/{draft_id}/approve")
  from data.drafts import get_drafts
  assert get_drafts("pending") == []
  approved = get_drafts("approved")
  assert len(approved) == 1
  assert approved[0]["id"] == draft_id


def test_get_draft_status_counts(admin_client, monkeypatch):
  pending_id = _insert_draft(admin_client, monkeypatch)
  approved_id = _insert_draft(admin_client, monkeypatch)
  admin_client.post(f"/api/drafts/{approved_id}/approve")
  from data.drafts import get_draft_status_counts
  counts = get_draft_status_counts()
  assert counts["pending"] == 1
  assert counts["approved"] == 1
  assert counts["all"] == 2


def test_get_draft_status_counts_empty_db(client):
  from data.drafts import get_draft_status_counts
  counts = get_draft_status_counts()
  assert counts == {"pending": 0, "approved": 0, "all": 0}


# ─── /admin/drafts status filtering ───────────────────────────────────────────

def test_admin_drafts_page_defaults_to_pending_only(admin_client, monkeypatch):
  pending_id = _insert_draft(admin_client, monkeypatch)
  approved_id = _insert_draft(admin_client, monkeypatch)
  admin_client.post(f"/api/drafts/{approved_id}/approve")
  resp = admin_client.get("/admin/drafts")
  html = resp.content.decode()
  assert f'id="draft-{pending_id}"' in html
  assert f'id="draft-{approved_id}"' not in html
  assert 'href="/admin/drafts?status=pending" class="tag-btn active"' in html


def test_admin_drafts_page_status_all_shows_everything(admin_client, monkeypatch):
  pending_id = _insert_draft(admin_client, monkeypatch)
  approved_id = _insert_draft(admin_client, monkeypatch)
  admin_client.post(f"/api/drafts/{approved_id}/approve")
  resp = admin_client.get("/admin/drafts?status=all")
  html = resp.content.decode()
  assert f'id="draft-{pending_id}"' in html
  assert f'id="draft-{approved_id}"' in html


def test_admin_drafts_page_status_approved_filters(admin_client, monkeypatch):
  pending_id = _insert_draft(admin_client, monkeypatch)
  approved_id = _insert_draft(admin_client, monkeypatch)
  admin_client.post(f"/api/drafts/{approved_id}/approve")
  resp = admin_client.get("/admin/drafts?status=approved")
  html = resp.content.decode()
  assert f'id="draft-{approved_id}"' in html
  assert f'id="draft-{pending_id}"' not in html


# ─── /admin/drafts series grouping ────────────────────────────────────────────

def _seed_series_row(series_id: str, total: int) -> None:
  import json
  parts = [{"part_number": i, "title": f"Outline P{i}", "angle": "a", "key_points": [], "suggested_tags": []}
           for i in range(1, total + 1)]
  with get_conn() as conn:
    conn.execute("INSERT INTO series (id, title, description, created_at, outline) VALUES (?,?,?,?,?)",
                 (series_id, "My Series", "d", "2026-07-16", json.dumps({"total": total, "parts": parts})))


def _insert_series_draft(series_id: str, order: int, status: str = "pending") -> str:
  did = str(uuid.uuid4())
  now = datetime.now(timezone.utc).isoformat()
  with get_conn() as conn:
    conn.execute(
      "INSERT INTO drafts (id, slug, title, date, summary, tags, content, generated_at, topic_id,"
      " status, sources, series_id, series_order) VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?)",
      (did, f"{series_id}-part-{order}", f"Part {order} Title", "2026-07-16", "s", '["t"]', "body",
       now, f"series:{series_id}", status, series_id, order),
    )
  return did


def test_admin_drafts_groups_series_parts_in_order(admin_client):
  _seed_series_row("grp", 2)
  d1 = _insert_series_draft("grp", 1)
  d2 = _insert_series_draft("grp", 2)
  html = admin_client.get("/admin/drafts?status=pending").content.decode()
  assert "My Series" in html
  assert html.index(f"draft-{d1}") < html.index(f"draft-{d2}")


def test_admin_drafts_shows_missing_part_with_generate(admin_client):
  _seed_series_row("grp", 3)
  _insert_series_draft("grp", 1)
  _insert_series_draft("grp", 2)  # Part 3 has no draft/post -> missing
  html = admin_client.get("/admin/drafts?status=pending").content.decode()
  assert "2 of 3 parts" in html
  assert "missing" in html
  assert "/api/series/grp/parts/3/generate" in html


def test_admin_drafts_lists_standalone_separately(admin_client, monkeypatch):
  _seed_series_row("grp", 1)
  _insert_series_draft("grp", 1)
  standalone_id = _insert_draft(admin_client, monkeypatch)  # non-series draft
  html = admin_client.get("/admin/drafts?status=pending").content.decode()
  assert "Standalone drafts" in html
  assert f"draft-{standalone_id}" in html


def _mock_client_usage(payload: dict, model: str = "claude-sonnet-4-6", inp: int = 1000, out: int = 2000):
  tb = MagicMock(); tb.type = "tool_use"; tb.input = payload
  u = MagicMock(); u.input_tokens = inp; u.output_tokens = out
  u.cache_read_input_tokens = 0; u.cache_creation_input_tokens = 0; u.server_tool_use = None
  m = MagicMock(); m.content = [tb]; m.usage = u; m.model = model
  c = MagicMock(); c.messages.create.return_value = m
  return c


def test_regenerate_accumulates_gen_cost(admin_client, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  did = str(uuid.uuid4())
  now = datetime.now(timezone.utc).isoformat()
  with get_conn() as conn:  # seed a pending draft that already cost $0.05 to generate
    conn.execute(
      "INSERT INTO drafts (id, slug, title, date, summary, tags, content, generated_at, topic_id,"
      " status, sources, gen_cost_usd) VALUES (?,?,?,?,?,?,?,?,'freeform','pending','[]',?)",
      (did, "s", "T", "2026-07-16", "sum", '["t"]', "body", now, 0.05),
    )
  with patch("routers.generate_api.anthropic.Anthropic", return_value=_mock_client_usage(MOCK_POST_DATA)):
    r = admin_client.post(f"/api/drafts/{did}/regenerate", json={"remarks": "tighten the intro"})
  assert r.status_code == 200
  assert r.json()["gen_cost_usd"] > 0.05  # original 0.05 + this regeneration's cost


def test_admin_drafts_completeness_counts_published(admin_client):
  _seed_series_row("grp", 2)
  _insert_series_draft("grp", 2)  # Part 2 pending draft
  with get_conn() as conn:  # Part 1 already published
    conn.execute("INSERT INTO posts (slug, title, date, summary, tags, content, series_id, series_order)"
                 " VALUES ('grp-part-1', 'P1', '2026-07-16', 's', '[\"t\"]', 'body', 'grp', 1)")
  html = admin_client.get("/admin/drafts?status=pending").content.decode()
  assert "2 of 2 parts" in html
  assert "published" in html


def test_admin_drafts_page_shows_filter_pill_counts(admin_client, monkeypatch):
  pending_id = _insert_draft(admin_client, monkeypatch)
  approved_id = _insert_draft(admin_client, monkeypatch)
  admin_client.post(f"/api/drafts/{approved_id}/approve")
  resp = admin_client.get("/admin/drafts?status=all")
  assert b"Pending (1)" in resp.content
  assert b"Approved (1)" in resp.content
  assert b"All (2)" in resp.content


def test_admin_drafts_page_no_rejected_badge_rendered(admin_client, monkeypatch):
  _insert_draft(admin_client, monkeypatch)
  resp = admin_client.get("/admin/drafts?status=all")
  assert b"rejected" not in resp.content


def test_admin_drafts_page_empty_pending_shows_pending_message(admin_client):
  resp = admin_client.get("/admin/drafts")
  assert b"No pending drafts." in resp.content


def test_admin_drafts_page_empty_approved_shows_generic_message(admin_client, monkeypatch):
  _insert_draft(admin_client, monkeypatch)
  resp = admin_client.get("/admin/drafts?status=approved")
  assert b"No approved drafts." in resp.content


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


def _seed_topics(topics: list[dict]) -> None:
  """Replace the DB-seeded topic pool with a controlled set (insertion order preserved).

  Topics now live in the SQLite `topics` table (not daily_topics.json), so tests seed the
  table directly instead of monkeypatching a file path."""
  from db import get_conn
  with get_conn() as conn:
    conn.execute("DELETE FROM topics")
    conn.executemany(
      "INSERT INTO topics (id, title_hint, description, audience, tone, tags, outline, created_at)"
      " VALUES (?,?,?,?,?,?,?,?)",
      [
        (
          t["id"], t["title_hint"], t.get("description", "d"), t.get("audience", "a"),
          t.get("tone", "t"), _json.dumps(t.get("tags", [])), _json.dumps(t.get("outline", [])),
          "2026-01-01T00:00:00+00:00",
        )
        for t in topics
      ],
    )


def _insert_draft_row(title: str, tags: list[str], status: str = "pending") -> None:
  """Insert a minimal draft row directly, to exercise cross-source discovery dedup."""
  import uuid

  from db import get_conn
  with get_conn() as conn:
    conn.execute(
      "INSERT INTO drafts (id, slug, title, date, summary, tags, content, generated_at, topic_id, status)"
      " VALUES (?,?,?,?,?,?,?,?,?,?)",
      (
        str(uuid.uuid4()), title.lower().replace(" ", "-"), title, "2026-01-01",
        "summary", _json.dumps(tags), "content", "2026-01-01T00:00:00+00:00", "some-topic", status,
      ),
    )


def _insert_post_row(title: str, tags: list[str]) -> None:
  """Insert a minimal published post row directly, to exercise cross-source discovery dedup."""
  from db import get_conn
  with get_conn() as conn:
    conn.execute(
      "INSERT INTO posts (slug, title, date, summary, tags, content) VALUES (?,?,?,?,?,?)",
      (title.lower().replace(" ", "-"), title, "2026-01-01", "summary", _json.dumps(tags), "content"),
    )


@pytest.fixture()
def small_topics(test_db):
  """A pool of 2 topics (below POOL_MIN_THRESHOLD=5) to exercise automatic discovery."""
  topics = [
    {"id": "small-one", "title_hint": "Small Topic One", "tags": ["python"]},
    {"id": "small-two", "title_hint": "Small Topic Two", "tags": ["docker"]},
  ]
  _seed_topics(topics)
  return topics


@pytest.fixture()
def healthy_topics(test_db):
  """A pool of 6 topics (>= POOL_MIN_THRESHOLD=5) — discovery must NOT fire."""
  topics = [
    {"id": f"healthy-{i}", "title_hint": f"Healthy Topic {i}", "tags": ["python"]}
    for i in range(6)
  ]
  _seed_topics(topics)
  return topics


@pytest.fixture()
def empty_topics(test_db):
  """An empty topic pool."""
  _seed_topics([])
  return []


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


def test_discover_and_replenish_topics_adds_valid_candidates(client, small_topics, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_discovery_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    from routers.drafts_api import discover_and_replenish_topics
    result = discover_and_replenish_topics()
  assert result["added"] == 1
  from routers.topics_api import _load_topics
  topics = _load_topics()
  assert len(topics) == 3
  added = topics[-1]
  assert added["title_hint"] == "Something New in Python 3.14"
  assert "source_note" not in added


def test_discover_and_replenish_topics_filters_duplicate(client, small_topics, monkeypatch):
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


def test_discover_and_replenish_topics_reports_zero_on_api_failure(client, small_topics, monkeypatch):
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


def test_generate_daily_drafts_triggers_discovery_when_pool_low(admin_client, small_topics, monkeypatch):
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
  from routers.topics_api import _load_topics
  assert len(_load_topics()) == 3


def test_generate_daily_drafts_skips_discovery_when_pool_healthy(admin_client, healthy_topics, monkeypatch):
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


def test_generate_daily_drafts_degrades_gracefully_when_pool_exhausted(admin_client, empty_topics, monkeypatch):
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


# ─── Cross-source discovery dedup ─────────────────────────────────────────────
# discover_and_replenish_topics() dedups new candidates against the FULL covered
# history — current topics + generated drafts + published posts — not just the pool.


def _candidate(title_hint: str, tags: list[str]) -> dict:
  return {
    "title_hint": title_hint, "description": "d", "audience": "a", "tone": "t",
    "tags": tags, "outline": [], "source_note": "found via search",
  }


def test_discovery_dedups_against_existing_topic(client, test_db, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  _seed_topics([{"id": "redis-caching", "title_hint": "Mastering Redis Caching Strategies", "tags": ["redis"]}])
  # Candidate re-covers the existing topic (title word-overlap ratio 1.0).
  mock_client = _make_discovery_mock_client(topics=[
    _candidate("Mastering Redis Caching Strategies Deep Dive", ["nosql"]),
  ])
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    from routers.drafts_api import discover_and_replenish_topics
    result = discover_and_replenish_topics()
  assert result["added"] == 0
  assert result["filtered"] == 1


def test_discovery_dedups_against_existing_draft(client, test_db, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  # Pool topic is unrelated, so any filtering must come from the draft corpus.
  _seed_topics([{"id": "bash-basics", "title_hint": "Bash Scripting Basics", "tags": ["bash"]}])
  _insert_draft_row("GraphQL Federation at Scale", ["graphql"])
  mock_client = _make_discovery_mock_client(topics=[
    _candidate("GraphQL Federation at Scale Explained", ["api"]),
  ])
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    from routers.drafts_api import discover_and_replenish_topics
    result = discover_and_replenish_topics()
  assert result["added"] == 0
  assert result["filtered"] == 1


def test_discovery_dedups_against_published_post(client, test_db, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  # Pool topic is unrelated, so any filtering must come from the published-post corpus.
  _seed_topics([{"id": "bash-basics", "title_hint": "Bash Scripting Basics", "tags": ["bash"]}])
  _insert_post_row("Kubernetes Operators From Scratch", ["kubernetes"])
  mock_client = _make_discovery_mock_client(topics=[
    _candidate("Kubernetes Operators From Scratch Tutorial", ["ops"]),
  ])
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    from routers.drafts_api import discover_and_replenish_topics
    result = discover_and_replenish_topics()
  assert result["added"] == 0
  assert result["filtered"] == 1


def test_discovery_accepts_fresh_candidate_across_all_sources(client, test_db, monkeypatch):
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  _seed_topics([{"id": "redis-caching", "title_hint": "Mastering Redis Caching Strategies", "tags": ["redis"]}])
  _insert_draft_row("GraphQL Federation at Scale", ["graphql"])
  _insert_post_row("Kubernetes Operators From Scratch", ["kubernetes"])
  # Unrelated to every existing topic, draft, and post → survives dedup.
  mock_client = _make_discovery_mock_client(topics=[
    _candidate("Why Rust Ownership Beats Garbage Collection", ["rust"]),
  ])
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    from routers.drafts_api import discover_and_replenish_topics
    result = discover_and_replenish_topics()
  assert result["added"] == 1
  from routers.topics_api import _load_topics
  titles = [t["title_hint"] for t in _load_topics()]
  assert "Why Rust Ownership Beats Garbage Collection" in titles


# ─── Auto-generation toggle ───────────────────────────────────────────────────

def test_scheduled_generation_skips_when_auto_gen_off(test_db, monkeypatch):
  # Default (no settings row) is OFF: the scheduled wrapper must no-op and touch no Claude.
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  from routers.drafts_api import run_scheduled_generation
  with patch("routers.generate_api.anthropic.Anthropic") as mock_anthropic:
    result = run_scheduled_generation()
  assert result == {"generated": 0, "skipped": True}
  mock_anthropic.assert_not_called()
  with get_conn() as conn:
    assert conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0


def test_scheduled_generation_runs_when_auto_gen_on(test_db, monkeypatch):
  import db
  db.set_setting("auto_generation_enabled", "1")
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_mock_client()
  from routers.drafts_api import run_scheduled_generation
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    result = run_scheduled_generation()
  assert result["generated"] == 1
  with get_conn() as conn:
    assert conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 1


def test_manual_generate_works_while_auto_gen_off(admin_client, monkeypatch):
  # Requirement 4: the manual trigger must generate even when scheduled auto-gen is OFF.
  monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
  mock_client = _make_mock_client()
  with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
    resp = admin_client.post("/api/drafts/generate")
  assert resp.status_code == 201
  assert resp.json()["generated"] == 1


def test_toggle_auto_gen_requires_admin(client):
  resp = client.post("/admin/drafts/toggle-auto-gen", follow_redirects=False)
  assert resp.status_code == 303


def test_toggle_auto_gen_flips_state(admin_client):
  import db
  # Starts OFF → first toggle turns it ON.
  resp = admin_client.post("/admin/drafts/toggle-auto-gen")
  assert resp.status_code == 200
  assert "Auto: on" in resp.text
  assert db.get_setting("auto_generation_enabled") == "1"
  # Second toggle turns it back OFF.
  resp = admin_client.post("/admin/drafts/toggle-auto-gen")
  assert "Auto: off" in resp.text
  assert db.get_setting("auto_generation_enabled") == "0"


def test_admin_drafts_page_shows_auto_toggle_off_by_default(admin_client):
  resp = admin_client.get("/admin/drafts")
  assert resp.status_code == 200
  assert b"Auto: off" in resp.content
