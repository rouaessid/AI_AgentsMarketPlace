from __future__ import annotations
import hashlib, json, logging, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import UploadFile

from app.core.config import get_settings
from app.models.agent import (
    AgentNewVersionRequest, AgentNewVersionResponse,
    AgentOnChainConfirm, AgentRecord, AgentRegistrationEntry,
    AgentRegistrationFile, AgentStatus, AgentSubmitRequest,
    AgentSubmitResponse, AgentVersionInfo, UnsignedTx,
)
from app.services.ipfs_service import IPFSService
from app.services.ngrok_service import get_agent_endpoint

logger   = logging.getLogger(__name__)
settings = get_settings()


def _build_reg_file(req: AgentSubmitRequest) -> AgentRegistrationFile:
    return AgentRegistrationFile(
        name=req.name, description=req.description, version=req.version,
        image=req.image_url, services=req.services, x402Support=req.x402_support,
        active=True, supportedTrust=req.supported_trust,
        agent_type=req.agent_type.value,
        capabilities={
            "llm_model": req.llm_model, "framework": req.framework,
            "language": req.language, "max_tokens": req.max_tokens,
            "supported_tasks": req.supported_tasks, "special_caps": req.special_caps,
            "price_per_task": req.price_per_task,
        },
        sandbox_config={
            "runtime": req.runtime, "entrypoint": req.entrypoint,
            "cpu_limit": req.cpu_limit, "ram_limit_mb": req.ram_limit_mb,
            "timeout_sec": req.timeout_sec, "env_var_keys": req.env_var_keys,
            "manifest_schema": req.manifest_schema,
        },
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def _build_register_tx(req: AgentSubmitRequest, agent_uri: str, metadata_hash: str) -> UnsignedTx:
    return UnsignedTx(
        contract_address=settings.identity_registry_address or "0x_NOT_DEPLOYED",
        function_name="register",
        abi_encoded_args={
            "agentId_":   req.agent_id,
            "agentType_": req.agent_type.to_uint8(),
            "agentURI_":  agent_uri,
            "version_":   req.version,
        },
        estimated_gas=300_000,
        chain_id=settings.chain_id,
    )


def _build_version_tx(agent_id: str, new_uri: str, new_version: str) -> UnsignedTx:
    return UnsignedTx(
        contract_address=settings.identity_registry_address or "0x_NOT_DEPLOYED",
        function_name="mintNewVersion",
        abi_encoded_args={
            "agentId_": agent_id, "newURI_": new_uri, "newVersion_": new_version,
        },
        estimated_gas=250_000,
        chain_id=settings.chain_id,
    )


async def _store_zip(registration_id: str, zip_file: UploadFile) -> tuple[str, str]:
    base = Path(settings.storage_path) / "zips" / registration_id
    base.mkdir(parents=True, exist_ok=True)
    dest = base / "agent.zip"
    hasher = hashlib.sha256()
    total  = 0
    max_b  = settings.max_zip_size_mb * 1024 * 1024
    async with aiofiles.open(dest, "wb") as f:
        while chunk := await zip_file.read(65_536):
            total += len(chunk)
            if total > max_b:
                dest.unlink(missing_ok=True)
                raise ValueError(f"ZIP trop grand: {total/1024/1024:.1f}MB")
            hasher.update(chunk)
            await f.write(chunk)
    try:
        with zipfile.ZipFile(dest): pass
    except zipfile.BadZipFile:
        dest.unlink(missing_ok=True)
        raise ValueError("ZIP invalide")
    return str(dest), "0x" + hasher.hexdigest()


_records:     dict[str, AgentRecord] = {}
_agent_index: dict[str, str]         = {}


class AgentService:
    def __init__(self):
        self.ipfs = IPFSService()

    async def submit(self, req: AgentSubmitRequest, zip_file: UploadFile | None = None) -> AgentSubmitResponse:
        if req.agent_id in _agent_index:
            raise ValueError(f"agentId '{req.agent_id}' deja utilise.")
        rid = str(uuid.uuid4())
        reg_file = _build_reg_file(req)
        content  = reg_file.model_dump_json(indent=2)
        cid, agent_uri, metadata_hash = await self.ipfs.upload(content, name=f"{req.agent_id}-v{req.version}")
        zip_path = zip_hash = None
        if zip_file:
            zip_path, zip_hash = await _store_zip(rid, zip_file)
        unsigned_tx = _build_register_tx(req, agent_uri, metadata_hash)
        record = AgentRecord(
            id=rid, agent_id=req.agent_id, current_token_id=None, agent_registry=None,
            name=req.name, version=req.version, agent_type=req.agent_type,
            status=AgentStatus.ACTIVE, owner_address=req.owner_address,
            ipfs_cid=cid, agent_uri=agent_uri, metadata_hash=metadata_hash,
            zip_path=zip_path, zip_hash=zip_hash, platform_endpoint=None,
            tx_hash=None, registered_at=None, updated_at=datetime.now(timezone.utc),
            versions=[], registration_file=reg_file,
        )
        _records[rid] = record
        _agent_index[req.agent_id] = rid
        return AgentSubmitResponse(
            registration_id=rid, agent_id=req.agent_id,
            ipfs_cid=cid, agent_uri=agent_uri, metadata_hash=metadata_hash,
            unsigned_tx=unsigned_tx,
        )

    async def confirm(self, body: AgentOnChainConfirm) -> AgentRecord:
        if body.registration_id not in _records:
            raise KeyError(f"Registration introuvable: {body.registration_id}")
        record = _records[body.registration_id]
        agent_registry = f"eip155:{settings.chain_id}:{settings.identity_registry_address}"
        if record.registration_file and body.token_id:
            updated_file = record.registration_file.model_copy(update={
                "registrations": [AgentRegistrationEntry(
                    agentId=record.agent_id, tokenId=body.token_id,
                    agentRegistry=agent_registry,
                )],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            content = updated_file.model_dump_json(indent=2)
            new_cid, new_uri, _ = await self.ipfs.upload(content, name=f"{record.agent_id}-confirmed")
            record = record.model_copy(update={
                "ipfs_cid": new_cid, "agent_uri": new_uri, "registration_file": updated_file,
            })
        v_info = AgentVersionInfo(
            token_id=body.token_id or 0, version=record.version,
            agent_uri=record.agent_uri or "", minted_at=datetime.now(timezone.utc),
        )
        record = record.model_copy(update={
            "current_token_id": body.token_id, "agent_registry": agent_registry,
            "tx_hash": body.tx_hash, "platform_endpoint": get_agent_endpoint(record.agent_id),
            "registered_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
            "versions": [v_info],
        })
        _records[body.registration_id] = record
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
        old = record.registration_file
        updates: dict[str, Any] = {
            "version": req.new_version, "active": req.active,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if req.description:  updates["description"]  = req.description
        if req.services:     updates["services"]      = req.services
        if req.capabilities: updates["capabilities"]  = req.capabilities
        new_file = old.model_copy(update=updates) if old else AgentRegistrationFile(
            name=record.name, description=req.description or "", version=req.new_version
        )
        content = new_file.model_dump_json(indent=2)
        new_cid, new_uri, new_hash = await self.ipfs.upload(content, name=f"{req.agent_id}-v{req.new_version}")
        unsigned_tx = _build_version_tx(req.agent_id, new_uri, req.new_version)
        _records[rid] = record.model_copy(update={
            "version": req.new_version, "ipfs_cid": new_cid,
            "agent_uri": new_uri, "metadata_hash": new_hash,
            "registration_file": new_file, "updated_at": datetime.now(timezone.utc),
        })
        return AgentNewVersionResponse(
            registration_id=rid, agent_id=req.agent_id, new_version=req.new_version,
            new_ipfs_cid=new_cid, new_agent_uri=new_uri, unsigned_tx=unsigned_tx,
        )

    async def get_by_agent_id(self, agent_id: str) -> AgentRecord:
        if agent_id not in _agent_index:
            raise KeyError(agent_id)
        return _records[_agent_index[agent_id]]

    async def list_by_owner(self, address: str) -> list[AgentRecord]:
        return [r for r in _records.values() if r.owner_address.lower() == address.lower()]

    async def list_all(self, page: int = 1, size: int = 20) -> tuple[list[AgentRecord], int]:
        seen: dict[str, AgentRecord] = {}
        for r in _records.values():
            if r.agent_id not in seen:
                seen[r.agent_id] = r
        items = list(seen.values())
        return items[(page-1)*size: page*size], len(items)