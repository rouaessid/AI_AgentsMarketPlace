"""
agent.py — Judge Beta core logic.

Role: Pure LLM reasoning — no external tools.
Critically analyses the agent output for correctness, completeness,
coherence and absence of hallucinations.

Decentralized flow:
  1. Platform stores execution trace on IPFS → CID
  2. Platform calls POST /run with just the CID in 'prompt'
  3. THIS judge fetches the trace from IPFS independently
  4. Evaluates with pure Groq reasoning (no search)
  5. Returns structured verdict

The judge provider knows nothing about the platform.
Only needs: GROQ_API_KEY, IPFS_GATEWAY (optional).
"""
from __future__ import annotations

import json
import logging
import os

import httpx

JUDGE_ID     = os.getenv("JUDGE_ID",     "judge-beta")
JUDGE_NAME   = os.getenv("JUDGE_NAME",   "Judge Beta")
LLM_MODEL    = os.getenv("LLM_MODEL",    "llama-3.3-70b-versatile")
IPFS_GATEWAY = os.getenv("IPFS_GATEWAY", "https://ipfs.io/ipfs")

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a strict and independent AI quality auditor.
Evaluate whether an AI agent correctly completed a task by analysing
its output, tool usage, and execution behaviour.
You do NOT use any search engine — rely solely on your reasoning.

Scoring rules:
- 0-59  → INVALID  (task failed, wrong output, hallucinations, no work done)
- 60-100 → VALID   (task completed correctly, output is useful and accurate)

Respond ONLY with a single valid JSON object:
{
  "score": <integer 0-100>,
  "verdict": "<VALID or INVALID>",
  "justification": "<2-3 sentences with specific observations>"
}
"""


def evaluate(cid: str, groq_api_key: str) -> dict:
    """
    Fetch trace from IPFS using CID, then evaluate with pure LLM reasoning.
    """
    trace = _fetch_trace(cid)
    if "error" in trace:
        return {
            "judge_id":      JUDGE_ID,
            "score":         0,
            "verdict":       "INVALID",
            "justification": f"Could not fetch trace from IPFS: {trace['error']}",
        }
    return _call_groq(_build_prompt(trace), groq_api_key)


# ── IPFS fetch ────────────────────────────────────────────────────────────────

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


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(trace: dict) -> str:
    trajectory_summary = _summarise_trajectory(trace.get("trajectory", []))
    return f"""Independently evaluate this AI agent execution.

TASK GIVEN TO THE AGENT:
{trace.get('task_prompt', '(not available)')}

AGENT FINAL OUTPUT:
{str(trace.get('agent_output', '(no output captured)'))[:2000]}

TOOL USAGE SUMMARY:
- Tools called:   {trace.get('tools_used', 'N/A')}
- LLM calls:      {trace.get('llm_calls', 'N/A')} | Search calls: {trace.get('search_calls', 'N/A')}
- Errors:         {trace.get('errors_count', 0)}
- Execution time: {trace.get('duration_sec', 'N/A')}s | Tokens: {trace.get('total_tokens', 'N/A')}

CALL TRAJECTORY (chronological):
{trajectory_summary}

Evaluate on:
1. Did the agent actually answer the task?
2. Is the output coherent and free of hallucinations?
3. Were the tools used appropriately?
4. Are there signs of failure (empty output, errors, nonsensical response)?

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


# ── LLM call ──────────────────────────────────────────────────────────────────

def _call_groq(user_prompt: str, groq_key: str) -> dict:
    if not groq_key:
        return {
            "judge_id":      JUDGE_ID,
            "score":         0,
            "verdict":       "INVALID",
            "justification": "Judge misconfigured: GROQ_API_KEY missing.",
        }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}"},
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens":  400,
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            return _parse(raw)
    except Exception as e:
        logger.error("Groq call failed: %s", e)
        return {
            "judge_id":      JUDGE_ID,
            "score":         0,
            "verdict":       "INVALID",
            "justification": f"Judge evaluation failed: {e}",
        }


def _parse(raw: str) -> dict:
    try:
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data    = json.loads(raw.strip())
        score   = max(0, min(100, int(data.get("score", 0))))
        verdict = "VALID" if score >= 60 else "INVALID"
        return {
            "judge_id":      JUDGE_ID,
            "score":         score,
            "verdict":       verdict,
            "justification": data.get("justification", "No justification provided."),
        }
    except Exception as e:
        logger.warning("Parse error: %s | raw: %s", e, raw[:200])
        return {
            "judge_id":      JUDGE_ID,
            "score":         0,
            "verdict":       "INVALID",
            "justification": f"Could not parse judge response: {raw[:200]}",
        }
