# Spec: Code Block Language Badges

## Overview

Add a small language label (e.g. "Python", "Bash", "YAML") to every syntax-highlighted
code block in blog posts, so readers can identify the language at a glance without
parsing the code itself. This extends the existing code-block enhancement pipeline in
`post-enhancements.js`, which already wraps every `<pre>` in a positioned wrapper and
injects a copy button — the badge is a third element injected into that same wrapper.

---

## Current State

**Code block wrapping pipeline:** `wrapCodeBlocks(prose)` in
`frontend/static/js/post-enhancements.js` (lines 51-100) runs on every `.prose-custom`
on page load and after each HTMX swap (`enhance()`, called from both the initial-load
path and the `htmx:afterSwap` listener at the bottom of the file). For each `<pre>` not
already wrapped:

- Skips Mermaid code blocks (`code.language-mermaid`) entirely — these get replaced with
  a `.mermaid` diagram div elsewhere (`initMermaid()`), not treated as code.
- Creates a `div.code-block-wrapper` (`position: relative` per `style.css` line 426-429)
  and moves the `<pre>` inside it.
- Appends a `button.copy-btn`, absolutely positioned `top: 0.5rem; right: 0.5rem`
  (`style.css` lines 433-448).
- Appends a `button.code-toggle` ("Hide"/"Show (N lines)"), absolutely positioned
  `top: 0.5rem; right: 3.5rem` — i.e. already shifted left to sit next to the copy
  button without overlapping it (`style.css` lines 476-491).
- Conditionally appends a `span.code-badge` (validation status — valid/error/warning,
  not language) at `top: 0.5rem; left: 0.5rem` if `window.__codeValidation` data exists
  for that block index (`style.css` lines 459-473). **Naming collision to be aware of:**
  this existing class is `.code-badge` for *validation* status; the new language badge
  needs a distinctly named class (`code-lang-badge`, as specified) to avoid colliding
  with or being confused for this unrelated existing feature.

