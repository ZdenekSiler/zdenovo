# Database Operations

## Overview

The app uses SQLite (`blog.db`). Dev and prod have different storage strategies:

| Environment | Storage | Location | Direct host access |
|-------------|---------|----------|--------------------|
| **Dev** | Bind mount | `./data/blog.db` on host | Yes — edit directly |
| **Prod** | Docker named volume | `backend_db_data:/data/blog.db` | No — use `docker compose cp` |

## Dev: Working with the Database

### Open in GUI

```bash
sqlitebrowser ./data/blog.db
```

Changes are **instant** — the app and sqlitebrowser share the same file. Just refresh the browser to see updates.

### Query via CLI

```bash
sqlite3 ./data/blog.db

# List posts
SELECT slug, title, date FROM posts ORDER BY date DESC;

# Update a post title
UPDATE posts SET title = 'New Title' WHERE slug = 'my-post';

# Delete a post
DELETE FROM posts WHERE slug = 'my-post';

# List drafts
SELECT id, title, status FROM drafts;
```

### Via the REST API

```bash
# List posts
curl http://localhost:8080/api/posts

# Delete a post
curl -X DELETE http://localhost:8080/api/posts/<slug>

# Update a post
curl -X PUT http://localhost:8080/api/posts/<slug> \
  -H "Content-Type: application/json" \
  -d '{"title":"New Title","summary":"...","tags":["python"],"content":"...","date":"2026-01-01"}'

# List drafts
curl http://localhost:8080/api/drafts

# Approve a draft (publishes it)
curl -X POST http://localhost:8080/api/drafts/<id>/approve

# Delete a draft
curl -X DELETE http://localhost:8080/api/drafts/<id>
```

### Restart behavior

On startup, `init_db()` in `db.py`:
- Creates tables if they don't exist
- Runs schema migrations (adds new columns)
- Seeds posts from `seed_posts.json` **only if the posts table is completely empty**

If at least one post exists, seed data is skipped.

---

## Prod: Working with the Database

The prod DB lives inside a Docker named volume (`db_data`), not directly on the host filesystem. You can't open it with sqlitebrowser directly.

### Copy DB out for inspection

```bash
# On the server
docker compose -f docker-compose.prod.yml cp web:/data/blog.db ./blog_backup.db
sqlite3 ./blog_backup.db "SELECT slug, title FROM posts;"
```

### Modify and copy back

```bash
# 1. Copy out
docker compose -f docker-compose.prod.yml cp web:/data/blog.db ./blog_edit.db

# 2. Edit
sqlite3 ./blog_edit.db "UPDATE posts SET title = 'Fixed Title' WHERE slug = 'my-post';"

# 3. Copy back
docker compose -f docker-compose.prod.yml cp blog_edit.db web:/data/blog.db

# 4. Clean up
rm blog_edit.db
```

Changes take effect immediately — SQLite reads from disk on each query.

### Via the REST API (preferred for prod)

Same API commands as dev, but against the prod URL:

```bash
curl -X DELETE https://yourdomain.com/api/posts/<slug>
```

The API is the safest way to modify prod data — it respects validation and won't corrupt the schema.

### Moving a draft (or fixing a hero image) dev → prod

A generated draft is a **row**, not a file, so `make prod` (git pull + rebuild) never carries
it over. To copy the exact reviewed draft into the prod DB — or swap a wrong hero image — use
the annotated **[draft dev→prod playbook](playbooks/draft-dev-to-prod.md)** and its runnable
wrapper `scripts/draft-to-prod.sh`:

```bash
./scripts/draft-to-prod.sh copy <draft_id>                        # dev row → prod drafts table
./scripts/draft-to-prod.sh set-image <draft_id> "<query>" [id]    # replace hero image (dev + prod)
DRY_RUN=1 ./scripts/draft-to-prod.sh copy <draft_id>             # print the commands, run nothing
```

Both back up `blog.db` before writing. The playbook explains every `docker compose cp`/`exec -T`
step and the secret-handling rules.

### Backup

```bash
# Manual backup
docker compose -f docker-compose.prod.yml cp web:/data/blog.db ./backups/blog_$(date +%Y%m%d).db

# Verify backup
sqlite3 ./backups/blog_*.db "SELECT COUNT(*) FROM posts;"
```

### Restore from backup

```bash
docker compose -f docker-compose.prod.yml cp ./backups/blog_20260620.db web:/data/blog.db
```

---

## Schema

```
posts:    slug (PK), title, date, summary, tags (JSON), content, image, sources (JSON),
          series_id, series_order
drafts:   id (PK/UUID), slug, title, date, summary, tags (JSON), content, image,
          generated_at, topic_id, status, quality_score, quality_issues (JSON),
          quality_strengths (JSON), admin_remarks, sources (JSON), series_id,
          series_order, gen_cost_usd
comments: id (PK/UUID), post_slug, author, body, created_at
```

> **Schema drift to know about:** the dev DB may carry an extra `drafts.related_posts` column
> that prod lacks. The `copy` playbook intersects columns, so it just drops that field on
> transfer — harmless. `init_db()` in `db.py` migrates each environment independently via
> `ALTER TABLE`, so column sets can differ until both have restarted on the same code.

## Danger Zone

- `docker compose down -v` **deletes the named volume** and all data. Use `docker compose down` (without `-v`) to stop containers while keeping data.
- If you delete all posts from the DB and restart the container, seed data from `seed_posts.json` will be re-inserted automatically.
- SQLite doesn't support concurrent writes well. Don't run multiple processes writing to the same DB file simultaneously.
