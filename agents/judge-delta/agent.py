"""
agent.py — Judge Delta core logic.

Hallucination detection specialist.
Extracts factual claims from agent output and cross-checks them against
the input context and execution trajectory.
"""
from __future__ import annotations

import json
import logging
import os
import re

import httpx

JUDGE_ID     = os.getenv("JUDGE_ID",     "judge-delta")
JUDGE_NAME   = os.getenv("JUDGE_NAME",   "Judge Delta")
LLM_MODEL    = os.getenv("LLM_MODEL",    "gemini-2.5-flash")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
IPFS_GATEWAY = os.getenv("IPFS_GATEWAY", "https://ipfs.io/ipfs")

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a hallucination detection specialist. Your task is to evaluate whether
the agent's output contains fabricated or unsupported claims.

Step 1 — Extract: List the main factual claims made in the agent output.
Step 2 — Check: For each claim, determine if it is grounded in the task prompt or
         the trajectory context provided.
Step 3 — Score the two dimensions below based on your analysis.

MANDATORY PROTOCOL — you MUST follow this exactly:

1. The trace contains a field "challenge_token". Copy its value VERBATIM into
   your response — do not alter it.

2. From the "trajectory" array in the trace, extract these six values:
   - steps_count   : total number of items in trajectory (integer)
   - first_tool    : "tool" field of trajectory[0], or "" if trajectory is empty
   - last_seq      : "seq" field of the last trajectory item, or -1 if empty
   - has_errors    : true if any item has "status" >= 400, false otherwise
   - error_count   : number of items where "status" >= 400 (integer)
   - output_length : exact character length of the agent output string (integer)

3. Score ONLY these two semantic dimensions (each 0-25):
   - task_completion : Did the agent actually complete the assigned task?
   - output_quality  : Is the output free of hallucinations and well-grounded?
                       (Use your hallucination analysis: fewer unsupported claims = higher score)

Respond ONLY with a single valid JSON object — no markdown, no text outside JSON:
{
  "judge_id": "judge-delta",
  "criteria": {
    "task_completion": <integer 0-25>,
    "output_quality":  <integer 0-25>
  },
  "trajectory_check": {
    "steps_count":   <integer>,
    "first_tool":    "<string>",
    "last_seq":      <integer>,
    "has_errors":    <true|false>,
    "error_count":   <integer>,
    "output_length": <integer>
  },
  "challenge_token": "<copied verbatim from trace>",
  "justification": "<2 concise sentences with the number of major claims checked and examples of unsupported claims, if any>"
}
"""


def evaluate(cid: str, groq_api_key: str) -> dict:
    trace = _fetch_trace(cid)
    if "error" in trace:
        return {
            "judge_id":           JUDGE_ID,
            "score":              0,
            "criteria":           {},
            "trajectory_check":   {},
            "challenge_token":    "",
            "justification":      f"Could not fetch trace from IPFS: {trace['error']}",
            "hallucination_rate": 1.0,
        }
    return _call_groq(_build_prompt(trace), groq_api_key)


def _fetch_trace(cid: str) -> dict:
    url = f"{IPFS_GATEWAY}/{cid}"
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error("IPFS fetch failed for CID %s: %s", cid, e)
        return {"error": str(e)}


def _slim_traj(trajectory: list) -> str:
    items = []
    for c in trajectory[:6]:
        item = {k: c[k] for k in ("seq", "tool", "tool_category", "status") if k in c}
        if c.get("request_query"):
            item["q"] = c["request_query"][:80]
        if c.get("error"):
            item["err"] = str(c["error"])[:80]
        items.append(item)
    return json.dumps(items, ensure_ascii=False)


def _build_prompt(trace: dict) -> str:
    trajectory  = trace.get("trajectory", [])
    traj_repr   = _slim_traj(trajectory)
    output_str  = str(trace.get("agent_output", "")).strip()
    error_count = sum(1 for c in trajectory if c.get("status", 200) >= 400)

    return f"""Evaluate hallucinations in this agent execution.

CHALLENGE TOKEN (copy this EXACTLY into your response — do not change it):
{trace.get('challenge_token', '')}

ORIGINAL TASK:
{trace.get('task_prompt', '(not provided)')[:300]}

AGENT OUTPUT (check this for hallucinations):
{output_str[:5000]}

EXECUTION METRICS:
- Search calls:  {trace.get('search_calls', 0)}
- steps_count:   {len(trajectory)} ← copy this integer into trajectory_check.steps_count
- last_seq:      {trajectory[-1].get('seq', -1) if trajectory else -1} ← copy into trajectory_check.last_seq
- error_count:   {error_count}   ← copy this integer into trajectory_check.error_count
- output_length: {len(output_str)} ← copy this integer into trajectory_check.output_length

