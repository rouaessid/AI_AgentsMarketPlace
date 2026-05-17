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
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import ResearchAgent

AGENT_ID   = "researcher-01"
AGENT_NAME = "ResearchBot"

_agent: ResearchAgent | None = None
_startup_error: str | None = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _agent, _startup_error
    groq_key   = os.environ.get("GROQ_API_KEY", "")
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if not groq_key or not tavily_key:
        missing = [k for k, v in {"GROQ_API_KEY": groq_key, "TAVILY_API_KEY": tavily_key}.items() if not v]
        _startup_error = f"Missing env vars: {', '.join(missing)}"
        print(f"[researcher] ERROR: {_startup_error}", flush=True)
    else:
        try:
            _agent = ResearchAgent(groq_api_key=groq_key, tavily_api_key=tavily_key)
            print("[researcher] Agent ready", flush=True)
        except Exception as e:
            _startup_error = str(e)
            print(f"[researcher] Startup failed: {e}", flush=True)
    yield


app = FastAPI(title=AGENT_NAME, version="1.0.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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
    if _startup_error:
        return {"status": "error", "agent": AGENT_ID, "message": _startup_error}
    return {"status": "ok", "agent": AGENT_ID}


@app.get("/info")
def info():
    return {"agent_id": AGENT_ID, "name": AGENT_NAME, "version": "1.0.0", "status": "active"}


@app.post("/run", response_model=RunResponse)
async def run(req: RunRequest):
    if not _agent:
        raise HTTPException(503, "Agent not ready")

    task_id = req.task_id or f"task-{uuid.uuid4().hex[:8]}"

    try:
        import asyncio, functools
        loop = asyncio.get_event_loop()
        # Run blocking sync code in a thread so the event loop stays free
        # (allows /health to respond during long Groq/Tavily calls)
        result = await loop.run_in_executor(
            None, functools.partial(_agent.run, query=req.prompt, task_id=task_id)
        )
        return RunResponse(task_id=task_id, output=result["output"])
    except Exception as e:
        raise HTTPException(500, str(e))
