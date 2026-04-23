"""
agent.py — Judge Alpha core logic.

This is ALL the judge provider writes.
The judge provider knows nothing about the platform.

Decentralized flow:
  1. Platform stores execution trace on IPFS → CID
  2. Platform calls POST /run with just the CID in 'prompt'
  3. THIS judge fetches the trace from IPFS independently
  4. Evaluates with Groq + optional Tavily fact-checking
  5. Returns structured verdict

The judge provider only needs:
  - GROQ_API_KEY
  - TAVILY_API_KEY  (optional — enables fact-checking)
  - IPFS_GATEWAY    (optional — defaults to public gateway)

No platform SDK. No backend access. No internal imports.
"""
from __future__ import annotations

import json
import logging
import os

import httpx

JUDGE_ID     = os.getenv("JUDGE_ID",     "judge-alpha")
JUDGE_NAME   = os.getenv("JUDGE_NAME",   "Judge Alpha")
LLM_MODEL    = os.getenv("LLM_MODEL",    "llama-3.3-70b-versatile")
IPFS_GATEWAY = os.getenv("IPFS_GATEWAY", "https://ipfs.io/ipfs")

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an independent AI judge. You receive the execution record of an AI agent
and must evaluate whether it correctly completed the assigned task.

Scoring rules:
- 0-59  → INVALID  (task failed, wrong output, hallucinations, no work done)
- 60-100 → VALID   (task completed correctly, output is useful and accurate)

You MUST respond ONLY with a single valid JSON object — no markdown, no explanation outside JSON:
{
  "score": <integer 0-100>,
  "verdict": "<VALID or INVALID>",
  "justification": "<2-3 sentences with specific observations>"
}
"""


def evaluate(cid: str, groq_api_key: str, tavily_api_key: str | None = None) -> dict:
    """
    Full evaluation flow:
      1. Fetch trace from IPFS using the CID
      2. Optional Tavily fact-checking
      3. Groq scoring
    """
    trace = _fetch_trace(cid)
    if "error" in trace:
        return {
            "judge_id":      JUDGE_ID,
            "score":         0,
            "verdict":       "INVALID",
            "justification": f"Could not fetch trace from IPFS: {trace['error']}",
        }

    evidence = _gather_evidence_sync(trace, tavily_api_key) if tavily_api_key else ""
    return _call_groq(_build_prompt(trace, evidence), groq_api_key)


# ── IPFS fetch ────────────────────────────────────────────────────────────────

def _fetch_trace(cid: str) -> dict:
    """Fetch the execution trace JSON from IPFS."""
    url = f"{IPFS_GATEWAY}/{cid}"
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error("IPFS fetch failed for CID %s: %s", cid, e)
        return {"error": str(e)}


# ── Evidence gathering (Tavily re-search) ─────────────────────────────────────

def _gather_evidence_sync(trace: dict, tavily_key: str) -> str:
    """Re-run up to 2 search queries from the trajectory for independent verification."""
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


# ── LLM scoring ───────────────────────────────────────────────────────────────

def _build_prompt(trace: dict, evidence: str) -> str:
    return f"""Evaluate this AI agent execution:

TASK GIVEN TO THE AGENT:
{trace.get('task_prompt', '(not provided)')}

AGENT OUTPUT:
{str(trace.get('agent_output', '(no output)'))[:2000]}

EXECUTION METRICS:
- Tools used:   {trace.get('tools_used', 'N/A')}
- LLM calls:    {trace.get('llm_calls', 'N/A')}
- Search calls: {trace.get('search_calls', 'N/A')}
- Errors:       {trace.get('errors_count', 0)}
- Duration:     {trace.get('duration_sec', 'N/A')}s
- Total tokens: {trace.get('total_tokens', 'N/A')}
{evidence}

Respond ONLY with valid JSON as instructed."""


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
