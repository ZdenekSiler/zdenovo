# Spec: Tag Page SEO

## Overview

Give tag-filtered blog pages (`/blog?tag=python`) their own unique title, meta
description, and canonical URL, and list them in the sitemap. Today every tag page
renders the same `{% block title %}Blog{% endblock %}` and the same meta description as
the unfiltered `/blog` page — search engines see N+1 pages with identical `<title>`,
identical `<meta name="description">`, and (because `canonical_url` falls back to
`request.url.path`, which excludes the query string) the same canonical URL as `/blog`.
Google folds these together as duplicate content, so tag pages never rank and never
appear in the sitemap for discovery.

This feature makes each tag page self-describing (own title/description/canonical) and
crawlable (listed in `sitemap.xml`), without changing the tag-filtering behavior itself
(`get_posts_page(page, tag=tag)` in `data/posts.py` already does the filtering).

---

## Current State

**`backend/main.py`** — `GET /blog` (line ~218) accepts `tag: str | None = None` and
passes `current_tag`, `posts`, `page`, `total_pages`, `popular_posts` to `blog.html`. It
does **not** compute or pass a tag-specific title, description, or canonical URL.

**`frontend/templates/blog.html`** — block overrides are all static:
```jinja
{% block title %}Blog{% endblock %}
{% block meta_description %}Notes on software engineering, AI development, tooling, and lessons learned the hard way.{% endblock %}
{% block og_title %}Blog — Zdenovo{% endblock %}
{% block og_description %}Notes on software engineering, AI development, tooling, and lessons learned the hard way.{% endblock %}
```
No `{% block canonical_url %}` or `{% block og_url %}` override exists, so both inherit
the `base.html` default `https://zdenovo.com{{ request.url.path }}` — which is
`https://zdenovo.com/blog` regardless of the `?tag=` query string. The `Blog` JSON-LD in
`{% block extra_meta %}` is also static and doesn't reflect the active tag.

**`backend/db.py`** — `posts.tags` is a JSON array column (`TEXT`, JSON-encoded). No
dedicated tags table.

**`backend/data/posts.py`** — `get_all_tags()` already exists:
```python
def get_all_tags() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT value FROM posts, json_each(tags) ORDER BY value"
        ).fetchall()
    return [row[0] for row in rows]
```
This is reused as-is for the sitemap — no new DB query needed.

**`backend/routers/seo.py`** — `sitemap()` builds `static_pages` (home, blog, about,
projects, fakturant) plus one `<url>` per post from `get_all_posts()`. No tag URLs are
included.

---

## Files to Modify

| File | Reason |
|------|---------|
| `backend/main.py` | Compute tag-specific `page_title`, `meta_description`, `canonical_url`, `og_url` in the `GET /blog` route and pass them in the template context |
| `frontend/templates/blog.html` | Make `title`, `meta_description`, `og_title`, `og_description` blocks conditional on `current_tag`; add `canonical_url` and `og_url` block overrides; make the `Blog` JSON-LD reflect the active tag |
| `backend/routers/seo.py` | Import `get_all_tags`; add one `<url>` entry per distinct tag to `sitemap.xml` |

## Files to Create

None.

---

## Implementation Notes

### `backend/main.py` — `GET /blog` route

