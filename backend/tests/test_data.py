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
