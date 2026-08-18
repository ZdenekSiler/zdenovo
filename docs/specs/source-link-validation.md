# Spec: Source Link Validation

## Overview

Validate the external reference URLs stored on drafts and posts, so dead links never reach a
published post. Adds a `link_validator` module (HTTP reachability checks), an admin endpoint
plus draft-preview UI to run them on demand, and a one-shot maintenance script to audit and
repair the sources already published on prod.

The critical requirement: **a non-200 response is not proof a link is dead.** Two of the most
common source domains on this blog — Medium (13 URLs) and DataCamp (12) — return `403` to any
automated request regardless of User-Agent, while serving the page fine to a human. A checker
that treats "not 200" as "delete it" would destroy ~13% of perfectly good references. The
validator must therefore classify into three buckets and only ever act on the first.

| Verdict | Signals | Action allowed |
|---|---|---|
| `dead` | 404, 410, DNS failure, connection refused | Safe to remove/replace |
| `blocked` | 403, 429, WAF/bot-wall, TLS refusal | **Never auto-remove** — flag for human review |
| `ok` | 2xx, or 3xx resolving to 2xx | Keep |

---

## Current State

**Storage:** `sources` is a JSON array column on both `posts` and `drafts`, shaped by
`Source` (`title`, `url`, `summary`) in `backend/routers/posts_api.py:27`. Exposed on
`PostOut.sources` and rendered in `frontend/templates/post.html:158` and
`draft_preview.html:129`.

**Generation:** `BlogGenerator.find_sources()` (`generate_api.py:314`) makes one Haiku call
with `web_search` (max_uses 1) and the `suggest_sources` tool. Fail-soft: returns `[]` on API
error. Prompts live in `data/prompts/sources_system.md` / `sources_tool.json` — already
hardened in this change (verbatim-URL rule, `minItems` lowered 3 → 0 so the model is never
pressured to invent a third URL).

**Existing validator to mirror:** `backend/code_validator.py` exposes `validate_content()`
returning a `ValidationSummary` (`results[]`, `total`, `valid`, `warnings`, `errors`,
`skipped`). It is called synchronously in `main.py:652` for the draft preview page and via
`POST /api/drafts/{id}/validate` (`drafts_api.py:419`). Link checking is network-bound, so it
must **not** copy the synchronous-on-page-render pattern.

**Prod scale:** 41 published posts, 38 with sources, 189 source URLs (126 unique).

---

## Files to Create

| File | Reason |
|------|---------|
| `backend/link_validator.py` | Reachability checks + three-bucket classification; mirrors `code_validator.py`'s shape |
| `backend/tests/test_link_validator.py` | Unit tests for classification, mirroring `test_<module>.py` convention |
| `scripts/lib/audit_sources.py` | Read-only: dump every post's sources from a DB to JSON (runs in the prod container) |
| `scripts/lib/repair_sources.py` | Apply an approved repair plan to a DB (backup first, mirrors `insert_draft.py`'s contract) |

## Files to Modify

| File | Reason |
|------|---------|
| `backend/routers/drafts_api.py` | Add `POST /api/drafts/{id}/validate-links` (admin) returning a `LinkValidationSummary` |
| `backend/main.py` | Add `POST /admin/drafts/{id}/validate-links` returning an HTMX fragment |
| `frontend/templates/draft_preview.html` | "Check links" button + result area near the existing sources block |
| `frontend/templates/_link_results.html` (new fragment) | Per-URL verdict rows, colour-coded by bucket |
| `scripts/draft-to-prod.sh` | `audit-sources` / `repair-sources` subcommands, following `copy-series` |
| `docs/architecture.md` | Endpoint table rows + a note on the three-bucket rule |

---

## Implementation Plan

**Phase 1 — validator core**
1. `link_validator.py`: `LinkResult(url, status, verdict, detail)`, `LinkSummary(results, total,
   ok, dead, blocked)`, and `check_links(sources) -> LinkSummary`.
2. Per URL: `HEAD` first, fall back to `GET` on 403/405/501 (many hosts refuse HEAD but serve
   GET); follow redirects; browser-like User-Agent; 12s timeout; concurrent via
   `ThreadPoolExecutor` (cap ~8 workers) so a 5-source draft returns in ~2s.
3. Classify per the table above. Anything ambiguous → `blocked`, never `dead`.

**Phase 2 — draft surface**
4. `POST /api/drafts/{id}/validate-links` — admin-only via `_get_require_admin()`, 404 on
   missing draft, returns `LinkSummary`. Do **not** add it to the draft-preview page render
   path; on-demand only.
5. HTMX button in `draft_preview.html` posting to the admin route, swapping in
   `_link_results.html`. Colour: green `ok`, red `dead`, amber `blocked` with the text
   "blocked by host — verify manually", so the UI never implies a blocked link is broken.

**Phase 3 — prod remediation** (data change, run once)
6. `audit-sources` dumps prod's post sources; check them locally; produce a repair plan
   (JSON: slug → sources to drop / replace).
7. Human reviews the plan. Replacements for dead links come from a `find_sources`-style Haiku
   call, and each candidate is re-validated before it enters the plan.
8. `repair-sources` applies the approved plan inside the prod container, backing up `blog.db`
   first and reporting per-post before/after counts.

---

## Tests Needed

`backend/tests/test_link_validator.py` — no live network; monkeypatch the fetch helper:
- `test_classify_404_is_dead`, `test_classify_410_is_dead`, `test_classify_dns_failure_is_dead`
- `test_classify_403_is_blocked_not_dead` ← the regression that matters most
- `test_classify_429_is_blocked`, `test_classify_200_is_ok`, `test_redirect_to_200_is_ok`
- `test_head_405_falls_back_to_get`
- `test_summary_counts_match_results`, `test_empty_sources_returns_empty_summary`

`backend/tests/test_drafts.py` — `test_validate_links_requires_admin` (303),
`test_validate_links_missing_draft_returns_404`, `test_validate_links_returns_summary`.

---

## Risks & Trade-offs

- **False positives are the main hazard.** Auto-deleting on non-200 would remove ~25 valid
  Medium/DataCamp links. Mitigation: three buckets, and only `dead` is ever actionable.
- **Network flakiness.** A transient timeout must not be recorded as `dead`; treat timeouts as
  `blocked` and require a second failed run before acting on them.
- **Rate limiting.** Concurrency is capped and checks are on-demand, not on page render, so a
  draft preview never fires 5 outbound requests just by being opened.
- **Cost.** Validation is free (plain HTTP). Only *replacing* a dead source costs a Haiku +
  `web_search` call — one per affected post, not per URL.
- **Prod writes.** Repairs run through the existing backup-first script contract; the plan is
  reviewed by a human before anything is applied.
