# Tests for HTML page routes and frontend HTML structure.


# ── Home ──────────────────────────────────────────────────────────────────────

def test_home_returns_200(client):
    r = client.get("/")
    assert r.status_code == 200


def test_home_is_html(client):
    r = client.get("/")
    assert "text/html" in r.headers["content-type"]


def test_home_contains_sidebar(client):
    r = client.get("/")
    assert b'<aside' in r.content


def test_home_nav_links_have_htmx_attributes(client):
    r = client.get("/")
    assert b'hx-get="/"' in r.content
    assert b'hx-get="/projects"' in r.content
    assert b'hx-get="/blog"' in r.content


def test_home_main_content_div_present(client):
    r = client.get("/")
    assert b'id="main-content"' in r.content


# ── Projects ──────────────────────────────────────────────────────────────────

def test_projects_returns_200(client):
    r = client.get("/projects")
    assert r.status_code == 200


def test_projects_lists_project_names(client):
    r = client.get("/projects")
    assert b"zdenovo" in r.content


# ── Blog list ─────────────────────────────────────────────────────────────────

def test_blog_returns_200(client):
    r = client.get("/blog")
    assert r.status_code == 200


def test_blog_contains_posts_list(client):
    r = client.get("/blog")
    assert b'id="posts-list"' in r.content


def test_blog_shows_seed_post_titles(client):
    r = client.get("/blog")
    assert b"HTMX Is Enough" in r.content
    assert b"Type Hints" in r.content


def test_blog_tag_filter_returns_200(client):
    r = client.get("/blog?tag=python")
    assert r.status_code == 200


def test_blog_tag_filter_hides_other_posts(client):
    r = client.get("/blog?tag=python")
    html = r.content.decode()
    posts_section = html.split('id="posts-list"')[1].split("</main>")[0]
    assert "Type Hints" in posts_section
    assert "HTMX Is Enough" not in posts_section


def test_blog_tag_buttons_have_htmx_attrs(client):
    r = client.get("/blog")
    assert b"hx-get=" in r.content
    assert b"posts-list" in r.content


# ── Blog post ─────────────────────────────────────────────────────────────────

def test_post_returns_200(client):
    r = client.get("/blog/htmx-is-enough")
    assert r.status_code == 200


def test_post_contains_title(client):
    r = client.get("/blog/htmx-is-enough")
    assert b"HTMX Is Enough" in r.content


def test_post_contains_reading_time(client):
    r = client.get("/blog/htmx-is-enough")
    assert b"min read" in r.content


def test_post_missing_returns_404(client):
    r = client.get("/blog/no-such-post")
    assert r.status_code == 404


def test_post_404_page_contains_link_home(client):
    r = client.get("/blog/no-such-post")
    assert b'href="/"' in r.content


# ── Pagination ────────────────────────────────────────────────────────────────

def test_blog_page_param_accepted(client):
    r = client.get("/blog?page=1")
    assert r.status_code == 200


def test_blog_page_2_returns_200(client):
    r = client.get("/blog?page=2")
    assert r.status_code == 200


def test_blog_pagination_controls_shown_when_page_size_exceeded(client, monkeypatch):
    import data.posts
    monkeypatch.setattr(data.posts, "PAGE_SIZE", 2)
    r = client.get("/blog?page=1")
    assert b"page=2" in r.content


def test_blog_pagination_second_page_has_prev_link(client, monkeypatch):
    import data.posts
    monkeypatch.setattr(data.posts, "PAGE_SIZE", 2)
    r = client.get("/blog?page=2")
    assert b"page=1" in r.content


# ── Blog sidebar ─────────────────────────────────────────────────────────────

def test_blog_sidebar_shows_most_popular(client):
    r = client.get("/blog")
    assert b"Most Popular" in r.content


def test_blog_sidebar_has_popular_post_links(client):
    r = client.get("/blog")
    html = r.content.decode()
    sidebar = html.split("Most Popular")[1].split("</aside>")[0]
    assert "/blog/" in sidebar


def test_home_sidebar_shows_profile_card(client):
    r = client.get("/")
    assert b"Zdenovo" in r.content
    assert b"Software Engineer" in r.content
    assert b"Most Popular" not in r.content


# ── About ─────────────────────────────────────────────────────────────────────

