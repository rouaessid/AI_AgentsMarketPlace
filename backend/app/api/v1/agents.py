from __future__ import annotations
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse
from web3 import Web3

from app.core.config import get_settings
from app.models.agent import (
    AgentEditRequest, AgentNewVersionRequest, AgentNewVersionResponse,
    AgentOnChainConfirm, AgentRecord,
    AgentSubmitRequest, AgentSubmitResponse,
    RunRequest,
)
from app.models.purchase import (
    PurchaseInfoResponse, PurchaseRequest, PurchaseResponse,
    AccessStatus, ValidationStatusResponse, JudgeVerdictOut,
)
from app.services.agent_service   import AgentService
from app.services.sandbox_service import SandboxInput, SandboxService
from app.services.ngrok_service   import get_agent_endpoint, get_ngrok_url
from app.db import access_repo

logger      = logging.getLogger(__name__)
router      = APIRouter(prefix="/agents", tags=["agents"])
agent_svc   = AgentService()
sandbox_svc = SandboxService()
_manifests: dict[str, dict] = {}
_settings   = get_settings()

# ── Minimal EscrowManager ABI for depositPayment ─────────────────────────────
_ESCROW_DEPOSIT_ABI = [{
    "inputs": [
        {"internalType": "string", "name": "taskId_",  "type": "string"},
        {"internalType": "string", "name": "agentId_", "type": "string"},
    ],
    "name": "depositPayment",
    "outputs": [],
    "stateMutability": "payable",
    "type": "function",
}]

# ── Minimal IdentityRegistry ABI for on-chain price/status checks ─────────────
_IDENTITY_REGISTRY_ABI = [
    {
        "inputs": [{"internalType": "string", "name": "agentId_", "type": "string"}],
        "name": "isActive",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "string", "name": "agentId_", "type": "string"}],
        "name": "getPricePerTask",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# ── Minimal IdentityRegistry ABI — price + status ────────────────────────────
_IDENTITY_REGISTRY_ABI = [
    {
        "inputs": [{"internalType": "string", "name": "agentId_", "type": "string"}],
        "name": "getPricePerTask",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "string", "name": "agentId_", "type": "string"}],
        "name": "isActive",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# ── Minimal ReputationRegistry ABI for giveFeedback ──────────────────────────
_REPUTATION_GIVE_FEEDBACK_ABI = [{
    "inputs": [
        {"internalType": "uint256", "name": "agentId",       "type": "uint256"},
        {"internalType": "int128",  "name": "value",         "type": "int128"},
        {"internalType": "uint8",   "name": "valueDecimals", "type": "uint8"},
        {"internalType": "string",  "name": "tag1",          "type": "string"},
        {"internalType": "string",  "name": "tag2",          "type": "string"},
        {"internalType": "string",  "name": "endpoint",      "type": "string"},
        {"internalType": "string",  "name": "feedbackURI",   "type": "string"},
        {"internalType": "bytes32", "name": "feedbackHash",  "type": "bytes32"},
    ],
    "name": "giveFeedback",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function",
}]



def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(404, detail=str(exc))
    if isinstance(exc, (PermissionError, ValueError)):
        return HTTPException(400, detail=str(exc))
    logger.exception("Erreur inattendue")
    return HTTPException(500, detail=str(exc))


@router.post("/register", response_model=AgentSubmitResponse, status_code=201)
async def register_agent(req: AgentSubmitRequest) -> AgentSubmitResponse:
    """Accept JSON body (AgentSubmitRequest) — sent by the React frontend."""
    try:
        return await agent_svc.submit(req)
    except Exception as e:
        raise _http(e)


@router.post("/{agent_id}/retry-register")
async def retry_register(agent_id: str) -> JSONResponse:
    """
    Re-génère unsigned_tx pour un agent bloqué en pending_signature.
    Utile quand le MetaMask tx a revert (ex: out of gas) sans avoir à re-remplir le formulaire.
    """
    from app.services.agent_service import _records, _agent_index, _build_register_tx
    rid = _agent_index.get(agent_id)
    if not rid or rid not in _records:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")
    record = _records[rid]
    if record.status.value not in ("pending_signature", "active"):
        raise HTTPException(400, detail=f"Agent '{agent_id}' n'est pas en pending_signature (status={record.status.value})")

    # Re-build unsigned_tx with fresh gas estimate — IPFS already uploaded
    class _FakeReq:
        def __init__(self, r):
            self.agent_id    = r.agent_id
            self.agent_type  = r.agent_type
            self.version     = r.version
            self.price_per_task = r.price_per_task or 0.0
    unsigned_tx = _build_register_tx(_FakeReq(record), record.agent_uri or "")
    return JSONResponse({
        "agent_id":        agent_id,
        "registration_id": rid,
        "agent_uri":       record.agent_uri,
        "ipfs_cid":        record.ipfs_cid,
        "unsigned_tx":     unsigned_tx.model_dump(),
        "status":          record.status.value,
    })


