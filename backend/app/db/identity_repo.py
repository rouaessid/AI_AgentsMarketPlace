"""
identity_repo.py — CRUD for agent_embeddings table + in-memory cache facade.

DB (agent_embeddings): agent_id, capability_embedding, ipfs_cid, status
Rich identity data (name, docker_image, price, token_id, owner...):
  → fetched from IPFS at startup, cached in agent_service._records
  → accessible via get_agent_identity() which reads the in-memory cache
"""
from __future__ import annotations
import logging
from typing import Any

from app.db.database import AgentEmbedding, get_session

logger = logging.getLogger(__name__)


# ── DB writes (agent_embeddings table only) ───────────────────────────────────

def upsert_agent_identity(*, agent_id: str, **fields) -> None:
    """
    Insert or update a row in agent_embeddings.
    Only persists: capability_embedding, ipfs_cid, status.
    All other fields go to IPFS manifest (already uploaded before this call).
    """
    allowed = {"capability_embedding", "ipfs_cid", "status"}
    db_fields = {k: v for k, v in fields.items() if k in allowed}
    db_fields.setdefault("status", "pending_signature")

    with get_session() as s:
        existing = s.get(AgentEmbedding, agent_id)
        if existing:
            for k, v in db_fields.items():
                if v is not None or k == "status":
                    setattr(existing, k, v)
        else:
            s.add(AgentEmbedding(agent_id=agent_id, **db_fields))
        s.commit()
    logger.debug("identity_repo upsert: %s status=%s", agent_id, db_fields.get("status"))


def update_agent_status(agent_id: str, status: str) -> None:
    with get_session() as s:
        row = s.get(AgentEmbedding, agent_id)
        if row:
            row.status = status
            s.commit()


def get_all_embeddings() -> list[dict[str, Any]]:
    """Return raw DB rows (agent_id, capability_embedding, ipfs_cid, status)."""
    with get_session() as s:
        return [
            {
                "agent_id":             r.agent_id,
                "capability_embedding": r.capability_embedding,
                "ipfs_cid":             r.ipfs_cid,
                "status":               r.status,
            }
            for r in s.query(AgentEmbedding).all()
        ]


def get_embedding(agent_id: str) -> str | None:
    with get_session() as s:
        row = s.get(AgentEmbedding, agent_id)
        return row.capability_embedding if row else None


# ── In-memory cache facade (rich identity data) ───────────────────────────────
# These functions read from agent_service._records (populated at startup from IPFS)

def get_agent_identity(agent_id: str) -> dict[str, Any] | None:
    from app.services.agent_service import get_agent_from_cache
    return get_agent_from_cache(agent_id)


def get_all_agent_identities() -> list[dict[str, Any]]:
    from app.services.agent_service import get_all_agents_from_cache
    return get_all_agents_from_cache()


def get_agents_by_owner(owner_address: str) -> list[dict[str, Any]]:
    from app.services.agent_service import get_all_agents_from_cache
    all_agents = get_all_agents_from_cache()
    return [
        a for a in all_agents
        if (a.get("owner_address") or "").lower() == owner_address.lower()
    ]
