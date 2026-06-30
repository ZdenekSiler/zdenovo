# Spec: Schema Markup Expansion

## Overview

Expand structured data (JSON-LD) coverage beyond the existing `BlogPosting` (posts) and
`Blog` (blog list) schemas. Add `WebSite` + `SearchAction` on the homepage (enables a
sitelinks search box in Google results), `BreadcrumbList` on post and blog pages
(enables breadcrumb trails in search results instead of a raw URL), and round out the
`Person` schema already on `/about` with the `sameAs` property (links the entity to
GitHub/LinkedIn, strengthening Google's entity graph for "Zdenovo" as a person).

This is additive structured-data work — no visible UI changes, no new routes, no DB
changes. Each schema block is independent: `WebSite` lives only on the homepage,
`BreadcrumbList` is per-page (different trail on `/blog` vs `/blog/{slug}`), `Person`
is a one-line addition to an existing block.

---

## Current State

**`frontend/templates/index.html`** (homepage) — extends `base.html`, overrides
`title`, `meta_description`, `og_title`, `og_description`. **No `{% block extra_meta %}`
override exists**, so no JSON-LD is emitted on the homepage at all today.

**`frontend/templates/post.html`** — has `BlogPosting` JSON-LD in `{% block extra_meta
%}` (lines 14-27 of the template): `headline`, `description`, `datePublished`, `author`,
`publisher`, `url`, `image`, `mainEntityOfPage`. No `BreadcrumbList`.

**`frontend/templates/blog.html`** — has `Blog` JSON-LD in `{% block extra_meta %}`:
`name`, `description`, `url`, `author`. No `BreadcrumbList`. (Feature seo-tag-pages.md
modifies this same block to be tag-aware — see Risks below for interaction.)

**`frontend/templates/about.html`** — **already has a `Person` JSON-LD block**:
```json
{
  "@context": "https://schema.org",
  "@type": "Person",
  "name": "Zdenovo",
  "url": "https://zdenovo.com",
  "jobTitle": "Software Engineer",
  "description": "Backend systems, AI workflows, and developer tooling with Python.",
  "knowsAbout": ["Python", "FastAPI", "Docker", "AI Agents", "Claude", "SQLite"]
}
```
It has `name`, `url`, `jobTitle` already — **missing only `sameAs`**. The GitHub and
LinkedIn URLs are already hardcoded elsewhere in the codebase (`base.html` sidebar,
lines 138-145): `https://github.com/ZdenekSiler` and
`https://www.linkedin.com/in/zdenek-siler-0666b9175/`.

**`frontend/templates/base.html`** — `{% block extra_meta %}{% endblock %}` (line 18)
is the shared insertion point every child template uses for JSON-LD. No existing
`BreadcrumbList` anywhere in the codebase.

---

## Files to Modify

| File | Reason |
|------|---------|
| `frontend/templates/index.html` | Add `{% block extra_meta %}` with `WebSite` + `SearchAction` JSON-LD (new block — doesn't exist on this template today) |
| `frontend/templates/post.html` | Add `BreadcrumbList` JSON-LD (second `<script type="application/ld+json">` block, alongside the existing `BlogPosting` one) |
| `frontend/templates/about.html` | Add `"sameAs": [...]` property to the existing `Person` JSON-LD object |
| `frontend/templates/blog.html` | Add `BreadcrumbList` JSON-LD (second `<script>` block, alongside the existing `Blog` one) |

## Files to Create

None.

---

## Implementation Notes

### `frontend/templates/index.html` — WebSite + SearchAction

Add a new `{% block extra_meta %}` override (none exists today, so this is additive, not
a modification of existing content):

```jinja
{% block extra_meta %}
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "url": "https://zdenovo.com",
  "name": "Zdenovo",
  "potentialAction": {
    "@type": "SearchAction",
    "target": "https://zdenovo.com/blog?q={search_term_string}",
    "query-input": "required name=search_term_string"
  }
}
</script>
{% endblock %}
```

**Important caveat:** `/blog?q=` is not currently a real search parameter — `GET /blog`
only accepts `tag` and `page` (see `backend/main.py`, `GET /blog` route signature:
`tag: str | None = None, page: int = 1`). The `SearchAction` schema is a forward
declaration of intent to Google; it does **not** require a working `?q=` search to be
emitted, but Google's Sitelinks Search Box feature will only actually activate once the
target URL performs a real search. This spec adds the *schema* only — implementing
`?q=` full-text search on `/blog` is out of scope and would be a separate feature
(`seo-blog-search.md` or similar) if pursued later. Document this gap inline as an HTML
comment above the script block so it isn't mistaken for working search:

```jinja
<!-- SearchAction target is a forward declaration; /blog?q= search is not yet implemented. -->
```

### `frontend/templates/post.html` — BreadcrumbList

Add a second JSON-LD `<script>` block in `{% block extra_meta %}`, after the existing
`BlogPosting` script (both blocks coexist — multiple `<script type="application/ld+json">`
tags per page is valid and Google-supported):

```jinja
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zdenovo.com"},
    {"@type": "ListItem", "position": 2, "name": "Blog", "item": "https://zdenovo.com/blog"},
    {"@type": "ListItem", "position": 3, "name": "{{ post.title }}", "item": "https://zdenovo.com/blog/{{ post.slug }}"}
  ]
}
</script>
```

Three levels: Home → Blog → [Post Title], matching the actual click path a user follows
(the post page's existing "All posts" back-link already goes to `/blog`).

### `frontend/templates/blog.html` — BreadcrumbList

Add a second JSON-LD `<script>` block alongside the existing `Blog` schema:

```jinja
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zdenovo.com"},
    {"@type": "ListItem", "position": 2, "name": "Blog", "item": "https://zdenovo.com/blog"}
  ]
}
</script>
```

Two levels: Home → Blog. This applies identically whether or not `?tag=` is active — the
breadcrumb trail reflects site structure, not the active filter, so it does not need to
be tag-aware (unlike the `Blog` schema's `name`/`url`, which `seo-tag-pages.md` makes
tag-aware in the same `extra_meta` block).

### `frontend/templates/about.html` — Person sameAs

Add `"sameAs"` to the existing JSON-LD object (single-line addition, not a new block):

```diff
   "description": "Backend systems, AI workflows, and developer tooling with Python.",
-  "knowsAbout": ["Python", "FastAPI", "Docker", "AI Agents", "Claude", "SQLite"]
+  "knowsAbout": ["Python", "FastAPI", "Docker", "AI Agents", "Claude", "SQLite"],
+  "sameAs": [
+    "https://github.com/ZdenekSiler",
+    "https://www.linkedin.com/in/zdenek-siler-0666b9175/"
+  ]
```

URLs match exactly what's already hardcoded in `base.html`'s sidebar profile card (lines
138-145) — no new source of truth introduced, just duplicated into the schema (templates
don't currently share a "social links" data structure; introducing one is out of scope
for this spec since it would touch `base.html` layout code, not just SEO metadata).

---

## Risks & Trade-offs

1. **`SearchAction` without working search is a known SEO gray area.** Some sources
   suggest Google may ignore or eventually penalize `SearchAction` markup that doesn't
   resolve to a functioning search. Given `/blog` has no `?q=` handling yet, this schema
   is aspirational. Mitigation: ship the schema now (it's harmless either way — Google
   either activates Sitelinks Search Box or silently ignores the markup), but track
   "`/blog?q=` search" as a follow-up feature so the gap doesn't linger indefinitely.

2. **`blog.html`'s `extra_meta` block is touched by two specs** (`seo-tag-pages.md` makes
   `Blog` schema tag-aware; this spec adds `BreadcrumbList` to the same block). They are
   compatible — `seo-tag-pages.md` only changes fields *within* the `Blog` object;
   this spec adds a second, independent `<script>` tag after it. Implementers should
   merge both changes into the same `{% block extra_meta %}` rather than overwriting one
   with the other.

3. **No `Organization` schema.** Zdenovo is a personal/solo brand, not a company, so
   `Person` (already present) is the correct entity type rather than `Organization` —
   intentionally not added.

---

## Tests (`backend/tests/test_routes.py`)

```
# Homepage WebSite schema
test_homepage_has_website_schema
test_homepage_website_schema_has_search_action

# Post BreadcrumbList
test_post_page_has_breadcrumblist_schema
test_post_breadcrumb_includes_post_title
test_post_page_still_has_blogposting_schema

# Blog BreadcrumbList
test_blog_page_has_breadcrumblist_schema
test_blog_page_still_has_blog_schema

# About Person sameAs
test_about_page_person_schema_has_sameas
test_about_page_sameas_includes_github
test_about_page_sameas_includes_linkedin
```

---

## Critical Files

- `frontend/templates/index.html` — new `extra_meta` block (WebSite + SearchAction)
- `frontend/templates/post.html` — BreadcrumbList added to existing `extra_meta` block
- `frontend/templates/blog.html` — BreadcrumbList added to existing `extra_meta` block
- `frontend/templates/about.html` — `sameAs` added to existing `Person` object
- `backend/tests/test_routes.py` — new test cases
