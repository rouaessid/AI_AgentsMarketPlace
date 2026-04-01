from __future__ import annotations
import logging
from typing import Any
from app.db.database import get_connection

logger = logging.getLogger(__name__)


def upsert_agent(
    agent_id:        str,
    registration_id: str,
    token_id:        int | None,
    tx_hash:         str | None,
    docker_image:    str | None,
    status:          str = "active",
    registered_at:   str | None = None,
    owner_address:   str = "",
) -> None:
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO agents
                (agent_id, registration_id, token_id, tx_hash,
                 docker_image, status, registered_at, owner_address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                registration_id = excluded.registration_id,
                token_id        = excluded.token_id,
                tx_hash         = excluded.tx_hash,
                docker_image    = excluded.docker_image,
                status          = excluded.status,
                registered_at   = excluded.registered_at,
                owner_address   = excluded.owner_address
        """, (agent_id, registration_id, token_id, tx_hash,
              docker_image, status, registered_at, owner_address))
        conn.commit()
        logger.info("DB upsert: %s tokenId=%s owner=%s",
                    agent_id, token_id, owner_address[:10] if owner_address else "")
    finally:
        conn.close()


def get_all_agents() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM agents").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_agent(agent_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_agents_by_owner(owner_address: str) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM agents WHERE LOWER(owner_address) = LOWER(?)",
            (owner_address,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_status(agent_id: str, status: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE agents SET status = ? WHERE agent_id = ?",
            (status, agent_id)
        )
        conn.commit()
    finally:
        conn.close()


def delete_all() -> None:
    """Dev only — vider la table."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM agents")
        conn.commit()
    finally:
        conn.close()