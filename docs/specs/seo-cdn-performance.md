# Spec: CDN Preconnect & Asset Hints

## Overview

`base.html` loads render-blocking and deferred assets from four separate third-party CDN
origins (`cdn.tailwindcss.com`, `unpkg.com`, `cdnjs.cloudflare.com`,
`cdn.jsdelivr.net`) plus Google Fonts (`fonts.googleapis.com` /
`fonts.gstatic.com`, which already has `preconnect` hints). None of the four CDN
origins have `preconnect` or `dns-prefetch` hints, so the browser pays full DNS + TCP +
TLS negotiation latency serially as it discovers each `<script>`/`<link>` tag during HTML
parsing — directly delaying First Contentful Paint and Largest Contentful Paint, both
Core Web Vitals that factor into Google's page-experience ranking signal. This is a
resource-hint-only change: no asset URLs, versions, or load order semantics change
beyond what's specified below.

---

## Current State

**`frontend/templates/base.html`**, `<head>` section (lines 19-42):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<script data-cfasync="false" src="https://cdn.tailwindcss.com"></script>
<script data-cfasync="false">
tailwind.config = { ... }
</script>
<script data-cfasync="false" src="https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css" />
<link rel="stylesheet" href="/static/css/style.css?v=2" />
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js" defer></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-python.min.js" defer></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-bash.min.js" defer></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-yaml.min.js" defer></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-json.min.js" defer></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js" defer></script>
```

Origins in use, with current hint status:

| Origin | Used for | Preconnect today? |
|--------|----------|--------------------|
| `fonts.googleapis.com` | Inter font CSS | Yes |
| `fonts.gstatic.com` | Inter font files | Yes |
| `cdn.tailwindcss.com` | Tailwind JIT compiler (render-blocking) | No |
| `unpkg.com` | HTMX | No |
| `cdnjs.cloudflare.com` | Prism CSS + 5 JS files (theme, core, python, bash, yaml, json) | No |
| `cdn.jsdelivr.net` | Mermaid | No |

Tailwind script has no `fetchpriority` attribute. Prism CSS `<link>` currently sits
**after** the Tailwind `<script src="...">` tag and its inline config script — meaning
the browser discovers the Prism stylesheet only after parsing past Tailwind's
render-blocking script.

---

## Files to Modify

| File | Reason |
|------|---------|
| `frontend/templates/base.html` | Add `preconnect`/`dns-prefetch` hints for the three un-hinted CDN origins; add `fetchpriority="high"` to the Tailwind script; reorder Prism CSS before Tailwind; add `preload` for the Inter font stylesheet |

## Files to Create

None. This is the only file in scope.

---

## Implementation Notes

All changes are confined to the `<head>` block in `frontend/templates/base.html`
(currently lines 19-42). No other template extends or duplicates this block, so a single
edit covers every page (HTML routes all `{% extends "base.html" %}`).

### 1. Add preconnect + dns-prefetch hints

Insert before the existing asset tags, immediately after the two existing font
preconnects (so all resource hints are grouped together at the top of `<head>`):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preconnect" href="https://cdn.tailwindcss.com">
<link rel="dns-prefetch" href="https://cdn.tailwindcss.com">
<link rel="preconnect" href="https://unpkg.com">
<link rel="dns-prefetch" href="https://unpkg.com">
<link rel="preconnect" href="https://cdnjs.cloudflare.com" crossorigin>
<link rel="dns-prefetch" href="https://cdnjs.cloudflare.com">
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="dns-prefetch" href="https://cdn.jsdelivr.net">
```

**Why both `preconnect` and `dns-prefetch` per origin:** `preconnect` does DNS + TCP +
TLS but is only supported by Chromium/Firefox/Safari (modern baseline); `dns-prefetch`
is the older, more broadly supported fallback (DNS only) for browsers that don't honor
`preconnect`. Pairing both is the standard defensive pattern.

**Why `crossorigin` on cdnjs and jsdelivr but not tailwindcss/unpkg:** `crossorigin` is
required on `preconnect` when the resource will be fetched in CORS mode (fonts, and
scripts/styles that may be subject to CORS depending on how the CDN serves them).
`cdnjs.cloudflare.com` and `cdn.jsdelivr.net` serve with CORS headers (consistent with
the existing `fonts.gstatic.com` precedent, which also has `crossorigin`). Tailwind's
CDN script and the unpkg HTMX script are loaded as plain `<script src>` (not `fetch`/
`import`), which doesn't require CORS mode, so omit `crossorigin` there to avoid opening
a connection that doesn't match how the resource is actually requested (a mismatched
`crossorigin` attribute causes the browser to open a *second* connection, wasting the
optimization).

### 2. `fetchpriority="high"` on Tailwind script

```html
<script data-cfasync="false" src="https://cdn.tailwindcss.com" fetchpriority="high"></script>
```

