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


def test_post_markdown_renders_html_not_escaped(client):
    # Markdown content must render as real HTML tags, not escaped entities like &lt;p&gt;
    r = client.get("/blog/htmx-is-enough")
    assert b"&lt;p&gt;" not in r.content
    assert b'class="prose-custom"' in r.content


def test_post_sidebar_has_avatar(client):
    # post.html overrides the sidebar block — must still include the avatar image
    r = client.get("/blog/htmx-is-enough")
    assert b"codinghard.png" in r.content


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


# ── SEO: tag pages ───────────────────────────────────────────────────────────

def test_tag_page_has_unique_title(client):
    r = client.get("/blog?tag=python")
    assert b"Python posts" in r.content

def test_tag_page_has_unique_meta_description(client):
    r = client.get("/blog?tag=python")
    assert b"tagged with python" in r.content

def test_tag_page_has_unique_canonical_url(client):
    r = client.get("/blog?tag=python")
    assert b'canonical" href="https://zdenovo.com/blog?tag=python"' in r.content

def test_tag_page_og_title_reflects_tag(client):
    r = client.get("/blog?tag=python")
    assert b'og:title" content="Python posts' in r.content

def test_tag_page_og_url_matches_canonical(client):
    r = client.get("/blog?tag=python")
    assert b'og:url" content="https://zdenovo.com/blog?tag=python"' in r.content

def test_tag_page_blog_jsonld_reflects_tag(client):
    r = client.get("/blog?tag=python")
    assert b'"Python posts"' in r.content
    assert b'"https://zdenovo.com/blog?tag=python"' in r.content

def test_untagged_blog_page_title_unchanged(client):
    r = client.get("/blog")
    assert b"<title>Blog" in r.content

def test_untagged_blog_page_canonical_unchanged(client):
    r = client.get("/blog")
    assert b'canonical" href="https://zdenovo.com/blog"' in r.content

def test_sitemap_contains_tag_urls(client):
    r = client.get("/sitemap.xml")
    assert b"/blog?tag=" in r.content

def test_sitemap_tag_url_uses_weekly_changefreq(client):
    r = client.get("/sitemap.xml")
    xml = r.content.decode()
    tag_block = xml[xml.find("/blog?tag="):]
    assert "weekly" in tag_block[:200]


# ── SEO: CDN performance hints ───────────────────────────────────────────────

def test_base_html_has_dns_prefetch_for_cdnjs(client):
    r = client.get("/")
    assert b'dns-prefetch" href="https://cdnjs.cloudflare.com"' in r.content

def test_base_html_has_dns_prefetch_for_jsdelivr(client):
    r = client.get("/")
    assert b'dns-prefetch" href="https://cdn.jsdelivr.net"' in r.content

def test_tailwind_script_has_fetchpriority_high(client):
    r = client.get("/")
    assert b'cdn.tailwindcss.com" fetchpriority="high"' in r.content

def test_prism_css_precedes_tailwind_script_in_head(client):
    r = client.get("/")
    html = r.content.decode()
    prism_pos = html.find("prism-tomorrow.min.css")
    tailwind_pos = html.find('src="https://cdn.tailwindcss.com"')
    assert prism_pos < tailwind_pos, "Prism CSS should load before Tailwind script"

def test_inter_font_stylesheet_has_preload_hint(client):
    r = client.get("/")
    assert b'rel="preload" as="style" href="https://fonts.googleapis.com' in r.content


# ── Blog search HTML route ───────────────────────────────────────────────────

def test_blog_search_route_returns_html_fragment(client):
    r = client.get("/blog/search?q=HTMX")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert b"htmx-is-enough" in r.content

def test_blog_search_empty_query_returns_empty_fragment(client):
    r = client.get("/blog/search?q=")
    assert r.status_code == 200
    assert b"<a " not in r.content  # no result links

def test_blog_search_does_not_clash_with_slug_route(client):
    # /blog/search must not be handled by the /{slug} route
    r = client.get("/blog/search?q=test")
    assert r.status_code == 200

def test_sidebar_search_widget_present_on_blog_page(client):
    r = client.get("/blog")
    assert b'hx-get="/blog/search"' in r.content
    assert b'sidebar-search-results' in r.content

def test_sidebar_search_widget_present_on_post_page(client):
    r = client.get("/blog/htmx-is-enough")
    assert b'hx-get="/blog/search"' in r.content
    assert b'sidebar-search-results' in r.content

def test_above_list_search_bar_targets_blog_search(client):
    r = client.get("/blog")
    assert b'hx-get="/blog/search"' in r.content
    assert b'hx-get="/api/posts/search"' not in r.content


# ── Public pages have no inline validation data ─────────────────────────────

def test_public_post_has_no_validation_data(client):
    r = client.get("/blog/htmx-is-enough")
    assert r.status_code == 200
    assert b"__codeValidation" not in r.content


# ── AI badge hidden from public ──────────────────────────────────────────────

def test_public_post_hides_ai_badge_on_generated_comments(client):
    # Insert a published AI-generated comment directly — it should appear in the
    # public comments section but WITHOUT the "AI" badge label.
    import uuid
    from db import get_conn
    cid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO comments (id, post_slug, author, body, status, is_generated, created_at)"
            " VALUES (?, 'htmx-is-enough', 'Bot', 'AI comment', 'published', 1, datetime('now'))",
            (cid,),
        )
    r = client.get("/blog/htmx-is-enough")
    assert b"AI comment" in r.content  # comment body is visible
    assert b">AI<" not in r.content    # but the AI badge label is not


def test_htmx_comment_post_response_hides_ai_badge(client):
    # Posting a comment returns the comments_section.html partial via HTMX.
    # That partial also must not show the AI badge for generated comments.
    import uuid
    from db import get_conn
    cid = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO comments (id, post_slug, author, body, status, is_generated, created_at)"
            " VALUES (?, 'htmx-is-enough', 'Bot', 'AI via htmx', 'published', 1, datetime('now'))",
            (cid,),
        )
    r = client.post("/blog/htmx-is-enough/comments", data={"author": "Alice", "body": "Real comment"})
    assert b"AI via htmx" in r.content
    assert b">AI<" not in r.content


# ── Base template Cloudflare safety ─────────────────────────────────────────

def test_theme_init_script_has_cfasync_false(client):
    # The inline theme-init script must be marked data-cfasync="false" so
    # Cloudflare Rocket Loader cannot defer it — deferral breaks light mode.
    r = client.get("/")
    html = r.content.decode()
    # Find the script that sets the theme class on <html>
    assert 'data-cfasync="false"' in html
    # Specifically the theme-init script (localStorage.getItem) must have it
    idx = html.find("localStorage.getItem('theme')")
    assert idx != -1, "theme-init script not found"
    surrounding = html[max(0, idx - 200):idx]
    assert 'data-cfasync="false"' in surrounding


def test_css_has_cache_busting_version(client):
    # style.css must carry a ?v= query param so Cloudflare serves fresh CSS
    # after deploys that change light-mode or other styles.
    r = client.get("/")
    assert b"style.css?v=" in r.content
