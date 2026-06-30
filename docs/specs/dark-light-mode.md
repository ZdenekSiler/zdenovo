# Spec: Dark/Light Mode Toggle

## Overview

Add a user-toggleable light mode to a site that is currently dark-only. The toggle persists across visits via `localStorage` and across HTMX navigations (since theme state lives on the `<html>` element, which HTMX never swaps). This spec covers the toggle button placement, the flash-of-wrong-theme prevention script, the Tailwind dark-mode strategy, and the light-mode CSS override approach.

---

## Current State

**Theme:** The entire site (`frontend/templates/base.html`, `frontend/static/css/style.css`) is hard-coded dark: `bg-zinc-950 text-zinc-100` on `<body>`, zinc-900/zinc-800 borders and cards throughout, indigo-400/indigo-500 accents. There is no concept of a "theme" anywhere in the codebase — no class toggling, no `localStorage` usage for preferences, no Tailwind dark-mode config.

**Tailwind setup:** Loaded via CDN script tag in `base.html` `<head>` (`<script src="https://cdn.tailwindcss.com">`), configured inline via a second `<script>` block setting `tailwind.config = { theme: { extend: { fontFamily: {...} } } }`. No `darkMode` key is set, so Tailwind defaults to `media` strategy (follows OS `prefers-color-scheme`) — but since no `dark:` utility classes exist anywhere in the templates, this default has no effect today. The site looks the same regardless of OS theme.

**CSS:** `frontend/static/css/style.css` contains plain CSS classes (`.card`, `.tag`, `.nav-link`, `.prose-custom`, etc.) with hard-coded hex colors (e.g. `#18181b`, `#27272a`, `#6366f1`) — no CSS custom properties, no theme variable indirection.

**Top nav (`base.html` lines ~70-104):** A `<nav class="flex items-center gap-0.5">` inside the sticky header, containing four `nav-link` anchors (Home/About/Projects/Blog). There is currently no space reserved for additional controls like a toggle button, but the header has a flex spacer (`<div class="flex-1"></div>`) between the brand and nav that establishes the layout pattern for adding elements to the right side of the bar.

**JS (`frontend/static/js/main.js`):** An IIFE-per-feature pattern is already established (active nav-link highlighting, terminal widget rotation, typing effect, scroll reveal) — each feature is a self-contained `(function () { ... })();` block, several of which re-run on `htmx:afterSwap` to handle HTMX-swapped content. No theme-related code exists yet.

---

## Files to Modify

| File | Reason |
|------|--------|
| `frontend/templates/base.html` | Add theme-init script in `<head>` (before Tailwind CDN script), set `darkMode: 'class'` in Tailwind config, add toggle button to top nav |
| `frontend/static/css/style.css` | Add `html.light` override block for every themed component |
| `frontend/static/js/main.js` | Add `toggleTheme()` function and toggle-button click handler, update icon state |
| `backend/tests/test_routes.py` | Add tests for toggle button and theme-init script presence |

## Files to Create

None. All changes fit within existing files.

---

## Implementation Notes

### `frontend/templates/base.html`

**Theme-init script (flash prevention).** Add an inline `<script>` as the very first thing in `<head>`, before the Tailwind CDN `<script>` tag (currently the first script at line ~22). This script must run synchronously and before first paint:
- Reads `localStorage.getItem('theme')`.
- Defaults to `"dark"` if the key is absent (matches current site behavior — no regression for existing visitors).
- Applies the class to `<html>`: adds `class="dark"` or `class="light"` (the `<html>` tag already carries `class="h-full"` — the theme class must be added alongside, not replace it).
- Must be inline (not an external file) and placed before any CSS/Tailwind loads, otherwise the page renders in the wrong theme for a frame before the class is applied (flash of unstyled/wrong theme).

**Tailwind config.** In the existing inline `tailwind.config = {...}` block (lines ~24-32), add a top-level `darkMode: 'class'` key, alongside the existing `theme: { extend: {...} }` key. This tells Tailwind's CDN runtime to honor `dark:` utility variants based on the presence of the `dark` class on an ancestor (here, `<html>`), rather than the OS media query. Since the codebase currently uses plain CSS (not `dark:` Tailwind utilities) for the existing dark theme, this setting mostly future-proofs the config; the actual light-mode visual overrides are implemented via the `html.light` CSS selector strategy described below (simpler than retrofitting every existing Tailwind utility class with a `dark:` variant).

