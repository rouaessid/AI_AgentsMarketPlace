"""
agent.py — Judge Epsilon core logic.

Rubric-based evaluation specialist.
Analyses agent output on multiple quality dimensions, then maps
to the platform's standard semantic scoring format (0-25 each).
  - task_completion (0-25): relevance + completeness + prompt adherence
  - output_quality  (0-25): accuracy + format
"""
from __future__ import annotations

import json
import logging
import os
import re

import httpx

JUDGE_ID     = os.getenv("JUDGE_ID",     "judge-epsilon")
JUDGE_NAME   = os.getenv("JUDGE_NAME",   "Judge Epsilon")
LLM_MODEL    = os.getenv("LLM_MODEL",    "gemini-2.5-flash")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
IPFS_GATEWAY = os.getenv("IPFS_GATEWAY", "https://ipfs.io/ipfs")

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a structured evaluation expert using a rubric-based scoring approach.
Internally analyse the agent output on 5 dimensions, then map your analysis
to the two required output dimensions.

Internal rubric (use for reasoning, do not output):
1. Relevance (0-25)        — Does the output directly address the original task?
2. Completeness (0-25)     — Are all expected elements/sections present?
3. Accuracy (0-25)         — Are facts and claims internally consistent and plausible?
4. Format (0-25)           — Is the output well-structured and readable?
5. Prompt Adherence (0-25) — Does the output follow the requested format/constraints?

Mapping to output dimensions:
- task_completion = floor((relevance + completeness + prompt_adherence) / 3)   [0-25]
- output_quality  = floor((accuracy + format) / 2)                             [0-25]

SCORING RUBRIC — be strict on each internal dimension (0-25):
  0-5   : Completely missing or wrong.
  6-10  : Major deficiencies — significant gaps, errors, or vague content.
  11-15 : Acceptable — meets basic expectations but lacks depth or specifics.
  16-20 : Good — clearly addresses criteria with minor issues.
  21-25 : Exceptional only — specific, verifiable, zero filler, exceeds expectations.
  DEFAULT BIAS: Most outputs deserve 10-16 per dimension. Only award 20+ for outputs
  with concrete, non-trivial, verifiable content. Generic correct answers score 11-14.

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

3. Output ONLY these two scored dimensions (each 0-25):
   - task_completion : mapped from your internal relevance/completeness/adherence
   - output_quality  : mapped from your internal accuracy/format

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
  "justification": "<2-3 sentences explaining the scores with specific observations>"
}
"""


def evaluate(cid: str, groq_api_key: str) -> dict:
    trace = _fetch_trace(cid)
    if "error" in trace:
        return {
            "judge_id":         JUDGE_ID,
            "score":            0,
            "criteria":         {},
            "trajectory_check": {},
            "challenge_token":  "",
            "justification":    f"Could not fetch trace from IPFS: {trace['error']}",
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
    return f"""Evaluate this agent execution using the rubric-based approach.

CHALLENGE TOKEN (copy this EXACTLY into your response — do not change it):
{trace.get('challenge_token', '')}

ORIGINAL TASK (what the agent was asked to do):
{trace.get('task_prompt', '(not provided)')[:300]}

AGENT OUTPUT (what was produced):
{output_str[:5000]}

EXECUTION METRICS:
- Tools used:    {trace.get('tools_used', 'N/A')}
- LLM calls:     {trace.get('llm_calls', 'N/A')}
- Search calls:  {trace.get('search_calls', 'N/A')}
- Duration:      {trace.get('duration_sec', 'N/A')}s
- steps_count:   {len(trajectory)} ← copy this integer into trajectory_check.steps_count
- last_seq:      {trajectory[-1].get('seq', -1) if trajectory else -1} ← copy into trajectory_check.last_seq
- error_count:   {error_count}   ← copy this integer into trajectory_check.error_count
- output_length: {len(output_str)} ← copy this integer into trajectory_check.output_length

TRAJECTORY (first 6 calls):
{traj_repr}

Apply your 5-dimension rubric internally, then map to task_completion and output_quality.
Remember: copy challenge_token verbatim, fill all six trajectory_check fields from the data above.
Respond ONLY with valid JSON as instructed."""


def _call_groq(user_prompt: str, groq_key: str) -> dict:
    if not groq_key:
        return {
            "judge_id":         JUDGE_ID,
            "score":            0,
            "criteria":         {},
            "trajectory_check": {},
            "challenge_token":  "",
            "justification":    "Judge misconfigured: GROQ_API_KEY missing.",
        }
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
                logger.warning("429 rate limit hit — returning error (no retry in container)")
                return {"judge_id": JUDGE_ID, "score": 0, "criteria": {},
                        "trajectory_check": {}, "challenge_token": "",
                        "justification": "Rate-limited (429). Try again in 1 minute."}
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            return _parse(raw)
    except Exception as e:
        logger.error("Groq call failed: %s", e)
        return {
            "judge_id":         JUDGE_ID,
            "score":            0,
            "criteria":         {},
            "trajectory_check": {},
            "challenge_token":  "",
            "justification":    f"Judge evaluation failed: {e}",
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
            "trajectory_check": traj_check,
            "challenge_token":  data.get("challenge_token", ""),
            "justification":    data.get("justification", "No justification provided."),
        }
    except Exception as e:
        logger.warning("Parse error: %s | raw: %s", e, raw[:200])
        return {
            "judge_id":         JUDGE_ID,
            "score":            0,
            "criteria":         {},
            "trajectory_check": {},
            "challenge_token":  "",
            "justification":    f"Could not parse judge response: {raw[:200]}",
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
