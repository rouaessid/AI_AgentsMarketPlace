"""
server.py — Judge Beta HTTP server.

Decentralized judge contract:
  - prompt = IPFS CID of the execution trace
  - Judge fetches the trace from IPFS independently
  - Evaluates with pure Groq reasoning (no external search)

POST /run
  { "task_id": "val-xyz", "prompt": "QmXxxx..." }

Response:
  {
    "task_id": "...",
    "output": { "judge_id": "judge-beta", "score": 78, "verdict": "VALID", "justification": "..." },
    "status": "completed"
  }
"""
from __future__ import annotations
import os
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import evaluate

AGENT_ID   = os.getenv("AGENT_ID",   "judge-beta")
AGENT_NAME = os.getenv("AGENT_NAME", "Judge Beta")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

_ROUTE = f"/api/v1/agents/{AGENT_ID}"

app = FastAPI(title=AGENT_NAME, version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class RunRequest(BaseModel):
    task_id: str | None = None
    prompt:  str        # IPFS CID of the execution trace


class RunResponse(BaseModel):
    task_id: str
    output:  dict
    status:  str = "completed"


@app.get("/health")
def health():
    return {"status": "ok", "agent": AGENT_ID, "role": "judge"}


@app.get(_ROUTE)
def info():
    return {"agent_id": AGENT_ID, "name": AGENT_NAME, "role": "judge",
            "version": "1.0.0", "status": "active"}


@app.post(_ROUTE + "/run", response_model=RunResponse)
async def run(req: RunRequest):
    """
    prompt = IPFS CID of the execution trace.
    The judge fetches the trace from IPFS and evaluates it independently.
    """
    task_id = req.task_id or f"judge-{uuid.uuid4().hex[:8]}"
    cid     = req.prompt.strip()

    verdict = evaluate(cid, groq_api_key=GROQ_API_KEY)
    return RunResponse(task_id=task_id, output=verdict)
