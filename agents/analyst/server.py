"""
server.py — AnalystBot HTTP server.

POST /api/v1/agents/analyst-01/run
  { "task_id": "task-abc", "prompt": "<text or JSON to analyze>" }

The platform proxy captures all outgoing HTTP calls automatically.
The seller knows nothing about IPFS, escrow, or staking.
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import AnalystAgent

AGENT_ID   = "analyst-01"
AGENT_NAME = "AnalystBot"

_agent: AnalystAgent | None = None
_startup_error: str | None = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _agent, _startup_error
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        _startup_error = "Missing env var: GROQ_API_KEY"
        print(f"[analyst] ERROR: {_startup_error}", flush=True)
    else:
        try:
            _agent = AnalystAgent(groq_api_key=groq_key)
            print("[analyst] Agent ready", flush=True)
        except Exception as e:
            _startup_error = str(e)
            print(f"[analyst] Startup failed: {e}", flush=True)
    yield


app = FastAPI(title=AGENT_NAME, version="1.0.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class RunRequest(BaseModel):
    task_id: str | None = None
    prompt:  str


class RunResponse(BaseModel):
    task_id: str
    output:  dict
    status:  str = "completed"


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
        result = await loop.run_in_executor(
            None, functools.partial(_agent.run, prompt=req.prompt, task_id=task_id)
        )
        return RunResponse(task_id=task_id, output=result["output"])
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/sandbox", response_model=RunResponse)
async def sandbox(req: RunRequest):
    return await run(req)
