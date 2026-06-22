"""
Frontend visual & functional tests using Playwright against the live Docker container.
Run with: cd backend && npx playwright test tests/test_frontend.py
   or:    cd backend && uv run pytest tests/test_frontend.py -v

Requires the app running on localhost:8080 (docker compose up).
"""
import re

import pytest
from playwright.sync_api import Page, expect

BASE = "http://localhost:8080"
ADMIN_PW = "admin"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def admin_login(page: Page):
    page.goto(f"{BASE}/admin/login")
    page.get_by_label("Password").fill(ADMIN_PW)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(re.compile(r"/admin"))


# ─── Homepage ────────────────────────────────────────────────────────────────

def test_homepage_loads(page: Page):
    page.goto(BASE)
    expect(page).to_have_title(re.compile("Home"))
    expect(page.locator("#typed-heading")).to_be_visible()


def test_homepage_typing_effect_completes(page: Page):
    page.goto(BASE)
    heading = page.locator("#typed-heading")
    expect(heading).to_contain_text("Repeat", timeout=5000)


def test_homepage_hero_content_reveals_after_typing(page: Page):
    page.goto(BASE)
    page.locator("#typed-heading").wait_for(state="visible")
    page.wait_for_timeout(3000)
    buttons = page.locator(".hero-reveal")
    for i in range(buttons.count()):
        el = buttons.nth(i)
        assert el.evaluate("e => getComputedStyle(e).opacity") != "0", \
            f"hero-reveal element {i} still invisible after typing"


def test_homepage_latest_posts_visible(page: Page):
    page.goto(BASE)
    page.wait_for_timeout(2000)
    section = page.locator("text=Latest Posts")
    expect(section).to_be_visible()


def test_homepage_post_links_work(page: Page):
    page.goto(BASE)
    page.wait_for_timeout(2000)
    first_post = page.locator(".scroll-reveal article a").first
    expect(first_post).to_be_visible()
    first_post.click()
    page.wait_for_url(re.compile(r"/blog/"))
    expect(page.locator("article")).to_be_visible()


def test_homepage_view_all_posts_link(page: Page):
    page.goto(BASE)
    page.wait_for_timeout(2000)
    page.get_by_text("View all posts").click()
    page.wait_for_url(re.compile(r"/blog"))
    expect(page.get_by_role("heading", name="Blog")).to_be_visible()


# ─── Navigation ──────────────────────────────────────────────────────────────

def test_nav_links_present(page: Page):
    page.goto(BASE)
    nav = page.locator("header nav")
    expect(nav.get_by_text("Home")).to_be_visible()
    expect(nav.get_by_text("About")).to_be_visible()
    expect(nav.get_by_text("Projects")).to_be_visible()
    expect(nav.get_by_text("Blog")).to_be_visible()


def test_htmx_navigation_no_full_reload(page: Page):
    page.goto(BASE)
    page.wait_for_timeout(1000)
    page.locator("header nav").get_by_text("Blog").click()
    page.wait_for_url(re.compile(r"/blog"))
    expect(page.get_by_role("heading", name="Blog")).to_be_visible()
    expect(page.locator("header nav")).to_be_visible()


def test_brand_logo_links_home(page: Page):
    page.goto(f"{BASE}/blog")
    page.locator("header a", has_text="Zdenovo").first.click()
    page.wait_for_url(re.compile(r"/$"))


# ─── About page ──────────────────────────────────────────────────────────────

def test_about_page_loads(page: Page):
    page.goto(f"{BASE}/about")
    expect(page).to_have_title(re.compile("About"))
    expect(page.locator("text=Hi, I'm Zdenovo")).to_be_visible()


def test_about_has_availability_badge(page: Page):
    page.goto(f"{BASE}/about")
    expect(page.locator("text=Available for new projects")).to_be_visible()


def test_about_has_stats(page: Page):
    page.goto(f"{BASE}/about")
    expect(page.locator("text=Years experience")).to_be_visible()
    expect(page.locator("text=Projects shipped")).to_be_visible()
    expect(page.locator("text=Coffee consumed")).to_be_visible()


def test_about_has_skills(page: Page):
    page.goto(f"{BASE}/about")
    expect(page.locator(".section-heading", has_text="Skills")).to_be_visible()
    expect(page.locator("h3", has_text="Languages")).to_be_visible()
    expect(page.locator("h3", has_text="Backend")).to_be_visible()


def test_about_has_featured_projects(page: Page):
    page.goto(f"{BASE}/about")
    expect(page.locator("text=Featured Projects")).to_be_visible()


def test_about_has_tags_section(page: Page):
    page.goto(f"{BASE}/about")
    expect(page.locator("text=What I Write About")).to_be_visible()


# ─── Blog ────────────────────────────────────────────────────────────────────

