from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone

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


# ── Cache accessors (called by identity_repo as facade) ───────────────────────

def _record_to_dict(record: AgentRecord) -> dict:
    """Convert an AgentRecord to the flat dict format expected by callers of get_agent_identity()."""
    reg_file = record.registration_file
    return {
        "agent_id":           record.agent_id,
        "registration_id":    record.id,
        "name":               record.name,
        "version":            record.version,
        "status":             record.status.value,
        "owner_address":      record.owner_address,
        "docker_image":       record.docker_image,
        "agent_type":         record.agent_type.to_uint8(),
        "agent_uri":          record.agent_uri,
        "ipfs_cid":           record.ipfs_cid,
        "price_per_task":     record.price_per_task,
        "stake_amount":       record.stake_amount,
        "current_token_id":   record.current_token_id,
        "tx_hash":            record.tx_hash,
        "registered_at":      record.registered_at.isoformat() if record.registered_at else None,
        "identity_metadata":  reg_file.model_dump_json() if reg_file else None,
    }


def get_agent_from_cache(agent_id: str) -> dict | None:
    rid = _agent_index.get(agent_id)
    if not rid or rid not in _records:
        return None
    return _record_to_dict(_records[rid])


def get_all_agents_from_cache() -> list[dict]:
    return [_record_to_dict(r) for r in _records.values()]


# ── IPFS manifest fetch (used at startup restore) ─────────────────────────────

def _fetch_ipfs_manifest(ipfs_cid: str, agent_id: str) -> AgentRegistrationFile | None:
    """Fetch and parse IPFS manifest from Pinata."""
    import httpx as _httpx
    for url in [
        f"https://gateway.pinata.cloud/ipfs/{ipfs_cid}",
        f"https://ipfs.io/ipfs/{ipfs_cid}",
    ]:
        try:
            r = _httpx.get(url, timeout=10)
            r.raise_for_status()
            return AgentRegistrationFile(**r.json())
        except Exception as e:
            logger.debug("IPFS fetch %s failed for %s: %s", url, agent_id, e)
    logger.warning("IPFS manifest not found for %s (cid=%s)", agent_id, ipfs_cid)
    return None


def _refresh_record_telemetry(agent_id: str, updates: dict) -> None:
    """Sync live telemetry into the in-memory AgentRecord capabilities so GET /agents returns fresh metrics."""
    rid = _agent_index.get(agent_id)
    if not rid or rid not in _records:
        return
    record = _records[rid]
    if record.registration_file:
        caps = dict(record.registration_file.capabilities)
        caps.update(updates)
        new_reg_file = record.registration_file.model_copy(update={"capabilities": caps})
    else:
        new_reg_file = AgentRegistrationFile(
            name=record.name or agent_id,
            description="",
            capabilities=updates,
        )
    _records[rid] = record.model_copy(update={"registration_file": new_reg_file, "updated_at": datetime.now(timezone.utc)})


