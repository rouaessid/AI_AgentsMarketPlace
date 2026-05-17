"""
collaboration_repo.py — DB helpers for collaboration_log table.

Written ONLY by blockchain_indexer.py (ScoreRecorded events from ValidationRegistry).
Read by eigentrust_service.py to compute C[i][j] via ATE.

This table is a cache — fully rebuildable from on-chain ScoreRecorded events.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from app.db.database import CollaborationLog, get_session

logger = logging.getLogger(__name__)


def insert_collaboration_score(
    event_id:     str,
    agent_id:     str,
    task_id:      str,
    score:        float,
    mode:         int,      # 0 = solo, 1 = pipeline
    tx_hash:      str = "",
    block_number: int = 0,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as s:
        if s.get(CollaborationLog, event_id):
            return
        s.add(CollaborationLog(
            id=event_id,
            agent_id=agent_id,
            task_id=task_id,
            score=score,
            mode=mode,
            tx_hash=tx_hash,
            block_number=block_number,
            created_at=now,
        ))
        s.commit()


def get_solo_scores(agent_id: str) -> list[float]:
    """Return all solo task scores for agent_id (mode=0), ordered by block."""
    with get_session() as s:
        rows = (
            s.query(CollaborationLog)
            .filter_by(agent_id=agent_id, mode=0)
            .order_by(CollaborationLog.block_number)
            .all()
        )
        return [r.score for r in rows]


def get_pipeline_scores(agent_id: str) -> list[float]:
    """Return all pipeline task scores for agent_id (mode=1), ordered by block."""
    with get_session() as s:
        rows = (
            s.query(CollaborationLog)
            .filter_by(agent_id=agent_id, mode=1)
            .order_by(CollaborationLog.block_number)
            .all()
        )
        return [r.score for r in rows]
