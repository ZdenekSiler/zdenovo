# Spec: Mobile Navigation

## Overview

Add a sticky bottom navigation bar for mobile viewports, giving mobile readers an always-visible, thumb-reachable way to move between the four primary sections (Home, Blog, About, Projects). Today, the right sidebar is hidden entirely below the `lg` breakpoint (`hidden lg:block`) and the only navigation is four shrinking text links in the top header — a poor mobile experience with no persistent navigation affordance. This is purely an additive, mobile-only UI element; desktop layout and the top nav are unaffected (beyond optionally decluttering the top nav text on small screens).

---

## Current State

**Top nav (`frontend/templates/base.html`, lines ~70-104):** A `<nav class="flex items-center gap-0.5">` inside the sticky header containing four `nav-link` anchors — Home, About, Projects, Blog — each with the standard HTMX attribute set (`hx-get`, `hx-target="#main-content"`, `hx-select="#main-content"`, `hx-push-url="true"`, `hx-swap="innerHTML"`, `hx-indicator="#htmx-indicator"`). At narrow widths these four text links compress via the `.nav-link` responsive padding rule (`@media (min-width: 640px)` in `style.css` widens padding/font-size above `sm`), but there's no icon mode or hiding — they just get tighter.

**Right sidebar (`base.html`, lines ~121-170):** `<aside class="w-64 shrink-0 hidden lg:block">` — entirely hidden below `lg` (1024px). Contains profile card, terminal widget, and per-page `{% block sidebar %}` content (e.g. "Most Popular" on the blog list). This sidebar content is simply unavailable to mobile/tablet users; this spec does not attempt to surface sidebar content on mobile, only adds primary navigation.

**Main content area (`base.html` line ~115):** `<main class="flex-1 min-w-0">` wrapping `<div id="main-content">`. No bottom padding reserved — content currently runs to the bottom of the viewport, so a new fixed-position bottom bar would overlap the last visible content without an added padding reservation.

**Active-link highlighting (`frontend/static/js/main.js`, lines 1-18):** An existing IIFE queries `header nav a`, compares `getAttribute("href")` against `window.location.pathname`, and toggles `text-zinc-100`/`text-zinc-400` classes on a match. This logic is scoped specifically to `header nav a` — it does not run again on `htmx:afterSwap`, meaning **even today's top nav active-state does not update after HTMX navigation** (a pre-existing gap, not something this spec needs to fix, but the bottom nav's active-state logic must not repeat the same omission, since a stale active tab would be more noticeable on a persistent bottom bar than in the top nav).

**Footer (`base.html` lines ~174-199):** Static, non-sticky, sits at the natural end of page flow. Not affected by this spec, but its presence confirms there's no existing fixed-bottom element to conflict with.

---

## Files to Modify

| File | Reason |
|------|--------|
| `frontend/templates/base.html` | Add bottom nav bar markup (mobile-only), add bottom padding to `<main>`, optionally simplify top nav on small screens |
| `frontend/static/css/style.css` | Bottom nav bar styles (fixed positioning, backdrop blur, safe-area padding, active-tab styling) |
| `frontend/static/js/main.js` | Active-tab highlighting for bottom nav, re-run on `htmx:afterSwap` (and ideally extend the same fix to top nav while touching this logic) |
| `backend/tests/test_routes.py` | Add test confirming bottom nav markup is present on rendered pages |

## Files to Create

None. All changes fit within existing files.

---

## Implementation Notes

### `frontend/templates/base.html`

**Bottom nav bar placement.** Add a new `<nav>` element as a direct child of `<body>`, positioned after the main content/sidebar flex container and before (or after — fixed positioning makes DOM order irrelevant to visual placement, but after `<footer>` keeps source order logical) the footer. Must be `lg:hidden` so it only renders/displays below the `lg` breakpoint, matching the inverse of the sidebar's `hidden lg:block`.

**Structure:** four tab items, each an anchor following the exact same HTMX pattern already used by the top nav links (`hx-get`, `hx-target="#main-content"`, `hx-select="#main-content"`, `hx-push-url="true"`, `hx-swap="innerHTML"`, `hx-indicator="#htmx-indicator"`) pointing at `/`, `/blog`, `/about`, `/projects` respectively (order per spec: Home, Blog, About, Projects). Each tab contains a small inline SVG icon stacked above a short text label (e.g. flex-col, centered), sized to fit comfortably in a 56px-tall bar.

**Icons:** simple stroke-based SVGs in the same visual style as existing icons in the codebase (the chevrons in `blog.html` pagination, the GitHub/LinkedIn icons in the sidebar profile card use `stroke-width="2"` / `fill="currentColor"` conventions) — no icon library dependency, consistent with the rest of the site. Suggested icon concepts: house (Home), document/list (Blog), person (About), folder/grid (Projects) — exact glyph choice is an implementation detail, not load-bearing for the spec.

**Active tab.** Each tab anchor needs a data attribute or distinguishing identifier (e.g. `data-nav-path="/blog"`) so JS can match it against `window.location.pathname`, mirroring the existing top-nav active-highlight approach but applied to the bottom bar (and fixed to also work after HTMX swaps — see JS section).

