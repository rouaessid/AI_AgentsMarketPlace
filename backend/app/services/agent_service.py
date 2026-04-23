from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.models.agent import (
    AgentEditRequest, AgentNewVersionRequest, AgentNewVersionResponse,
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


def _refresh_record_telemetry(agent_id: str, updates: dict) -> None:
    """Sync live telemetry into the in-memory AgentRecord capabilities so GET /agents returns fresh metrics."""
    rid = _agent_index.get(agent_id)
    if not rid or rid not in _records:
        return
    record = _records[rid]
    if not record.registration_file:
        return
    caps = dict(record.registration_file.capabilities)
    caps.update(updates)
    new_reg_file = record.registration_file.model_copy(update={"capabilities": caps})
    _records[rid] = record.model_copy(update={"registration_file": new_reg_file, "updated_at": datetime.now(timezone.utc)})


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
            # Données historiques simulées pour le design "Premium"
            "monthly_tasks": [12, 18, 15, 22, 30, 28, 35, 42, 38, 45, 50, 0][:12], # Zéro pour le futur
            "weekly_success": [95, 98, 97, 99, 96, 98, 100],
            "success_rate": 98.5,
            "reputation_score": 95,
            "tasks_performed": 335,
            "usage_count": 1250,
            "avg_response_time": 1.2,
            "task_completion_rate": 99.2,
            "uptime": 99.9,
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


def _build_register_tx(req, agent_uri) -> UnsignedTx:
    from web3 import Web3
    from app.services.blockchain_service import _IDENTITY_ABI
    contract_addr = settings.identity_registry_address or "0x_NOT_DEPLOYED"
    price_wei = int(req.price_per_task * 10**18)
    data: str | None = None
    try:
        w3 = Web3()
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(contract_addr), abi=_IDENTITY_ABI
        )
        data = contract.encode_abi(
            "register",
            args=[req.agent_id, req.agent_type.to_uint8(), agent_uri, req.version, price_wei],
        )
    except Exception as e:
        logger.warning("encode_abi failed: %s", e, exc_info=True)
    return UnsignedTx(
        contract_address=contract_addr,
        function_name="register",
        abi_encoded_args={
            "agentId_": req.agent_id, "agentType_": req.agent_type.to_uint8(),
            "agentURI_": agent_uri, "version_": req.version, "pricePerTask_": price_wei,
        },
        data=data,
        estimated_gas=800_000, chain_id=settings.chain_id,
    )


def _build_version_tx(agent_id, new_uri, new_version) -> UnsignedTx:
    return UnsignedTx(
        contract_address=settings.identity_registry_address or "0x_NOT_DEPLOYED",
        function_name="mintNewVersion",
        abi_encoded_args={
            "agentId_": agent_id, "newURI_": new_uri, "newVersion_": new_version,
        },
        estimated_gas=500_000, chain_id=settings.chain_id,
    )


