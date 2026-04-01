from __future__ import annotations
import json
import logging
import uuid
from typing import Annotated

from fastapi import (
    APIRouter, BackgroundTasks, Form,
    HTTPException, Query,
)
from fastapi.responses import JSONResponse

from app.models.agent import (
    AgentNewVersionRequest, AgentNewVersionResponse,
    AgentOnChainConfirm, AgentRecord,
    AgentSubmitRequest, AgentSubmitResponse,
    RunRequest,
)
from app.services.agent_service   import AgentService
from app.services.sandbox_service import SandboxInput, SandboxService
from app.services.ngrok_service   import get_agent_endpoint, get_ngrok_url

logger      = logging.getLogger(__name__)
router      = APIRouter(prefix="/agents", tags=["agents"])
agent_svc   = AgentService()
sandbox_svc = SandboxService()
_manifests: dict[str, dict] = {}


def _parse(data: str) -> dict:
    try:
        return json.loads(data)
    except Exception as e:
        raise HTTPException(422, detail=f"JSON invalide: {e}")


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(404, detail=str(exc))
    if isinstance(exc, (PermissionError, ValueError)):
        return HTTPException(400, detail=str(exc))
    logger.exception("Erreur inattendue")
    return HTTPException(500, detail=str(exc))


# ─── Register ────────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=AgentSubmitResponse,
    status_code=201,
    summary="Enregistrer un nouvel agent",
    description="""
Formulaire d'enregistrement d'un agent.

Champs importants :
- `docker_image` : image Docker Hub ex: username/agent:v1
- `env_var_keys` : clés API requises (noms seulement) ex: ["GROQ_API_KEY"]
- `readme` : instructions markdown pour le buyer
- `stake_amount` : ETH a staker (Phase 2)
- `price_per_task` : USDC par appel
- `access_duration_days` : duree d'acces en jours
""",
)
async def register_agent(
    data: Annotated[str, Form(description="AgentSubmitRequest JSON")],
) -> AgentSubmitResponse:
    try:
        req = AgentSubmitRequest.model_validate(_parse(data))
    except Exception as e:
        raise HTTPException(422, detail=str(e))
    try:
        return await agent_svc.submit(req)
    except Exception as e:
        raise _http(e)


@router.post(
    "/confirm",
    response_model=AgentRecord,
    summary="Confirmer la transaction on-chain",
    description="""
Appele apres que le wallet a signe et broadcaste register().
La plateforme :
1. Resout le digest SHA256 de l'image Docker (immuable)
2. Re-upload JSON IPFS avec registrations + digest
3. Lie le tokenId NFT au record
4. Enregistre l'endpoint dans endpoints.json (persistant)
""",
)
async def confirm_onchain(
    body: AgentOnChainConfirm,
    bg:   BackgroundTasks,
) -> AgentRecord:
    try:
        record = await agent_svc.confirm(body)
    except Exception as e:
        raise _http(e)
    return record


# ─── Dev ─────────────────────────────────────────────────────────────────────

@router.delete("/reset", tags=["dev"], summary="Reset memoire (dev only)")
async def reset_store() -> JSONResponse:
    from app.services.agent_service import _records, _agent_index
    _records.clear()
    _agent_index.clear()
    return JSONResponse({"message": "Store reset OK"})


# ─── Versioning ───────────────────────────────────────────────────────────────

@router.post(
    "/{agent_id}/version",
    response_model=AgentNewVersionResponse,
    summary="Publier une nouvelle version",
)
async def new_version(
    agent_id: str,
    body:     AgentNewVersionRequest,
) -> AgentNewVersionResponse:
    if body.agent_id != agent_id:
        raise HTTPException(400, detail="agent_id mismatch")
    try:
        return await agent_svc.new_version(body)
    except Exception as e:
        raise _http(e)


# ─── Read ─────────────────────────────────────────────────────────────────────

@router.get("/owner/{owner_address}", summary="Lister les agents d'un owner")
async def list_by_owner(owner_address: str) -> JSONResponse:
    if not (owner_address.startswith("0x") and len(owner_address) == 42):
        raise HTTPException(400, detail="Adresse Ethereum invalide")
    records = await agent_svc.list_by_owner(owner_address)
    return JSONResponse({
        "agents": [r.model_dump(mode="json") for r in records],
        "total":  len(records),
    })