TRAJECTORY (first 6 calls):
{traj_repr}

Remember: copy challenge_token verbatim, fill all six trajectory_check fields from the data above.
Return a complete JSON object with integer scores. Do not write comments such as //.
Respond ONLY with valid JSON as instructed."""


def _call_groq(user_prompt: str, groq_key: str) -> dict:
    if not groq_key:
        return {
            "judge_id":           JUDGE_ID,
            "score":              0,
            "criteria":           {},
            "trajectory_check":   {},
            "challenge_token":    "",
            "justification":      "Judge misconfigured: GROQ_API_KEY missing.",
            "hallucination_rate": 1.0,
        }
    try:
        with httpx.Client(timeout=55) as client:
            resp = client.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}"},
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens":  1500,
                    "response_format": {"type": "json_object"},
                },
            )
            if resp.status_code == 429:
                logger.warning("429 rate limit hit — returning error (no retry in container)")
                return {"judge_id": JUDGE_ID, "score": 0, "criteria": {},
                        "trajectory_check": {}, "challenge_token": "",
                        "justification": "Rate-limited (429). Try again in 1 minute.",
                        "hallucination_rate": 1.0}
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            return _parse(raw)
    except Exception as e:
        logger.error("Groq call failed: %s", e)
        return {
            "judge_id":           JUDGE_ID,
            "score":              0,
            "criteria":           {},
            "trajectory_check":   {},
            "challenge_token":    "",
            "justification":      f"Judge evaluation failed: {e}",
            "hallucination_rate": 1.0,
        }


def _parse(raw: str) -> dict:
    try:
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        if not raw.startswith("{"):
            m = re.search(r'\{[\s\S]*\}', raw)
            if m:
                raw = m.group(0)
        data            = json.loads(raw)
        criteria        = data.get("criteria") or {}
        task_completion = max(0, min(25, int(criteria.get("task_completion", 0))))
        output_quality  = max(0, min(25, int(criteria.get("output_quality",  0))))

        traj_check      = data.get("trajectory_check") or {}
        declared_steps  = int(traj_check.get("steps_count",    0))
        declared_errors = int(traj_check.get("error_count",    0))
        declared_outlen = int(traj_check.get("output_length",  0))

        if declared_steps == 0 and declared_outlen > 100:
            no_fabrication = 0
        elif declared_steps == 0:
            no_fabrication = 5
        else:
            ratio = min(1.0, declared_steps / max(1, declared_outlen / 500))
            no_fabrication = int(ratio * 25)
        tool_usage = (
            int((1.0 - declared_errors / declared_steps) * 25)
            if declared_steps > 0 else 0
        )
        no_fabrication = max(0, min(25, no_fabrication))
        tool_usage     = max(0, min(25, tool_usage))

        total_score = task_completion + output_quality + no_fabrication + tool_usage
        return {
            "judge_id":  JUDGE_ID,
            "score":     total_score,
            "criteria":  {
                "task_completion": task_completion,
                "output_quality":  output_quality,
                "no_fabrication":  no_fabrication,
                "tool_usage":      tool_usage,
            },
            "trajectory_check":   traj_check,
            "challenge_token":    data.get("challenge_token", ""),
            "justification":      data.get("justification", "No justification provided."),
            "hallucination_rate": float(data.get("hallucination_rate", 0.0)),
        }
    except Exception as e:
        logger.warning("Parse error: %s | raw: %s", e, raw[:200])
        return {
            "judge_id":           JUDGE_ID,
            "score":              0,
            "criteria":           {},
            "trajectory_check":   {},
            "challenge_token":    "",
            "justification":      f"Could not parse judge response: {raw[:200]}",
            "hallucination_rate": 1.0,
        }


# ── HTTP server ───────────────────────────────────────────────────────────────

import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

_GROQ_KEY = os.environ.get("GROQ_API_KEY", "")

app = FastAPI(title=JUDGE_NAME, version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class _RunRequest(BaseModel):
    task_id: str | None = None
    prompt:  str


class _RunResponse(BaseModel):
    task_id: str
    output:  dict
    status:  str = "completed"


@app.get("/health")
def _health():
    return {"status": "ok", "agent": JUDGE_ID}


@app.get("/info")
def _info():
    return {"agent_id": JUDGE_ID, "name": JUDGE_NAME, "version": "2.0.0", "status": "active"}


@app.post("/run", response_model=_RunResponse)
async def _run(req: _RunRequest):
    tid = req.task_id or f"task-{uuid.uuid4().hex[:8]}"
    try:
        import asyncio, functools
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, functools.partial(evaluate, req.prompt, groq_api_key=_GROQ_KEY)
        )
        return _RunResponse(task_id=tid, output=result)
    except Exception as e:
        raise HTTPException(500, str(e))