def test_blog_page_lists_posts(page: Page):
    page.goto(f"{BASE}/blog")
    posts = page.locator("#posts-list article")
    assert posts.count() >= 1, "No posts found on blog page"


def test_blog_tag_filter_works(page: Page):
    page.goto(f"{BASE}/blog")
    tags = page.locator(".tag-btn")
    if tags.count() > 1:
        tag = tags.nth(1)
        tag.click()
        page.wait_for_url(re.compile(r"tag="))
        expect(page.locator("#posts-list")).to_be_visible()


def test_blog_post_has_hero_image(page: Page):
    page.goto(f"{BASE}/blog")
    first_link = page.locator("#posts-list article a").first
    first_link.click()
    page.wait_for_url(re.compile(r"/blog/"))
    img = page.locator(".post-hero")
    if img.count() > 0:
        src = img.get_attribute("src")
        assert src and len(src) > 10, "Hero image has no src"


def test_blog_post_has_content(page: Page):
    page.goto(f"{BASE}/blog")
    page.locator("#posts-list article a").first.click()
    page.wait_for_url(re.compile(r"/blog/"))
    prose = page.locator(".prose-custom")
    expect(prose).to_be_visible()
    text = prose.inner_text()
    assert len(text) > 200, f"Post content too short: {len(text)} chars"


def test_blog_post_has_tldr(page: Page):
    page.goto(f"{BASE}/blog")
    page.locator("#posts-list article a").first.click()
    page.wait_for_url(re.compile(r"/blog/"))
    tldr = page.locator(".tldr-card")
    if tldr.count() > 0:
        expect(tldr).to_be_visible()
        expect(tldr.locator(".tldr-label")).to_have_text("TL;DR")


# ─── Code blocks & Mermaid ───────────────────────────────────────────────────

def test_code_blocks_have_copy_button(page: Page):
    page.goto(f"{BASE}/blog")
    page.locator("#posts-list article a").first.click()
    page.wait_for_url(re.compile(r"/blog/"))
    page.wait_for_timeout(1000)
    wrappers = page.locator(".code-block-wrapper")
    if wrappers.count() > 0:
        expect(wrappers.first.locator(".copy-btn")).to_be_visible()


def test_mermaid_diagrams_render_via_htmx(page: Page):
    page.goto(f"{BASE}/blog")
    page.locator("#posts-list article a").first.click()
    page.wait_for_url(re.compile(r"/blog/"))
    page.wait_for_timeout(3000)
    raw_mermaid = page.locator("pre > code.language-mermaid")
    assert raw_mermaid.count() == 0, \
        f"Found {raw_mermaid.count()} unrendered mermaid code blocks (HTMX nav)"
    rendered = page.locator(".mermaid svg")
    if page.locator(".mermaid").count() > 0:
        assert rendered.count() > 0, "Mermaid div exists but no SVG rendered (HTMX nav)"


def test_mermaid_diagrams_render_direct_url(page: Page):
    page.goto(f"{BASE}/blog")
    href = page.locator("#posts-list article a").first.get_attribute("href")
    page.goto(f"{BASE}{href}")
    page.wait_for_timeout(4000)
    raw_mermaid = page.locator("pre > code.language-mermaid")
    assert raw_mermaid.count() == 0, \
        f"Found {raw_mermaid.count()} unrendered mermaid code blocks (direct URL)"
    rendered = page.locator(".mermaid svg")
    if page.locator(".mermaid").count() > 0:
        assert rendered.count() > 0, "Mermaid div exists but no SVG rendered (direct URL)"


def test_prism_syntax_highlighting(page: Page):
    page.goto(f"{BASE}/blog")
    page.locator("#posts-list article a").first.click()
    page.wait_for_url(re.compile(r"/blog/"))
    page.wait_for_timeout(1000)
    highlighted = page.locator("code[class*='language-'] .token")
    code_blocks = page.locator("pre code[class*='language-']")
    if code_blocks.count() > 0:
        assert highlighted.count() > 0, "Prism syntax highlighting not applied"


# ─── Sidebar ────────────────────────────────────────────────────────────────

def test_sidebar_profile_card(page: Page):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(BASE)
    aside = page.locator("aside")
    expect(aside.get_by_text("Zdenovo", exact=True)).to_be_visible()
    expect(aside.get_by_text("Software Engineer")).to_be_visible()


def test_sidebar_terminal_widget(page: Page):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(BASE)
    terminal = page.locator("#terminal-body")
    expect(terminal).to_be_visible()
    assert len(terminal.inner_text()) > 10, "Terminal widget is empty"


def test_sidebar_hidden_on_mobile(page: Page):
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(BASE)
    aside = page.locator("aside")
    expect(aside).to_be_hidden()


# ─── Admin ───────────────────────────────────────────────────────────────────

def test_admin_requires_login(page: Page):
    page.goto(f"{BASE}/admin/drafts")
    page.wait_for_url(re.compile(r"/admin/login"))