def _build_reg_file(req: AgentSubmitRequest) -> AgentRegistrationFile:
    return AgentRegistrationFile(
        name=req.name, description=req.description, version=req.version,
        image=req.image_url, readme=req.readme, services=req.services,
        x402Support=req.x402_support, active=True,
        supportedTrust=req.supported_trust, agent_type=req.agent_type.value,
        evaluation_skills=req.evaluation_skills,
        validated_task_types=req.validated_task_types,
        evaluation_domains=req.evaluation_domains,
        tools_used=req.tools_used,
        evaluation_style=req.evaluation_style,
        capabilities={
            "llm_model": req.llm_model, "framework": req.framework,
            "language": req.language, "max_tokens": req.max_tokens,
            "supported_tasks": req.supported_tasks, "special_caps": req.special_caps,
            "env_var_keys": req.env_var_keys,
            "avg_response_time": None,
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
    from app.core.abis import IDENTITY_REGISTRY_ABI as _IDENTITY_ABI
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
    Rebuild in-memory cache at startup.

    Sources (in priority order):
      1. agent_embeddings DB — agent_id + status (operational state)
      2. The Graph           — tokenId, owner, agentType, agentURI (on-chain truth)
      3. IPFS manifest       — CID extrait de agentURI — name, price, docker_image, capabilities
      4. agent_telemetry DB  — runtime metrics
    """
    from app.repo.identity_repo import get_all_embeddings, upsert_agent_identity
    from app.repo.telemetry_repo import get_all_telemetry
    from app.services.graph_client import get_agent, get_eigentrust_score, get_agent_score, get_agent_validation_history

    rows      = get_all_embeddings()   # [{agent_id, capability_embedding, status}]
    telemetry = get_all_telemetry()    # {agent_id: dict}

    if not rows:
        # DB is empty — bootstrap from The Graph (agents already on-chain + IPFS)
        logger.info("DB vide — bootstrap depuis The Graph...")
        from app.services.graph_client import get_all_agents as _get_all_graph_agents
        graph_agents = _get_all_graph_agents()
        if not graph_agents:
            logger.info("The Graph ne retourne aucun agent — DB reste vide")
            return
        for ga in graph_agents:
            upsert_agent_identity(agent_id=ga["id"])
            logger.info("Bootstrap: %s (tokenId=%s)", ga["id"], ga.get("tokenId"))
        rows = get_all_embeddings()
        if not rows:
            logger.warning("Bootstrap The Graph terminé mais DB toujours vide")
            return

    _valid_statuses = {s.value for s in AgentStatus}

    # Fetch IPFS manifests + The Graph data in parallel
    import asyncio as _asyncio
    loop = _asyncio.get_event_loop()

    async def _fetch_row(row: dict) -> tuple[dict, object, dict | None]:
        agent_id = row.get("agent_id")
        # On-chain d'abord — agentURI contient le CID IPFS
        on_chain = await loop.run_in_executor(None, lambda a=agent_id: get_agent(a))
        agent_uri = (on_chain.get("agentURI") or "") if on_chain else ""
        ipfs_cid  = agent_uri[len("ipfs://"):] if agent_uri.startswith("ipfs://") else None
        reg_file  = await loop.run_in_executor(
            None, lambda c=ipfs_cid, a=agent_id: _fetch_ipfs_manifest(c, a) if c else None
        )
        return row, reg_file, on_chain

    fetched = await _asyncio.gather(*[_fetch_row(r) for r in rows], return_exceptions=True)

    for result in fetched:
        if isinstance(result, Exception):
            logger.warning("Erreur fetch parallèle: %s", result)
            continue
        row, reg_file, on_chain = result
        agent_id = row.get("agent_id")
        try:
            if not reg_file:
                logger.warning("Pas de manifest IPFS pour %s", agent_id)

            # ── 2. The Graph (on-chain truth) ─────────────────────────────────
            token_id     = int(on_chain["tokenId"])    if on_chain and on_chain.get("tokenId")    else None
            owner        = (on_chain.get("owner")      if on_chain else None) or ""
            _manifest_type = getattr(reg_file, "agent_type", None) if reg_file else None
            _manifest_type_v = 1 if str(_manifest_type).lower() in ("1", "judge") else 0
            agent_type_v = int(on_chain["agentType"]) if on_chain and on_chain.get("agentType") else _manifest_type_v
            agent_uri    = (on_chain.get("agentURI") if on_chain else None) or None
            version      = (on_chain.get("version")    if on_chain else None) or (
                reg_file.version if reg_file else "1.0.0"
            )
            name    = reg_file.name if reg_file else agent_id
            pricing = reg_file.pricing if reg_file else {}
            # Status : utiliser registration_status DB si dispo, sinon dériver depuis The Graph
            db_status = row.get("registration_status")
            if db_status and db_status not in ("pending_signature", "pending_index"):
                status = db_status  # active / pending_validation / validation_failed
            elif on_chain and token_id:
                # Agent indexé — vérifier honeypot pour les juges
                if agent_type_v == 1:  # JUDGE
                    from app.services.honeypot_service import is_judge_authorized
                    status = "active" if is_judge_authorized(agent_id) else "pending_validation"
                else:
                    status = "active"
            else:
                status = "pending_signature"

            # ── 3. Telemetry (sandbox metrics uniquement) ─────────────────────
            tel = telemetry.get(agent_id, {})
            # tasks_performed et last_active viennent de get_agent_score() (The Graph/RPC)
            agent_score  = get_agent_score(agent_id) if token_id else None
            _avg_score   = float(agent_score.get("averageScore", 0)) if agent_score else 0.0
            _et_score    = get_eigentrust_score(token_id) or 0.0
            _hist        = get_agent_validation_history(agent_id) if token_id else {}
            _n_agents    = len([a for a in _records.values() if a.current_token_id and a.agent_type != AgentType.JUDGE])
            # N=1 → EigenTrust artefact (always 100) → use avg_score; N>1 → use EigenTrust
            _rep_score   = _avg_score if (_n_agents <= 1 or not _et_score) else _et_score
            tel_caps = {
                "tasks_performed":   agent_score.get("totalTasks", 0) if agent_score else 0,
                "avg_response_time": tel.get("avg_response_time"),
                "success_rate":      round(_avg_score / 100.0, 4),
                "reputation_score":  _rep_score,
                "monthly_tasks":     _hist.get("monthly_tasks", [0]*12),
                "weekly_success":    _hist.get("weekly_success", [0.0]*7),
            }
            if reg_file:
                caps = dict(reg_file.capabilities)
                caps.update(tel_caps)
                reg_file = reg_file.model_copy(update={"capabilities": caps})
            elif tel:
                reg_file = AgentRegistrationFile(
                    name=agent_id,
                    description="",
                    capabilities=tel_caps,
                )

            # ── 4. Build AgentRecord ──────────────────────────────────────────
            rid    = str(uuid.uuid4())
            record = AgentRecord(
                id=rid, agent_id=agent_id,
                current_token_id=token_id,
                agent_registry=None,
                name=name, version=version,
                agent_type=AgentType.JUDGE if agent_type_v == 1 else AgentType.PROVIDER,
                status=AgentStatus(status) if status in _valid_statuses else AgentStatus.ACTIVE,
                owner_address=owner,
                ipfs_cid=agent_uri[len("ipfs://"):] if agent_uri and agent_uri.startswith("ipfs://") else None,
                agent_uri=agent_uri,
                metadata_hash=None,
                docker_image=(
                    reg_file.sandbox_config.get("docker_image")
                    if reg_file and isinstance(reg_file.sandbox_config, dict) else None
                ),
                platform_endpoint=None,
                stake_amount=reg_file.stake_amount if reg_file else 0.0,
                price_per_task=pricing.get("price_per_task", 0.0),
                access_duration_days=pricing.get("access_duration_days", 30),
                max_calls_per_day=pricing.get("max_calls_per_day", 100),
                tx_hash=None,
                registered_at=None,
                updated_at=datetime.now(timezone.utc),
                versions=[AgentVersionInfo(
                    token_id=token_id, version=version,
                    agent_uri=agent_uri or "", docker_image=None,
                )] if token_id else [],
                registration_file=reg_file,
            )

            _records[rid]          = record
            _agent_index[agent_id] = rid
            logger.info("Agent restaure: %s (tokenId=%s owner=%s)",
                        agent_id, token_id, owner[:10] if owner else "")
        except Exception as e:
            logger.warning("Erreur restauration %s: %s", agent_id, e)

    logger.info("DB → %d agents charges en memoire", len(rows))


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
    rid: str,
    req: "AgentEditRequest",
    new_file: "AgentRegistrationFile | None",
) -> None:
    """Refresh the in-memory cache after IPFS update (CID comes from agentURI on-chain)."""
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
        from app.repo.identity_repo import get_agent_identity, upsert_agent_identity

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

        # ── 4. DB: slim pending marker — identity lives in IPFS ──────────────
        upsert_agent_identity(agent_id=req.agent_id)
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

        # Vérifier enregistrement on-chain — IdentityRegistry.isActive() direct RPC
        if settings.identity_registry_address and settings.rpc_url:
            try:
                from web3 import Web3 as _W3
                _w3 = _W3(_W3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 5}))
                from app.core.abis import IDENTITY_REGISTRY_ABI as _ir_abi
                _ir = _w3.eth.contract(address=_W3.to_checksum_address(settings.identity_registry_address), abi=_ir_abi)
                if not _ir.functions.isActive(record.agent_id).call():
                    raise ValueError(f"Agent '{record.agent_id}' non actif on-chain — transaction non confirmée")
            except ValueError:
                raise
            except Exception as e:
                logger.warning("isActive check échoué (non-bloquant): %s", e)

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

        # tx receipt confirmé → tokenId reçu = agent enregistré on-chain
        # PROVIDER → actif directement, JUGE → en attente du honeypot
        final_status = (
            AgentStatus.PENDING_VALIDATION
            if record.agent_type == AgentType.JUDGE
            else AgentStatus.ACTIVE
        )

        endpoint = register_agent_endpoint(record.agent_id)
        record   = record.model_copy(update={
            "current_token_id":  body.token_id,
            "agent_registry":    agent_registry,
            "tx_hash":           body.tx_hash,
            "status":            final_status,
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

        from app.repo.identity_repo import upsert_agent_identity
        upsert_agent_identity(
            agent_id=record.agent_id,
            registration_status=final_status.value,
        )
        return record

    async def new_version(self, req: AgentNewVersionRequest) -> AgentNewVersionResponse:
        """
        New code version — blockchain-first:
          1. Resolve docker digest (must differ from current)
          2. IPFS upload with new version + new docker image
          3. blockchain.mint_new_version() ← SOURCE DE VERITE
          4. DB: pending_version marker (indexer fills token_id on AgentVersionMinted)
        """
        from app.repo.identity_repo import get_agent_identity, upsert_agent_identity

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

        # ── Build unsigned_tx — MetaMask du seller signe ─────────────────
        unsigned_tx = _build_version_tx(req.agent_id, new_uri, req.new_version)

        # ── DB: slim pending marker ───────────────────────────────────────
        upsert_agent_identity(agent_id=req.agent_id)
        return AgentNewVersionResponse(
            registration_id=rid, agent_id=req.agent_id,
            new_version=req.new_version, new_ipfs_cid=new_cid,
            new_agent_uri=new_uri, status="pending_signature",
            tx_hash=None, unsigned_tx=unsigned_tx,
            message="IPFS OK — signez mintNewVersion() avec votre wallet",
        )

    async def edit_agent(self, agent_id: str, req: AgentEditRequest) -> dict:
        """
        Editorial changes (description, readme, name, price) — no blockchain tx, same NFT token.

        Flow:
          1. Build updated manifest from current identity_metadata
          2. IPFS upload → new CID  (IPFS toujours mis à jour)
          3. _records mis à jour (même token_id, même agent_uri on-chain)
          4. _records mis à jour immédiatement (pas besoin d'attendre l'indexer)

        Le smart contract garde le même URI on-chain.
        La prochaine new_version() inclura ces changements dans son manifest IPFS.
        """
        from app.repo.identity_repo import get_agent_identity

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
        _persist_edit(rid, req, new_file)

        updated_fields = [k for k in ("name", "description", "readme", "price_per_task")
                          if getattr(req, k) is not None]
        logger.info("edit_agent(%s) mis a jour: %s", agent_id, updated_fields)
        return {"agent_id": agent_id, "updated": updated_fields, "ipfs_cid": new_cid}

    async def get_by_agent_id(self, agent_id: str) -> AgentRecord:
        if agent_id not in _agent_index:
            raise KeyError(agent_id)
        return _records[_agent_index[agent_id]]

    def update_run_metrics(self, agent_id: str, *, duration_sec: float | None = None) -> None:
        """
        Met à jour avg_response_time après chaque exécution sandbox.
        tasks_performed et last_active → dérivables depuis ScoreRecorded (The Graph).
        """
        if not duration_sec:
            return
        from app.repo.telemetry_repo import get_telemetry, upsert_telemetry

        tel     = get_telemetry(agent_id) or {}
        prev    = float(tel.get("avg_response_time") or 0)
        new_avg = round((prev + duration_sec) / 2, 2) if prev else round(duration_sec, 2)

        upsert_telemetry(agent_id, avg_response_time=new_avg)
        _refresh_record_telemetry(agent_id, {"avg_response_time": new_avg})
        logger.debug("Telemetry updated for %s: avg=%.2fs", agent_id, new_avg)

    def update_validation_metrics(self, agent_id: str, *, score: float) -> None:
        """
        Score de validation — ancré on-chain via ScoreRecorded.
        Aucune écriture en DB nécessaire ici.
        """
        logger.info("Validation completed for %s: score=%d (on-chain via ScoreRecorded)", agent_id, score)

    def _persist_record(self, record: AgentRecord) -> None:
        """Persist agent_id in agent_embeddings so the row exists for embedding lookup."""
        from app.repo.identity_repo import upsert_agent_identity
        upsert_agent_identity(agent_id=record.agent_id)

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