**Toggle button.** Add a button inside the `<nav>` flex container in the header (after the existing four `nav-link` anchors, or as a sibling element in the header's flex row — visually grouped with nav but distinct, e.g. separated by a small gap or a vertical divider). Markup:
- A `<button>` (not a link — it has no `href`/navigation semantics) with `id="theme-toggle"`, `aria-label="Toggle theme"`.
- Contains two inline SVG icons (sun and moon, simple stroke-based icons matching the existing icon style already used elsewhere in `base.html`, e.g. the GitHub/LinkedIn icons or pagination chevrons in `blog.html`) — both present in the DOM, visibility toggled via CSS/class rather than swapped, to avoid layout shift.
- Icon logic: when current theme is dark, show the moon icon (indicating "dark mode is active"); when light, show the sun icon. (Spec explicitly: moon = dark active, sun = light active — this is showing the *current state*, not the action the button performs.)
- Styled consistently with `.nav-link` sizing/padding so it sits naturally in the header row at both mobile and desktop widths.

### `frontend/static/css/style.css`

**Approach:** Rather than retrofitting every existing class with Tailwind `dark:` variants (which would touch dozens of templates), add a parallel `html.light` override block at the end of `style.css` that re-declares the same classes with light-mode colors. This keeps the existing dark styles as the unmodified default (zero risk of regression) and makes light mode strictly additive.

**Palette mapping** (dark → light):
- Page background: `zinc-950`/`zinc-900` → white / `zinc-50`
- Card/border backgrounds (`.card`, `.skill-card`, `.toc`, terminal widget, profile card, etc.): `#18181b`/`#27272a` → white/`zinc-50`, borders `zinc-200`
- Body text: `zinc-100`/`zinc-200` → `zinc-900`
- Secondary/muted text (`zinc-500`/`zinc-600`): → `zinc-500`/`zinc-600` (mid-gray tends to work on both backgrounds; verify contrast)
- Accent (indigo-400 `#818cf8`/`#6366f1`): → indigo-600 `#4f46e5` (darker indigo reads better on white per spec's stated palette)
- Borders (`#27272a`, `#3f3f46`): → `zinc-200`/`zinc-300`

**Components requiring explicit `html.light` overrides:** every class in `style.css` that hard-codes a dark-theme color needs a light counterpart — at minimum: `.nav-link`, `.btn-ghost`, `.card`, `.tag`, `.tag-btn`, `.skill-card`, `.prose-custom` (and all its descendant selectors: headings, code, pre, blockquote, table), `.post-thumb`/`.post-hero` borders, `.toc`, `.tldr-card`, `.mermaid`, scrollbar colors, `::selection`. Each gets a corresponding `html.light .classname { ... }` rule block. This is the largest part of the implementation effort — not technically complex, but mechanically thorough (every color value in the file needs a light counterpart considered).

**Body/html base background:** Since `<body>` carries `bg-zinc-950 text-zinc-100` as Tailwind utility classes (not a custom CSS class), and Tailwind's CDN runtime is configured with `darkMode: 'class'`, the simplest fix is to change `<body>`'s classes in `base.html` from hard-coded `bg-zinc-950 text-zinc-100` to `bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100` (using Tailwind's own `dark:` variant, which activates correctly now that `darkMode: 'class'` is set and `<html>` carries the `dark` class by default). This is the one spot where using Tailwind's native `dark:` variant is simpler than a custom CSS override, since it's a single utility-class line in one template rather than a whole new CSS rule.

### `frontend/static/js/main.js`

Add a new IIFE block (following the existing pattern) containing:
- `toggleTheme()`: reads current class on `document.documentElement`, flips between `dark`/`light`, updates the class, writes the new value to `localStorage.setItem('theme', ...)`, and updates the toggle button's icon visibility (swap which of the two SVGs is shown).
- A click listener attached to `#theme-toggle` calling `toggleTheme()`.
- Since the toggle button lives in `base.html`'s header (outside `#main-content`, never replaced by HTMX swaps), the click listener only needs to be attached once on initial page load — no need to re-bind on `htmx:afterSwap` the way the nav-link highlighter or terminal widget do. Confirm this by checking that `<header>` is a sibling of `<div id="main-content">`, not a descendant (it is, per `base.html` structure).
- On load, also sync the icon state to match whatever the inline `<head>` script already applied (so the button shows the correct icon immediately, not just after first toggle).

---

## Risks & Trade-offs

1. **Maintenance burden of a parallel light palette.** Every future component added to `style.css` must remember to add an `html.light` counterpart, or it will silently stay dark-themed in light mode. This is an ongoing tax, not a one-time cost. Acceptable given the alternative (CSS custom properties / theme tokens) would require a larger refactor of the existing dark-only stylesheet.
2. **Flash prevention depends on script order.** If the inline theme-init script is accidentally placed after the Tailwind CDN `<script>` or after any CSS `<link>`, a flash of incorrect theme becomes possible on slow connections. Must remain the first element in `<head>`.
3. **`prefers-color-scheme` is intentionally ignored.** The spec defaults new visitors to dark (matching current site identity) rather than respecting OS preference. This is a deliberate product choice, not an oversight — flagged here in case it's reconsidered later.
4. **Tailwind CDN + `darkMode: 'class'` only affects new `dark:`-variant utilities added going forward** (e.g. the `<body>` background fix); it does not retroactively theme the custom CSS classes in `style.css`, which rely on the `html.light` override strategy instead. Two parallel theming mechanisms (Tailwind dark: variants + custom CSS overrides) coexist by necessity, which a future refactor could unify under one approach (e.g. CSS variables) if the stylesheet grows further.

---

## Tests Needed (`backend/tests/test_routes.py`)

```
test_base_html_contains_theme_toggle_button
test_base_html_theme_toggle_has_aria_label
test_base_html_contains_theme_init_script_in_head
test_base_html_theme_init_script_precedes_tailwind_script
test_base_html_tailwind_config_sets_dark_mode_class
```

---

## Critical Files

- `frontend/templates/base.html` — theme-init script, Tailwind `darkMode: 'class'` config, toggle button markup, body class update
- `frontend/static/css/style.css` — `html.light` override block (all themed components)
- `frontend/static/js/main.js` — `toggleTheme()` function, click handler, icon sync on load
- `backend/tests/test_routes.py` — new test cases
