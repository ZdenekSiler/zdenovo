from datetime import date


# ── posts ─────────────────────────────────────────────────────────────────────

def test_get_all_posts_returns_list(test_db):
    from data.posts import get_all_posts
    posts = get_all_posts()
    assert isinstance(posts, list)
    assert len(posts) == 3


def test_get_all_posts_sorted_newest_first(test_db):
    from data.posts import get_all_posts
    posts = get_all_posts()
    dates = [p["date"] for p in posts]
    assert dates == sorted(dates, reverse=True)


def test_get_all_posts_each_has_required_keys(test_db):
    from data.posts import get_all_posts
    required = {"slug", "title", "date", "summary", "tags", "content", "reading_time"}
    for post in get_all_posts():
        assert required <= post.keys()


def test_get_post_by_slug_returns_correct_post(test_db):
    from data.posts import get_post_by_slug
    post = get_post_by_slug("htmx-is-enough")
    assert post is not None
    assert post["slug"] == "htmx-is-enough"
    assert isinstance(post["tags"], list)


def test_get_post_by_slug_returns_none_for_missing(test_db):
    from data.posts import get_post_by_slug
    assert get_post_by_slug("does-not-exist") is None


# ── categories ────────────────────────────────────────────────────────────────

def test_get_all_posts_filters_by_category(test_db):
    from data.posts import get_all_posts
    from db import get_conn
    with get_conn() as conn:
        conn.execute("UPDATE posts SET category = 'python-backend' WHERE slug = 'htmx-is-enough'")
    posts = get_all_posts(category="python-backend")
    assert len(posts) == 1
    assert posts[0]["slug"] == "htmx-is-enough"


def test_get_all_posts_no_category_returns_all(test_db):
    from data.posts import get_all_posts
    assert len(get_all_posts()) == 3


def test_get_category_counts_omits_uncategorized_when_zero(test_db):
    from data.posts import get_category_counts
    from db import get_conn
    with get_conn() as conn:
        conn.execute(
            "UPDATE posts SET category = CASE slug "
            "WHEN 'why-i-switched-to-type-hints' THEN 'python-backend' "
            "WHEN 'designing-with-subagents' THEN 'ai-agents-llm' "
            "WHEN 'htmx-is-enough' THEN 'deploy-devops-war-stories' END"
        )
    counts = get_category_counts()
    assert {c["id"] for c in counts} == {
        "ai-agents-llm", "python-backend", "solo-consulting-startup", "deploy-devops-war-stories",
    }
    by_id = {c["id"]: c["count"] for c in counts}
    assert by_id["python-backend"] == 1
    assert by_id["ai-agents-llm"] == 1
    assert by_id["solo-consulting-startup"] == 0


def test_get_category_counts_includes_uncategorized_when_present(test_db):
    from data.posts import get_category_counts
    counts = get_category_counts()
    by_id = {c["id"]: c for c in counts}
    assert by_id[None]["label"] == "Uncategorized"
    assert by_id[None]["count"] == 3


# ── projects ──────────────────────────────────────────────────────────────────

def test_get_all_projects_returns_list():
    from data.projects import get_all_projects
    projects = get_all_projects()
    assert isinstance(projects, list)
    assert len(projects) > 0


def test_get_all_projects_featured_first():
    from data.projects import get_all_projects
    projects = get_all_projects()
    featured = [p["featured"] for p in projects]
    # All featured=True entries come before featured=False
    switched = False
    for f in featured:
        if not f:
            switched = True
        if switched and f:
            pytest.fail("Non-featured project appears before a featured one")


def test_get_all_projects_each_has_required_keys():
    from data.projects import get_all_projects
    required = {"name", "description", "tags", "url", "featured"}
    for project in get_all_projects():
        assert required <= project.keys()