@router.post("/confirm", response_model=AgentRecord)
async def confirm_onchain(body: AgentOnChainConfirm, bg: BackgroundTasks) -> AgentRecord:
    try:
        return await agent_svc.confirm(body)
    except Exception as e:
        raise _http(e)


@router.delete("/reset", tags=["dev"])
async def reset_store() -> JSONResponse:
    from app.services.agent_service import _records, _agent_index
    _records.clear()
    _agent_index.clear()
    return JSONResponse({"message": "Store reset OK"})


@router.get("/{agent_id}/status")
async def registration_status(agent_id: str) -> JSONResponse:
    """
    Polling endpoint for the pure blockchain-first registration flow.

    Frontend calls this every 2 s after submit() returns tx_hash.
    Returns the current DB status:
      - "pending_index"    : tx sent, indexer hasn't seen AgentCreated yet
      - "pending_signature": blockchain unavailable, MetaMask signature needed
      - "active"           : indexer confirmed AgentCreated — agent is live
      - "suspended" / "revoked" : changed by governance
    """
    from app.db.identity_repo import get_agent_identity
    row = get_agent_identity(agent_id)
    if not row:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")
    return JSONResponse({
        "agent_id":   agent_id,
        "status":     row["status"],
        "token_id":   row["current_token_id"],
        "tx_hash":    row["tx_hash"],
        "block_number": row["block_number"],
        "confirmed":  row["status"] == "active",
    })


@router.post("/{agent_id}/version", response_model=AgentNewVersionResponse)
async def new_version(agent_id: str, body: AgentNewVersionRequest) -> AgentNewVersionResponse:
    if body.agent_id != agent_id:
        raise HTTPException(400, detail="agent_id mismatch")
    try:
        return await agent_svc.new_version(body)
    except Exception as e:
        raise _http(e)


@router.get("/owner/{owner_address}")
async def list_by_owner(owner_address: str) -> JSONResponse:
    if not (owner_address.startswith("0x") and len(owner_address) == 42):
        raise HTTPException(400, detail="Adresse Ethereum invalide")
    records = await agent_svc.list_by_owner(owner_address)

    from app.models.agent import AgentType as _AgentType
    from app.db.judge_reputation_repo import get_judge_reputation
    from app.db.escrow_repo import get_escrow_events_for_agent

    result = []
    for r in records:
        data = r.model_dump(mode="json")

        # ── Earnings from escrow: sum released payments for this agent ──────
        events        = get_escrow_events_for_agent(r.agent_id)
        released_wei  = sum(int(e["amount_wei"] or 0) for e in events if e["event_type"] == "released")
        data["earnings_eth"] = round(released_wei / 1e18, 6)

        # ── Judge-specific metrics injected into capabilities ────────────────
        if r.agent_type == _AgentType.JUDGE:
            rep  = get_judge_reputation(r.agent_id)
            reg  = data.get("registration_file") or {}
            caps = dict(reg.get("capabilities") or {})
            caps["tasks_performed"]  = rep["total_validations"]
            caps["reputation_score"] = round(rep["agreement_rate"] * 100, 1)
            caps["success_rate"]     = round(rep["agreement_rate"] * 100, 1)
            if data.get("registration_file") is not None:
                data["registration_file"]["capabilities"] = caps

        result.append(data)

    return JSONResponse({"agents": result, "total": len(result)})


@router.get("")
async def list_all(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)) -> JSONResponse:
    records, total = await agent_svc.list_all(page, size)
    return JSONResponse({"agents": [r.model_dump(mode="json") for r in records],
                         "total": total, "page": page, "size": size})