async def restore_from_db() -> None:
    """
    Load agents from DB into memory at startup.

    Identity (canonical) comes from identity_repo (written by indexer).
    Telemetry comes from telemetry_repo (written by runtime).
    IPFS is only a fallback if identity_metadata is missing.
    """
    from app.db.identity_repo import get_all_agent_identities
    from app.db.telemetry_repo import get_all_telemetry

    agents    = get_all_agent_identities()
    telemetry = get_all_telemetry()  # {agent_id: dict}

    if not agents:
        logger.info("DB vide — aucun agent a charger")
        return

    ipfs_dir = Path(settings.storage_path) / "ipfs_local"

    for a in agents:
        try:
            rid      = a["registration_id"]
            agent_id = a["agent_id"]
            tel      = telemetry.get(agent_id, {})
            reg_file = None

            # Priority 1: identity_metadata from DB (written by indexer or submit)
            if a.get("identity_metadata"):
                try:
                    reg_file = AgentRegistrationFile(**json.loads(a["identity_metadata"]))
                except Exception:
                    logger.warning("identity_metadata invalide pour %s", agent_id)

            # Priority 2 (fallback): IPFS local
            if not reg_file and ipfs_dir.exists():
                files = sorted(ipfs_dir.glob("*.json"),
                               key=lambda x: x.stat().st_mtime, reverse=True)
                for f in files:
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        regs = data.get("registrations", [])
                        if any(r.get("agentId") == agent_id for r in regs):
                            reg_file = AgentRegistrationFile(**data)
                            break
                    except Exception:
                        continue

            name    = a.get("name") or (reg_file.name if reg_file else agent_id)
            version = a.get("version") or (reg_file.version if reg_file else "1.0.0")
            pricing = reg_file.pricing if reg_file else {}

            # Merge telemetry into capabilities (display layer only)
            if reg_file and tel:
                caps = dict(reg_file.capabilities)
                caps.update({
                    "tasks_performed":      tel.get("tasks_performed", 0),
                    "usage_count":          tel.get("usage_count", 0),
                    "avg_response_time":    tel.get("avg_response_time", 1.2),
                    "task_completion_rate": tel.get("task_completion_rate", 99.2),
                    "uptime":               tel.get("uptime", 99.9),
                    "monthly_tasks":        tel.get("monthly_tasks", [0]*12),
                    "weekly_success":       tel.get("weekly_success", [0]*7),
                    "success_rate":         tel.get("success_rate", 98.5),
                    "reputation_score":     tel.get("reputation_score", 95.0),
                    "last_active":          tel.get("last_active"),
                })
                reg_file = reg_file.model_copy(update={"capabilities": caps})

            record = AgentRecord(
                id=rid, agent_id=agent_id,
                current_token_id=a.get("current_token_id"),
                agent_registry=None,
                name=name, version=version,
                agent_type=AgentType.JUDGE if a.get("agent_type") == 1 else AgentType.PROVIDER,
                status=AgentStatus(a.get("status", "active")),
                owner_address=a.get("owner_address", ""),
                ipfs_cid=a.get("ipfs_cid"),
                agent_uri=a.get("agent_uri"),
                metadata_hash=None,
                docker_image=a.get("docker_image"),
                platform_endpoint=None,
                stake_amount=a.get("stake_amount") or (reg_file.stake_amount if reg_file else 0.0),
                price_per_task=a.get("price_per_task") or pricing.get("price_per_task", 0.0),
                access_duration_days=pricing.get("access_duration_days", 30),
                max_calls_per_day=pricing.get("max_calls_per_day", 100),
                tx_hash=a.get("tx_hash"),
                registered_at=datetime.fromisoformat(a["registered_at"])
                              if a.get("registered_at") else None,
                updated_at=datetime.now(timezone.utc),
                versions=[AgentVersionInfo(
                    token_id=a["current_token_id"] or 0, version=version,
                    agent_uri=a.get("agent_uri") or "", docker_image=a.get("docker_image"),
                )] if a.get("current_token_id") else [],
                registration_file=reg_file,
            )

            _records[rid]            = record
            _agent_index[agent_id]   = rid
            logger.info("Agent restaure: %s (tokenId=%s owner=%s)",
                        agent_id, a.get("current_token_id"),
                        (a.get("owner_address") or "")[:10])
        except Exception as e:
            logger.warning("Erreur restauration %s: %s", a.get("agent_id"), e)

    logger.info("DB → %d agents charges en memoire", len(agents))


# ── Edit helpers (module-level to keep AgentService.edit_agent simple) ────────

def _apply_edit_to_manifest(
    old_file: "AgentRegistrationFile | None",
    req: "AgentEditRequest",
) -> "AgentRegistrationFile | None":
    """Return a copy of old_file with edited fields applied, or None if no file."""
    if old_file is None:
        return None
    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if req.name        is not None: updates["name"]        = req.name
    if req.description is not None: updates["description"] = req.description
    if req.readme      is not None: updates["readme"]      = req.readme
    if req.price_per_task is not None:
        updates["pricing"] = {**old_file.pricing, "price_per_task": req.price_per_task}
    return old_file.model_copy(update=updates)


