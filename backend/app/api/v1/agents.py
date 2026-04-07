from __future__ import annotations
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Query
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


@router.post("/register", response_model=AgentSubmitResponse, status_code=201)
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
    return JSONResponse({"agents": [r.model_dump(mode="json") for r in records], "total": len(records)})


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
async def run_agent_public(agent_id: str, body: RunRequest) -> JSONResponse:
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")

    if record.status.value != "active":
        raise HTTPException(403, detail=f"Agent '{agent_id}' non actif")

    rf            = record.registration_file
    required_keys = rf.sandbox_config.get("env_var_keys", []) if rf else []
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
        "error":         manifest.error,
        "endpoint":      f"{ngrok_url}/api/v1/agents/{agent_id}/run" if ngrok_url else None,
        "proxy_hash":    manifest.proxy_hash,
        "proxy_cid":     manifest.proxy_cid,
        "proxy_metrics": manifest.proxy_metrics,
    })


async def _bg_sandbox(record: AgentRecord, inp: SandboxInput) -> None:
    try:
        m = await sandbox_svc.run_agent(record, inp)
        _manifests[m.run_id] = m.to_dict()
    except Exception:
        logger.exception("BG sandbox failed for %s", record.agent_id)