**Main content padding.** Add `pb-16 lg:pb-0` (or equivalent, sized to clear the bar's height + safe-area inset) to the `<main>` element's existing `class="flex-1 min-w-0"`, so the last bit of page content is never obscured behind the fixed bottom bar on mobile, while no extra padding is added on `lg`+ where the bar doesn't render.

**Top nav simplification (optional per spec).** Below `sm`, either hide the top nav's text labels (icon-only, if icons were added there too) or hide the top nav entirely in favor of the bottom bar taking over primary navigation duty. Simplest implementation: add a `hidden sm:flex` (or similar) class to the existing top `<nav>` so it disappears on the smallest screens where the bottom bar is already present, reducing redundant navigation chrome. This keeps the brand/logo and header bar itself intact (still useful as a scroll-to-top affordance and for showing the HTMX loading indicator), just drops the duplicate links.

### `frontend/static/css/style.css`

Add a new block for the bottom nav, e.g. `.bottom-nav`:
- `position: fixed; bottom: 0; left: 0; right: 0;`
- `height: 56px` (plus safe-area handling, see below)
- `background-color: rgba(24, 24, 27, 0.95)` (zinc-900/95, matching the header's `bg-zinc-900/80` pattern but slightly more opaque since it sits over arbitrary page content rather than just below the viewport top)
- `backdrop-filter: blur(...)` matching the header's `backdrop-blur-sm`
- `border-top: 1px solid` zinc-800, matching the header's `border-b border-zinc-800/60`
- `z-index` high enough to sit above page content but should be coordinated with the existing `.htmx-indicator` (`z-index: 9999`) and `.reading-progress` (`z-index: 10000`) — bottom nav should sit below both of those (they're transient overlays at the very top of the viewport, no actual overlap risk, but z-index values should be chosen consciously relative to the existing stacking context, e.g. `z-index: 40`).
- `padding-bottom: env(safe-area-inset-bottom)` so the bar isn't obscured by the iOS home-indicator gesture area on notched devices; the bar's *content* (icons/labels) should stay vertically centered in the 56px region above the safe-area padding, not be pushed down by it.

Tab styling: flex row, each tab `flex: 1` (equal width), centered icon+label stack, default color muted (`zinc-500`, consistent with `.nav-link`'s default `#71717a`), active state using the indigo accent (`#818cf8`/`#a5b4fc`, consistent with `.tag-btn.active` and `.nav-link.active` color choices already established elsewhere).

### `frontend/static/js/main.js`

Extend (or add a sibling block to) the existing active-nav-link IIFE at the top of the file:
- Generalize the selector beyond `header nav a` to also include the new bottom nav's tab anchors (e.g. query both `header nav a` and `.bottom-nav a`, or give both navs a shared class like `.site-nav-link` to query in one pass).
- **Critical fix while touching this code:** wrap the highlighting logic in a named function and register it to run both on initial load and on `htmx:afterSwap` (following the exact pattern already used by the typing-effect and scroll-reveal IIFEs later in the same file, which both call `document.body.addEventListener("htmx:afterSwap", fn)`). Today's top-nav active-highlight only runs once at initial page load and goes stale after HTMX navigation; the bottom nav must not inherit that bug, since an incorrect active tab is more visible on a persistent always-on bar than in the top nav.
- Active tab should reflect `window.location.pathname` at the time of each HTMX swap (HTMX updates `window.location` via `hx-push-url="true"` before/as it fires `htmx:afterSwap`, consistent with how pagination and tag-filter links elsewhere in the codebase already rely on this).

---

## Risks & Trade-offs

1. **Fixed bottom bar covers content unless every page reserves padding.** The `pb-16 lg:pb-0` addition to `<main>` must be present on the shared `base.html` template (not per-page), so it automatically applies to all pages including ones rendered via HTMX partial swaps — confirm the padding class lives on the `<main>` wrapper itself (outside `#main-content`, which is what gets swapped) so it's never lost during HTMX navigation.
2. **Reusing the active-nav-link bug fix here, but not required to fix the top nav's existing staleness.** Since both navs will likely share the same JS function after this change, fixing the bottom nav's `htmx:afterSwap` re-run naturally also fixes the pre-existing top-nav staleness as a side effect — a net improvement, not a regression risk, but worth calling out as an incidental fix bundled into this feature.
3. **Safe-area inset support is iOS-specific** (`env(safe-area-inset-bottom)` is a no-op on platforms without a notch/home-indicator) — no negative impact on Android/desktop, pure progressive enhancement.
4. **Top nav hide-on-mobile is optional/cosmetic** — if skipped, the only downside is mildly redundant navigation (both top text links and bottom icon tabs visible simultaneously on mobile), not a functional bug. Can be deferred to a follow-up if there's any concern about removing the top nav links from very small screens.

---

## Tests Needed (`backend/tests/test_routes.py`)

```
test_base_html_contains_mobile_bottom_nav
test_bottom_nav_has_four_tabs
test_bottom_nav_tabs_have_hx_get_navigation_attrs
test_bottom_nav_links_target_main_content
test_main_content_has_mobile_bottom_padding_class
```

---

## Critical Files

- `frontend/templates/base.html` — bottom nav markup, main content padding, optional top nav mobile hiding
- `frontend/static/css/style.css` — `.bottom-nav` fixed positioning, safe-area padding, active-tab styling
- `frontend/static/js/main.js` — active-tab highlighting shared between top nav and bottom nav, fixed to re-run on `htmx:afterSwap`
- `backend/tests/test_routes.py` — new test cases
