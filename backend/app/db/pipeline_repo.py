"""
pipeline_repo.py — CRUD pour PipelineTask.

Zone opérationnelle : écrit par backend runtime (planner/execution services).
Les scores finaux sont toujours committés on-chain via ScoreRecorded séparément.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.database import get_connection

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_pipeline_task(
    task_id:      str,
    task_prompt:  str,
    mode:         str,
    buyer_wallet: str = "",
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO pipeline_tasks
                (id, task_prompt, mode, status, buyer_wallet, created_at)
            VALUES (?, ?, ?, 'planning', ?, ?)
            """,
            (task_id, task_prompt, mode, buyer_wallet, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def update_pipeline_task(task_id: str, **kwargs: Any) -> None:
    """
    Met à jour n'importe quel champ de pipeline_tasks.
    kwargs : status, plan_json, selected_agents_json, steps_json,
             final_output, val_task_id, finished_at
    Les valeurs dict/list sont auto-sérialisées en JSON.
    """
    if not kwargs:
        return

    sets, vals = [], []
    for k, v in kwargs.items():
        sets.append(f"{k} = ?")
        vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)

    vals.append(task_id)
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE pipeline_tasks SET {', '.join(sets)} WHERE id = ?",
            vals,
        )
        conn.commit()
    finally:
        conn.close()


def get_pipeline_task(task_id: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM pipeline_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        for field in ("plan_json", "selected_agents_json", "steps_json"):
            raw = data.get(field)
            if raw:
                try:
                    data[field] = json.loads(raw)
                except Exception:
                    pass
        return data
    finally:
        conn.close()


def reset_stale_pipeline_tasks() -> int:
    """
    Called on backend startup.
    Any task stuck in 'executing' was orphaned when the process restarted.
    Reset to 'failed' so the buyer can re-run.
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE pipeline_tasks SET status = 'failed' WHERE status IN ('executing', 'validating')"
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def list_pipeline_tasks(buyer_wallet: str | None = None, limit: int = 50) -> list[dict]:
    conn = get_connection()
    try:
        if buyer_wallet:
            rows = conn.execute(
                "SELECT * FROM pipeline_tasks WHERE buyer_wallet = ? ORDER BY created_at DESC LIMIT ?",
                (buyer_wallet, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pipeline_tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
