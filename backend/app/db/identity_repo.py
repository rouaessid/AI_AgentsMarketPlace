"""
identity_repo.py — CRUD for agent_embeddings table + in-memory cache facade.

DB (agent_embeddings): agent_id, capability_embedding
Status et agentURI viennent de The Graph :
  - agent absent du Graph  →  en cours d'enregistrement (pending)
  - agent présent du Graph →  actif
"""
from __future__ import annotations
import logging
from typing import Any

from app.db.database import get_session
from app.entities.agent import AgentEmbedding

logger = logging.getLogger(__name__)


def _cid_from_uri(agent_uri: str | None) -> str | None:
    """Extrait le CID IPFS depuis agentURI ('ipfs://Qm...' → 'Qm...')."""
    if agent_uri and agent_uri.startswith("ipfs://"):
        return agent_uri[len("ipfs://"):]
    return None


# ── DB writes ─────────────────────────────────────────────────────────────────

def upsert_agent_identity(*, agent_id: str, **fields) -> None:
    """
    Insère ou met à jour une ligne dans agent_embeddings.
    Seul capability_embedding est persisté ici.
    Status et ipfs_cid viennent de The Graph.
    """
    allowed  = {"capability_embedding", "registration_status"}
    db_fields = {k: v for k, v in fields.items() if k in allowed}

    with get_session() as s:
        existing = s.get(AgentEmbedding, agent_id)
        if existing:
            for k, v in db_fields.items():
                if v is not None:
                    setattr(existing, k, v)
        else:
            s.add(AgentEmbedding(agent_id=agent_id, **db_fields))
        s.commit()
    logger.debug("identity_repo upsert: %s", agent_id)


def get_all_embeddings() -> list[dict[str, Any]]:
    """Retourne [{agent_id, capability_embedding, registration_status}] pour tous les agents en DB."""
    with get_session() as s:
        return [
            {
                "agent_id":             r.agent_id,
                "capability_embedding": r.capability_embedding,
                "registration_status":  r.registration_status,
            }
            for r in s.query(AgentEmbedding).all()
        ]


def get_embedding(agent_id: str) -> str | None:
    with get_session() as s:
        row = s.get(AgentEmbedding, agent_id)
        return row.capability_embedding if row else None


# ── In-memory cache facade ────────────────────────────────────────────────────

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
