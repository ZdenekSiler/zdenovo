#!/usr/bin/env python3
"""Insert one draft row (from JSON) into the drafts table. Runs INSIDE the prod container.

Safe by construction:
  - backs up the DB (SQLite online backup) before any write
  - only touches columns present in BOTH the JSON and the live table (tolerates schema drift,
    e.g. dev has a `related_posts` column that prod does not)
  - INSERT OR REPLACE keyed on id, so re-running is idempotent

The DB path is DB_DIR/blog.db (DB_DIR=/data inside the prod container).

Usage: insert_draft.py <row_json>
"""
import json
import os
import sqlite3
import sys
import time

DB = os.path.join(os.environ.get("DB_DIR", "/data"), "blog.db")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with open(sys.argv[1]) as fh:
        row = json.load(fh)
    draft_id = row["id"]

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # 1) Backup (online backup API — safe even while the app holds the DB open)
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_path = f"{DB}.pre-insert-{ts}.bak"
    with sqlite3.connect(backup_path) as bck:
        conn.backup(bck)
    print(f"backup: {backup_path} ({os.path.getsize(backup_path)} bytes)")

    # 2) Column intersection — defensive against schema drift between dev and prod
    table_cols = [r[1] for r in conn.execute("PRAGMA table_info(drafts)")]
    cols = [c for c in table_cols if c in row]
    ignored = [c for c in row if c not in table_cols]
    if ignored:
        print(f"note: JSON keys not in prod table (ignored): {ignored}")

    # 3) Insert
    placeholders = ",".join("?" for _ in cols)
    collist = ",".join(cols)
    values = [row[c] for c in cols]
    before = conn.execute(
        "SELECT COUNT(*) FROM drafts WHERE id = ?", (draft_id,)
    ).fetchone()[0]
    conn.execute(
        f"INSERT OR REPLACE INTO drafts ({collist}) VALUES ({placeholders})", values
    )
    conn.commit()

    # 4) Verify
    chk = conn.execute(
        "SELECT id, status, quality_score, title FROM drafts WHERE id = ?", (draft_id,)
    ).fetchone()
    total = conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
    conn.close()

    if not chk:
        sys.exit("FAIL: row not present after insert")
    print(f"was_present_before: {bool(before)}")
    print(f"inserted: id={chk['id']} status={chk['status']} score={chk['quality_score']}")
    print(f"title: {chk['title']}")
    print(f"total_drafts_now: {total}")
    print("OK")


if __name__ == "__main__":
    main()
