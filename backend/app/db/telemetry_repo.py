"""
telemetry_repo.py — CRUD for agent_telemetry table.

Seule métrique conservée :
  avg_response_time : latence mesurée par le proxy sandbox (pas on-chain)

Tout le reste (tasks_performed, uptime, last_active, etc.) est dérivable
depuis ScoreRecorded via The Graph ou n'est pas mesuré.
"""
from __future__ import annotations
import logging
from typing import Any

from app.db.database import get_session
from app.entities.agent import AgentTelemetry

logger = logging.getLogger(__name__)


def upsert_telemetry(
    agent_id:          str,
    *,
    avg_response_time: float | None = None,
) -> None:
    with get_session() as s:
        row = s.get(AgentTelemetry, agent_id)
        if row is None:
            row = AgentTelemetry(agent_id=agent_id)
            s.add(row)
        if avg_response_time is not None:
            row.avg_response_time = avg_response_time
        s.commit()


def get_telemetry(agent_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        row = s.get(AgentTelemetry, agent_id)
        return _to_dict(row) if row else None


def get_all_telemetry() -> dict[str, dict[str, Any]]:
    with get_session() as s:
        rows = s.query(AgentTelemetry).all()
        return {r.agent_id: _to_dict(r) for r in rows}


def _to_dict(row: AgentTelemetry) -> dict[str, Any]:
    return {
        "agent_id":          row.agent_id,
        "avg_response_time": row.avg_response_time,
    }
