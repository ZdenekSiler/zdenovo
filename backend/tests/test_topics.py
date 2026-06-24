import json
from unittest.mock import MagicMock, patch

import pytest

_PASSWORD = "test-password"

SAMPLE_TOPICS = [
    {
        "id": "test-topic-one",
        "title_hint": "Test Topic One",
        "description": "A test topic for unit tests.",
        "audience": "Developers",
        "tone": "practical",
        "tags": ["python", "testing"],
        "outline": ["Introduction", "Main points", "Conclusion"],
    },
    {
        "id": "test-topic-two",
        "title_hint": "Test Topic Two",
        "description": "Another test topic.",
        "audience": "Backend engineers",
        "tone": "technical",
        "tags": ["docker"],
        "outline": ["Setup", "Build"],
    },
]


@pytest.fixture()
def topics_file(tmp_path, monkeypatch):
    """Write sample topics to a temp file and patch DAILY_TOPICS_PATH everywhere."""
    path = tmp_path / "daily_topics.json"
    path.write_text(json.dumps(SAMPLE_TOPICS, indent=2))
    from routers import drafts_api, topics_api
    monkeypatch.setattr(topics_api, "DAILY_TOPICS_PATH", path)
    monkeypatch.setattr(drafts_api, "DAILY_TOPICS_PATH", path)
    return path


@pytest.fixture()
def admin(client):
    client.post("/admin/login", data={"password": _PASSWORD, "next": "/admin"}, follow_redirects=False)
    return client


# ─── List page ────────────────────────────────────────────────────────────────

def test_topics_list_returns_200(admin, topics_file):
    r = admin.get("/admin/topics")
    assert r.status_code == 200


def test_topics_list_shows_topics(admin, topics_file):
    r = admin.get("/admin/topics")
    assert b"Test Topic One" in r.content
    assert b"Test Topic Two" in r.content


def test_topics_list_shows_tags(admin, topics_file):
    r = admin.get("/admin/topics")
    assert b"python" in r.content
    assert b"docker" in r.content


def test_topics_list_shows_topic_count(admin, topics_file):
    r = admin.get("/admin/topics")
    assert b"2 of 2 available" in r.content


def test_topics_list_unauthenticated_redirects(client, topics_file):
    r = client.get("/admin/topics", follow_redirects=False)
    assert r.status_code == 303
    assert "/admin/login" in r.headers["location"]


# ─── New topic form ───────────────────────────────────────────────────────────

def test_new_topic_form_returns_200(admin, topics_file):
    r = admin.get("/admin/topics/new")
    assert r.status_code == 200
    assert b"New Topic" in r.content


# ─── Edit topic form ─────────────────────────────────────────────────────────

def test_edit_topic_form_returns_200(admin, topics_file):
    r = admin.get("/admin/topics/test-topic-one/edit")
    assert r.status_code == 200
    assert b"Edit Topic" in r.content
    assert b"Test Topic One" in r.content


def test_edit_topic_not_found_returns_404(admin, topics_file):
    r = admin.get("/admin/topics/nonexistent/edit")
    assert r.status_code == 404


# ─── Create topic ─────────────────────────────────────────────────────────────

