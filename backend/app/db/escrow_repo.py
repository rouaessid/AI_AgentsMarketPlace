"""
escrow_repo.py — CRUD for EscrowManager blockchain events.

Table: escrow_events
Written by: blockchain_indexer.py ONLY.
Read by: API endpoints for payment history / dashboard.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.database import EscrowEvent, get_session

logger = logging.getLogger(__name__)


def insert_escrow_event(
    *,
    event_id:    str,          # f"{tx_hash}-{log_index}"
    task_id:     str,
    event_type:  str,          # "deposited" | "released" | "refunded"
    agent_id:    str | None  = None,
    client:      str | None  = None,
    provider:    str | None  = None,
    amount_wei:  str | None  = None,
    tx_hash:     str | None  = None,
    block_number: int | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as s:
        if s.get(EscrowEvent, event_id):
            return  # idempotent — indexer may replay blocks
        s.add(EscrowEvent(
            id=event_id,
            task_id=task_id,
            event_type=event_type,
            agent_id=agent_id,
            client=client,
            provider=provider,
            amount_wei=amount_wei,
            tx_hash=tx_hash,
            block_number=block_number,
            created_at=now,
        ))
        s.commit()
    logger.info("escrow_event: %s task=%s type=%s", event_id[:12], task_id, event_type)


def get_escrow_events_for_task(task_id: str) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = (
            s.query(EscrowEvent)
            .filter(EscrowEvent.task_id == task_id)
            .order_by(EscrowEvent.block_number)
            .all()
        )
        return [_to_dict(r) for r in rows]


def get_escrow_events_for_agent(agent_id: str) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = (
            s.query(EscrowEvent)
            .filter(EscrowEvent.agent_id == agent_id)
            .order_by(EscrowEvent.block_number.desc())
            .all()
        )
        return [_to_dict(r) for r in rows]


def get_last_task_status(task_id: str) -> str | None:
    """Return the latest event_type for a task (= current status)."""
    events = get_escrow_events_for_task(task_id)
    if not events:
        return None
    order = {"deposited": 0, "released": 1, "refunded": 1}
    latest = max(events, key=lambda e: order.get(e["event_type"], 0))
    return latest["event_type"]


def _to_dict(row: EscrowEvent) -> dict[str, Any]:
    return {
        "id":           row.id,
        "task_id":      row.task_id,
        "event_type":   row.event_type,
        "agent_id":     row.agent_id,
        "client":       row.client,
        "provider":     row.provider,
        "amount_wei":   row.amount_wei,
        "tx_hash":      row.tx_hash,
        "block_number": row.block_number,
        "created_at":   row.created_at,
    }