@router.get("/{agent_id}/versions")
async def get_versions(agent_id: str) -> JSONResponse:
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")
    return JSONResponse({
        "agent_id": agent_id,
        "versions": [v.model_dump(mode="json") for v in record.versions],
        "total_versions": len(record.versions),
        "current_token_id": record.current_token_id,
    })


@router.get("/{agent_id}/endpoint")
async def get_endpoint(agent_id: str) -> JSONResponse:
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")
    endpoint = record.platform_endpoint or get_agent_endpoint(agent_id)
    return JSONResponse({"agent_id": agent_id, "platform_endpoint": endpoint,
                         "available": endpoint is not None})


@router.patch("/{agent_id}")
async def edit_agent(agent_id: str, body: AgentEditRequest) -> JSONResponse:
    """
    Editorial changes — no blockchain tx, no new token.
    Accepts: description, readme, price_per_task, name.
    Updates DB + re-uploads IPFS manifest.
    """
    try:
        result = await agent_svc.edit_agent(agent_id, body)
        return JSONResponse(result)
    except Exception as e:
        raise _http(e)


@router.get("/{agent_id}/readme")
async def get_readme(agent_id: str) -> JSONResponse:
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")
    rf = record.registration_file
    return JSONResponse({
        "agent_id":     agent_id,
        "name":         record.name,
        "version":      record.version,
        "readme":       rf.readme if rf else "Aucune documentation.",
        "env_var_keys": rf.capabilities.get("env_var_keys", []) if rf else [],
        "pricing":      rf.pricing if rf else {},
        "endpoint":     record.platform_endpoint or get_agent_endpoint(agent_id),
    })


@router.get("/{agent_id}", response_model=AgentRecord)
async def get_agent(agent_id: str) -> AgentRecord:
    try:
        return await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")


@router.post("/{agent_id}/sandbox")
async def run_sandbox(agent_id: str, task_prompt: str = Query("Test sandbox")) -> JSONResponse:
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")
    try:
        manifest = await sandbox_svc.run_agent(
            record,
            SandboxInput(task_id=f"sandbox_{record.id[:8]}",
                         agent_id=agent_id, task_prompt=task_prompt),
        )
    except Exception as e:
        logger.exception("Erreur Sandbox: %s", e)
        raise HTTPException(500, detail=str(e))
    _manifests[manifest.run_id] = manifest.to_dict()
    return JSONResponse(manifest.to_dict())


@router.get("/{agent_id}/sandbox/{run_id}")
async def get_manifest(agent_id: str, run_id: str) -> JSONResponse:
    if run_id not in _manifests:
        raise HTTPException(404, detail="Manifest introuvable")
    return JSONResponse(_manifests[run_id])


# ─── Run public — buyer ───────────────────────────────────────────────────────