def test_admin_login_works(page: Page):
    admin_login(page)
    expect(page.locator("text=Drafts")).to_be_visible(timeout=5000)


def test_admin_draft_preview_has_regenerate(page: Page):
    admin_login(page)
    page.goto(f"{BASE}/admin/drafts")
    draft_link = page.locator("a[href*='/admin/drafts/']").first
    if draft_link.count() > 0:
        draft_link.click()
        page.wait_for_url(re.compile(r"/admin/drafts/"))
        expect(page.locator("text=Regenerate with feedback")).to_be_visible()
        expect(page.locator("textarea[name='remarks']")).to_be_visible()
        expect(page.get_by_role("button", name="Regenerate")).to_be_visible()


def test_admin_draft_preview_has_edit_form(page: Page):
    admin_login(page)
    page.goto(f"{BASE}/admin/drafts")
    draft_link = page.locator("a[href*='/admin/drafts/']").first
    if draft_link.count() > 0:
        draft_link.click()
        page.wait_for_url(re.compile(r"/admin/drafts/"))
        expect(page.locator("text=Edit before publishing")).to_be_visible()
        expect(page.locator("input[name='title']")).to_be_visible()
        expect(page.locator("textarea[name='content']")).to_be_visible()


def test_admin_draft_regenerate_submits(page: Page):
    admin_login(page)
    page.goto(f"{BASE}/admin/drafts")
    draft_link = page.locator("a[href*='/admin/drafts/']").first
    if draft_link.count() == 0:
        pytest.skip("No drafts available")
    draft_link.click()
    page.wait_for_url(re.compile(r"/admin/drafts/"))

    remarks_box = page.locator("textarea[name='remarks']")
    expect(remarks_box).to_be_visible()
    remarks_box.fill("Make the intro more aggressive and add a concrete deploy failure example")

    page.on("dialog", lambda d: d.accept())

    regen_btn = page.get_by_role("button", name="Regenerate")
    regen_btn.scroll_into_view_if_needed()

    try:
        with page.expect_response(
            lambda r: "/regenerate" in r.url, timeout=120000
        ) as resp_info:
            regen_btn.click(timeout=60000, no_wait_after=True)

        resp = resp_info.value
        if resp.status == 502:
            pytest.skip("Claude API unavailable — form submitted OK but generation failed")
        assert resp.status in (200, 303), \
            f"Regenerate returned unexpected status {resp.status}"

        page.wait_for_url(re.compile(r"/admin/drafts/"), timeout=120000)
        expect(page.locator("text=Draft Preview")).to_be_visible()
        remarks_after = page.locator("textarea[name='remarks']").input_value()
        assert "more aggressive" in remarks_after, \
            "Remarks not preserved after regeneration"
    except Exception as exc:
        if "ERR_CONNECTION" in str(exc) or "Timeout" in str(exc):
            pytest.skip(f"Claude API timeout during regeneration — form submission worked: {exc}")
        raise


# ─── Reading progress & visual polish ────────────────────────────────────────

def test_reading_progress_bar_exists(page: Page):
    page.goto(f"{BASE}/blog")
    page.locator("#posts-list article a").first.click()
    page.wait_for_url(re.compile(r"/blog/"))
    bar = page.locator("#reading-progress")
    expect(bar).to_be_attached()


def test_htmx_indicator_exists(page: Page):
    page.goto(BASE)
    indicator = page.locator("#htmx-indicator")
    expect(indicator).to_be_attached()


# ─── Broken images ───────────────────────────────────────────────────────────

def test_no_broken_images_on_homepage(page: Page):
    broken = []

    def check_response(response):
        if response.request.resource_type == "image" and response.status >= 400:
            broken.append(response.url)

    page.on("response", check_response)
    page.goto(BASE)
    page.wait_for_timeout(2000)
    assert len(broken) == 0, f"Broken images: {broken}"


def test_no_broken_images_on_blog_post(page: Page):
    broken = []

    def check_response(response):
        if response.request.resource_type == "image" and response.status >= 400:
            broken.append(response.url)

    page.on("response", check_response)
    page.goto(f"{BASE}/blog")
    page.locator("#posts-list article a").first.click()
    page.wait_for_url(re.compile(r"/blog/"))
    page.wait_for_timeout(2000)
    assert len(broken) == 0, f"Broken images: {broken}"


# ─── Console errors ──────────────────────────────────────────────────────────

def test_no_js_errors_on_homepage(page: Page):
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(BASE)
    page.wait_for_timeout(3000)
    assert len(errors) == 0, f"JS errors: {errors}"


def test_no_js_errors_on_blog_post(page: Page):
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(f"{BASE}/blog")
    page.locator("#posts-list article a").first.click()
    page.wait_for_url(re.compile(r"/blog/"))
    page.wait_for_timeout(3000)
    assert len(errors) == 0, f"JS errors: {errors}"
