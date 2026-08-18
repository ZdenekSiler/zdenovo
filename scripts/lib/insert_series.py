#!/usr/bin/env python3
"""Insert one series row (from JSON) into the series table. Runs INSIDE the prod container.

Why this exists: copying a draft carries its series_id, but not the series row it points
at. Without the header row, /series/{id} 404s and the "Part N of M" strip on each post has
no title to link back to — so a series' parts must be accompanied by this.

Safe by construction (same contract as insert_draft.py):
  - backs up the DB (SQLite online backup) before any write
  - only touches columns present in BOTH the JSON and the live table (tolerates schema drift)
  - INSERT OR REPLACE keyed on id, so re-running is idempotent

The DB path is DB_DIR/blog.db (DB_DIR=/data inside the prod container).

Usage: insert_series.py <row_json>
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
    series_id = row["id"]

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # 1) Backup (online backup API — safe even while the app holds the DB open)
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_path = f"{DB}.pre-series-{ts}.bak"
    with sqlite3.connect(backup_path) as bck:
        conn.backup(bck)
    print(f"backup: {backup_path} ({os.path.getsize(backup_path)} bytes)")

    # 2) Column intersection — defensive against schema drift between dev and prod
    table_cols = [r[1] for r in conn.execute("PRAGMA table_info(series)")]
    cols = [c for c in table_cols if c in row]
    ignored = [c for c in row if c not in table_cols]
    if ignored:
        print(f"note: JSON keys not in prod table (ignored): {ignored}")

    # 3) Insert
    placeholders = ",".join("?" for _ in cols)
    collist = ",".join(cols)
    values = [row[c] for c in cols]
    before = conn.execute(
        "SELECT COUNT(*) FROM series WHERE id = ?", (series_id,)
    ).fetchone()[0]
    conn.execute(
        f"INSERT OR REPLACE INTO series ({collist}) VALUES ({placeholders})", values
    )
    conn.commit()

    # 4) Verify — and report how many parts on THIS db already point at the series
    chk = conn.execute(
        "SELECT id, title FROM series WHERE id = ?", (series_id,)
    ).fetchone()
    pending = conn.execute(
        "SELECT COUNT(*) FROM drafts WHERE series_id = ?", (series_id,)
    ).fetchone()[0]
    published = conn.execute(
        "SELECT COUNT(*) FROM posts WHERE series_id = ?", (series_id,)
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM series").fetchone()[0]
    conn.close()

    if not chk:
        sys.exit("FAIL: row not present after insert")
    print(f"was_present_before: {bool(before)}")
    print(f"inserted: id={chk['id']}")
    print(f"title: {chk['title']}")
    print(f"parts_on_prod: {pending} draft(s), {published} published post(s)")
    print(f"total_series_now: {total}")
    print("OK")


if __name__ == "__main__":
    main()