@router.post("/{agent_id}/run")
async def run_agent_public(
    agent_id: str,
    body: RunRequest,
    bg: BackgroundTasks,
) -> JSONResponse:
    print(f"\n🚀 [DEBUG] REQUETE RECUE POUR L'AGENT: {agent_id}")
    print(f"📝 Prompt: {body.prompt[:50]}...")
    logger.info("Incoming run request for agent=%s", agent_id)
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")

    if record.status.value != "active":
        raise HTTPException(403, detail=f"Agent '{agent_id}' non actif")

    rf            = record.registration_file
    _SENSITIVE    = ("PRIVATE_KEY", "SECRET_KEY", "WALLET_KEY", "MNEMONIC", "SEED_PHRASE")
    all_keys      = rf.sandbox_config.get("env_var_keys", []) if rf else []
    # Only require keys the buyer is expected to provide (same filter as frontend).
    required_keys = [k for k in all_keys if not any(p in k.upper() for p in _SENSITIVE)]
    missing       = [k for k in required_keys if k not in body.params]
    if missing:
        raise HTTPException(400, detail=f"Cles API manquantes: {missing}. Requises: {required_keys}")

    # ── Résoudre le digest frais à la volée ───────────────────────────────
    # Évite exit_code 125 "image not found" après docker build --no-cache
    docker_image = record.docker_image or ""
    image_tag    = docker_image.split("@")[0] if "@" in docker_image else docker_image

    if image_tag:
        try:
            fresh = await sandbox_svc.resolve_image_digest(image_tag)
            if "@sha256:" in fresh and fresh != docker_image:
                logger.warning("Digest obsolète %s → mise à jour automatique", agent_id)
                from app.services.agent_service import _records, _agent_index
                from app.db.agent_repo import upsert_agent
                rid = _agent_index.get(agent_id)
                if rid and rid in _records:
                    _records[rid] = _records[rid].model_copy(
                        update={"docker_image": fresh}
                    )
                upsert_agent(
                    agent_id=record.agent_id, registration_id=record.id,
                    token_id=record.current_token_id, tx_hash=record.tx_hash,
                    docker_image=fresh, status=record.status.value,
                    registered_at=record.registered_at.isoformat()
                                  if record.registered_at else None,
                    owner_address=record.owner_address,
                )
                record = record.model_copy(update={"docker_image": fresh})
                logger.info("Digest mis à jour: %s", fresh[:70])
            elif "@sha256:" not in fresh:
                logger.warning(
                    "Image '%s' non trouvée localement — "
                    "le seller doit faire 'docker build -t %s .'",
                    image_tag, image_tag
                )
        except Exception as e:
            logger.warning("Résolution digest: %s", e)
    # ── FIN ───────────────────────────────────────────────────────────────

    try:
        manifest = await sandbox_svc.run_agent(
            record,
            SandboxInput(
                task_id=str(uuid.uuid4())[:8],
                agent_id=agent_id,
                task_prompt=body.prompt,
                task_params=body.params,
            ),
            env_vars=body.params,
        )
    except Exception as e:
        logger.exception("Erreur Run: %s", e)
        raise HTTPException(500, detail=str(e))

    _manifests[manifest.run_id] = manifest.to_dict()
    ngrok_url = get_ngrok_url()

    # ── Update run metrics (usage_count, tasks_performed, avg_response_time) ──
    agent_svc.update_run_metrics(
        agent_id,
        success=manifest.status not in ("error", "failed"),
        duration_sec=manifest.duration_sec,
    )

    # ── Trigger validation if buyer has paid ─────────────────────────────────
    if manifest.status not in ("error", "failed") and manifest.proxy_cid and body.buyer_wallet:
        grant = access_repo.get_access_grant(agent_id, body.buyer_wallet)
        if grant:
            val_task_id = f"val-{manifest.run_id[:16]}"
            access_repo.upsert_validation_session(
                agent_id, val_task_id=val_task_id, status="pending"
            )
            from app.services.judge_service import run_validation
            bg.add_task(
                run_validation, agent_id, val_task_id, manifest.proxy_cid,
                0, body.prompt,
            )
            logger.info("Validation triggered for agent=%s cid=%s", agent_id, manifest.proxy_cid)

    return JSONResponse({
        "run_id":            manifest.run_id,
        "agent_id":          agent_id,
        "token_id":          manifest.token_id,
        "docker_image":      manifest.docker_image,
        "status":            manifest.status,
        "output":            manifest.output,
        "manifest_hash":     manifest.manifest_hash,
        "platform_sig":      manifest.platform_sig,
        "duration_sec":      manifest.duration_sec,
        "error":             manifest.error,
        "endpoint":          f"{ngrok_url}/api/v1/agents/{agent_id}/run" if ngrok_url else None,
        "proxy_hash":        manifest.proxy_hash,
        "proxy_cid":         manifest.proxy_cid,
        "proxy_metrics":     manifest.proxy_metrics,
        "validation_started": bool(manifest.proxy_cid and body.buyer_wallet
                                   and access_repo.get_access_grant(agent_id, body.buyer_wallet or "")),
    })


async def _bg_sandbox(record: AgentRecord, inp: SandboxInput) -> None:
    try:
        m = await sandbox_svc.run_agent(record, inp)
        _manifests[m.run_id] = m.to_dict()
    except Exception:
        logger.exception("BG sandbox failed for %s", record.agent_id)


