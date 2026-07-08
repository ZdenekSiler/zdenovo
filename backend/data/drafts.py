from db import draft_row_to_dict, get_conn


def get_drafts(status: str | None = None) -> list[dict]:
    """List drafts, optionally filtered by status. status=None returns all."""
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM drafts WHERE status = ? ORDER BY generated_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM drafts ORDER BY generated_at DESC").fetchall()
    return [draft_row_to_dict(r) for r in rows]


def get_draft_status_counts() -> dict:
    """Draft counts per status, for the admin filter pills. Only 'pending' and
    'approved' are ever persisted — rejecting a draft deletes the row rather than
    setting a 'rejected' status."""
    with get_conn() as conn:
        rows = conn.execute("SELECT status, COUNT(*) as n FROM drafts GROUP BY status").fetchall()
    counts = {row["status"]: row["n"] for row in rows}
    return {"pending": counts.get("pending", 0), "approved": counts.get("approved", 0), "all": sum(counts.values())}
