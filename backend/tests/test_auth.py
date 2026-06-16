# Tests for admin authentication: login, logout, session protection.

_PASSWORD = "test-password"  # matches conftest._TEST_ADMIN_PASSWORD


# ─── Login page ───────────────────────────────────────────────────────────────

def test_login_page_returns_200(client):
    r = client.get("/admin/login")
    assert r.status_code == 200


def test_login_page_contains_form(client):
    r = client.get("/admin/login")
    assert b'action="/admin/login"' in r.content
    assert b'name="password"' in r.content


def test_login_page_already_authenticated_redirects(admin_client):
    r = admin_client.get("/admin/login", follow_redirects=False)
    assert r.status_code == 303
    assert "/admin" in r.headers["location"]


# ─── POST /admin/login ────────────────────────────────────────────────────────

def test_login_correct_password_redirects(client):
    r = client.post(
        "/admin/login",
        data={"password": _PASSWORD, "next": "/admin/posts"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/posts"


def test_login_wrong_password_returns_401(client):
    r = client.post(
        "/admin/login",
        data={"password": "wrong", "next": "/admin/posts"},
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_login_wrong_password_shows_error(client):
    r = client.post(
        "/admin/login",
        data={"password": "wrong", "next": "/admin/posts"},
    )
    assert b"Wrong password" in r.content


def test_login_unsafe_next_redirects_to_admin_posts(client):
    """next must start with /admin to prevent open redirect."""
    r = client.post(
        "/admin/login",
        data={"password": _PASSWORD, "next": "https://evil.com"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/posts"


# ─── POST /admin/logout ───────────────────────────────────────────────────────

def test_logout_redirects_to_login(admin_client):
    r = admin_client.post("/admin/logout", follow_redirects=False)
    assert r.status_code == 303
    assert "/admin/login" in r.headers["location"]


def test_logout_clears_session(admin_client):
    admin_client.post("/admin/logout")
    # After logout, admin routes redirect to login
    r = admin_client.get("/admin/posts", follow_redirects=False)
    assert r.status_code == 303
    assert "/admin/login" in r.headers["location"]


# ─── Unauthenticated access ───────────────────────────────────────────────────

def test_unauthenticated_admin_posts_redirects(client):
    r = client.get("/admin/posts", follow_redirects=False)
    assert r.status_code == 303
    assert "/admin/login" in r.headers["location"]


def test_unauthenticated_admin_drafts_redirects(client):
    r = client.get("/admin/drafts", follow_redirects=False)
    assert r.status_code == 303
    assert "/admin/login" in r.headers["location"]


def test_unauthenticated_admin_comments_redirects(client):
    r = client.get("/admin/comments", follow_redirects=False)
    assert r.status_code == 303
    assert "/admin/login" in r.headers["location"]


def test_unauthenticated_admin_root_redirects(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303


def test_unauthenticated_redirect_preserves_next(client):
    r = client.get("/admin/posts", follow_redirects=False)
    assert "next=/admin/posts" in r.headers["location"]


# ─── Authenticated access ─────────────────────────────────────────────────────

def test_authenticated_admin_posts_returns_200(admin_client):
    r = admin_client.get("/admin/posts")
    assert r.status_code == 200


def test_authenticated_admin_drafts_returns_200(admin_client):
    r = admin_client.get("/admin/drafts")
    assert r.status_code == 200


def test_authenticated_admin_comments_returns_200(admin_client):
    r = admin_client.get("/admin/comments")
    assert r.status_code == 200


def test_admin_posts_page_shows_stats(admin_client):
    r = admin_client.get("/admin/posts")
    assert b"Published" in r.content
    assert b"Pending drafts" in r.content
    assert b"Comments" in r.content