In the existing `blog()` handler, after computing `posts`/`total`, branch on whether
`tag` is set and build the SEO strings server-side (keeps Jinja simple — no string
concatenation logic in templates beyond what's already there for pagination links):

```python
if tag:
    page_title = f"{tag.capitalize()} posts"
    meta_description = f"Posts tagged with {tag} on Zdenovo."
    canonical_url = f"https://zdenovo.com/blog?tag={tag}"
else:
    page_title = "Blog"
    meta_description = "Notes on software engineering, AI development, tooling, and lessons learned the hard way."
    canonical_url = "https://zdenovo.com/blog"
```

Pass `page_title`, `meta_description`, `canonical_url` into the `TemplateResponse`
context alongside the existing keys. `og_url` reuses `canonical_url` (no separate
variable needed — pass the same value or derive it in the template).

**Pagination interaction:** tag pages with `page > 1` (e.g. `/blog?tag=python&page=2`)
keep the same `canonical_url` as page 1 of that tag (`?tag=python`, no `&page=`) to
avoid splitting ranking signal across paginated tag pages — this matches how `/blog`
itself behaves today (canonical is always the bare path regardless of `?page=`).

### `frontend/templates/blog.html`

Replace the static blocks with conditionals driven by the new context variables (using
`current_tag`, which is already passed today):

```jinja
{% block title %}{{ page_title }}{% endblock %}
{% block meta_description %}{{ meta_description }}{% endblock %}
{% block canonical_url %}{{ canonical_url }}{% endblock %}
{% block og_title %}{{ page_title }} — Zdenovo{% endblock %}
{% block og_description %}{{ meta_description }}{% endblock %}
{% block og_url %}{{ canonical_url }}{% endblock %}
```

This removes the hardcoded "Blog — Zdenovo" / "Notes on software engineering..." strings
from the template in favor of values computed in `main.py`, so the default (non-tag) case
must still render identically to today's output — verified by existing tests that check
`b"Blog</title>" in r.content` style assertions for the untagged `/blog`.

**JSON-LD (`extra_meta` block):** when `current_tag` is set, change `"name"` to
`"{{ page_title }}"` and add `"url": "{{ canonical_url }}"` (currently hardcoded to
`https://zdenovo.com/blog`) so the structured data matches the canonical for that page:

```jinja
{% block extra_meta %}
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Blog",
  "name": "{{ page_title if current_tag else 'Zdenovo Blog' }}",
  "description": "{{ meta_description }}",
  "url": "{{ canonical_url }}",
  "author": {"@type": "Person", "name": "Zdenovo", "url": "https://zdenovo.com/about"}
}
</script>
{% endblock %}
```

### `backend/routers/seo.py` — `sitemap()`

Add `from data.posts import get_all_tags` to the existing import line (currently
`from data.posts import get_all_posts`). After the existing per-post loop, add a
per-tag loop:

```python
for t in get_all_tags():
    lines.append(
        f"  <url><loc>{DOMAIN}/blog?tag={t}</loc>"
        f"<changefreq>weekly</changefreq><priority>0.6</priority></url>"
    )
```

Placed after posts, before `</urlset>`. `changefreq=weekly` (tag pages change less often
than `/blog` itself but more than static pages) and `priority=0.6` (between the `/blog`
listing at `0.9` and individual posts at `0.8` — tag pages are secondary navigation, not
primary content). No `<lastmod>` — tags don't have a single meaningful modification date
the way a post does.

**Tag values in URLs:** tags are plain lowercase alphanumeric strings already (e.g.
`python`, `fastapi`, `ai-agents` per `data/daily_topics.json` conventions) — no
URL-encoding helper is introduced since none of the codebase's existing tags contain
characters requiring escaping. If a tag with spaces/special characters is ever added,
`urllib.parse.quote` would need to be added at that point — out of scope here.

---

## Risks & Trade-offs

1. **Canonical ignores `page` param for tag pages.** Matches existing behavior for the
   untagged `/blog`, so it's consistent, but means `/blog?tag=python&page=2` self-reports
   a canonical that isn't itself. This is standard practice for paginated category pages
   (Google's guidance: canonicalize paginated series to page 1) and avoids introducing
   new logic just for tags.

2. **Sitemap could grow with tag count.** Currently ~5 static pages + N posts. Adding M
   tags is small in practice (the blog has a handful of tags), but if tag count ever
   exceeded ~100 a separate tag-sitemap or noindex-low-value-tags policy would be needed.
   Not a concern at current scale.

3. **No `noindex` for empty/near-empty tag pages.** A tag with only one post still gets a
   canonical + sitemap entry. Thin content risk is accepted here since blog tags are
   curated (not user-generated), so empty/near-empty tags are unlikely.

---

## Tests (`backend/tests/test_routes.py`)

```
# Tag page title/meta
test_tag_page_has_unique_title
test_tag_page_has_unique_meta_description
test_tag_page_has_unique_canonical_url
test_tag_page_og_url_matches_canonical
test_untagged_blog_page_title_unchanged
test_untagged_blog_page_canonical_unchanged

# JSON-LD
test_tag_page_blog_jsonld_reflects_tag

# Sitemap
test_sitemap_contains_tag_urls
test_sitemap_tag_url_uses_weekly_changefreq
test_sitemap_no_tag_urls_when_no_posts
```

---

## Critical Files

- `backend/main.py` — `GET /blog` route, computes tag-specific SEO context
- `frontend/templates/blog.html` — conditional title/meta/canonical/JSON-LD blocks
- `backend/routers/seo.py` — sitemap tag URLs
- `backend/data/posts.py` — `get_all_tags()` (reused, no changes needed)
- `backend/tests/test_routes.py` — new test cases
