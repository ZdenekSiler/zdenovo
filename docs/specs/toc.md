# Spec: Table of Contents

## Overview

Add an auto-generated table of contents (TOC) to long-form blog posts so readers can
scan and jump to sections. Posts are plain Markdown rendered to HTML server-side; the
TOC is built entirely client-side by scanning the rendered heading elements — no new
backend data, no schema change, no template-side heading extraction.

The TOC only appears on posts with enough structure (3+ headings) to be worth
navigating. On desktop it sits in a sticky panel; on mobile it collapses into an
accordion at the top of the post to avoid pushing content down on small screens.

---

## Current State

**Heading rendering:** `post.content` is Markdown, rendered through the `markdown`
Jinja filter into `.prose-custom` in `frontend/templates/post.html` (line 85-87). The
filter output is raw HTML — `h2`/`h3` elements currently have **no `id` attributes**, so
there is nothing to link/scroll to yet.

**Dead TOC code already exists:** `frontend/static/js/post-enhancements.js` has an
unused `buildToc(prose)` function (lines 25-48) that:
- targets a `#toc` element (which does not exist anywhere in the templates today)
- only scans `h2` (not `h3`)
- requires 2+ headings (not 3+)
- assigns ids as `"section-" + i` (not slugified from heading text)
- is never invoked from `enhance()` — it is unreachable dead code

**Matching CSS already exists:** `frontend/static/css/style.css` (lines 291-332) has a
`.toc` / `.toc-title` / `.toc ol` / `.toc li` / `.toc a` block already styled (card
background, numbered list with `counter()`, indigo accent numerals, hover state). This
CSS assumes a numbered-list layout, not a nested h2/h3 tree, and was written for the old
`buildToc()` shape.

**Sidebar mechanism:** `frontend/templates/base.html` has a `{% block sidebar %}`
(lines 121-170) rendering a sticky `<aside>` (`sticky top-16`, `hidden lg:block` — i.e.
desktop-only, `lg:` breakpoint and up) containing a profile card and a terminal widget.
`post.html` does not currently override this block, so post pages show the default
profile/terminal sidebar.

**No reading-position tracking:** `initProgress()` in `post-enhancements.js` reads
scroll position for the top progress bar but does not track which heading is in view —
active-heading highlighting needs new logic.

**Conclusion:** This is not a from-scratch build — it is a replacement of dead/mismatched
code. The existing `buildToc()` and `.toc` CSS should be removed/superseded rather than
left alongside the new implementation, to avoid two competing TOC code paths.

---

## Files to Modify

| File | Reason |
|------|---------|
| `frontend/templates/post.html` | Add TOC container markup; override `{% block sidebar %}` on post pages; add `<script src="/static/js/toc.js">` |
| `frontend/static/css/style.css` | Replace the old `.toc` block with styles for the new sticky sidebar panel, mobile accordion, and active-heading highlight |
| `frontend/static/js/post-enhancements.js` | Remove the dead `buildToc()` function (superseded by `toc.js`) so there is a single TOC implementation |

## Files to Create

| File | Reason |
|------|---------|
| `frontend/static/js/toc.js` | All TOC generation, slugging, scroll-spy, and smooth-scroll logic |

---

## Implementation Notes

### `frontend/static/js/toc.js` (new)

Self-contained IIFE, following the existing convention in `post-enhancements.js`
(2-space indent, `camelCase`, wrapped in `(function () { "use strict"; ... })();`).

**Responsibilities, in order:**

1. **Locate content.** Find `.prose-custom` in the current page. If absent, do nothing
   (mirrors the guard at the top of `enhance()` in `post-enhancements.js`).

2. **Collect headings.** Query `h2, h3` within `.prose-custom`, in document order.

3. **Threshold check.** If fewer than 3 headings are found, do not render a TOC at all —
   remove/hide the TOC container and leave the sidebar showing the default profile card
   (desktop) and skip rendering the mobile accordion entirely (not just hide it — avoid
   leaving an empty accordion shell in the DOM).

4. **Slugify and assign ids.** For each heading, derive an id from its text content:
   lowercase, trim, replace whitespace runs with `-`, strip characters outside
   `[a-z0-9-]`, collapse repeated `-`. If a heading already has a non-empty `id` (e.g.
   set by some future Markdown extension), leave it as-is and use that id instead of
   regenerating one. If two headings slugify to the same value, suffix the second and
   later occurrences with `-2`, `-3`, etc. to keep ids unique (anchors must be unique
   per HTML spec, and duplicate ids would break scroll-spy `id` lookups).