Tailwind's CDN script is render-blocking (it injects `<style>` synchronously before
paint) and currently has no explicit priority, so the browser's default heuristic
(based on script position and type) applies. Marking it `fetchpriority="high"` tells the
browser's preload scanner to prioritize this fetch over same-priority-class resources
discovered later in the document, shaving time off the render-blocking path specifically
— don't apply this to HTMX, Prism, or Mermaid since none of them block first paint
(HTMX is needed for interactivity not paint; Prism/Mermaid are `defer`red).

### 3. Reorder Prism CSS before Tailwind

Move the existing line:
```html
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css" />
```//
from its current position (after the Tailwind script + inline config block) to
**immediately after the new preconnect/dns-prefetch block**, before the Tailwind
`<script>` tag. Stylesheets don't block script execution and vice versa, but the
*browser's preload scanner* discovers resources in document order — moving the Prism
`<link>` earlier lets its fetch start in parallel with (rather than strictly after)
Tailwind's script discovery, since the scanner doesn't have to first walk past the
script tag and inline config block to find it.

Final relative order in `<head>` after this change:
```
1. charset / viewport / title / meta description / canonical / RSS alternate
2. OG tags
3. extra_meta block (per-page JSON-LD)
4. font preconnects (existing) + new CDN preconnects/dns-prefetch (grouped)
5. Inter font stylesheet (preload — see #4 below)
6. Prism CSS (moved up)
7. Tailwind script (fetchpriority=high) + inline config
8. HTMX script
9. Site stylesheet (/static/css/style.css)
10. Prism JS files (deferred, unchanged order)
11. Mermaid (deferred, unchanged)
```

### 4. Preload the Inter font stylesheet

```html
<link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
```

The existing `preconnect` to `fonts.googleapis.com`/`fonts.gstatic.com` opens the
connection early but the browser still discovers the actual font CSS request only when
the parser reaches the `<link rel="stylesheet">` tag. Adding a `rel="preload" as="style"`
hint for the same URL tells the preload scanner to fetch it as a high-priority resource
as soon as it's seen, without waiting for CSSOM construction to reach that point — the
font CSS (and the `@font-face` declarations it contains) is on the critical path for
text rendering (`font-sans` is applied via Tailwind config to `body`), so faster delivery
reduces flash-of-invisible-text / layout shift risk. The existing `<link rel="stylesheet">`
tag is kept as-is (browsers that don't support `preload` simply ignore the hint and fall
through to the normal stylesheet load — no duplicate fetch).

---

## Risks & Trade-offs

1. **Diminishing returns vs. complexity.** Preconnect to 4 extra origins means the
   browser opens up to 4 additional early connections even if, for a given page, not
   every asset on that origin is strictly needed yet (e.g. Mermaid is only used on posts
   containing diagrams, but the script tag — and now its preconnect — loads on every
   page via `base.html`). This is consistent with the existing pattern (Prism/Mermaid
   already load unconditionally on every page today), so it's not a new problem
   introduced by this spec, just a pre-existing one not being fixed here. A future spec
   could explore conditionally loading Mermaid only on pages whose content contains a
   mermaid code block — out of scope here (this spec is resource-hints only, no
   conditional loading logic).

2. **No origin removal/self-hosting.** The deeper fix for 4-CDN sprawl would be
   self-hosting Tailwind (build step) or bundling HTMX/Prism/Mermaid locally, eliminating
   the external requests entirely. Explicitly out of scope: the architecture doc states
   "No Build Step" is a deliberate decision (CDN-only, no npm/bundler) — this spec works
   within that constraint rather than challenging it.

3. **Browser connection limits.** Most browsers cap simultaneous preconnects in practice
   (they're treated as hints, not guarantees) — adding hints for 4 more origins won't
   cause connection exhaustion, but the marginal benefit shrinks as more origins compete
   for the browser's early-connection budget. This is a known limitation of the
   preconnect mechanism in general, not specific to this implementation.

---

## Tests (`backend/tests/test_routes.py`)

```
test_base_html_has_preconnect_for_tailwindcss
test_base_html_has_preconnect_for_unpkg
test_base_html_has_preconnect_for_cdnjs
test_base_html_has_preconnect_for_jsdelivr
test_base_html_has_dns_prefetch_for_cdn_origins
test_tailwind_script_has_fetchpriority_high
test_prism_css_precedes_tailwind_script_in_head
test_inter_font_stylesheet_has_preload_hint
test_homepage_still_renders_200_after_head_changes
```

The last test is a basic regression guard — since every page extends `base.html`, a
malformed `<head>` edit would break every route, not just one; one cheap end-to-end
smoke test (`GET /` returns 200 and contains expected body markers) catches an
extends-chain break early.

---

## Critical Files

- `frontend/templates/base.html` — sole file touched; all four asset-hint changes live
  in the `<head>` block (currently lines 19-42)
- `backend/tests/test_routes.py` — new test cases
