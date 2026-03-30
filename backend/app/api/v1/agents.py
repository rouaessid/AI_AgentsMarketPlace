from __future__ import annotations
import json, logging
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from app.models.agent import (
    AgentNewVersionRequest, AgentNewVersionResponse,
    AgentOnChainConfirm, AgentRecord,
    AgentSubmitRequest, AgentSubmitResponse,
)
from app.services.agent_service import AgentService
from app.services.ngrok_service import get_agent_endpoint

logger    = logging.getLogger(__name__)
router    = APIRouter(prefix="/agents", tags=["agents"])
agent_svc = AgentService()


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
    data:     Annotated[str, Form()],
    zip_file: Annotated[UploadFile | None, File()] = None,
) -> AgentSubmitResponse:
    try:
        req = AgentSubmitRequest.model_validate(_parse(data))
    except Exception as e:
        raise HTTPException(422, detail=str(e))
    if zip_file and not (zip_file.filename or "").endswith((".zip", ".tar.gz")):
        raise HTTPException(400, detail="ZIP attendu (.zip ou .tar.gz)")
    try:
        return await agent_svc.submit(req, zip_file)
    except Exception as e:
        raise _http(e)


@router.post("/confirm", response_model=AgentRecord)
async def confirm_onchain(body: AgentOnChainConfirm) -> AgentRecord:
    try:
        return await agent_svc.confirm(body)
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


@router.get("/{agent_id}/endpoint")
async def get_endpoint(agent_id: str) -> JSONResponse:
    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")
    endpoint = record.platform_endpoint or get_agent_endpoint(agent_id)
    return JSONResponse({"agent_id": agent_id, "platform_endpoint": endpoint,
                         "available": endpoint is not None})


@router.get("/{agent_id}", response_model=AgentRecord)
async def get_agent(agent_id: str) -> AgentRecord:
    try:
        return await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        raise HTTPException(404, detail=f"Agent '{agent_id}' introuvable")