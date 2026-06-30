# Spec: Post Card Redesign

## Overview

Redesign the blog list post card to add visual hierarchy and engagement signals without changing the overall layout. Today, cards in `frontend/templates/blog.html` show a thumbnail, date, reading time, title, summary, and static tag pills — but tags are not clickable independently of the card, there is no view-count signal, and the reading-time text blends into the metadata row with no visual distinction. This spec adds an HTMX-driven tag filter, a formatted view count, a pill-styled reading-time badge, a subtle hover affordance on the title, and a slightly larger thumbnail on wide screens. No structural change to the horizontal card layout.

---

## Current State

**Template (`frontend/templates/blog.html`):** Each post card is a single anchor (`<a href="/blog/{{ post.slug }}" hx-get=...>`) wrapping the entire card — thumbnail, metadata row (date · reading time), title, summary, and tags. Because the whole card is one link, the tag pills (`<span class="tag">{{ t }}</span>`) are inert text, not links — clicking a tag does nothing (the click is swallowed by the outer anchor's navigation to the post). Reading time renders as plain inline text: `{{ post.reading_time }} min read`, visually identical in weight to the date next to it.

**CSS (`frontend/static/css/style.css`):** Two relevant classes already exist:
- `.tag` (line ~97) — static pill, used for display-only tags (background `#27272a`, color `#71717a`, no hover/active state, not a link style).
- `.tag-btn` (line ~109) — an HTMX-clickable filter pill style already defined with hover and `.active` states (indigo accent on hover/active), but **not currently used in `blog.html`**. This class appears to have been built for exactly this purpose and is sitting unused.
- `.post-thumb` (line ~216) — fixed `96px × 68px` thumbnail, used in the card loop.

**Backend (`backend/main.py`, `backend/data/posts.py`):** `get_posts_page()` does `SELECT * FROM posts ...`, so `views` (an `INTEGER NOT NULL DEFAULT 0` column already on the `posts` table per `backend/db.py`) is already present on every `post` dict reaching the template via `row_to_dict()`. The `/blog` route already accepts `tag: str | None = None` as a query param, runs it through `get_posts_page(page, tag=tag)`, and exposes it to the template as `current_tag`. **No backend changes are required** — `post.views` and tag filtering already work server-side; this is a template/CSS-only feature.

**Tag filtering today:** Only reachable via the sidebar's tag list (if present) or manually constructing `/blog?tag=X` URLs — not from a click on a tag pill inside a post card itself.

---

## Files to Modify

| File | Reason |
|------|--------|
| `frontend/templates/blog.html` | Convert tag spans to HTMX-linked pills, add view count, restyle reading-time badge, add hover "Read →" affordance, widen thumbnail at `sm`+ |
| `frontend/static/css/style.css` | Add reading-time badge style, hover-reveal arrow style, larger thumbnail breakpoint rule |
| `backend/tests/test_routes.py` | Add tests for tag links and reading-time badge |

## Files to Create

None. All changes fit within existing files.

---

## Implementation Notes

### `frontend/templates/blog.html`

**Tag pills become HTMX filter links.** Replace the inert `<span class="tag">{{ t }}</span>` loop with `<a>` elements using the existing-but-unused `.tag-btn` class:
- Each tag becomes `<a class="tag-btn" hx-get="/blog?tag={{ t }}" hx-target="#posts-list" hx-select="#posts-list" hx-swap="outerHTML" hx-push-url="true" hx-indicator="#htmx-indicator">{{ t }}</a>`, matching the same target/swap/push-url pattern already used by the pagination links lower in the same template.
- Critical: the tag link must call `event.stopPropagation()` (or rely on the fact that it's not nested inside the outer card `<a>`) so a click on a tag does not also trigger the card's own navigation to the post. Since browsers do not allow nested `<a>` tags validly, the tag row must be **moved outside** the outer card anchor — i.e. restructure the card so the clickable "go to post" region wraps the thumbnail + metadata + title + summary, and the tag row sits as a sibling block below/outside that anchor, still inside the `<article>`. This is the only structural adjustment needed to make tags independently clickable; the visual layout (tags appearing below the summary) is unchanged.
- Active-tag state: if `current_tag == t`, add the `active` class so the currently-filtered tag is visually distinguished (already styled via `.tag-btn.active`).

**View count.** In the metadata row (currently `date · reading time`), add a third segment for views, following the same pattern already used in the sidebar's "Most Popular" block (`{% if p.views > 0 %}`). Add a Jinja filter or inline expression to format the number: values ≥ 1000 render as `1.2k views` (one decimal, trimmed if `.0`), values < 1000 render as a plain integer (`342 views`). Only render the segment when `post.views > 0`, consistent with the sidebar's existing convention, separated by the same `·` divider already used between date and reading time.

**Reading-time badge.** Move `{{ post.reading_time }} min read` out of the plain-text metadata row styling and into a small pill (similar visual weight to `.tag` but distinct color, e.g. a faint indigo tint) so it reads as a badge rather than blending into the date/views text. Keep it in the same position in the metadata row, just visually distinct via a new CSS class (see below).

**"Read →" hover affordance.** The title (`<h2>`) already has `group-hover:text-indigo-400`. Add a small inline arrow/text element after or near the title (e.g. `<span class="read-more-hint">Read →</span>`) that is invisible by default (`opacity-0`) and fades in on `group-hover` (`group-hover:opacity-100`), colored `text-indigo-400`. This requires the `group` class to remain on the outer clickable anchor (or the `<article>`, whichever currently carries `group` — confirm it stays on the linked region after the tag-row restructuring above).

**Larger thumbnail on wide screens.** `.post-thumb` is fixed at `96px × 68px` for all viewports. Add a responsive variant: keep `96×68` on mobile (`base`), increase to something like `128×88` or `140×96` at the `sm:` breakpoint and above, matching the breakpoint convention already used elsewhere in `blog.html` (e.g. `sm:px-6`). This is a CSS-only change (new class or `sm:` Tailwind utility override) — no new `<img>` markup needed beyond a class/size adjustment.

### `frontend/static/css/style.css`

- Add a `.reading-time-badge` class: pill shape (`border-radius: 9999px`), small padding, subtle background (e.g. `#1e1b4b40` — matching the indigo-tinted backgrounds already used for `.tldr-card`/`.code-badge--valid` patterns in this file), `color: #a5b4fc`, small font size matching `.tag`.
- Add a `.read-more-hint` class: `opacity: 0`, `transition: opacity 150ms ease`, `color: #818cf8`, small font weight; paired with `.group:hover .read-more-hint { opacity: 1; }` following the exact pattern already used for `.group:hover .post-thumb` border-color.
- Add a `sm:` (or custom media query) override for `.post-thumb` width/height — either a new modifier class (`.post-thumb-lg`) applied via Tailwind responsive class composition, or a `@media (min-width: 640px) { .post-thumb { width: ...; height: ...; } }` block, consistent with the existing `@media (min-width: 640px)` block already present for `.nav-link`.
- No changes needed to `.tag-btn` — it already has the hover/active states required.

### Backend

No backend changes required. `post.views` is already present in the template context for every post in the `/blog` route (confirmed: `get_posts_page()` uses `SELECT *`, and `views` is a column on `posts` with `DEFAULT 0`). The `?tag=` query param and `current_tag` context variable already exist and work identically to what the sidebar/pagination already use.

---

## Risks & Trade-offs

1. **Nested anchors are invalid HTML.** The current card wraps everything (including tags, if they were links) in one big `<a>`. Making tags independently clickable requires restructuring so the tag row is a sibling of the card's main link, not a descendant of it. This is a small DOM change but must be done carefully to preserve the existing `group` hover behavior on the title and thumbnail.
2. **View count formatting is cosmetic only** — no new data dependency, so this can't introduce backend bugs. Edge case: exactly `1000` views should display as `1k views` (not `1.0k`), and `1500` as `1.5k views`.
3. **Reusing `.tag-btn` instead of inventing a new style** keeps the codebase DRY — the class already exists with correct hover/active states, just unused until now.

---

## Tests Needed (`backend/tests/test_routes.py`)

```
test_blog_card_tags_are_hx_get_links
test_blog_card_tag_click_filters_without_full_navigation   # hx-get target/swap attrs present
test_blog_card_active_tag_has_active_class
test_blog_card_shows_view_count_when_views_positive
test_blog_card_hides_view_count_when_views_zero
test_blog_card_formats_view_count_with_k_suffix_over_1000
test_blog_card_shows_reading_time_badge
```

---

## Critical Files

- `frontend/templates/blog.html` — card markup restructuring, tag links, view count, reading-time badge, hover hint
- `frontend/static/css/style.css` — `.reading-time-badge`, `.read-more-hint`, responsive `.post-thumb` sizing
- `backend/tests/test_routes.py` — new test cases