def test_about_returns_200(client):
    r = client.get("/about")
    assert r.status_code == 200


def test_about_is_html(client):
    r = client.get("/about")
    assert "text/html" in r.headers["content-type"]


# ── Images ────────────────────────────────────────────────────────────────────

def test_blog_list_shows_post_images(client):
    r = client.get("/blog")
    assert b"post-thumb" in r.content


def test_post_detail_shows_hero_image(client):
    r = client.get("/blog/htmx-is-enough")
    assert b"post-hero" in r.content


# ── SEO: sitemap, robots.txt, RSS ────────────────────────────────────────────

def test_sitemap_returns_xml(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "xml" in r.headers["content-type"]


def test_sitemap_contains_posts(client):
    r = client.get("/sitemap.xml")
    assert b"/blog/htmx-is-enough" in r.content


def test_sitemap_contains_static_pages(client):
    r = client.get("/sitemap.xml")
    assert b"/blog</loc>" in r.content
    assert b"/about</loc>" in r.content


def test_robots_txt_returns_plain_text(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]


def test_robots_txt_disallows_admin(client):
    r = client.get("/robots.txt")
    assert b"Disallow: /admin/" in r.content


def test_robots_txt_references_sitemap(client):
    r = client.get("/robots.txt")
    assert b"Sitemap:" in r.content
    assert b"sitemap.xml" in r.content


def test_rss_feed_returns_xml(client):
    r = client.get("/feed.xml")
    assert r.status_code == 200
    assert "rss" in r.headers["content-type"]


def test_rss_feed_contains_posts(client):
    r = client.get("/feed.xml")
    assert b"<item>" in r.content
    assert b"HTMX Is Enough" in r.content


def test_rss_feed_has_channel_info(client):
    r = client.get("/feed.xml")
    assert b"<title>Zdenovo Blog</title>" in r.content
    assert b"<description>" in r.content


# ── SEO: meta tags ───────────────────────────────────────────────────────────

def test_home_has_meta_description(client):
    r = client.get("/")
    assert b'<meta name="description"' in r.content


def test_home_has_og_tags(client):
    r = client.get("/")
    assert b'og:title' in r.content
    assert b'og:description' in r.content


def test_post_has_article_og_type(client):
    r = client.get("/blog/htmx-is-enough")
    assert b'og:type" content="article' in r.content


def test_post_has_json_ld(client):
    r = client.get("/blog/htmx-is-enough")
    assert b"application/ld+json" in r.content
    assert b"BlogPosting" in r.content


def test_blog_has_canonical_url(client):
    r = client.get("/blog")
    assert b'rel="canonical"' in r.content


def test_home_has_rss_link(client):
    r = client.get("/")
    assert b'type="application/rss+xml"' in r.content


# ── Related posts ────────────────────────────────────────────────────────────

def test_related_posts_shown_when_tags_overlap(client):
    from data.posts import get_related_posts
    related = get_related_posts("why-i-switched-to-type-hints", ["python", "frontend"])
    assert len(related) > 0


# ── About page CTA ──────────────────────────────────────────────────────────

def test_about_has_consulting_cta(client):
    r = client.get("/about")
    assert b"Work with me" in r.content


# ── Sources section ──────────────────────────────────────────────────────────


def test_post_with_sources_shows_section(client):
    import json
    from db import get_conn
    sources = [{"title": "Python Docs", "url": "https://docs.python.org", "summary": "Official docs."}]
    with get_conn() as conn:
        conn.execute("UPDATE posts SET sources = ? WHERE slug = 'why-i-switched-to-type-hints'", (json.dumps(sources),))
    r = client.get("/blog/why-i-switched-to-type-hints")
    assert r.status_code == 200
    assert b"Sources &amp; Further Reading" in r.content or b"Sources & Further Reading" in r.content
    assert b"Python Docs" in r.content
    assert b"https://docs.python.org" in r.content


def test_post_without_sources_hides_section(client):
    r = client.get("/blog/why-i-switched-to-type-hints")
    assert r.status_code == 200
    assert b"Further Reading" not in r.content


# ── Public pages have no inline validation data ─────────────────────────────

def test_public_post_has_no_validation_data(client):
    r = client.get("/blog/htmx-is-enough")
    assert r.status_code == 200
    assert b"__codeValidation" not in r.content
