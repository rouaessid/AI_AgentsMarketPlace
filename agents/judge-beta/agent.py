from __future__ import annotations

import json
import logging
import os
import re

import httpx

JUDGE_ID     = os.getenv("JUDGE_ID",     "judge-beta")
JUDGE_NAME   = os.getenv("JUDGE_NAME",   "Judge Beta")
LLM_MODEL    = os.getenv("LLM_MODEL",    "gemini-2.5-flash")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
IPFS_GATEWAY = os.getenv("IPFS_GATEWAY", "https://ipfs.io/ipfs")

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a strict and independent AI quality auditor.
Evaluate whether an AI agent correctly completed a task by analysing
its output, tool usage, and execution behaviour.
You do NOT use any external search engine — rely solely on your reasoning.

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
   - task_completion : Did the agent correctly answer the task?
   - output_quality  : Is the output useful, accurate, and free of hallucinations?

Respond ONLY with a single valid JSON object — no markdown, no text outside JSON:
{
  "judge_id": "<your judge id>",
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
  "justification": "<2-3 sentences with specific observations>"
}
"""


def evaluate(cid: str, groq_api_key: str) -> dict:
    trace = _fetch_trace(cid)
    if "error" in trace:
        return {"judge_id": JUDGE_ID, "score": 0, "criteria": {},
                "trajectory_check": {}, "challenge_token": "",
                "justification": f"Could not fetch trace: {trace['error']}"}
    return _call_groq(_build_prompt(trace), groq_api_key)


def _fetch_trace(cid: str) -> dict:
    url = f"{IPFS_GATEWAY}/{cid}"
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error("Fetch failed for %s: %s", cid, e)
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
    trajectory   = trace.get("trajectory", [])
    traj_repr    = _slim_traj(trajectory)
    output_str   = str(trace.get("agent_output", "")).strip()
    error_count  = sum(1 for c in trajectory if c.get("status", 200) >= 400)
    return f"""Independently evaluate this AI agent execution.

CHALLENGE TOKEN (copy this EXACTLY into your response — do not change it):
{trace.get('challenge_token', '')}

TASK GIVEN TO THE AGENT:
{trace.get('task_prompt', '(not available)')[:300]}

AGENT FINAL OUTPUT:
{output_str[:5000]}

EXECUTION METRICS:
- Tools called:   {trace.get('tools_used', 'N/A')}
- LLM calls:      {trace.get('llm_calls', 'N/A')} | Search calls: {trace.get('search_calls', 'N/A')}
- Execution time: {trace.get('duration_sec', 'N/A')}s | Tokens: {trace.get('total_tokens', 'N/A')}
- steps_count:    {len(trajectory)} ← copy this integer into trajectory_check.steps_count
- last_seq:       {trajectory[-1].get('seq', -1) if trajectory else -1} ← copy into trajectory_check.last_seq
- error_count:    {error_count}   ← copy this integer into trajectory_check.error_count
- output_length:  {len(output_str)} ← copy this integer into trajectory_check.output_length

TRAJECTORY (first 6 calls):
{traj_repr}

Evaluate on:
1. Did the agent actually answer the task?
2. Is the output coherent and free of hallucinations?
3. Were the tools used appropriately?
4. Are there signs of failure (empty output, errors, nonsensical response)?

Remember: copy challenge_token verbatim, fill all six trajectory_check fields from the data above.
Respond ONLY with valid JSON as instructed."""


def _summarise_trajectory(trajectory: list) -> str:
    if not trajectory:
        return "(no calls captured)"
    lines = []
    for c in trajectory[:8]:
        tool = c.get("tool", "?")
        cat  = c.get("tool_category", "?")
        st   = c.get("status", "?")
        q    = c.get("request_query") or ""
        rc   = (c.get("response_content") or "")[:120]
        line = f"  [{c.get('seq', 0)}] {tool} ({cat}) → HTTP {st}"
        if q:
            line += f" | query: {q}"
        if rc:
            line += f" | response: {rc}..."
        lines.append(line)
    return "\n".join(lines)


def _call_groq(user_prompt: str, groq_key: str) -> dict:
    import time
    if not groq_key:
        return {"judge_id": JUDGE_ID, "score": 0, "criteria": {},
                "trajectory_check": {}, "challenge_token": "",
                "justification": "Judge misconfigured: GROQ_API_KEY missing."}

    _neutral = {"judge_id": JUDGE_ID, "score": 50, "criteria": {},
                "trajectory_check": {}, "challenge_token": "",
                "justification": "Rate-limited after retries — abstaining with neutral score 50."}

    for attempt in range(1, 4):
        try:
            with httpx.Client(timeout=55) as client:
                resp = client.post(
                    f"{LLM_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "HTTP-Referer":  "http://localhost:8000",
                        "X-Title":       "AgentMarket",
                    },
                    json={
                        "model": LLM_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user",   "content": user_prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens":  1500,
                    },
                )
                if resp.status_code == 429:
                    wait = 15 * attempt
                    logger.warning("429 rate limit (attempt %d/3) — retrying in %ds", attempt, wait)
                    if attempt < 3:
                        time.sleep(wait)
                        continue
                    return _neutral
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                return _parse(raw)
        except Exception as e:
            logger.error("Groq call failed (attempt %d): %s", attempt, e)
            if attempt == 3:
                return {"judge_id": JUDGE_ID, "score": 0, "criteria": {},
                        "trajectory_check": {}, "challenge_token": "",
                        "justification": f"Judge evaluation failed: {e}"}
            time.sleep(10 * attempt)
    return _neutral


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
            "trajectory_check": traj_check,
            "challenge_token":  data.get("challenge_token", ""),
            "justification":    data.get("justification", "No justification provided."),
        }
    except Exception as e:
        logger.warning("Parse error: %s | raw: %s", e, raw[:200])
        return {"judge_id": JUDGE_ID, "score": 0, "criteria": {},
                "trajectory_check": {}, "challenge_token": "",
                "justification": f"Could not parse judge response: {raw[:200]}"}


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
