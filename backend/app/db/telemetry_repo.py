"""
telemetry_repo.py — CRUD for the Telemetry zone.

Table: agent_telemetry
Written by: backend runtime ONLY (agent_service.update_run_metrics, health checks).
NEVER written by the blockchain indexer.

Note: reputation_score and success_rate are temporary placeholders here.
They will move entirely to reputation_events once ReputationContract is deployed.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.database import AgentTelemetry, get_session

logger = logging.getLogger(__name__)


def get_telemetry(agent_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        row = s.get(AgentTelemetry, agent_id)
        return _to_dict(row) if row else None


def upsert_telemetry(
    agent_id: str,
    *,
    tasks_performed:      int   | None = None,
    usage_count:          int   | None = None,
    avg_response_time:    float | None = None,
    task_completion_rate: float | None = None,
    uptime:               float | None = None,
    last_active:          str   | None = None,
    monthly_tasks:        list  | None = None,
    weekly_success:       list  | None = None,
    # Temporary reputation fields (until ReputationContract)
    reputation_score:     float | None = None,
    success_rate:         float | None = None,
    val_count:            int   | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as s:
        row = s.get(AgentTelemetry, agent_id)
        if row is None:
            row = AgentTelemetry(agent_id=agent_id)
            s.add(row)

        if tasks_performed is not None:
            row.tasks_performed = tasks_performed
        if usage_count is not None:
            row.usage_count = usage_count
        if avg_response_time is not None:
            row.avg_response_time = avg_response_time
        if task_completion_rate is not None:
            row.task_completion_rate = task_completion_rate
        if uptime is not None:
            row.uptime = uptime
        row.last_active = last_active or now
        if monthly_tasks is not None:
            row.monthly_tasks_json = json.dumps(monthly_tasks)
        if weekly_success is not None:
            row.weekly_success_json = json.dumps(weekly_success)
        if reputation_score is not None:
            row.reputation_score = reputation_score
        if success_rate is not None:
            row.success_rate = success_rate
        if val_count is not None:
            row.val_count = val_count

        s.commit()


def get_all_telemetry() -> dict[str, dict[str, Any]]:
    """Return {agent_id: telemetry_dict} for all agents."""
    with get_session() as s:
        rows = s.query(AgentTelemetry).all()
        return {r.agent_id: _to_dict(r) for r in rows}


def _to_dict(row: AgentTelemetry) -> dict[str, Any]:
    return {
        "agent_id":             row.agent_id,
        "tasks_performed":      row.tasks_performed or 0,
        "usage_count":          row.usage_count or 0,
        "avg_response_time":    row.avg_response_time,
        "task_completion_rate": row.task_completion_rate,
        "uptime":               row.uptime,
        "last_active":          row.last_active,
        "monthly_tasks":        json.loads(row.monthly_tasks_json) if row.monthly_tasks_json else [0]*12,
        "weekly_success":       json.loads(row.weekly_success_json) if row.weekly_success_json else [0]*7,
        "reputation_score":     row.reputation_score or 0.0,
        "success_rate":         row.success_rate or 0.0,
        "val_count":            row.val_count or 0,
    }
