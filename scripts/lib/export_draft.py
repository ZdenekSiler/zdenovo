#!/usr/bin/env python3
"""Export one draft row from a SQLite DB to a JSON file. Runs DEV-side (read-only).

The drafts table is self-contained (sources/tags/quality live on the row as JSON
columns — there are no child tables and no foreign keys), so a single row is a
complete, portable draft.

Usage: export_draft.py <db_path> <draft_id> <out_json>
"""
import json
import sqlite3
import sys


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    db_path, draft_id, out_json = sys.argv[1], sys.argv[2], sys.argv[3]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        sys.exit(f"no draft {draft_id!r} in {db_path}")

    data = {k: row[k] for k in row.keys()}
    with open(out_json, "w") as fh:
        json.dump(data, fh)

    print(f"exported {len(data)} columns -> {out_json}")
    print(f"  title:  {data['title']}")
    print(f"  status: {data['status']}  score: {data.get('quality_score')}")


if __name__ == "__main__":
    main()
