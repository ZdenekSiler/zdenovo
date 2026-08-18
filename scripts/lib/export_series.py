#!/usr/bin/env python3
"""Export one series row from a SQLite DB to a JSON file. Runs DEV-side (read-only).

The series table is a flat (id, title, description, created_at) row — parts are linked
by drafts.series_id / posts.series_id, not by a child table — so a single row is a
complete, portable series header.

Usage: export_series.py <db_path> <series_id> <out_json>
"""
import json
import sqlite3
import sys


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    db_path, series_id, out_json = sys.argv[1], sys.argv[2], sys.argv[3]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
    if row is None:
        sys.exit(f"no series {series_id!r} in {db_path}")

    data = {k: row[k] for k in row.keys()}
    parts = conn.execute(
        "SELECT series_order, title FROM drafts WHERE series_id = ?"
        " UNION ALL SELECT series_order, title FROM posts WHERE series_id = ?"
        " ORDER BY series_order",
        (series_id, series_id),
    ).fetchall()

    with open(out_json, "w") as fh:
        json.dump(data, fh)

    print(f"exported {len(data)} columns -> {out_json}")
    print(f"  id:    {data['id']}")
    print(f"  title: {data['title']}")
    print(f"  parts on dev: {len(parts)}")
    for p in parts:
        print(f"    {p['series_order']}. {p['title']}")


if __name__ == "__main__":
    main()