5. **Build the TOC tree.** Render as a nested list reflecting heading levels: each `h3`
   nests under the preceding `h2` in the list structure (not a flat list) so the visual
   hierarchy matches the document structure. A post that starts with an `h3` before any
   `h2` (malformed but possible) should still render flat rather than erroring.

6. **Render into two targets, not one:**
   - **Desktop:** a sticky panel. Because `post.html` overrides `{% block sidebar %}`
     with the TOC instead of the profile card (see below), the desktop TOC list is
     injected into a container already present in that block's markup — e.g.
     `#toc-sidebar`. This container lives inside the existing `sticky top-16` wrapper in
     `base.html`, so it inherits sticky behavior for free; `toc.js` does not need its
     own `position: sticky` JS logic.
   - **Mobile:** a collapsible accordion injected into a container near the top of the
     article (e.g. `#toc-mobile`), placed in `post.html` right after the post `<header>`
     and before the hero image / TL;DR card. Collapsed by default (a `<details>` element
     is the simplest correct primitive here — gives free collapse/expand and
     keyboard/accessibility behavior with no custom JS state, vs. hand-rolling an
     expand/collapse button with ARIA attributes).
   - Both targets are populated from the same heading list scan (run once), not two
     separate DOM scans, to avoid duplicate id-assignment or divergent slugs between
     desktop and mobile views.

7. **Active-heading highlighting (IntersectionObserver).** Observe all collected
   headings. On intersection, mark the corresponding TOC link(s) — both the desktop and
   mobile copies, since both exist in the DOM simultaneously (desktop hidden on small
   screens via CSS, mobile hidden on large screens via CSS — not removed) — with an
   `active` class. Use a root margin that biases toward the top of the viewport (e.g.
   negative bottom margin) so the "active" section corresponds to what's actually
   visible near the reading position, not whatever is barely poking into view at the
   bottom of the screen. When multiple headings are simultaneously intersecting, the
   topmost one wins.

8. **Smooth scroll on click.** Intercept clicks on TOC links, call
   `scrollIntoView({behavior: "smooth", block: "start"})` on the target heading (or
   equivalent), and update the URL hash via `history.pushState` (not a raw `location.hash`
   assignment, which would trigger an extra jump/scroll). Account for the sticky header
   in `base.html` — a plain `scrollIntoView` would land the heading directly under the
   fixed top nav; apply a scroll offset (e.g. `scroll-margin-top` CSS on headings, set to
   roughly the header height) so the heading is not obscured.

9. **Re-run after HTMX swaps.** This codebase uses HTMX `hx-swap="innerHTML"` to replace
   `#main-content` for SPA-like navigation between posts (see `architecture.md`). Like
   `post-enhancements.js`, `toc.js` must re-run its full build on
   `document.body.addEventListener("htmx:afterSwap", ...)`, not just on initial page
   load — otherwise navigating from one post to another via the sidebar nav/related-posts
   links would leave a stale or missing TOC. It must also disconnect any previous
   IntersectionObserver before creating a new one, to avoid observers accumulating across
   swaps and firing callbacks against detached DOM nodes.

10. **No-op safety on non-post pages.** Since the script tag is only added in
    `post.html`, this is mostly moot, but the function should still guard on
    `.prose-custom` existing (step 1) so an `htmx:afterSwap` firing while the user is on
    a non-post page (e.g. they navigated away) doesn't throw.

### `frontend/templates/post.html`

- **Mobile accordion container:** add a `<div id="toc-mobile"></div>` immediately after
  the `</header>` closing tag (line 72) and before the hero image block (line 74).
  Empty by default; `toc.js` populates it (and leaves it empty/hidden if under the
  3-heading threshold).

