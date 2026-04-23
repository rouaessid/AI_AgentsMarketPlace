"""
validation_repo.py — CRUD for ValidationRegistry + ReputationContract events.

Tables: validation_events, reputation_events
Written by: blockchain_indexer.py ONLY.
Read by: judge_service.py, API dashboard endpoints.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.database import ReputationEvent, ValidationEvent, get_session

logger = logging.getLogger(__name__)


# ── validation_events ────────────────────────────────────────────────────────

def insert_validation_event(
    *,
    event_id:    str,           # f"{tx_hash}-{log_index}"
    task_id:     str,
    event_type:  str,
    # "request"|"judges_assigned"|"vote_committed"|"vote_revealed"|"verdict"|"expired"
    agent_id:    str | None  = None,
    verdict:     str | None  = None,   # "VALID" | "INVALID"
    score:       float | None = None,
    judge_id:    str | None  = None,
    tx_hash:     str | None  = None,
    block_number: int | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as s:
        if s.get(ValidationEvent, event_id):
            return  # idempotent
        s.add(ValidationEvent(
            id=event_id,
            task_id=task_id,
            agent_id=agent_id,
            event_type=event_type,
            verdict=verdict,
            score=score,
            judge_id=judge_id,
            tx_hash=tx_hash,
            block_number=block_number,
            created_at=now,
        ))
        s.commit()
    logger.info("validation_event: %s task=%s type=%s verdict=%s",
                event_id[:12], task_id, event_type, verdict)


def get_validation_events_for_task(task_id: str) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = (
            s.query(ValidationEvent)
            .filter(ValidationEvent.task_id == task_id)
            .order_by(ValidationEvent.block_number)
            .all()
        )
        return [_val_to_dict(r) for r in rows]


def get_final_verdict(task_id: str) -> dict[str, Any] | None:
    """Return the verdict event for a task if it exists."""
    with get_session() as s:
        row = (
            s.query(ValidationEvent)
            .filter(
                ValidationEvent.task_id == task_id,
                ValidationEvent.event_type == "verdict",
            )
            .first()
        )
        return _val_to_dict(row) if row else None


def get_validation_history_for_agent(agent_id: str) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = (
            s.query(ValidationEvent)
            .filter(
                ValidationEvent.agent_id == agent_id,
                ValidationEvent.event_type == "verdict",
            )
            .order_by(ValidationEvent.block_number.desc())
            .all()
        )
        return [_val_to_dict(r) for r in rows]


def _val_to_dict(row: ValidationEvent) -> dict[str, Any]:
    return {
        "id":           row.id,
        "task_id":      row.task_id,
        "agent_id":     row.agent_id,
        "event_type":   row.event_type,
        "verdict":      row.verdict,
        "score":        row.score,
        "judge_id":     row.judge_id,
        "tx_hash":      row.tx_hash,
        "block_number": row.block_number,
        "created_at":   row.created_at,
    }


# ── reputation_events (futur ReputationContract) ─────────────────────────────

def insert_reputation_event(
    *,
    event_id:         str,
    agent_id:         str,
    event_type:       str,
    reputation_score: float | None = None,
    success_rate:     float | None = None,
    tx_hash:          str | None   = None,
    block_number:     int | None   = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as s:
        if s.get(ReputationEvent, event_id):
            return
        s.add(ReputationEvent(
            id=event_id,
            agent_id=agent_id,
            event_type=event_type,
            reputation_score=reputation_score,
            success_rate=success_rate,
            tx_hash=tx_hash,
            block_number=block_number,
            created_at=now,
        ))
        s.commit()
    logger.info("reputation_event: agent=%s type=%s score=%s",
                agent_id, event_type, reputation_score)


def get_latest_reputation(agent_id: str) -> dict[str, Any] | None:
    """Return the most recent reputation event for an agent."""
    with get_session() as s:
        row = (
            s.query(ReputationEvent)
            .filter(ReputationEvent.agent_id == agent_id)
            .order_by(ReputationEvent.block_number.desc())
            .first()
        )
        if not row:
            return None
        return {
            "agent_id":         row.agent_id,
            "event_type":       row.event_type,
            "reputation_score": row.reputation_score,
            "success_rate":     row.success_rate,
            "block_number":     row.block_number,
            "created_at":       row.created_at,
        }