def _persist_edit(
    agent_id: str,
    rid: str,
    req: "AgentEditRequest",
    new_file: "AgentRegistrationFile | None",
    new_cid: str | None,
    upsert_fn,
) -> None:
    """Write edited fields to DB and update the in-memory _records cache."""
    db_kw: dict = {"ipfs_cid": new_cid} if new_cid else {}
    if req.name           is not None: db_kw["name"]           = req.name
    if req.price_per_task is not None: db_kw["price_per_task"] = req.price_per_task
    upsert_fn(
        agent_id=agent_id,
        registration_id=rid,
        identity_metadata=new_file.model_dump_json() if new_file else None,
        **db_kw,
    )
    if rid in _records:
        mem: dict = {"updated_at": datetime.now(timezone.utc)}
        if req.name           is not None: mem["name"]             = req.name
        if req.price_per_task is not None: mem["price_per_task"]   = req.price_per_task
        if new_file:                        mem["registration_file"] = new_file
        _records[rid] = _records[rid].model_copy(update=mem)


class AgentService:
    def __init__(self):
        self.ipfs = IPFSService()

    async def submit(self, req: AgentSubmitRequest) -> AgentSubmitResponse:
        """
        Pure blockchain-first registration flow:

          1. IPFS upload  (immutable manifest)
          2. Blockchain tx  ← source of truth
          3. DB = minimal pending marker ONLY
             (token_id, name, block_number filled by indexer on AgentCreated)
          4. Return tx_hash — frontend polls GET /agents/{id}/status

        The agent does NOT appear in _records / list_all() until the indexer
        confirms AgentCreated.  This is the correct ERC-8004 behaviour.
        """
        from app.db.identity_repo import get_agent_identity, upsert_agent_identity
        from app.db.telemetry_repo import upsert_telemetry
        from app.services.blockchain_service import BlockchainService

        if req.agent_id in _agent_index or get_agent_identity(req.agent_id):
            raise ValueError(f"agentId '{req.agent_id}' deja utilise.")

        rid      = str(uuid.uuid4())
        reg_file = _build_reg_file(req)

        # ── 1. IPFS ───────────────────────────────────────────────────────────
        cid, agent_uri, metadata_hash = await self.ipfs.upload(
            reg_file.model_dump_json(indent=2), name=f"{req.agent_id}-v{req.version}"
        )
        logger.info("IPFS upload %s -> %s", req.agent_id, cid)

        # ── 2. Build unsigned tx — MetaMask will sign it ─────────────────────
        unsigned_tx = _build_register_tx(req, agent_uri)
        logger.info("unsigned_tx built for %s — MetaMask must sign", req.agent_id)

        # ── 3. Register endpoint ──────────────────────────────────────────────
        endpoint = register_agent_endpoint(req.agent_id)

        # ── 4. DB: pending_signature marker ──────────────────────────────────
        upsert_agent_identity(
            agent_id=req.agent_id,
            registration_id=rid,
            owner_address=req.owner_address,
            docker_image=req.docker_image,
            agent_type=req.agent_type.to_uint8(),
            status="pending_signature",
            tx_hash=None,
            agent_uri=agent_uri,
            ipfs_cid=cid,
            price_per_task=req.price_per_task,
            stake_amount=req.stake_amount,
            identity_metadata=reg_file.model_dump_json(),
        )
        upsert_telemetry(
            req.agent_id,
            tasks_performed=0, usage_count=0,
            monthly_tasks=[0]*12, weekly_success=[0]*7,
            reputation_score=0.0, success_rate=0.0,
        )
        # Pre-populate cache as pending so /confirm can find the record
        try:
            record = AgentRecord(
                id=rid,
                agent_id=req.agent_id,
                current_token_id=None,
                agent_registry=f"eip155:{settings.chain_id}:{settings.identity_registry_address}",
                name=req.name,
                version=req.version,
                agent_type=AgentType.JUDGE if req.agent_type.to_uint8() == 1 else AgentType.PROVIDER,
                status=AgentStatus.PENDING_SIGNATURE,
                owner_address=req.owner_address,
                ipfs_cid=cid,
                agent_uri=agent_uri,
                metadata_hash=metadata_hash,
                docker_image=req.docker_image,
                platform_endpoint=endpoint,
                stake_amount=req.stake_amount,
                price_per_task=req.price_per_task,
                access_duration_days=req.access_duration_days,
                max_calls_per_day=req.max_calls_per_day,
                tx_hash=None,
                registered_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                supported_tasks=req.supported_tasks,
                special_caps=req.special_caps,
                versions=[],
                registration_file=reg_file,
            )
            _records[rid]              = record
            _agent_index[req.agent_id] = rid
            logger.info("Cache pre-populated (pending_signature) for %s", req.agent_id)
        except Exception as e:
            logger.warning("Cache pre-populate failed (non-critical): %s", e)

        resp_message = "IPFS OK — signez register() via MetaMask pour finaliser"
        return AgentSubmitResponse(
            registration_id=rid,   agent_id=req.agent_id,
            status="pending_signature",
            ipfs_cid=cid,          agent_uri=agent_uri,    metadata_hash=metadata_hash,
            token_id=None,
            tx_hash=None,
            stake_tx_hash=None,
            platform_endpoint=endpoint,
            unsigned_tx=unsigned_tx,
            stake_contract=settings.staking_contract_address or None,
            stake_amount_eth=req.stake_amount,
            message=resp_message,
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
            "status":            AgentStatus.ACTIVE,
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
        self._persist_record(record)
        return record

    async def new_version(self, req: AgentNewVersionRequest) -> AgentNewVersionResponse:
        """
        New code version — blockchain-first:
          1. Resolve docker digest (must differ from current)
          2. IPFS upload with new version + new docker image
          3. blockchain.mint_new_version() ← SOURCE DE VERITE
          4. DB: pending_version marker (indexer fills token_id on AgentVersionMinted)
        """
        from app.db.identity_repo import get_agent_identity, upsert_agent_identity
        from app.services.blockchain_service import BlockchainService

        row = get_agent_identity(req.agent_id)
        if not row:
            raise KeyError(f"Agent introuvable: {req.agent_id}")
        if row["status"] not in ("active",):
            raise ValueError(f"Agent '{req.agent_id}' doit etre actif pour creer une version")
        if not row["current_token_id"]:
            raise ValueError("Agent pas encore confirme on-chain (pas de token_id)")

        # ── Resolve docker digest (must differ) ───────────────────────────
        from app.services.sandbox_service import SandboxService
        new_docker = await SandboxService().resolve_image_digest(req.docker_image)
        old_docker = row.get("docker_image") or ""
        if new_docker == old_docker:
            old_tag = old_docker.split("@")[0] if "@" in old_docker else old_docker
            raise ValueError(
                f"Image identique a la version actuelle — digest inchange.\n"
                f"Faites 'docker build --no-cache -t {old_tag} .' pour creer une nouvelle image."
            )
        logger.info("Nouvelle image pour %s : %s", req.agent_id, new_docker[:60])

        # ── Build new IPFS manifest (version + docker image only) ─────────
        rid      = row.get("registration_id") or (_agent_index.get(req.agent_id) or str(uuid.uuid4()))
        old_file = (_records[rid].registration_file if rid in _records else None)
        sandbox  = {**(old_file.sandbox_config if old_file else {}), "docker_image": new_docker}
        new_file = (
            old_file.model_copy(update={
                "version":       req.new_version,
                "updated_at":    datetime.now(timezone.utc).isoformat(),
                "sandbox_config": sandbox,
            })
            if old_file
            else AgentRegistrationFile(
                name=row.get("name") or req.agent_id,
                description="",
                version=req.new_version,
                sandbox_config=sandbox,
            )
        )

        # ── IPFS upload ───────────────────────────────────────────────────
        new_cid, new_uri, _ = await self.ipfs.upload(
            new_file.model_dump_json(indent=2),
            name=f"{req.agent_id}-v{req.new_version}",
        )
        logger.info("IPFS version %s %s → cid=%s", req.agent_id, req.new_version, new_cid)

        # ── Blockchain FIRST ──────────────────────────────────────────────
        chain       = BlockchainService()
        tx_hash     = ""
        unsigned_tx = None
        if chain.is_available():
            tx_hash, _ = chain.mint_new_version(req.agent_id, new_uri, req.new_version)
            if not tx_hash:
                raise RuntimeError("mint_new_version() returned empty tx_hash")
            logger.info("mintNewVersion(%s) tx=%s", req.agent_id, tx_hash[:20])
        else:
            unsigned_tx = _build_version_tx(req.agent_id, new_uri, req.new_version)

        # ── DB: pending marker — _records updated by indexer only ─────────
        upsert_agent_identity(
            agent_id=req.agent_id,
            registration_id=rid,
            docker_image=new_docker,
            status="pending_version" if tx_hash else "pending_signature",
            tx_hash=tx_hash or None,
            agent_uri=new_uri,
            ipfs_cid=new_cid,
            identity_metadata=new_file.model_dump_json(),
        )
        resp_status = "pending_version" if tx_hash else "pending_signature"
        return AgentNewVersionResponse(
            registration_id=rid, agent_id=req.agent_id,
            new_version=req.new_version, new_ipfs_cid=new_cid,
            new_agent_uri=new_uri, status=resp_status,
            tx_hash=tx_hash or None, unsigned_tx=unsigned_tx,
            message=(
                f"Tx envoyee ({tx_hash[:20]}...). Poll GET /agents/{req.agent_id}/status"
                if tx_hash
                else "IPFS OK — signez mintNewVersion() avec votre wallet"
            ),
        )

    async def edit_agent(self, agent_id: str, req: AgentEditRequest) -> dict:
        """
        Editorial changes (description, readme, name, price) — no blockchain tx, same NFT token.

        Flow:
          1. Build updated manifest from current identity_metadata
          2. IPFS upload → new CID  (IPFS toujours mis à jour)
          3. DB: nouveau ipfs_cid + identity_metadata (même token_id, même agent_uri on-chain)
          4. _records mis à jour immédiatement (pas besoin d'attendre l'indexer)

        Le smart contract garde le même URI on-chain.
        La prochaine new_version() inclura ces changements dans son manifest IPFS.
        """
        from app.db.identity_repo import get_agent_identity, upsert_agent_identity

        row = get_agent_identity(agent_id)
        if not row:
            raise KeyError(f"Agent introuvable: {agent_id}")

        rid      = row.get("registration_id") or (_agent_index.get(agent_id) or str(uuid.uuid4()))
        old_file = (_records[rid].registration_file if rid in _records else None)

        # ── Build updated manifest ────────────────────────────────────────
        new_file = _apply_edit_to_manifest(old_file, req)

        # ── IPFS upload — toujours ────────────────────────────────────────
        new_cid = row.get("ipfs_cid")
        if new_file:
            new_cid, _, _ = await self.ipfs.upload(
                new_file.model_dump_json(indent=2),
                name=f"{agent_id}-edit",
            )
            logger.info("IPFS edit %s → nouveau cid=%s", agent_id, new_cid)

        # ── DB + _records ─────────────────────────────────────────────────
        _persist_edit(agent_id, rid, req, new_file, new_cid, upsert_agent_identity)

        updated_fields = [k for k in ("name", "description", "readme", "price_per_task")
                          if getattr(req, k) is not None]
        logger.info("edit_agent(%s) mis a jour: %s", agent_id, updated_fields)
        return {"agent_id": agent_id, "updated": updated_fields, "ipfs_cid": new_cid}

    async def get_by_agent_id(self, agent_id: str) -> AgentRecord:
        if agent_id not in _agent_index:
            raise KeyError(agent_id)
        return _records[_agent_index[agent_id]]

    def update_run_metrics(self, agent_id: str, *, success: bool, duration_sec: float | None = None) -> None:
        """
        Increment usage counters after every run. Called from the /run endpoint.
        Writes to agent_telemetry (telemetry zone) only — never touches identity.
        """
        from app.db.telemetry_repo import get_telemetry, upsert_telemetry

        tel = get_telemetry(agent_id) or {}
        n   = int(tel.get("tasks_performed") or 0) + 1
        now = datetime.now(timezone.utc)

        # Rolling average response time
        prev_avg = float(tel.get("avg_response_time") or 0)
        new_avg  = round((prev_avg * (n - 1) + (duration_sec or 0)) / n, 2) if duration_sec else prev_avg

        # Rolling task_completion_rate
        prev_rate = float(tel.get("task_completion_rate") or 0)
        prev_ok   = round(prev_rate * (n - 1) / 100)
        new_rate  = round((prev_ok + (1 if success else 0)) * 100 / n, 1)

        # Monthly task volume (rolling 12 months)
        monthly = list(tel.get("monthly_tasks") or [0]*12)
        if len(monthly) != 12:
            monthly = [0]*12
        monthly[now.month - 1] += 1

        # Weekly success rate snapshot (rolling 7 days)
        weekly = list(tel.get("weekly_success") or [0]*7)
        if len(weekly) != 7:
            weekly = [0]*7
        weekly[now.weekday()] = new_rate

        new_usage = int(tel.get("usage_count") or 0) + 1
        upsert_telemetry(
            agent_id,
            tasks_performed=n,
            usage_count=new_usage,
            avg_response_time=new_avg,
            task_completion_rate=new_rate,
            last_active=now.isoformat(),
            monthly_tasks=monthly,
            weekly_success=weekly,
        )
        _refresh_record_telemetry(agent_id, {
            "tasks_performed":      n,
            "usage_count":          new_usage,
            "avg_response_time":    new_avg,
            "task_completion_rate": new_rate,
            "last_active":          now.isoformat(),
            "monthly_tasks":        monthly,
            "weekly_success":       weekly,
        })
        logger.debug("Telemetry updated for %s: tasks=%d avg=%.2fs rate=%.1f%%",
                     agent_id, n, new_avg, new_rate)

    def update_validation_metrics(self, agent_id: str, *, verdict: str, score: float) -> None:
        """
        Update reputation after a validation completes.
        Writes to agent_telemetry (telemetry zone) only.
        Will be replaced by ReputationContract indexer events in the future.
        """
        from app.db.telemetry_repo import get_telemetry, upsert_telemetry

        tel       = get_telemetry(agent_id) or {}
        val_count = int(tel.get("val_count") or 0) + 1
        is_valid  = verdict == "VALID"

        prev_rate = float(tel.get("success_rate") or 0)
        prev_ok   = round(prev_rate * (val_count - 1) / 100)
        new_rate  = round((prev_ok + (1 if is_valid else 0)) * 100 / val_count, 1)
        new_rep   = round(new_rate * 0.6 + score * 0.4)

        weekly = list(tel.get("weekly_success") or [0]*7)
        if len(weekly) != 7:
            weekly = [0]*7
        weekly[datetime.now(timezone.utc).weekday()] = new_rate

        upsert_telemetry(
            agent_id,
            success_rate=new_rate,
            reputation_score=float(new_rep),
            val_count=val_count,
            weekly_success=weekly,
        )
        _refresh_record_telemetry(agent_id, {
            "success_rate":     new_rate,
            "reputation_score": float(new_rep),
            "weekly_success":   weekly,
        })
        logger.info("Validation telemetry updated for %s: success_rate=%.1f%% rep=%d",
                    agent_id, new_rate, new_rep)

    def _persist_record(self, record: AgentRecord) -> None:
        """Sync identity fields to DB (identity zone only — no telemetry here)."""
        from app.db.identity_repo import upsert_agent_identity
        upsert_agent_identity(
            agent_id=record.agent_id,
            registration_id=record.id,
            owner_address=record.owner_address,
            current_token_id=record.current_token_id,
            docker_image=record.docker_image,
            status=record.status.value,
            tx_hash=record.tx_hash,
            registered_at=record.registered_at.isoformat() if record.registered_at else None,
            agent_uri=record.agent_uri,
            ipfs_cid=record.ipfs_cid,
            name=record.name,
            version=record.version,
            price_per_task=record.price_per_task,
            stake_amount=record.stake_amount,
            identity_metadata=(
                record.registration_file.model_dump_json()
                if record.registration_file else None
            ),
        )

    async def list_by_owner(self, address: str) -> list[AgentRecord]:
        results = [r for r in _records.values()
                   if r.owner_address.lower() == address.lower()]
        if results:
            return results
        # Fallback: reload from DB (covers backend-restart case)
        await restore_from_db()
        return [r for r in _records.values()
                if r.owner_address.lower() == address.lower()]

    async def list_all(self, page: int = 1, size: int = 20) -> tuple[list[AgentRecord], int]:
        seen: dict[str, AgentRecord] = {}
        for r in _records.values():
            # Uniquement les PROVIDER dans le marketplace public
            if r.agent_type == AgentType.PROVIDER and r.agent_id not in seen:
                seen[r.agent_id] = r
        items = list(seen.values())
        return items[(page-1)*size: page*size], len(items)