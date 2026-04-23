"""
identity_repo.py — CRUD for the Identity zone.

Tables: agents, agent_versions
Written by: blockchain_indexer.py ONLY (never by agent_service directly).
Read by: agent_service.restore_from_db(), API list/get endpoints.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.database import Agent, AgentVersion, get_session

logger = logging.getLogger(__name__)


# ── agents ──────────────────────────────────────────────────────────────────

def _apply_identity_update(row: "Agent", **kw) -> None:
    """Patch only the non-None / non-zero optional fields onto an existing Agent row."""
    if kw.get("owner_address")    is not None: row.owner_address    = kw["owner_address"]
    if kw.get("current_token_id") is not None: row.current_token_id = kw["current_token_id"]
    if kw.get("docker_image"):                 row.docker_image     = kw["docker_image"]
    if kw.get("tx_hash"):                      row.tx_hash          = kw["tx_hash"]
    if kw.get("block_number")     is not None: row.block_number     = kw["block_number"]
    if kw.get("registered_at"):                row.registered_at    = kw["registered_at"]
    if kw.get("agent_uri"):                    row.agent_uri        = kw["agent_uri"]
    if kw.get("ipfs_cid"):                     row.ipfs_cid         = kw["ipfs_cid"]
    if kw.get("name"):                         row.name             = kw["name"]
    if kw.get("version"):                      row.version          = kw["version"]
    if kw.get("identity_metadata"):            row.identity_metadata = kw["identity_metadata"]
    if kw.get("registration_id"):   row.registration_id   = kw["registration_id"]
    row.status          = kw["status"]
    row.price_per_task  = kw["price_per_task"]
    row.stake_amount    = kw["stake_amount"]
    if kw.get("agent_type") is not None:
        row.agent_type = kw["agent_type"]


def upsert_agent_identity(*, agent_id: str, **fields) -> None:
    """Insert or update a canonical agent identity row.

    Accepted keyword fields (all optional except registration_id):
      registration_id, owner_address, current_token_id, docker_image,
      status (default "active"), tx_hash, block_number, registered_at,
      agent_uri, ipfs_cid, name, version,
      price_per_task (default 0.0), stake_amount (default 0.0),
      identity_metadata
    """
    fields.setdefault("status", "active")
    fields.setdefault("price_per_task", 0.0)
    fields.setdefault("stake_amount", 0.0)
    with get_session() as s:
        existing = s.get(Agent, agent_id)
        if existing:
            _apply_identity_update(existing, **fields)
        else:
            s.add(Agent(agent_id=agent_id, **fields))
        s.commit()
    logger.info("identity_repo upsert: %s tokenId=%s owner=%s",
                agent_id, fields.get("current_token_id"),
                (fields.get("owner_address") or "")[:10])


def get_agent_identity(agent_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        row = s.get(Agent, agent_id)
        if row is None:
            return None
        return _agent_to_dict(row)


def get_all_agent_identities() -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.query(Agent).all()
        return [_agent_to_dict(r) for r in rows]


def get_agents_by_owner(owner_address: str) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = s.query(Agent).filter(
            Agent.owner_address.ilike(owner_address)
        ).all()
        return [_agent_to_dict(r) for r in rows]


def update_agent_status(agent_id: str, status: str) -> None:
    with get_session() as s:
        row = s.get(Agent, agent_id)
        if row:
            row.status = status
            s.commit()


def _agent_to_dict(row: Agent) -> dict[str, Any]:
    return {
        "agent_id":          row.agent_id,
        "registration_id":   row.registration_id,
        "current_token_id":  row.current_token_id,
        "owner_address":     row.owner_address,
        "docker_image":      row.docker_image,
        "status":            row.status,
        "tx_hash":           row.tx_hash,
        "block_number":      row.block_number,
        "registered_at":     row.registered_at,
        "agent_uri":         row.agent_uri,
        "ipfs_cid":          row.ipfs_cid,
        "name":              row.name,
        "version":           row.version,
        "price_per_task":    row.price_per_task,
        "stake_amount":      row.stake_amount,
        "agent_type":        row.agent_type,
        "identity_metadata": row.identity_metadata,
    }


# ── agent_versions ───────────────────────────────────────────────────────────

def upsert_agent_version(
    *,
    token_id:    int,
    agent_id:    str,
    version:     str,
    agent_uri:   str | None = None,
    docker_image: str | None = None,
    block_number: int | None = None,
    minted_at:   str | None  = None,
) -> None:
    """
    Insert or update a version row.
    Called by indexer on AgentCreated (v1) and AgentVersionMinted (v2+).
    """
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as s:
        existing = s.get(AgentVersion, token_id)
        if existing:
            existing.agent_id     = agent_id
            existing.version      = version
            if agent_uri:
                existing.agent_uri = agent_uri
            if docker_image:
                existing.docker_image = docker_image
            if block_number is not None:
                existing.block_number = block_number
        else:
            s.add(AgentVersion(
                token_id=token_id,
                agent_id=agent_id,
                version=version,
                agent_uri=agent_uri,
                docker_image=docker_image,
                block_number=block_number,
                minted_at=minted_at or now,
            ))
        s.commit()
    logger.debug("version upsert: agent=%s tokenId=%d version=%s",
                 agent_id, token_id, version)


def get_versions_for_agent(agent_id: str) -> list[dict[str, Any]]:
    """Return all versions (NFTs) for a given agentId, ordered by token_id."""
    with get_session() as s:
        rows = (
            s.query(AgentVersion)
            .filter(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.token_id)
            .all()
        )
        return [
            {
                "token_id":    r.token_id,
                "agent_id":    r.agent_id,
                "version":     r.version,
                "agent_uri":   r.agent_uri,
                "docker_image": r.docker_image,
                "block_number": r.block_number,
                "minted_at":   r.minted_at,
            }
            for r in rows
        ]