@router.get("", summary="Lister tous les agents")
async def list_all(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    records, total = await agent_svc.list_all(page, size)
    return JSONResponse({
        "agents": [r.model_dump(mode="json") for r in records],
        "total":  total,
        "page":   page,
        "size":   size,
    })


@router.get("/{agent_id}/versions", summary="Historique des versions")
async def get_versions(agent_id: str) -> JSONResponse:
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")
    return JSONResponse({
        "agent_id":         agent_id,
        "versions":         [v.model_dump(mode="json") for v in record.versions],
        "total_versions":   len(record.versions),
        "current_token_id": record.current_token_id,
    })


@router.get("/{agent_id}/endpoint", summary="Endpoint public de l'agent")
async def get_endpoint(agent_id: str) -> JSONResponse:
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")
    endpoint = record.platform_endpoint or get_agent_endpoint(agent_id)
    return JSONResponse({
        "agent_id":          agent_id,
        "platform_endpoint": endpoint,
        "available":         endpoint is not None,
    })


@router.get("/{agent_id}/readme", summary="README et instructions pour le buyer")
async def get_readme(agent_id: str) -> JSONResponse:
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")
    rf = record.registration_file
    return JSONResponse({
        "agent_id":    agent_id,
        "name":        record.name,
        "version":     record.version,
        "readme":      rf.readme if rf else "Aucune documentation.",
        "env_var_keys": rf.capabilities.get("env_var_keys", []) if rf else [],
        "pricing":     rf.pricing if rf else {},
        "endpoint":    record.platform_endpoint or get_agent_endpoint(agent_id),
    })


@router.get(
    "/{agent_id}",
    response_model=AgentRecord,
    summary="Recuperer un agent par agentId",
)
async def get_agent(agent_id: str) -> AgentRecord:
    try:
        return await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")


# ─── Sandbox ─────────────────────────────────────────────────────────────────

@router.post(
    "/{agent_id}/sandbox",
    summary="Executer l'agent dans le sandbox (test plateforme)",
)
async def run_sandbox(
    agent_id:    str,
    task_prompt: str = Query("Test sandbox"),
) -> JSONResponse:
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")
    try:
        manifest = await sandbox_svc.run_agent(
            record,
            SandboxInput(
                task_id=f"sandbox_{record.id[:8]}",
                agent_id=agent_id,
                task_prompt=task_prompt,
            ),
        )
    except Exception as e:
        logger.exception("Sandbox error")
        raise HTTPException(500, detail=str(e))
    _manifests[manifest.run_id] = manifest.to_dict()
    return JSONResponse(manifest.to_dict())


@router.get(
    "/{agent_id}/sandbox/{run_id}",
    summary="Recuperer un manifest d'execution",
)
async def get_manifest(agent_id: str, run_id: str) -> JSONResponse:
    if run_id not in _manifests:
        raise HTTPException(404, detail="Manifest introuvable")
    return JSONResponse(_manifests[run_id])


# ─── Run public — buyer ───────────────────────────────────────────────────────

@router.post(
    "/{agent_id}/run",
    summary="Executer l'agent — endpoint public buyer",
    description="""
Endpoint consomme par le buyer via l'URL cloudflare tunnel.

Body :
```json
{
  "prompt": "Analyse le marche crypto mars 2026",
  "params": {
    "GROQ_API_KEY":   "gsk_...",
    "TAVILY_API_KEY": "tvly-..."
  }
}
```

- `prompt` : la tache a executer
- `params` : les cles API requises declarees dans env_var_keys

La plateforme verifie que toutes les cles sont presentes
puis les injecte dans le container Docker isole.
""",
)
async def run_agent_public(
    agent_id: str,
    body:     RunRequest,
) -> JSONResponse:
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")

    if record.status.value != "active":
        raise HTTPException(403, detail=f"Agent '{agent_id}' non actif")

    # Verifier que toutes les cles requises sont presentes
    rf            = record.registration_file
    required_keys = rf.sandbox_config.get("env_var_keys", []) if rf else []
    missing       = [k for k in required_keys if k not in body.params]
    if missing:
        raise HTTPException(
            400,
            detail=f"Cles API manquantes dans params: {missing}. "
                   f"Cles requises: {required_keys}"
        )

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
        raise HTTPException(500, detail=str(e))

    _manifests[manifest.run_id] = manifest.to_dict()
    ngrok_url = get_ngrok_url()

    return JSONResponse({
        "run_id":        manifest.run_id,
        "agent_id":      agent_id,
        "token_id":      manifest.token_id,
        "docker_image":  manifest.docker_image,
        "status":        manifest.status,
        "output":        manifest.output,
        "manifest_hash": manifest.manifest_hash,
        "platform_sig":  manifest.platform_sig,
        "duration_sec":  manifest.duration_sec,
        "endpoint":      f"{ngrok_url}/api/v1/agents/{agent_id}/run"
                         if ngrok_url else None,
    })


# ─── Background ──────────────────────────────────────────────────────────────

async def _bg_sandbox(record: AgentRecord, inp: SandboxInput) -> None:
    try:
        m = await sandbox_svc.run_agent(record, inp)
        _manifests[m.run_id] = m.to_dict()
        logger.info("BG sandbox: %s status=%s", m.run_id, m.status)
    except Exception:
        logger.exception("BG sandbox failed for %s", record.agent_id)