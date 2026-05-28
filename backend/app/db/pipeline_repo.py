"""
pipeline_repo.py — CRUD pour PipelineTask (PostgreSQL via SQLAlchemy ORM).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.database import PipelineTask, get_session

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_pipeline_task(
    task_id:      str,
    task_prompt:  str,
    mode:         str,
    buyer_wallet: str = "",
) -> None:
    with get_session() as s:
        s.add(PipelineTask(
            id=task_id, task_prompt=task_prompt, mode=mode,
            status="planning", buyer_wallet=buyer_wallet, created_at=_now(),
        ))
        s.commit()


def update_pipeline_task(task_id: str, **kwargs: Any) -> None:
    if not kwargs:
        return
    with get_session() as s:
        row = s.get(PipelineTask, task_id)
        if not row:
            logger.warning("update_pipeline_task: task %s not found", task_id)
            return
        for k, v in kwargs.items():
            setattr(row, k, json.dumps(v) if isinstance(v, (dict, list)) else v)
        s.commit()


def get_pipeline_task(task_id: str) -> dict | None:
    with get_session() as s:
        row = s.get(PipelineTask, task_id)
        if not row:
            return None
        data = {c.name: getattr(row, c.name) for c in PipelineTask.__table__.columns}
        for field in ("plan_json", "selected_agents_json", "steps_json"):
            raw = data.get(field)
            if raw:
                try:
                    data[field] = json.loads(raw)
                except Exception:
                    pass
        return data


def reset_stale_pipeline_tasks() -> int:
    with get_session() as s:
        count = (
            s.query(PipelineTask)
            .filter(PipelineTask.status.in_(["executing", "validating"]))
            .update({"status": "failed"}, synchronize_session=False)
        )
        s.commit()
        return count


def list_pipeline_tasks(buyer_wallet: str | None = None, limit: int = 50) -> list[dict]:
    with get_session() as s:
        q = s.query(PipelineTask).order_by(PipelineTask.created_at.desc())
        if buyer_wallet:
            q = q.filter(PipelineTask.buyer_wallet == buyer_wallet)
        rows = q.limit(limit).all()
        return [{c.name: getattr(r, c.name) for c in PipelineTask.__table__.columns} for r in rows]