**Language class source:** Prism.js (loaded via CDN per `architecture.md`'s "no build
step" approach) highlights `<code class="language-python">` etc. inside each `<pre>`.
`rehighlight(prose)` calls `Prism.highlightAllUnder(prose)` after `wrapCodeBlocks` and
`classifyBlockquotes` run (see `enhance()`, lines 4-12) — so by the time
`wrapCodeBlocks` runs, the `language-*` class is already present on `<code>` from the
Markdown-to-HTML rendering step (Prism's highlighting itself doesn't add the class, it
relies on it being present already, typically emitted by the Markdown renderer's fenced
code block handling).

**Existing right-side occupancy:** the wrapper's top-right corner already hosts two
buttons side by side (copy at `right: 0.5rem`, toggle at `right: 3.5rem`). A new
top-right badge needs a third horizontal slot, not just "move the copy button left" —
the toggle button is also there and must not be overlapped.

---

## Files to Modify

| File | Reason |
|------|---------|
| `frontend/static/js/post-enhancements.js` | Add language-badge injection inside `wrapCodeBlocks()` |
| `frontend/static/css/style.css` | Add `.code-lang-badge` styles; adjust `.copy-btn` / `.code-toggle` horizontal offsets to make room |

## Files to Create

None.

---

## Implementation Notes

### `frontend/static/js/post-enhancements.js`

All changes live inside the existing `wrapCodeBlocks(prose)` function (lines 51-100) —
no new top-level function, since this is a small, tightly-coupled addition to an
existing per-block loop, not an independent concern like Mermaid or blockquote
classification.

**Logic, inserted into the per-`pre` loop, after the wrapper/copy-button/toggle setup
and before the existing validation-badge block (so the DOM order is consistent: wrapper
→ pre → copy-btn → toggle → lang-badge → validation-badge, or any fixed order — order in
the DOM doesn't matter visually since everything is absolutely positioned, but keeping
new code adjacent to related existing code aids readability):**

1. Read the `<code>` element already looked up earlier in the loop (the existing code
   reuses `pre.querySelector("code")` in a couple of places — reuse that same lookup
   rather than querying again).
2. Find the language from its `classList`: look for a class matching `language-*`
   (Prism's convention; also covers the `lang-*` alias Prism sometimes accepts, but this
   codebase's renderer emits `language-*` per the existing `code.language-mermaid` check
   elsewhere in this same file, so matching `language-*` only is sufficient and
   consistent with existing code).
3. If no such class exists, or the matched value is empty/`language-none`/`language-plain`
   (common "no specific language" markers), inject nothing — per spec, no badge when
   there's no language. Don't render an empty/placeholder badge.
4. Strip the `language-` prefix to get the raw identifier (e.g. `python`, `bash`,
   `yaml`, `json`, `ts`, `tsx`).
5. Map the raw identifier to a display label. Most cases are a straight capitalize
   (`python` → `Python`, `bash` → `Bash`). Some need a lookup table for correct casing
   since naive capitalization is wrong for acronyms/compound names — at minimum:
   `yaml` → `YAML`, `json` → `JSON`, `html` → `HTML`, `css` → `CSS`, `sql` → `SQL`,
   `ts` → `TypeScript`, `tsx` → `TSX`, `js` → `JavaScript`, `jsx` → `JSX`,
   `yml` → `YAML` (alias), `sh`/`shell` → `Shell`, `bash` → `Bash`. Anything not in the
   table falls back to capitalize-first-letter. Keep this as a small constant map at the
   top of the file or inline in the function — not a separate data file, since it's a
   handful of UI-label entries, not domain data (per `architecture.md`'s rule that
   `data/*.json` is for backend-relevant static/config data).
6. Create `span.code-lang-badge`, set `textContent` to the display label, append to the
   wrapper (same pattern as the copy button and toggle button — `wrapper.appendChild(...)`).
7. Re-run safety: like the rest of `wrapCodeBlocks`, this only runs once per `<pre>`
   because the whole function is guarded by the
   `if (pre.parentElement.classList.contains("code-block-wrapper")) return;` early-return
   at the top of the loop — already-wrapped blocks (e.g. after a re-run that doesn't
   actually re-process them) are skipped, so no duplicate-badge risk on repeated
   `enhance()` calls.

### `frontend/static/css/style.css`

- **New `.code-lang-badge` rule**, near the existing `.copy-btn` / `.code-badge` /
  `.code-toggle` rules (after line 503, before the Prism overrides section) for
  locality with related styles:
  - `position: absolute; top: 0.5rem;`
  - Horizontal position: top-right corner, per spec — but the copy button currently
    occupies that exact corner (`right: 0.5rem`) and the toggle sits at `right: 3.5rem`.
    Per the spec's instruction ("the copy button... moves slightly left to not overlap
    the badge"), the badge takes the rightmost slot and both existing buttons shift
    further left:
    - `.code-lang-badge` → `right: 0.5rem` (new rightmost position)
    - `.copy-btn` → shift from `right: 0.5rem` to roughly `right: 3.5rem` (where the
      toggle currently is)
    - `.code-toggle` → shift from `right: 3.5rem` to roughly `right: 6.5rem` (where
      nothing currently is)
    - Exact spacing should be tuned so labels of varying width (e.g. "TypeScript" vs.
      "Go") don't collide with the copy/toggle buttons — a fixed `right` offset per
      element is simpler than dynamic JS measurement and consistent with how the
      existing buttons are positioned, but the offset for `.copy-btn` and `.code-toggle`
      may need to be a bit more generous than the badge's own width to comfortably fit
      the longest expected label.
  - Small, monospace, low-emphasis per spec: `font-family: ui-monospace, SFMono-Regular,
    Menlo, monospace` (reuse the same stack already used in `.prose-custom code`,
    line 183, for consistency), `font-size` matching the other badges/buttons in this
    cluster (`0.625rem`–`0.6875rem` range, matching `.copy-btn`/`.code-toggle`/
    `.code-badge`), `padding: 0.375rem` per spec's "6px padding" (`0.375rem` = 6px at
    the standard 16px root), `border-radius` matching the rounded style of sibling
    elements (`0.375rem`, same as `.copy-btn`), `background-color` zinc-600
    (`#52525b` — Tailwind's zinc-600), `color` zinc-400 (`#a1a1aa` — Tailwind's
    zinc-400), per spec.
  - `z-index: 2` to match the other floating controls in the wrapper (`.copy-btn`,
    `.code-toggle`, `.code-badge` all use `z-index: 2`) so stacking order is consistent
    and predictable if any ever overlap during a window resize.
  - No hover/interactive states needed — it's a static label, not a button (unlike
    `.copy-btn`/`.code-toggle` which both have `:hover` rules).

---

## Tests Needed

`backend/tests/test_routes.py` (existing file, structural/HTML-level assertions only —
consistent with how this file already tests static asset wiring, not JS runtime
behavior):

```
test_post_page_includes_post_enhancements_script_tag   # response contains <script src="/static/js/post-enhancements.js">
```

This single assertion is already implicitly likely covered if `post-enhancements.js` is
already referenced by existing post-page tests — if so, this is a no-op confirmation
rather than a new test; if not already covered, add it. No backend logic changes, so no
new API/unit tests are needed.

Client-side behavior (badge text correctness per language, absence of a badge for
unlabeled code blocks, no overlap with copy/toggle buttons, correct display-name mapping
including the acronym cases) is not exercised by `pytest`/`TestClient` since it requires
Prism to run and a real DOM. Suggested additions to `backend/tests/test_frontend.py`
(Playwright, requires dev server) if/when that file is extended for this feature:

```
test_code_block_shows_language_badge_for_python
test_code_block_shows_uppercase_badge_for_yaml_and_json
test_code_block_without_language_class_shows_no_badge
test_code_lang_badge_does_not_overlap_copy_or_toggle_buttons
```

---

## Critical Files

- `frontend/static/js/post-enhancements.js` — badge injection logic inside `wrapCodeBlocks()`
- `frontend/static/css/style.css` — `.code-lang-badge` styles, repositioned `.copy-btn` / `.code-toggle`
- `backend/tests/test_routes.py` — script-tag presence assertion