# ═════════════════════════════════════════════════════════════════════════════
#  BUYER — Purchase & Validation endpoints
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/{agent_id}/purchase-info")
async def get_purchase_info(agent_id: str) -> PurchaseInfoResponse:
    """
    Returns everything the frontend needs to build the MetaMask transaction:
    - a unique task_id
    - the exact ETH amount required (read from IdentityRegistry via web3)
    - the EscrowManager address
    - the encoded calldata for depositPayment()
    """
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")

    task_id = f"task-{uuid.uuid4().hex[:16]}"

    # Fallback: DB price
    price_eth = record.price_per_task or 0.0
    price_wei = int(price_eth * 10**18)

    escrow_address = _settings.escrow_manager_address or ""
    call_data = "0x"

    w3 = Web3(Web3.HTTPProvider(_settings.rpc_url))

    # Read the real price from IdentityRegistry (set at registration time).
    # This is the authoritative value that EscrowManager will enforce on-chain.
    if _settings.identity_registry_address:
        try:
            ir = w3.eth.contract(
                address=Web3.to_checksum_address(_settings.identity_registry_address),
                abi=_IDENTITY_REGISTRY_ABI,
            )
            on_chain_wei: int = ir.functions.getPricePerTask(agent_id).call()
            price_wei = on_chain_wei
            price_eth = on_chain_wei / 10**18
        except Exception as e:
            logger.warning("Could not read on-chain price for %s (using DB fallback): %s", agent_id, e)

    # Build calldata for depositPayment(taskId_, agentId_)
    if escrow_address:
        try:
            escrow = w3.eth.contract(
                address=Web3.to_checksum_address(escrow_address),
                abi=_ESCROW_DEPOSIT_ABI,
            )
            call_data = escrow.encode_abi("depositPayment", args=[task_id, agent_id])
        except Exception as e:
            logger.warning("Could not encode calldata: %s", e)

    return PurchaseInfoResponse(
        task_id=task_id,
        agent_id=agent_id,
        required_wei=hex(price_wei),
        required_eth=price_eth,
        escrow_address=escrow_address,
        call_data=call_data,
    )


@router.post("/{agent_id}/purchase")
async def purchase_agent(
    agent_id: str,
    body: PurchaseRequest,
) -> PurchaseResponse:
    """
    Called after buyer's MetaMask tx is confirmed.
    Grants access — validation fires after the first Run (needs proxy_cid).
    """
    try:
        await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")

    # Check not already purchased by this buyer
    existing = access_repo.get_access_grant(agent_id, body.buyer_wallet)
    if existing:
        return PurchaseResponse(
            access_id=existing["id"],
            agent_id=agent_id,
            task_id=existing["task_id"],
            tx_hash=existing["tx_hash"] or body.tx_hash,
            status="granted",
            validation_status=_get_val_status(agent_id),
        )

    # Verify payment exists on-chain before granting access
    from app.db.escrow_repo import get_escrow_events_for_task
    onchain = get_escrow_events_for_task(body.task_id)
    if not any(e["event_type"] == "deposited" for e in onchain):
        raise HTTPException(402, detail="Paiement non trouvé on-chain — attendez la confirmation du bloc")

    access_id = access_repo.create_access_grant(
        agent_id=agent_id,
        buyer_wallet=body.buyer_wallet,
        task_id=body.task_id,
        tx_hash=body.tx_hash,
    )

    # Validation is NOT triggered here — it fires after the first Run
    # so judges have a real proxy trace (proxy_cid) to evaluate.
    access_repo.upsert_validation_session(
        agent_id, val_task_id=None, status="awaiting_run"
    )

    return PurchaseResponse(
        access_id=access_id,
        agent_id=agent_id,
        task_id=body.task_id,
        tx_hash=body.tx_hash,
        status="granted",
        validation_status="awaiting_run",
    )


@router.get("/{agent_id}/access")
async def check_access(
    agent_id: str,
    buyer_wallet: str = Query(description="Buyer Ethereum address"),
) -> JSONResponse:
    """Check whether a buyer has paid for this agent."""
    grant = access_repo.get_access_grant(agent_id, buyer_wallet)
    if not grant:
        return JSONResponse(AccessStatus(
            agent_id=agent_id,
            buyer_wallet=buyer_wallet,
            has_access=False,
        ).model_dump())

    val_status = _get_val_status(agent_id)
    return JSONResponse(AccessStatus(
        agent_id=agent_id,
        buyer_wallet=buyer_wallet,
        has_access=True,
        task_id=grant["task_id"],
        tx_hash=grant["tx_hash"],
        validation_status=val_status,
    ).model_dump())