def test_create_topic_redirects(admin, topics_file):
    r = admin.post("/admin/topics", data={
        "title_hint": "Brand New Topic",
        "description": "A fresh topic.",
        "audience": "Everyone",
        "tone": "casual",
        "tags": "python, web",
        "outline": "Step one\nStep two",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/topics"


def test_create_topic_adds_to_file(admin, topics_file):
    admin.post("/admin/topics", data={
        "title_hint": "Brand New Topic",
        "description": "A fresh topic.",
        "audience": "Everyone",
        "tone": "casual",
        "tags": "python, web",
        "outline": "Step one\nStep two",
    }, follow_redirects=False)
    topics = json.loads(topics_file.read_text())
    assert len(topics) == 3
    new = topics[-1]
    assert new["id"] == "brand-new-topic"
    assert new["title_hint"] == "Brand New Topic"
    assert new["tags"] == ["python", "web"]
    assert new["outline"] == ["Step one", "Step two"]


def test_create_topic_deduplicates_id(admin, topics_file):
    admin.post("/admin/topics", data={
        "title_hint": "Test Topic One",
        "description": "Duplicate title.",
        "audience": "Devs",
        "tone": "dry",
        "tags": "",
        "outline": "",
    }, follow_redirects=False)
    topics = json.loads(topics_file.read_text())
    ids = [t["id"] for t in topics]
    assert ids.count("test-topic-one") == 1
    assert any(i.startswith("test-topic-one-") for i in ids)


# ─── Update topic ─────────────────────────────────────────────────────────────

def test_update_topic_redirects(admin, topics_file):
    r = admin.post("/admin/topics/test-topic-one", data={
        "title_hint": "Updated Title",
        "description": "Updated desc.",
        "audience": "Updated audience",
        "tone": "updated tone",
        "tags": "new-tag",
        "outline": "New outline item",
    }, follow_redirects=False)
    assert r.status_code == 303


def test_update_topic_modifies_file(admin, topics_file):
    admin.post("/admin/topics/test-topic-one", data={
        "title_hint": "Updated Title",
        "description": "Updated desc.",
        "audience": "Updated audience",
        "tone": "updated tone",
        "tags": "new-tag",
        "outline": "New outline item",
    }, follow_redirects=False)
    topics = json.loads(topics_file.read_text())
    t = next(t for t in topics if t["id"] == "test-topic-one")
    assert t["title_hint"] == "Updated Title"
    assert t["tags"] == ["new-tag"]
    assert t["outline"] == ["New outline item"]


def test_update_topic_not_found_returns_404(admin, topics_file):
    r = admin.post("/admin/topics/nonexistent", data={
        "title_hint": "X", "description": "X", "audience": "X",
        "tone": "X", "tags": "", "outline": "",
    })
    assert r.status_code == 404


# ─── Delete topic ─────────────────────────────────────────────────────────────

def test_delete_topic_redirects(admin, topics_file):
    r = admin.post("/admin/topics/test-topic-one/delete", follow_redirects=False)
    assert r.status_code == 303


def test_delete_topic_removes_from_file(admin, topics_file):
    admin.post("/admin/topics/test-topic-one/delete", follow_redirects=False)
    topics = json.loads(topics_file.read_text())
    assert len(topics) == 1
    assert topics[0]["id"] == "test-topic-two"


def test_delete_nonexistent_topic_is_safe(admin, topics_file):
    r = admin.post("/admin/topics/nonexistent/delete", follow_redirects=False)
    assert r.status_code == 303
    topics = json.loads(topics_file.read_text())
    assert len(topics) == 2


# ─── Generate from topic ─────────────────────────────────────────────────────

def _make_mock_client():
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = {
        "title": "Test Generated Post",
        "summary": "A test post.",
        "tags": ["python"],
        "content": "## Intro\n\nTest content.",
    }
    mock_message = MagicMock()
    mock_message.content = [tool_block]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    return mock_client


def test_admin_generate_topic_redirects_to_draft(admin, topics_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = _make_mock_client()
    with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
        r = admin.post("/admin/topics/test-topic-one/generate", follow_redirects=False)
    assert r.status_code == 303
    assert "/admin/drafts/" in r.headers["location"]


def test_admin_generate_topic_creates_draft(admin, topics_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = _make_mock_client()
    with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
        admin.post("/admin/topics/test-topic-one/generate", follow_redirects=False)
    drafts = admin.get("/api/drafts").json()
    assert len(drafts) == 1
    assert drafts[0]["topic_id"] == "test-topic-one"


def test_admin_topics_page_has_generate_button(admin, topics_file):
    r = admin.get("/admin/topics")
    assert r.status_code == 200
    assert b"Generate" in r.content
    assert b"/admin/topics/test-topic-one/generate" in r.content


# ─── Hub shows topics count ──────────────────────────────────────────────────

def test_admin_hub_shows_topics_count(admin, topics_file):
    r = admin.get("/admin")
    assert r.status_code == 200
    assert b"Topics" in r.content
    assert b"/admin/topics" in r.content


# ─── REST API: GET /api/topics ────────────────────────────────────────────────

def test_api_list_topics(client, topics_file):
    r = client.get("/api/topics")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["id"] == "test-topic-one"
    assert data[1]["id"] == "test-topic-two"


def test_api_get_topic(client, topics_file):
    r = client.get("/api/topics/test-topic-one")
    assert r.status_code == 200
    data = r.json()
    assert data["title_hint"] == "Test Topic One"
    assert data["tags"] == ["python", "testing"]


def test_api_get_topic_not_found(client, topics_file):
    r = client.get("/api/topics/nonexistent")
    assert r.status_code == 404


# ─── REST API: POST /api/topics ───────────────────────────────────────────────

def test_api_create_topic(client, topics_file):
    r = client.post("/api/topics", json={
        "title_hint": "New API Topic",
        "description": "Created via API.",
        "audience": "API users",
        "tone": "formal",
        "tags": ["api"],
        "outline": ["Intro", "Usage"],
    })
    assert r.status_code == 201
    data = r.json()
    assert data["id"] == "new-api-topic"
    assert data["title_hint"] == "New API Topic"
    topics = json.loads(topics_file.read_text())
    assert len(topics) == 3


def test_api_create_topic_deduplicates_id(client, topics_file):
    r = client.post("/api/topics", json={
        "title_hint": "Test Topic One",
        "description": "Dup.",
        "audience": "Devs",
        "tone": "dry",
    })
    assert r.status_code == 201
    assert r.json()["id"] != "test-topic-one"


def test_api_create_topic_validation(client, topics_file):
    r = client.post("/api/topics", json={"title_hint": ""})
    assert r.status_code == 422


# ─── REST API: PUT /api/topics/{id} ──────────────────────────────────────────

def test_api_update_topic(client, topics_file):
    r = client.put("/api/topics/test-topic-one", json={
        "title_hint": "Updated Via API",
        "description": "Updated.",
        "audience": "Updated audience",
        "tone": "updated",
        "tags": ["updated"],
        "outline": ["New outline"],
    })
    assert r.status_code == 200
    assert r.json()["title_hint"] == "Updated Via API"
    topics = json.loads(topics_file.read_text())
    t = next(t for t in topics if t["id"] == "test-topic-one")
    assert t["title_hint"] == "Updated Via API"


def test_api_update_topic_not_found(client, topics_file):
    r = client.put("/api/topics/nonexistent", json={
        "title_hint": "X", "description": "X", "audience": "X", "tone": "X",
    })
    assert r.status_code == 404


# ─── REST API: DELETE /api/topics/{id} ────────────────────────────────────────

def test_api_delete_topic(client, topics_file):
    r = client.delete("/api/topics/test-topic-one")
    assert r.status_code == 204
    topics = json.loads(topics_file.read_text())
    assert len(topics) == 1


def test_api_delete_topic_not_found(client, topics_file):
    r = client.delete("/api/topics/nonexistent")
    assert r.status_code == 404


# ─── Topic deduplication ─────────────────────────────────────────────────────

def test_api_topics_show_status_available(client, topics_file):
    r = client.get("/api/topics")
    for t in r.json():
        assert t["status"] == "available"
        assert t["draft_id"] is None


def test_api_topic_status_draft_pending(admin, topics_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = _make_mock_client()
    with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
        admin.post("/admin/topics/test-topic-one/generate", follow_redirects=False)
    r = admin.get("/api/topics")
    topics = {t["id"]: t for t in r.json()}
    assert topics["test-topic-one"]["status"] == "draft_pending"
    assert topics["test-topic-one"]["draft_id"] is not None
    assert topics["test-topic-two"]["status"] == "available"


def test_generate_blocks_duplicate_topic(admin, topics_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = _make_mock_client()
    with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
        admin.post("/admin/topics/test-topic-one/generate", follow_redirects=False)
        r = admin.post("/api/drafts/generate/test-topic-one")
    assert r.status_code == 409


def test_delete_draft_makes_topic_available_again(admin, topics_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = _make_mock_client()
    with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
        admin.post("/admin/topics/test-topic-one/generate", follow_redirects=False)
    drafts = admin.get("/api/drafts").json()
    draft_id = drafts[0]["id"]
    admin.delete(f"/api/drafts/{draft_id}")
    r = admin.get("/api/topics/test-topic-one")
    assert r.json()["status"] == "available"


def test_admin_topics_hides_generate_for_used_topic(admin, topics_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = _make_mock_client()
    with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
        admin.post("/admin/topics/test-topic-one/generate", follow_redirects=False)
    r = admin.get("/admin/topics")
    assert b"/admin/topics/test-topic-one/generate" not in r.content
    assert b"/admin/topics/test-topic-two/generate" in r.content


def test_admin_topics_shows_available_count(admin, topics_file, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = _make_mock_client()
    with patch("routers.generate_api.anthropic.Anthropic", return_value=mock_client):
        admin.post("/admin/topics/test-topic-one/generate", follow_redirects=False)
    r = admin.get("/admin/topics")
    assert b"1 of 2 available" in r.content
