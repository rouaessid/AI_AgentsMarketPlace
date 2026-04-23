"""
server.py — ResearchBot HTTP server.

Le seller écrit CE fichier (ou n'importe quel framework).
La plateforme AgentMarket se charge de :
  - Runner ce container derrière son proxy (capture automatique des traces)
  - Uploader les traces sur IPFS
  - Soumettre validationRequest() on-chain

Le seller ne connaît RIEN de tout cela.
Il expose juste un endpoint POST /run qui prend un prompt et retourne un résultat.
"""
from __future__ import annotations
import os
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import ResearchAgent

# ── Config ────────────────────────────────────────────────────────────────────
AGENT_ID   = "researcher-01"
AGENT_NAME = "ResearchBot"

GROQ_API_KEY   = os.environ["GROQ_API_KEY"]
TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title=AGENT_NAME, version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_agent: ResearchAgent | None = None


@app.on_event("startup")
def startup():
    global _agent
    _agent = ResearchAgent(groq_api_key=GROQ_API_KEY, tavily_api_key=TAVILY_API_KEY)


# ── Schemas ───────────────────────────────────────────────────────────────────
class RunRequest(BaseModel):
    task_id: str | None = None
    prompt:  str


class RunResponse(BaseModel):
    task_id: str
    output:  dict
    status:  str = "completed"


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "agent": AGENT_ID}


@app.get(f"/api/v1/agents/{AGENT_ID}")
def info():
    return {"agent_id": AGENT_ID, "name": AGENT_NAME, "version": "1.0.0", "status": "active"}


@app.post(f"/api/v1/agents/{AGENT_ID}/run", response_model=RunResponse)
async def run(req: RunRequest):
    """
    Main endpoint called by the platform after a buyer submits a task.
    The platform wraps this call with its proxy → traces all HTTP calls automatically.
    """
    if not _agent:
        raise HTTPException(503, "Agent not ready")

    task_id = req.task_id or f"task-{uuid.uuid4().hex[:8]}"

    try:
        # agent.run() makes HTTP calls (Groq API + Tavily API)
        # → all captured automatically by platform proxy
        result = _agent.run(query=req.prompt, task_id=task_id)
        return RunResponse(task_id=task_id, output=result["output"])
    except Exception as e:
        raise HTTPException(500, str(e))
