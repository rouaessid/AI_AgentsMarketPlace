from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.models.agent import (
    AgentNewVersionRequest, AgentNewVersionResponse,
    AgentOnChainConfirm, AgentRecord, AgentRegistrationEntry,
    AgentRegistrationFile, AgentStatus, AgentSubmitRequest,
    AgentSubmitResponse, AgentVersionInfo, UnsignedTx,
    AgentType,
)
from app.services.ipfs_service import IPFSService
from app.services.ngrok_service import register_agent_endpoint

logger   = logging.getLogger(__name__)
settings = get_settings()

_records:     dict[str, AgentRecord] = {}
_agent_index: dict[str, str]         = {}


def _build_reg_file(req: AgentSubmitRequest) -> AgentRegistrationFile:
    return AgentRegistrationFile(
        name=req.name, description=req.description, version=req.version,
        image=req.image_url, readme=req.readme, services=req.services,
        x402Support=req.x402_support, active=True,
        supportedTrust=req.supported_trust, agent_type=req.agent_type.value,
        capabilities={
            "llm_model": req.llm_model, "framework": req.framework,
            "language": req.language, "max_tokens": req.max_tokens,
            "supported_tasks": req.supported_tasks, "special_caps": req.special_caps,
            "env_var_keys": req.env_var_keys,
        },
        sandbox_config={
            "docker_image": req.docker_image, "cpu_limit": req.cpu_limit,
            "ram_limit_mb": req.ram_limit_mb, "timeout_sec": req.timeout_sec,
            "env_var_keys": req.env_var_keys, "manifest_schema": "default_v1",
        },
        pricing={
            "price_per_task": req.price_per_task,
            "access_duration_days": req.access_duration_days,
            "max_calls_per_day": req.max_calls_per_day, "currency": "USDC",
        },
        stake_amount=req.stake_amount,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def _build_register_tx(req, agent_uri, metadata_hash) -> UnsignedTx:
    return UnsignedTx(
        contract_address=settings.identity_registry_address or "0x_NOT_DEPLOYED",
        function_name="register",
        abi_encoded_args={
            "agentId_": req.agent_id, "agentType_": req.agent_type.to_uint8(),
            "agentURI_": agent_uri, "version_": req.version,
        },
        estimated_gas=300_000, chain_id=settings.chain_id,
    )


def _build_version_tx(agent_id, new_uri, new_version) -> UnsignedTx:
    return UnsignedTx(
        contract_address=settings.identity_registry_address or "0x_NOT_DEPLOYED",
        function_name="mintNewVersion",
        abi_encoded_args={
            "agentId_": agent_id, "newURI_": new_uri, "newVersion_": new_version,
        },
        estimated_gas=250_000, chain_id=settings.chain_id,
    )


async def restore_from_db() -> None:
    from app.db.agent_repo import get_all_agents
    agents = get_all_agents()
    if not agents:
        logger.info("DB vide — aucun agent a charger")
        return
    ipfs_dir = Path(settings.storage_path) / "ipfs_local"
    for a in agents:
        try:
            rid      = a["registration_id"]
            reg_file = None
            if ipfs_dir.exists():
                files = sorted(ipfs_dir.glob("*.json"),
                               key=lambda x: x.stat().st_mtime, reverse=True)
                for f in files:
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        regs = data.get("registrations", [])
                        if any(r.get("agentId") == a["agent_id"] for r in regs):
                            reg_file = AgentRegistrationFile(**data)
                            break
                    except Exception:
                        continue
            name    = reg_file.name    if reg_file else a["agent_id"]
            version = reg_file.version if reg_file else "1.0.0"
            pricing = reg_file.pricing if reg_file else {}
            record  = AgentRecord(
                id=rid, agent_id=a["agent_id"],
                current_token_id=a.get("token_id"), agent_registry=None,
                name=name, version=version, agent_type=AgentType.PROVIDER,
                status=AgentStatus(a.get("status", "active")),
                owner_address=a.get("owner_address", ""),
                ipfs_cid=None, agent_uri=None, metadata_hash=None,
                docker_image=a.get("docker_image"),
                platform_endpoint=None,
                stake_amount=reg_file.stake_amount if reg_file else 0.0,
                price_per_task=pricing.get("price_per_task", 0.0),
                access_duration_days=pricing.get("access_duration_days", 30),
                max_calls_per_day=pricing.get("max_calls_per_day", 100),
                tx_hash=a.get("tx_hash"),
                registered_at=datetime.fromisoformat(a["registered_at"])
                              if a.get("registered_at") else None,
                updated_at=datetime.now(timezone.utc),
                versions=[AgentVersionInfo(
                    token_id=a["token_id"] or 0, version=version,
                    agent_uri="", docker_image=a.get("docker_image"),
                )] if a.get("token_id") else [],
                registration_file=reg_file,
            )
            _records[rid]               = record
            _agent_index[a["agent_id"]] = rid
            logger.info("Agent restaure: %s (tokenId=%s owner=%s docker=%s)",
                        a["agent_id"], a.get("token_id"),
                        (a.get("owner_address") or "")[:10],
                        (a.get("docker_image") or "")[:50])
        except Exception as e:
            logger.warning("Erreur restauration %s: %s", a["agent_id"], e)
    logger.info("DB → %d agents charges en memoire", len(agents))


class AgentService:
    def __init__(self):
        self.ipfs = IPFSService()

    async def submit(self, req: AgentSubmitRequest) -> AgentSubmitResponse:
        from app.db.agent_repo import get_agent as db_get
        if req.agent_id in _agent_index or db_get(req.agent_id):
            raise ValueError(f"agentId '{req.agent_id}' deja utilise.")
        rid      = str(uuid.uuid4())
        reg_file = _build_reg_file(req)
        cid, agent_uri, metadata_hash = await self.ipfs.upload(
            reg_file.model_dump_json(indent=2), name=f"{req.agent_id}-v{req.version}"
        )
        unsigned_tx = _build_register_tx(req, agent_uri, metadata_hash)
        record = AgentRecord(
            id=rid, agent_id=req.agent_id, current_token_id=None,
            agent_registry=None, name=req.name, version=req.version,
            agent_type=req.agent_type, status=AgentStatus.ACTIVE,
            owner_address=req.owner_address, ipfs_cid=cid,
            agent_uri=agent_uri, metadata_hash=metadata_hash,
            docker_image=req.docker_image, platform_endpoint=None,
            stake_amount=req.stake_amount, price_per_task=req.price_per_task,
            access_duration_days=req.access_duration_days,
            max_calls_per_day=req.max_calls_per_day,
            tx_hash=None, registered_at=None,
            updated_at=datetime.now(timezone.utc),
            versions=[], registration_file=reg_file,
        )
        _records[rid]              = record
        _agent_index[req.agent_id] = rid
        return AgentSubmitResponse(
            registration_id=rid, agent_id=req.agent_id, ipfs_cid=cid,
            agent_uri=agent_uri, metadata_hash=metadata_hash, unsigned_tx=unsigned_tx,
        )

    async def confirm(self, body: AgentOnChainConfirm) -> AgentRecord:
        if body.registration_id not in _records:
            raise KeyError(f"Registration introuvable: {body.registration_id}")
        record         = _records[body.registration_id]
        agent_registry = f"eip155:{settings.chain_id}:{settings.identity_registry_address}"

        # ── Résoudre le digest SHA256 — préserver le tag original ─────────
        if record.docker_image and "@sha256:" not in record.docker_image:
            original_image = record.docker_image  # ex: "strategy-agent:v1"
            from app.services.sandbox_service import SandboxService
            svc    = SandboxService()
            digest = await svc.resolve_image_digest(original_image)
            if "@sha256:" in digest:
                record = record.model_copy(update={"docker_image": digest})
                logger.info("Digest résolu: %s → %s", original_image, digest[:70])
            else:
                # Image non trouvée — garder le tag original (pas perdre le :v1)
                logger.warning(
                    "Image '%s' non trouvée localement — "
                    "digest non résolu, tag original conservé.", original_image
                )
                # record.docker_image reste original_image ("strategy-agent:v1")
        # ──────────────────────────────────────────────────────────────────

        if record.registration_file and body.token_id:
            updated_file = record.registration_file.model_copy(update={
                "registrations": [AgentRegistrationEntry(
                    agentId=record.agent_id, tokenId=body.token_id,
                    agentRegistry=agent_registry,
                )],
                "sandbox_config": {
                    **record.registration_file.sandbox_config,
                    "docker_image": record.docker_image,
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            new_cid, new_uri, _ = await self.ipfs.upload(
                updated_file.model_dump_json(indent=2),
                name=f"{record.agent_id}-confirmed"
            )
            record = record.model_copy(update={
                "ipfs_cid": new_cid, "agent_uri": new_uri,
                "registration_file": updated_file,
            })

        endpoint = register_agent_endpoint(record.agent_id)
        record   = record.model_copy(update={
            "current_token_id":  body.token_id,
            "agent_registry":    agent_registry,
            "tx_hash":           body.tx_hash,
            "platform_endpoint": endpoint,
            "registered_at":     datetime.now(timezone.utc),
            "updated_at":        datetime.now(timezone.utc),
            "versions":          [AgentVersionInfo(
                token_id=body.token_id or 0, version=record.version,
                agent_uri=record.agent_uri or "",
                docker_image=record.docker_image,
                minted_at=datetime.now(timezone.utc),
            )],
        })
        _records[body.registration_id] = record

        from app.db.agent_repo import upsert_agent
        upsert_agent(
            agent_id=record.agent_id, registration_id=record.id,
            token_id=record.current_token_id, tx_hash=record.tx_hash,
            docker_image=record.docker_image, status=record.status.value,
            registered_at=record.registered_at.isoformat()
                          if record.registered_at else None,
            owner_address=record.owner_address,
        )
        return record

    async def new_version(self, req: AgentNewVersionRequest) -> AgentNewVersionResponse:
        if req.agent_id not in _agent_index:
            raise KeyError(f"Agent introuvable: {req.agent_id}")
        rid    = _agent_index[req.agent_id]
        record = _records[rid]
        if record.owner_address.lower() != req.owner_address.lower():
            raise PermissionError("Seul le owner peut publier une nouvelle version")
        if record.current_token_id is None:
            raise ValueError("Agent pas encore confirme on-chain")

        # ── Résoudre + vérifier le nouveau digest ─────────────────────────
        from app.services.sandbox_service import SandboxService
        svc        = SandboxService()
        new_digest = await svc.resolve_image_digest(req.docker_image)
        old_digest = record.docker_image or ""
        old_tag    = old_digest.split("@")[0] if "@" in old_digest else old_digest

        if new_digest == old_digest:
            raise ValueError(
                f"Image identique à la version actuelle.\n"
                f"Digest actuel : {old_digest[:60]}\n"
                f"Faites 'docker build --no-cache -t {old_tag} .' "
                f"pour créer une nouvelle image avant de déclarer une nouvelle version."
            )
        logger.info("Nouvelle version %s : %s → %s",
                    req.agent_id, old_digest[:30], new_digest[:30])
        # ──────────────────────────────────────────────────────────────────

        old     = record.registration_file
        updates: dict[str, Any] = {
            "version": req.new_version, "active": req.active,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if req.description:  updates["description"]  = req.description
        if req.readme:       updates["readme"]        = req.readme
        if req.services:     updates["services"]      = req.services
        if req.capabilities: updates["capabilities"]  = req.capabilities
        if old and old.sandbox_config:
            updates["sandbox_config"] = {**old.sandbox_config, "docker_image": new_digest}

        new_file = old.model_copy(update=updates) if old else AgentRegistrationFile(
            name=record.name, description=req.description or "", version=req.new_version,
        )
        new_cid, new_uri, new_hash = await self.ipfs.upload(
            new_file.model_dump_json(indent=2), name=f"{req.agent_id}-v{req.new_version}"
        )
        unsigned_tx = _build_version_tx(req.agent_id, new_uri, req.new_version)
        _records[rid] = record.model_copy(update={
            "version": req.new_version, "ipfs_cid": new_cid, "agent_uri": new_uri,
            "metadata_hash": new_hash, "docker_image": new_digest,
            "registration_file": new_file, "updated_at": datetime.now(timezone.utc),
        })
        from app.db.agent_repo import upsert_agent
        upsert_agent(
            agent_id=record.agent_id, registration_id=record.id,
            token_id=record.current_token_id, tx_hash=record.tx_hash,
            docker_image=new_digest, status=record.status.value,
            registered_at=record.registered_at.isoformat()
                          if record.registered_at else None,
            owner_address=record.owner_address,
        )
        return AgentNewVersionResponse(
            registration_id=rid, agent_id=req.agent_id,
            new_version=req.new_version, new_ipfs_cid=new_cid,
            new_agent_uri=new_uri, unsigned_tx=unsigned_tx,
        )

    async def get_by_agent_id(self, agent_id: str) -> AgentRecord:
        if agent_id not in _agent_index:
            raise KeyError(agent_id)
        return _records[_agent_index[agent_id]]

    async def list_by_owner(self, address: str) -> list[AgentRecord]:
        return [r for r in _records.values()
                if r.owner_address.lower() == address.lower()]

    async def list_all(self, page: int = 1, size: int = 20) -> tuple[list[AgentRecord], int]:
        seen: dict[str, AgentRecord] = {}
        for r in _records.values():
            if r.agent_id not in seen:
                seen[r.agent_id] = r
        items = list(seen.values())
        return items[(page-1)*size: page*size], len(items)