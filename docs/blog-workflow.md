# Blog Post Workflow

Three ways to get a post onto the blog. All generated content goes through a draft review
step before publishing — nothing Claude writes lands directly in production.

---

## Path 1 — Generate from a brief (on-demand)

Use this when you want to write a specific post from a pre-defined brief.

```bash
# List available briefs
curl http://localhost:8000/api/posts/briefs

# Trigger generation for a specific brief
curl -X POST http://localhost:8000/api/posts/generate/claude-code-repo-best-practices
```

Response is a draft object:
```json
{
  "id": "c62f2d7d-33b0-4a91-9a99-8ce3640c60fb",
  "slug": "structuring-a-claude-code-repository-for-maximum-ai-leverage",
  "title": "Structuring a Claude Code Repository for Maximum AI Leverage",
  "status": "pending",
  "topic_id": "claude-code-repo-best-practices",
  ...
}
```

The draft is now at `/admin/drafts` for review.

**Briefs live in:** `backend/data/post_briefs.json`

Each brief has:
- `id` — used in the URL
- `title_hint` — suggested title for Claude
- `description` — what the post should cover
- `audience` — who is reading it
- `tone` — writing style
- `tags` — suggested tags
- `outline` — required sections

---

## Path 2 — Generate from a free-form description (on-demand)

Use this for one-off posts without a stored brief.

```bash
curl -X POST http://localhost:8000/api/posts/generate \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Why SQLite is actually fine in production for small-to-medium apps, and when to stop worrying and ship it",
    "tags": ["sqlite", "production", "databases"]
  }'
```

Same response shape as Path 1. Saved as a draft with `topic_id: "freeform"`.

---

## Path 3 — Scheduled daily drafts

Every day at 02:00 UTC, the scheduler picks 3 random topics from `backend/data/daily_topics.json`
and generates drafts automatically. No action needed.

To trigger manually (same logic as the scheduler):

```bash
curl -X POST http://localhost:8000/api/drafts/generate
# → {"generated": 3}
```

Or click **"Generate today's drafts"** button at `/admin/drafts`.

**Topics live in:** `backend/data/daily_topics.json` — same format as briefs.

---

## Reviewing and publishing drafts

All three paths land in the drafts queue.

**Admin UI:** http://localhost:8000/admin/drafts

### Preview a draft
```
GET /admin/drafts/{id}
```
Shows rendered Markdown, tags, reading time, and the edit form.

### Edit before publishing
On the draft preview page, scroll down to the **"Edit before publishing"** form.
Change title, summary, tags (comma-separated), or the Markdown content, then save.

Or via API:
```bash
curl -X PATCH http://localhost:8000/api/drafts/{id} \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Better title",
    "tags": ["sqlite", "production"]
  }'
```
Only the fields you send are updated; others stay as-is.

### Approve (publish)
```bash
curl -X POST http://localhost:8000/api/drafts/{id}/approve
```
Copies the draft into the `posts` table. The post immediately appears on `/blog`.

Or click **"Approve & Publish"** on the draft preview page.

### Reject (delete)
```bash
curl -X DELETE http://localhost:8000/api/drafts/{id}
```
Or click **"Reject"** on the draft preview page.

---

## Voice and tone

All generation uses this system prompt (in `routers/generate_api.py`):

> You are writing for a personal technical blog run by Zdenek, a software engineer and
> consultant. The tone is dry, sarcastic, and self-deprecating — think deploy war stories,
> things that went wrong, and lessons earned the hard way. Avoid corporate language and
> buzzword-heavy intros. If there's a way to make a point with a deploy-fail-fix analogy
> or a dark joke about production, take it. Write like someone who has been paged at 3am
> and has opinions about it.

---

## Full flow summary

```
Brief / description / scheduled topic
        │
        ▼
  Claude (claude-sonnet-4-6)
  forced write_post tool use
        │
        ▼
  drafts table (status: pending)
        │
        ├── /admin/drafts      ← list view
        ├── /admin/drafts/{id} ← preview + edit form
        │
        ▼
  Approve → posts table → live on /blog
  Reject  → deleted
```

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/posts/briefs` | List stored briefs |
| `POST` | `/api/posts/generate` | Generate from free-form description → draft |
| `POST` | `/api/posts/generate/{brief_id}` | Generate from brief → draft |
| `POST` | `/api/drafts/generate` | Trigger daily batch (3 random topics) → drafts |
| `GET` | `/api/drafts` | List all drafts |
| `GET` | `/api/drafts/{id}` | Get single draft |
| `PATCH` | `/api/drafts/{id}` | Edit draft fields |
| `POST` | `/api/drafts/{id}/approve` | Publish draft to live blog |
| `DELETE` | `/api/drafts/{id}` | Delete draft |
