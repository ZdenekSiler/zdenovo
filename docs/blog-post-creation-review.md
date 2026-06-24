# Blog Post Creation — Flow Review

## What exists

**Path 1: Manual API** (`POST /api/posts`) — Direct write to the `posts` table. No Claude, no draft step. Good for seeding but requires raw JSON via curl or Swagger.

**Path 2: On-demand generation** (`POST /api/posts/generate/{brief_id}`) — Calls Claude with one of the 8 briefs, returns a `PostOut` JSON blob. The result is never saved. If you close the response tab, the generated content is gone. To actually publish it you'd need to copy the JSON and hit `/api/posts` manually. This path is effectively broken as a workflow.

**Path 3: Scheduled drafts** (`generate_daily_drafts()` at 02:00 UTC) — Picks 3 random topics, calls Claude, saves to `drafts` table, admin reviews at `/admin/drafts`. This is the only complete end-to-end pipeline.

---

## Problems

**1. On-demand generation is a dead end.** The response just floats away. It should save to drafts first, let you review, then approve.

**2. No draft editing.** Only approve or delete. If Claude writes something 80% good, you can't fix the remaining 20% — you delete and start over.

**3. Generic system prompt.** `"You are a technical blog post writer."` The generated posts will be corporate-bland. The site's whole tone is sarcastic, deploy-fail-fix, caffeine-fueled. Claude doesn't know that.

**4. ~~Topics get reused without tracking.~~** ✓ Fixed — topics with existing drafts (pending or approved) are now skipped during generation. Deleting a rejected draft returns the topic to the pool.

**5. Slug collision with no escape.** The approve endpoint does a 409 if the slug already exists, with no way to rename it. One bad title from Claude can permanently block a draft from being published.

**6. No web UI for anything write-related.** Approving from the admin view probably works, but triggering generation, editing drafts, or managing briefs all require API calls.

---

## Recommendations

### High priority

1. **Route on-demand generation through drafts** — make `generate_from_brief()` save to the `drafts` table instead of returning raw JSON. Then the brief flow and the scheduled flow converge into the same admin review UX.

2. **Add `PATCH /api/drafts/{id}`** with `{title, summary, content, tags}` body + a textarea in `/admin/drafts/{id}` so you can edit before approving. This is the single biggest quality-of-life improvement.

3. **Inject your voice into the system prompt.** Something like: *"You are writing for a personal technical blog. The tone is dry, sarcastic, and self-deprecating — deploy war stories, things that went wrong, lessons earned the hard way. Avoid corporate language. If there's a way to make a point with a deploy-fail-fix joke, take it."*

### Medium priority

4. **Add a trigger button in the admin UI** — a simple `<button hx-post="/api/drafts/generate">Generate drafts</button>` so you don't need curl to kick off generation.

5. ~~**Track generated topic IDs.**~~ ✓ Done — deduplication uses the existing `drafts` table (`topic_id` column). No new tables needed.

6. **Allow slug override on drafts** — add a `slug` field to the draft edit form and use it on approval instead of re-deriving from the title.

### Low priority

7. **Merge briefs and daily topics** — they're the same `PostBrief` model, just used in different contexts. A single `topics.json` with a `scheduled: bool` flag would be cleaner.

8. **Regeneration endpoint** — `POST /api/drafts/{id}/regenerate` that re-runs Claude on the same `topic_id` and replaces the draft content. Useful when output is poor.
