#!/usr/bin/env python3
"""Update one draft's hero image. Backs up the DB first.

Works both DEV-side (run locally with DB_DIR pointing at ./data) and INSIDE the prod
container (DB_DIR=/data) — same code, same DB layout.

Usage: update_draft_image.py <draft_id> <image_url_file>
  (the URL is read from a file, not argv, so a long URL full of '&' never has to be
   shell-escaped)
"""
import os
import sqlite3
import sys
import time

DB = os.path.join(os.environ.get("DB_DIR", "/data"), "blog.db")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    draft_id = sys.argv[1]
    image = open(sys.argv[2]).read().strip()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{DB}.pre-img-{ts}.bak"
    with sqlite3.connect(backup) as bck:
        conn.backup(bck)
    print(f"backup: {backup} ({os.path.getsize(backup)} bytes)")

    before = conn.execute(
        "SELECT image FROM drafts WHERE id = ?", (draft_id,)
    ).fetchone()
    if not before:
        sys.exit(f"FAIL: no draft {draft_id!r}")
    print("old image:", (before["image"] or "")[:70])

    conn.execute("UPDATE drafts SET image = ? WHERE id = ?", (image, draft_id))
    conn.commit()
    after = conn.execute(
        "SELECT image FROM drafts WHERE id = ?", (draft_id,)
    ).fetchone()["image"]
    conn.close()

    print("new image:", after[:70])
    print("OK" if after == image else "FAIL: mismatch")


if __name__ == "__main__":
    main()
