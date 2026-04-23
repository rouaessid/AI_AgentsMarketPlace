"""
agent.py — Judge Gamma core logic.

Role: Behavioural trace analysis.
Evaluates execution behaviour: tool call logic, trajectory coherence,
consistency between process and claimed output, suspicious patterns.
Uses temperature 0.3 for a genuinely independent third opinion.

Decentralized flow:
  1. Platform stores execution trace on IPFS → CID
  2. Platform calls POST /run with just the CID in 'prompt'
  3. THIS judge fetches the trace from IPFS independently
  4. Evaluates execution process (not just output correctness)
  5. Returns structured verdict

The judge provider knows nothing about the platform.
Only needs: GROQ_API_KEY, IPFS_GATEWAY (optional).
"""
from __future__ import annotations

import json
import logging
import os

import httpx

JUDGE_ID     = os.getenv("JUDGE_ID",     "judge-gamma")
JUDGE_NAME   = os.getenv("JUDGE_NAME",   "Judge Gamma")
LLM_MODEL    = os.getenv("LLM_MODEL",    "llama-3.3-70b-versatile")
IPFS_GATEWAY = os.getenv("IPFS_GATEWAY", "https://ipfs.io/ipfs")

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an independent AI agent auditor specialised in execution behaviour analysis.
Evaluate whether an AI agent followed a rational, complete and trustworthy
process to produce its output.

Focus on:
- Tool call logic (are calls relevant and purposeful?)
- Trajectory coherence (does the process logically lead to the output?)
- Suspicious patterns (loops, empty calls, premature termination, fabricated results)
- Volume of work vs task complexity

Scoring rules:
- 0-59  → INVALID  (untrustworthy execution, fabricated output, or process mismatch)
- 60-100 → VALID   (execution is rational, consistent, and trustworthy)

Respond ONLY with a single valid JSON object:
{
  "score": <integer 0-100>,
  "verdict": "<VALID or INVALID>",
  "justification": "<2-3 sentences referencing specific trace observations>"
}
"""


def evaluate(cid: str, groq_api_key: str) -> dict:
    """
    Fetch trace from IPFS using CID, then evaluate execution behaviour.
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
    detailed_trace = _build_detailed_trace(trace.get("trajectory", []))
    traj_count     = len(trace.get("trajectory", []))
    return f"""Evaluate this agent execution independently and completely.

ORIGINAL TASK:
{trace.get('task_prompt', '(not captured)')}

FINAL OUTPUT PRODUCED:
{str(trace.get('agent_output', '(no output)'))[:2000]}

FULL EXECUTION TRACE:
{detailed_trace}

EXECUTION STATISTICS:
- Total API calls: {traj_count}
- LLM calls: {trace.get('llm_calls', 'N/A')} | Search calls: {trace.get('search_calls', 'N/A')}
- Errors: {trace.get('errors_count', 0)} | Duration: {trace.get('duration_sec', 'N/A')}s
- Tokens consumed: {trace.get('total_tokens', 'N/A')}

Evaluate:
1. Is the execution trajectory logical for this type of task?
2. Do tool calls support the final output, or does the output appear fabricated?
3. Are there errors, loops, or missing steps that undermine reliability?
4. Does the volume of work (tokens, calls, time) match the complexity of the task?

Respond ONLY with valid JSON as instructed."""


def _build_detailed_trace(trajectory: list) -> str:
    if not trajectory:
        return "(empty — agent made no external calls)"
    lines = []
    for c in trajectory[:10]:
        line = _format_call(c)
        lines.append(line)
    if len(trajectory) > 10:
        lines.append(f"  ... ({len(trajectory) - 10} more calls not shown)")
    return "\n".join(lines)


def _format_call(c: dict) -> str:
    tool = c.get("tool", "unknown")
    cat  = c.get("tool_category", "?")
    st   = c.get("status", 0)
    lat  = c.get("latency_ms", 0)
    tok  = c.get("tokens_total", 0)
    err  = c.get("error")
    q    = c.get("request_query", "")
    rc   = (c.get("response_content") or "")[:150]
    rr   = c.get("response_results")

    line = f"  Step {c.get('seq', 0)}: {tool} ({cat}) | HTTP {st} | {lat:.0f}ms"
    if tok:
        line += f" | {tok} tokens"
    if q:
        line += f"\n    → query: \"{q[:100]}\""
    if rc:
        line += f"\n    → response: \"{rc}...\""
    if rr is not None:
        line += f"\n    → {rr} results returned"
    if err:
        line += f"\n    ⚠ error: {err}"
    return line


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
                    "temperature": 0.3,   # higher → genuinely independent third opinion
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
