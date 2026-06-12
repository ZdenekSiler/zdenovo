import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a temp file and seed it before each test."""
    import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield tmp_path / "test.db"


@pytest.fixture()
def client(test_db):
    """TestClient wired to a fresh in-memory DB."""
    from main import app
    return TestClient(app, raise_server_exceptions=True)
