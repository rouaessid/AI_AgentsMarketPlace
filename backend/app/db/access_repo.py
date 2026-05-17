from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
from app.db.database import get_connection


# ── Access Grants ─────────────────────────────────────────────────────────────

def create_access_grant(
    agent_id:     str,
    buyer_wallet: str,
    task_id:      str,
    paid_wei:     str = "0",
    tx_hash:      str | None = None,
) -> str:
    """Insert a new access grant and return its id."""
    grant_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO access_grants
               (id, agent_id, buyer_wallet, task_id, paid_wei, tx_hash, status, granted_at)
               VALUES (?, ?, ?, ?, ?, ?, 'granted', ?)""",
            (grant_id, agent_id, buyer_wallet.lower(), task_id, paid_wei, tx_hash, now),
        )
        conn.commit()
    finally:
        conn.close()
    return grant_id


def has_any_access_grant(buyer_wallet: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM access_grants WHERE LOWER(buyer_wallet) = LOWER(?) LIMIT 1",
            (buyer_wallet,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_access_grant(agent_id: str, buyer_wallet: str) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT * FROM access_grants
               WHERE agent_id = ? AND LOWER(buyer_wallet) = LOWER(?)
               ORDER BY granted_at DESC LIMIT 1""",
            (agent_id, buyer_wallet),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_access_grant_by_task(task_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM access_grants WHERE task_id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── Validation Sessions ───────────────────────────────────────────────────────

def upsert_validation_session(
    agent_id:         str,
    val_task_id:      str | None = None,
    status:           str = "pending",
    consensus_verdict: str | None = None,
    aggregated_score: int | None = None,
    started_at:       str | None = None,
    finished_at:      str | None = None,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO validation_sessions
               (agent_id, val_task_id, status, consensus_verdict,
                aggregated_score, started_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                   val_task_id       = excluded.val_task_id,
                   status            = excluded.status,
                   consensus_verdict = excluded.consensus_verdict,
                   aggregated_score  = excluded.aggregated_score,
                   started_at        = CASE WHEN excluded.started_at IS NOT NULL THEN excluded.started_at ELSE validation_sessions.started_at END,
                   finished_at       = excluded.finished_at""",
            (agent_id, val_task_id, status, consensus_verdict,
             aggregated_score, started_at, finished_at),
        )
        conn.commit()
    finally:
        conn.close()


def get_validation_session(agent_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM validation_sessions WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── Judge Verdicts ────────────────────────────────────────────────────────────

def insert_judge_verdict(
    agent_id:      str,
    judge_id:      str,
    judge_name:    str,
    score:         int,
    justification: str,
    verdict:       str,
) -> None:
    verdict_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO judge_verdicts
               (id, agent_id, judge_id, judge_name, score, justification, verdict, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (verdict_id, agent_id, judge_id, judge_name, score, justification, verdict, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_judge_verdicts(agent_id: str) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM judge_verdicts WHERE agent_id = ? ORDER BY created_at",
            (agent_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def clear_judge_verdicts(agent_id: str) -> None:
    """Remove old verdicts before a fresh validation run."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM judge_verdicts WHERE agent_id = ?", (agent_id,))
        conn.commit()
    finally:
        conn.close()


def reset_stale_validations() -> int:
    """
    Called on backend startup.
    Any session stuck in 'pending' or 'in_progress' was orphaned when the
    process restarted (background task is gone). Reset them to 'awaiting_run'
    so the buyer can trigger a fresh run instead of seeing an infinite spinner.
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """UPDATE validation_sessions
               SET status = 'awaiting_run', val_task_id = NULL,
                   started_at = NULL, finished_at = NULL
               WHERE status IN ('pending', 'in_progress')""",
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