@router.get("/{agent_id}/validation")
async def get_validation(agent_id: str) -> ValidationStatusResponse:
    """Return the validation status and judge verdicts for an agent."""
    session  = access_repo.get_validation_session(agent_id)
    verdicts = access_repo.get_judge_verdicts(agent_id)

    if not session:
        return ValidationStatusResponse(agent_id=agent_id, status="not_started")

    return ValidationStatusResponse(
        agent_id=agent_id,
        status=session["status"],
        consensus_verdict=session["consensus_verdict"],
        aggregated_score=session["aggregated_score"],
        started_at=session["started_at"],
        finished_at=session["finished_at"],
        judges=[
            JudgeVerdictOut(
                judge_id=v["judge_id"],
                judge_name=v["judge_name"],
                score=v["score"],
                justification=v["justification"],
                verdict=v["verdict"],
            )
            for v in verdicts
        ],
    )


@router.post("/{agent_id}/validate", tags=["dev"])
async def trigger_validation(agent_id: str, bg: BackgroundTasks) -> JSONResponse:
    """Dev endpoint: manually trigger validation for an agent without payment."""
    try:
        await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")

    val_task_id = f"val-dev-{uuid.uuid4().hex[:12]}"
    access_repo.upsert_validation_session(agent_id, val_task_id=val_task_id, status="pending")

    # Use a placeholder CID for dev trigger — judges will get minimal trace data
    dev_proxy_cid = f"QmDEV{uuid.uuid4().hex[:40]}"
    from app.services.judge_service import run_validation
    bg.add_task(run_validation, agent_id, val_task_id, dev_proxy_cid)

    return JSONResponse({"agent_id": agent_id, "val_task_id": val_task_id, "status": "validation_started"})


# ── Reputation ────────────────────────────────────────────────────────────────

@router.get("/{agent_id}/reputation")
async def get_agent_reputation(agent_id: str):
    """
    Return on-chain reputation signals for an agent, aggregated by tag1.

    Signals are indexed from ReputationRegistry NewFeedback events:
      - successRate : judge verdicts from ValidationRegistry
      - starred     : user ratings (1-5 stars, stored as 20-100)
      - eigenTrust  : platform EigenTrust score (Phase 2)
    """
    from app.db.identity_repo import get_agent_identity
    from app.db.reputation_repo import get_aggregated_score, get_reputation_signals

    identity = get_agent_identity(agent_id)
    if not identity:
        raise HTTPException(404, detail=f"Agent {agent_id!r} not found")

    token_id = identity.get("current_token_id")
    if not token_id:
        return JSONResponse({
            "agent_id":  agent_id,
            "token_id":  None,
            "signals":   [],
            "aggregated": {},
            "message":  "Agent not yet registered on-chain",
        })

    aggregated = get_aggregated_score(token_id)
    signals    = get_reputation_signals(token_id)

    return JSONResponse({
        "agent_id":   agent_id,
        "token_id":   token_id,
        "aggregated": aggregated,
        "signals":    signals,
    })


@router.get("/{agent_id}/feedback-info")
async def get_feedback_info(
    agent_id: str,
    score: int = Query(..., ge=1, le=5, description="Note 1-5 étoiles"),
):
    """
    Retourne le calldata encodé pour que le frontend puisse appeler
    giveFeedback() via MetaMask (msg.sender = adresse user = clientAddress).

    score 1-5 → value = score × 20  (range 20-100, valueDecimals=0, tag1="starred")

    Flux frontend :
      1. GET /agents/{id}/feedback-info?score=4
      2. Signer + envoyer la tx avec MetaMask (to=reputation_address, data=call_data)
      3. L'indexer capte le NewFeedback event → reputation_events mis à jour
    """
    from app.db.identity_repo import get_agent_identity

    identity = get_agent_identity(agent_id)
    if not identity:
        raise HTTPException(404, detail=f"Agent {agent_id!r} introuvable")

    token_id = identity.get("current_token_id")
    if not token_id:
        raise HTTPException(400, detail="Agent non encore enregistré on-chain")

    reputation_address = _settings.reputation_registry_address or ""
    call_data = "0x"

    if reputation_address:
        try:
            w3 = Web3(Web3.HTTPProvider(_settings.rpc_url))
            rep = w3.eth.contract(
                address=Web3.to_checksum_address(reputation_address),
                abi=_REPUTATION_GIVE_FEEDBACK_ABI,
            )
            value_on_chain = score * 20   # 1★=20, 2★=40, 3★=60, 4★=80, 5★=100
            call_data = rep.encode_abi(
                "giveFeedback",
                args=[
                    token_id,         # agentId (uint256 = tokenId)
                    value_on_chain,   # value (int128)
                    0,                # valueDecimals
                    "starred",        # tag1
                    "",               # tag2
                    "",               # endpoint
                    "",               # feedbackURI
                    b"\x00" * 32,     # feedbackHash
                ],
            )
        except Exception as e:
            logger.warning("feedback-info encode error: %s", e)

    return JSONResponse({
        "agent_id":           agent_id,
        "token_id":           token_id,
        "score":              score,
        "value_on_chain":     score * 20,
        "reputation_address": reputation_address,
        "call_data":          call_data,
    })


