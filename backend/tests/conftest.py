import pytest
from fastapi.testclient import TestClient

_TEST_ADMIN_PASSWORD = "test-password"


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a temp file and seed it before each test."""
    import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield tmp_path / "test.db"


@pytest.fixture(autouse=True)
def _reset_blog_generator():
    """Reset the BlogGenerator singleton between tests so mocked clients don't leak."""
    from routers.generate_api import blog_generator
    blog_generator._client = None
    yield
    blog_generator._client = None


@pytest.fixture()
def client(test_db, monkeypatch):
    """TestClient wired to a fresh in-memory DB."""
    monkeypatch.setenv("ADMIN_PASSWORD", _TEST_ADMIN_PASSWORD)
    from main import app
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def admin_client(client):
    """TestClient already authenticated as admin."""
    resp = client.post(
        "/admin/login",
        data={"password": _TEST_ADMIN_PASSWORD, "next": "/admin/posts"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"Login failed: {resp.status_code}"
    return client
