from __future__ import annotations

import json
import logging
import os
import re

import httpx

JUDGE_ID     = os.getenv("JUDGE_ID",     "judge-alpha")
JUDGE_NAME   = os.getenv("JUDGE_NAME",   "Judge Alpha")
LLM_MODEL    = os.getenv("LLM_MODEL",    "llama-3.1-8b-instant")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
IPFS_GATEWAY = os.getenv("IPFS_GATEWAY", "https://ipfs.io/ipfs")

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an independent AI judge. You evaluate whether an AI agent correctly
completed the assigned task.

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

SCORING RUBRIC — be strict. Most outputs deserve 10-17, not 20+:
  task_completion:
    0-5   : Not completed, off-topic, or fundamentally wrong.
    6-10  : Partially addressed with major errors or missing key elements.
    11-15 : Addressed but with notable gaps, vague statements, or weak reasoning.
    16-20 : Correctly completed with minor omissions or imprecisions.
    21-25 : Exceptional only — specific, complete, accurate, zero generic filler.
  output_quality:
    0-5   : Unusable — hallucinations, incoherent, or purely generic filler.
    6-10  : Low quality — vague, generic, or likely hallucinated facts.
    11-15 : Acceptable — some specifics but notable filler or minor inaccuracies.
    16-20 : Good — mostly accurate and structured with clear reasoning.
    21-25 : Excellent only — concrete verifiable facts, no filler, well-structured.
  DEFAULT BIAS: when in doubt, score lower. A correct but generic answer is 11-14.
  Reserve 20+ only when the output contains specific, verifiable, non-trivial information.

You MUST respond ONLY with a single valid JSON object — no markdown, no text
outside JSON:
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


def evaluate(cid: str, groq_api_key: str, tavily_api_key: str | None = None) -> dict:
    trace = _fetch_trace(cid)
    if "error" in trace:
        return {
            "judge_id":        JUDGE_ID,
            "score":           0,
            "criteria":        {},
            "trajectory_check": {},
            "challenge_token": "",
            "justification":   f"Could not fetch trace: {trace['error']}",
        }
    evidence = _gather_evidence_sync(trace, tavily_api_key) if tavily_api_key else ""
    return _call_groq(_build_prompt(trace, evidence), groq_api_key)


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


def _gather_evidence_sync(trace: dict, tavily_key: str) -> str:
    queries = _extract_queries(trace)
    if not queries:
        return ""
    lines = ["\nINDEPENDENT VERIFICATION (Tavily re-search):"]
    with httpx.Client(timeout=15) as client:
        for q in queries[:2]:
            lines.extend(_tavily_search(client, q, tavily_key))
    return "\n".join(lines) if len(lines) > 1 else ""


def _extract_queries(trace: dict) -> list[str]:
    queries: list[str] = []
    for call in trace.get("trajectory", []):
        if call.get("tool_category") == "search" and call.get("request_query"):
            queries.append(call["request_query"])
        if len(queries) >= 2:
            break
    if not queries and trace.get("task_prompt"):
        queries = [trace["task_prompt"][:200]]
    return queries


def _tavily_search(client: httpx.Client, query: str, tavily_key: str) -> list[str]:
    try:
        resp = client.post(
            "https://api.tavily.com/search",
            json={"api_key": tavily_key, "query": query, "max_results": 3},
        )
        if resp.status_code == 200:
            return [
                f"  [{r.get('title', '')}] {r.get('content', '')[:300]}"
                for r in resp.json().get("results", [])[:3]
            ]
    except Exception as e:
        logger.warning("Tavily search failed for '%s': %s", query, e)
    return []


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


def _build_prompt(trace: dict, evidence: str = "") -> str:
    trajectory    = trace.get("trajectory", [])
    traj_repr     = _slim_traj(trajectory)
    output_str    = str(trace.get("agent_output", "")).strip()
    error_count   = sum(1 for c in trajectory if c.get("status", 200) >= 400)
    return f"""Evaluate this AI agent execution.

CHALLENGE TOKEN (copy this EXACTLY into your response — do not change it):
{trace.get('challenge_token', '')}

TASK GIVEN TO THE AGENT:
{trace.get('task_prompt', '(not provided)')[:300]}

AGENT OUTPUT:
{output_str[:800]}

EXECUTION METRICS:
- Tools used:    {trace.get('tools_used', 'N/A')}
- LLM calls:     {trace.get('llm_calls', 'N/A')}
- Search calls:  {trace.get('search_calls', 'N/A')}
- Duration:      {trace.get('duration_sec', 'N/A')}s
- Total tokens:  {trace.get('total_tokens', 'N/A')}
- steps_count:   {len(trajectory)} ← copy this integer into trajectory_check.steps_count
- last_seq:      {trajectory[-1].get('seq', -1) if trajectory else -1} ← copy into trajectory_check.last_seq
- error_count:   {error_count}   ← copy this integer into trajectory_check.error_count
- output_length: {len(output_str)} ← copy this integer into trajectory_check.output_length

TRAJECTORY (first 6 calls — use this to fill trajectory_check):
{traj_repr}

Remember: copy challenge_token verbatim, fill all six trajectory_check fields from the data above.
Respond ONLY with valid JSON as instructed."""


def _call_groq(user_prompt: str, groq_key: str) -> dict:
    if not groq_key:
        return {"judge_id": JUDGE_ID, "score": 0, "criteria": {},
                "trajectory_check": {}, "challenge_token": "",
                "justification": "Judge misconfigured: GROQ_API_KEY missing."}
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
        return {"judge_id": JUDGE_ID, "score": 0, "criteria": {},
                "trajectory_check": {}, "challenge_token": "",
                "justification": f"Judge evaluation failed: {e}"}


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

        traj_check     = data.get("trajectory_check") or {}
        declared_steps  = int(traj_check.get("steps_count",    0))
        declared_errors = int(traj_check.get("error_count",    0))
        declared_outlen = int(traj_check.get("output_length",  0))

        # Structural scores — deterministic formula in Python, LLM only declares integer facts
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

_GROQ_KEY   = os.environ.get("GROQ_API_KEY",   "")
_TAVILY_KEY = os.environ.get("TAVILY_API_KEY",  "")

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
            None, functools.partial(evaluate, req.prompt,
                                    groq_api_key=_GROQ_KEY,
                                    tavily_api_key=_TAVILY_KEY or None)
        )
        return _RunResponse(task_id=tid, output=result)
    except Exception as e:
        raise HTTPException(500, str(e))
