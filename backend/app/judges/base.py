"""
judges/base.py
--------------
Shared interface and trace loader for all judge agents.

Each judge:
  - Receives only the IPFS proxy trace (no backend access)
  - Evaluates the FULL execution independently
  - Returns JudgeResult(score, justification, verdict)

Designed so each judge folder can later become a standalone
registered agent with its own Docker image, stake, and reputation.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class JudgeResult:
    judge_id:         str
    judge_name:       str
    score:            int          # 0-100, recalculé par la plateforme
    justification:    str
    verdict:          str          # "VALID" | "INVALID"
    criteria:         dict = None  # {"task_completion": N, "output_quality": N}
    trajectory_check: dict = None  # {"steps_count": N, "first_tool": S, ...}

    def __post_init__(self):
        if self.criteria is None:
            self.criteria = {}
        if self.trajectory_check is None:
            self.trajectory_check = {}


@dataclass
class TraceData:
    """Normalised view of the proxy trace given to each judge."""
    run_id:          str
    agent_id:        str
    task_prompt:     str
    agent_output:    str        # raw string output from the agent
    tools_used:      list[str]
    llm_calls:       int
    search_calls:    int
    errors_count:    int
    duration_sec:    float
    total_tokens:    int
    trajectory:      list[dict[str, Any]]   # full call list


async def load_trace(proxy_cid: str) -> TraceData:
    """Fetch proxy trace from Pinata. Raises RuntimeError if unreachable."""
    raw = await _fetch_raw(proxy_cid)
    return _parse(raw)


async def _fetch_raw(cid: str) -> dict:
    for url in [
        f"https://gateway.pinata.cloud/ipfs/{cid}",
        f"https://ipfs.io/ipfs/{cid}",
    ]:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.debug("Gateway %s failed: %s", url, e)
    raise RuntimeError(f"Trace not found on IPFS for CID={cid}")


def _parse(raw: dict) -> TraceData:
    trajectory = raw.get("trajectory", [])

    # Extract task_prompt and agent_output from trajectory when possible
    task_prompt  = raw.get("task_prompt", "")
    agent_output = raw.get("agent_output", "")

    if not task_prompt or not agent_output:
        for call in trajectory:
            msgs = call.get("request_messages") or []
            for m in msgs:
                if isinstance(m, dict) and m.get("role") == "user" and not task_prompt:
                    task_prompt = m.get("content", "")
            if call.get("response_content") and not agent_output:
                agent_output = call["response_content"]

    return TraceData(
        run_id=raw.get("run_id", ""),
        agent_id=raw.get("agent_id", ""),
        task_prompt=task_prompt,
        agent_output=agent_output,
        tools_used=raw.get("tools_used", []),
        llm_calls=raw.get("llm_calls", 0),
        search_calls=raw.get("search_calls", 0),
        errors_count=raw.get("errors_count", 0),
        duration_sec=raw.get("duration_sec", 0.0),
        total_tokens=raw.get("total_tokens", 0),
        trajectory=trajectory,
    )
