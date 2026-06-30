"""Tests for /api/deploys and the admin deploy history pages."""

_TOKEN = "test-secret-token"


def _post_deploy(client, monkeypatch, commit_hash="abc1234", status="success", duration_s=42):
    monkeypatch.setenv("DEPLOY_TOKEN", _TOKEN)
    return client.post(
        "/api/deploys",
        json={"commit_hash": commit_hash, "status": status, "duration_s": duration_s},
        headers={"X-Deploy-Token": _TOKEN},
    )


# ─── POST /api/deploys ────────────────────────────────────────────────────────

def test_post_deploy_with_valid_token_returns_201(client, monkeypatch):
    resp = _post_deploy(client, monkeypatch)
    assert resp.status_code == 201


def test_post_deploy_missing_token_returns_401(client, monkeypatch):
    monkeypatch.setenv("DEPLOY_TOKEN", _TOKEN)
    resp = client.post(
        "/api/deploys",
        json={"commit_hash": "abc1234", "status": "success"},
    )
    assert resp.status_code == 401


def test_post_deploy_wrong_token_returns_401(client, monkeypatch):
    monkeypatch.setenv("DEPLOY_TOKEN", _TOKEN)
    resp = client.post(
        "/api/deploys",
        json={"commit_hash": "abc1234", "status": "success"},
        headers={"X-Deploy-Token": "not-the-right-token"},
    )
    assert resp.status_code == 401


def test_post_deploy_creates_row_in_db(client, monkeypatch):
    resp = _post_deploy(client, monkeypatch, commit_hash="deadbee")
    assert resp.status_code == 201
    deploy_id = resp.json()["id"]

    import db
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM deploys WHERE id = ?", (deploy_id,)).fetchone()
    assert row is not None
    assert row["commit_hash"] == "deadbee"


def test_post_deploy_failed_status_is_stored(client, monkeypatch):
    resp = _post_deploy(client, monkeypatch, status="failed")
    assert resp.status_code == 201
    assert resp.json()["status"] == "failed"


# ─── GET /api/deploys ─────────────────────────────────────────────────────────

def test_get_deploys_requires_admin(client, monkeypatch):
    _post_deploy(client, monkeypatch)
    resp = client.get("/api/deploys", follow_redirects=False)
    assert resp.status_code == 303


def test_get_deploys_returns_list(admin_client, monkeypatch):
    _post_deploy(admin_client, monkeypatch)
    resp = admin_client.get("/api/deploys")
    assert resp.status_code == 200
    results = resp.json()
    assert isinstance(results, list)
    assert len(results) == 1


def test_get_deploys_newest_first(admin_client, monkeypatch):
    monkeypatch.setenv("DEPLOY_TOKEN", _TOKEN)
    admin_client.post(
        "/api/deploys",
        json={"commit_hash": "older111", "status": "success", "duration_s": 10},
        headers={"X-Deploy-Token": _TOKEN},
    )
    admin_client.post(
        "/api/deploys",
        json={"commit_hash": "newer222", "status": "success", "duration_s": 20},
        headers={"X-Deploy-Token": _TOKEN},
    )

    # Force distinct, ordered deployed_at timestamps directly in the DB.
    import db
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE deploys SET deployed_at = '2026-01-01T00:00:00+00:00' WHERE commit_hash = 'older111'"
        )
        conn.execute(
            "UPDATE deploys SET deployed_at = '2026-01-02T00:00:00+00:00' WHERE commit_hash = 'newer222'"
        )

    resp = admin_client.get("/api/deploys")
    assert resp.status_code == 200
    results = resp.json()
    assert results[0]["commit_hash"] == "newer222"
    assert results[1]["commit_hash"] == "older111"


# ─── Admin HTML pages ─────────────────────────────────────────────────────────

def test_admin_deploys_page_returns_200(admin_client, monkeypatch):
    _post_deploy(admin_client, monkeypatch)
    resp = admin_client.get("/admin/deploys")
    assert resp.status_code == 200


def test_admin_deploys_page_shows_commit_hash(admin_client, monkeypatch):
    _post_deploy(admin_client, monkeypatch, commit_hash="cafef00d")
    resp = admin_client.get("/admin/deploys")
    assert b"cafef00d" in resp.content


def test_admin_hub_shows_last_deploy_commit(admin_client, monkeypatch):
    _post_deploy(admin_client, monkeypatch, commit_hash="hub12345")
    resp = admin_client.get("/admin")
    assert resp.status_code == 200
    assert b"hub12345" in resp.content
