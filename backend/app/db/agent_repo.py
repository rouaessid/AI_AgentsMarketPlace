"""
agent_repo.py — Compatibility shim + indexer_state helpers.

All identity writes now go through identity_repo.py.
All telemetry writes go through telemetry_repo.py.

This module is kept for:
  1. Backward-compat calls from agent_service.py (during transition)
  2. IndexerState CRUD (last processed block per contract)
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.database import IndexerState, get_session
from app.db.identity_repo import (
    get_agent_identity,
    get_all_agent_identities,
    update_agent_status,
    upsert_agent_identity,
)

logger = logging.getLogger(__name__)


# ── Backward-compat wrappers (called by agent_service during transition) ──────

def upsert_agent(
    agent_id:        str,
    registration_id: str,
    token_id:        int | None   = None,
    tx_hash:         str | None   = None,
    docker_image:    str | None   = None,
    status:          str          = "active",
    registered_at:   str | None   = None,
    owner_address:   str          = "",
    metadata:        str | None   = None,   # legacy — stored as identity_metadata
) -> None:
    """
    Compatibility wrapper → delegates to identity_repo.upsert_agent_identity().
    The `metadata` column (old JSON blob) is stored as identity_metadata for now.
    It will be split into identity_metadata + telemetry once agent_service is refactored.
    """
    upsert_agent_identity(
        agent_id=agent_id,
        registration_id=registration_id,
        current_token_id=token_id,
        tx_hash=tx_hash,
        docker_image=docker_image,
        status=status,
        registered_at=registered_at,
        owner_address=owner_address,
        identity_metadata=metadata,
    )


def get_all_agents() -> list[dict[str, Any]]:
    """Backward-compat: returns list of dicts with legacy key names."""
    rows = get_all_agent_identities()
    return [_to_legacy(r) for r in rows]


def get_agent(agent_id: str) -> dict[str, Any] | None:
    row = get_agent_identity(agent_id)
    return _to_legacy(row) if row else None


def update_status(agent_id: str, status: str) -> None:
    update_agent_status(agent_id, status)


def delete_all() -> None:
    """Dev only."""
    from app.db.database import Agent, get_session
    with get_session() as s:
        s.query(Agent).delete()
        s.commit()


def _to_legacy(row: dict[str, Any]) -> dict[str, Any]:
    """Map new column names to the legacy key names expected by agent_service."""
    return {
        "agent_id":       row["agent_id"],
        "registration_id": row["registration_id"],
        "token_id":       row["current_token_id"],
        "tx_hash":        row["tx_hash"],
        "docker_image":   row["docker_image"],
        "status":         row["status"],
        "registered_at":  row["registered_at"],
        "owner_address":  row["owner_address"],
        "metadata":       row["identity_metadata"],   # legacy consumers expect this key
    }


# ── IndexerState — last processed block per contract ─────────────────────────

def get_last_block(contract_name: str) -> int:
    """Return the last block processed by the indexer for a given contract."""
    with get_session() as s:
        row = s.get(IndexerState, contract_name)
        return row.last_block if row else 0


def set_last_block(contract_name: str, block: int) -> None:
    """Persist the last processed block after each indexer loop."""
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as s:
        row = s.get(IndexerState, contract_name)
        if row:
            row.last_block = block
            row.updated_at = now
        else:
            s.add(IndexerState(
                contract_name=contract_name,
                last_block=block,
                updated_at=now,
            ))
        s.commit()
