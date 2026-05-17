"""
agent.py — AnalystBot core logic.

Takes raw text, research output, or JSON data and produces a structured
analysis with key insights, risks, opportunities, and a clear verdict.
No web search — pure LLM analysis on provided content.
"""
from __future__ import annotations

import json
import os
import uuid

from groq import Groq

LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
AGENT_ID  = "analyst-01"

SYSTEM_PROMPT = """\
You are a structured analysis expert. Given any text, research output, or JSON data,
produce a concise structured analysis.

Respond ONLY with a valid JSON object — no markdown fences, no explanation outside JSON:
{
  "summary": "<2-3 sentence executive summary>",
  "key_insights": ["<insight 1>", "<insight 2>", "<insight 3>"],
  "risks": ["<risk 1>", "<risk 2>"],
  "opportunities": ["<opportunity 1>", "<opportunity 2>"],
  "verdict": "<POSITIVE|NEUTRAL|NEGATIVE>",
  "confidence": <integer 0-100>
}

Rules:
- verdict: POSITIVE = strong findings, clear value; NEUTRAL = mixed/uncertain; NEGATIVE = risks dominate
- confidence: 0 = no usable data, 100 = very clear conclusion
- key_insights: the 3 most important findings from the content
- risks: real, specific risks — not generic platitudes
- opportunities: concrete, actionable items
"""


class AnalystAgent:
    def __init__(self, groq_api_key: str):
        self.llm = Groq(api_key=groq_api_key)

    def run(self, prompt: str, task_id: str | None = None) -> dict:
        task_id = task_id or f"task-{uuid.uuid4().hex[:8]}"
        analysis = self._analyze(prompt)
        return {
            "task_id":  task_id,
            "agent_id": AGENT_ID,
            "output":   analysis,
            "status":   "completed",
        }

    def _analyze(self, content: str) -> dict:
        resp = self.llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": content[:8000]},
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        raw = resp.choices[0].message.content.strip()
        try:
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            return {
                "summary":       raw[:500],
                "key_insights":  [],
                "risks":         [],
                "opportunities": [],
                "verdict":       "NEUTRAL",
                "confidence":    0,
            }