# ── Judge-specific endpoints ──────────────────────────────────────────────────

@router.get("/{agent_id}/judge-stats")
async def get_judge_stats(agent_id: str):
    """Aggregated statistics for a judge agent (for the 'My Agents > View' panel)."""
    from app.db.judge_reputation_repo import get_judge_reputation
    from app.db.access_repo import get_verdicts_by_judge
    from datetime import datetime, timezone, timedelta

    rep      = get_judge_reputation(agent_id)
    verdicts = get_verdicts_by_judge(agent_id)
    now      = datetime.now(timezone.utc)

    total       = len(verdicts)
    valid_count = sum(1 for v in verdicts if v["verdict"] == "VALID")
    avg_score   = round(sum(v["score"] for v in verdicts) / total, 1) if total else 0
    valid_rate  = round((valid_count / total) * 100, 1) if total else 0
    this_month  = sum(
        1 for v in verdicts
        if (v.get("created_at") or "")[:7] == now.strftime("%Y-%m")
    )

    # Monthly validation volume — last 12 months
    monthly_data = []
    for i in range(11, -1, -1):
        month_num  = now.month - i
        year_delta = 0
        while month_num <= 0:
            month_num  += 12
            year_delta -= 1
        yr  = now.year + year_delta
        ym  = f"{yr:04d}-{month_num:02d}"
        lbl = datetime(yr, month_num, 1).strftime("%b")
        cnt = sum(1 for v in verdicts if (v.get("created_at") or "")[:7] == ym)
        monthly_data.append({"month": lbl, "validations": cnt})

    # Weekly verdicts breakdown — last 7 days
    weekly_data = []
    for i in range(6, -1, -1):
        day     = now - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        lbl     = day.strftime("%a")
        valid   = sum(1 for v in verdicts
                      if (v.get("created_at") or "")[:10] == day_str and v["verdict"] == "VALID")
        invalid = sum(1 for v in verdicts
                      if (v.get("created_at") or "")[:10] == day_str and v["verdict"] == "INVALID")
        weekly_data.append({"day": lbl, "valid": valid, "invalid": invalid})

    return JSONResponse({
        "judge_id":          agent_id,
        "total_validations": rep["total_validations"],
        "agreement_rate":    round(rep["agreement_rate"] * 100, 1),
        "agreement_count":   rep["agreement_count"],
        "avg_score":         avg_score,
        "valid_rate":        valid_rate,
        "this_month":        this_month,
        "monthly_data":      monthly_data,
        "weekly_data":       weekly_data,
    })


@router.get("/{agent_id}/judge-history")
async def get_judge_history(
    agent_id: str,
    limit:  int = Query(50,  ge=1, le=200),
    offset: int = Query(0,   ge=0),
):
    """Paginated list of verdicts issued by this judge agent."""
    from app.db.access_repo import get_verdicts_by_judge

    all_v = get_verdicts_by_judge(agent_id)
    page  = all_v[offset: offset + limit]

    return JSONResponse({
        "total":  len(all_v),
        "offset": offset,
        "limit":  limit,
        "verdicts": [
            {
                "agent_id":      v["agent_id"],
                "verdict":       v["verdict"],
                "score":         v["score"],
                "justification": v["justification"],
                "created_at":    v["created_at"],
            }
            for v in page
        ],
    })


# ── Internal helper ───────────────────────────────────────────────────────────

def _get_val_status(agent_id: str) -> str:
    session = access_repo.get_validation_session(agent_id)
    return session["status"] if session else "not_started"