- **Sidebar override:** add `{% block sidebar %}` to this template. On post pages, the
  TOC should replace the profile card (per the design direction), not stack above/below
  it — the sidebar is narrow (`w-64`) and stacking both would push the terminal widget
  far down. Keep the terminal widget block from `base.html`'s default below the TOC.
  Concretely: copy the terminal-widget markup into this override (or factor it into a
  reusable `{% block sidebar_extra %}`/include if a third post-design feature is likely
  to touch this area too — but for this feature, a direct copy is simplest and keeps the
  change localized to one file). Add an empty `<div id="toc-sidebar"></div>` above the
  terminal widget for `toc.js` to populate. If the post ends up with fewer than 3
  headings, `toc.js` leaves `#toc-sidebar` empty — in that case the spec intentionally
  accepts a slightly sparse sidebar (no profile card) rather than conditionally
  rendering the profile card server-side, since heading count is only known after
  Markdown rendering happens client-side... **Note:** since `post.reading_time` is
  already computed server-side and available in the template context (used at line 70),
  prefer gating the sidebar override on that instead: only override `{% block sidebar %}`
  with the TOC container when `post.reading_time >= 5` (matches the stated problem,
  "posts over 5 min read"), otherwise fall through to the default profile-card sidebar
  unchanged. This avoids the empty-sidebar edge case entirely and matches the problem
  statement's framing more directly than a pure heading-count check. The 3-heading
  client-side check in `toc.js` remains as a secondary guard for whether the TOC
  *content* renders within that container.

- **Script tag:** add `<script src="/static/js/toc.js"></script>` near the bottom of the
  template (after content, consistent with where other page-specific behavior is wired
  up), loaded only here — not in `base.html` — so it never runs on non-post pages.

### `frontend/static/css/style.css`

- **Remove** the existing `.toc` / `.toc-title` / `.toc ol` / `.toc li::before` /
  `.toc a` block (lines 291-332) — it's built for the old flat numbered-list shape and
  conflicts with the new nested h2/h3 tree and dual desktop/mobile rendering.

- **Add new styles** covering:
  - `#toc-sidebar` panel: reuses the existing `.card`-like visual language (border,
    rounded corners, `bg-zinc-900`-family background) already established by the
    profile card it replaces, for visual consistency in that slot.
  - Nested list indentation so `h3` entries are visually subordinate to their parent
    `h2` entry.
  - `.toc-link` (or similar) base state, hover state (consistent with existing link hover
    treatment elsewhere, e.g. `.prose-custom a:hover` uses the `#a5b4fc` indigo-light
    accent), and `.active` state — active should be visually distinct (e.g. left border
    accent + brighter text) since this is the dynamic part driven by scroll position.
  - `#toc-mobile` accordion: styled `<details>`/`<summary>` — summary row looks like a
    clickable header ("On this page" + chevron), matching `.section-heading` typography
    (uppercase, letter-spaced, small) used elsewhere for section labels.
  - `scroll-margin-top` on `.prose-custom h2, .prose-custom h3` so anchor-jumping (both
    TOC clicks and direct `#hash` links) doesn't hide the heading under the sticky header.

---

## Tests Needed

`backend/tests/test_routes.py` (HTML route / structure tests — these test
template-rendered markup, not client-side JS behavior, consistent with how this file
tests other HTMX/structural concerns):

```
test_post_page_includes_toc_mobile_container        # GET /blog/{slug} response contains id="toc-mobile"
test_post_page_includes_toc_sidebar_container_for_long_post   # post with reading_time >= 5 contains id="toc-sidebar"
test_post_page_omits_toc_sidebar_for_short_post      # post with reading_time < 5 falls back to default profile card markup
test_post_page_includes_toc_script_tag               # response contains <script src="/static/js/toc.js">
```

Client-side behavior (slugification, threshold gating on heading count, scroll-spy,
smooth scroll, HTMX re-init) is not exercised by the `pytest`/`TestClient` suite since it
requires a real browser DOM — that belongs in `backend/tests/test_frontend.py`
(Playwright, requires the dev server running). Suggested additions there if/when that
file is extended for this feature:

```
test_toc_renders_for_post_with_three_or_more_headings
test_toc_hidden_for_post_with_fewer_than_three_headings
test_toc_click_scrolls_to_heading_and_updates_hash
test_toc_active_heading_updates_on_scroll
test_toc_rebuilds_after_htmx_navigation_between_posts
```

---

## Critical Files

- `frontend/static/js/toc.js` — new, all TOC logic
- `frontend/templates/post.html` — TOC containers, sidebar override, script tag
- `frontend/static/css/style.css` — replaces old `.toc` block with new panel/accordion/active-state styles
- `frontend/static/js/post-enhancements.js` — remove dead `buildToc()`
- `backend/tests/test_routes.py` — container/script-tag presence tests
