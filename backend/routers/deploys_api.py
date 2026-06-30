"""REST API for deploy history tracking."""

import secrets as _secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from config import read_secret
from db import get_conn
from routers.auth import require_admin

router = APIRouter(prefix="/api/deploys", tags=["deploys"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class DeployIn(BaseModel):
    """Request body for recording a deploy."""
    commit_hash: str
    branch: str = "main"
    status: Literal["success", "failed"]
    duration_s: int | None = None
    triggered_by: str = "makefile"
    notes: str | None = None


class DeployOut(BaseModel):
    """Response body for a deploy record."""
    id: str
    commit_hash: str
    branch: str
    deployed_at: datetime
    status: str
    duration_s: int | None
    triggered_by: str
    notes: str | None


# ─── Auth ─────────────────────────────────────────────────────────────────────

def _verify_deploy_token(x_deploy_token: str | None = Header(None)) -> None:
    """Dependency that enforces a shared-secret deploy token on write requests."""
    expected = read_secret("deploy_token") or ""
    if not x_deploy_token or not expected or not _secrets.compare_digest(x_deploy_token, expected):
        raise HTTPException(status_code=401, detail="Invalid deploy token")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _row_to_deploy_out(row: sqlite3.Row) -> DeployOut:
    d = dict(row)
    return DeployOut(
        id=d["id"],
        commit_hash=d["commit_hash"],
        branch=d["branch"],
        deployed_at=datetime.fromisoformat(d["deployed_at"]),
        status=d["status"],
        duration_s=d.get("duration_s"),
        triggered_by=d["triggered_by"],
        notes=d.get("notes"),
    )


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("", response_model=DeployOut, status_code=201)
def create_deploy(body: DeployIn, _: None = Depends(_verify_deploy_token)) -> DeployOut:
    """Record a deploy (called by the deploy pipeline with a shared secret token)."""
    deploy_id = str(uuid.uuid4())
    deployed_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO deploys (id, commit_hash, branch, deployed_at, status, duration_s, triggered_by, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                deploy_id,
                body.commit_hash,
                body.branch,
                deployed_at,
                body.status,
                body.duration_s,
                body.triggered_by,
                body.notes,
            ),
        )
        row = conn.execute("SELECT * FROM deploys WHERE id = ?", (deploy_id,)).fetchone()
    return _row_to_deploy_out(row)


@router.get("", response_model=list[DeployOut])
def list_deploys(_: None = Depends(require_admin)) -> list[DeployOut]:
    """List deploys, newest first (admin only)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM deploys ORDER BY deployed_at DESC LIMIT 100"
        ).fetchall()
    return [_row_to_deploy_out(r) for r in rows]
