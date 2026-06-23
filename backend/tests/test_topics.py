import json

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
    """Write sample topics to a temp file and patch main.DAILY_TOPICS_PATH."""
    path = tmp_path / "daily_topics.json"
    path.write_text(json.dumps(SAMPLE_TOPICS, indent=2))
    from routers import topics_api
    monkeypatch.setattr(topics_api, "DAILY_TOPICS_PATH", path)
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
    assert b"2 topics in rotation" in r.content


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
