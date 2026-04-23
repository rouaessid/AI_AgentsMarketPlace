"""
agent.py — ResearchBot core logic.

This is the seller's business logic. Nothing platform-specific here.
The platform proxy captures all outgoing HTTP calls automatically.

Flow:
  1. Plan 3 targeted search queries with LLM
  2. Execute Tavily searches
  3. Synthesize findings → structured JSON report
"""
from __future__ import annotations
import os
import json
import uuid

from groq import Groq
from tavily import TavilyClient

LLM_MODEL   = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
AGENT_ID    = "researcher-01"
MAX_RESULTS = int(os.getenv("TAVILY_MAX_RESULTS", "5"))

PLANNER_PROMPT = """\
You are a research planner. Given a user query, generate 3 focused search queries
that together cover the topic from different angles (overview, recent news, data/stats).
Respond ONLY with a JSON array of 3 strings.
Example: ["query one", "query two", "query three"]
"""

SYNTHESIZER_PROMPT = """\
You are a research analyst. Given a user question and raw search results,
produce a structured research report in JSON with this exact schema:
{
  "summary": "<2-3 sentence executive summary>",
  "key_findings": [{"point": "<finding>", "source": "<url or multiple sources>"}],
  "trends": ["<trend 1>", "<trend 2>"],
  "data_points": ["<stat or figure>"],
  "conclusion": "<1-2 sentence conclusion>",
  "sources": ["<url1>", "<url2>"]
}
Respond ONLY with valid JSON. No markdown fences.
"""


class ResearchAgent:
    def __init__(self, groq_api_key: str, tavily_api_key: str):
        self.llm    = Groq(api_key=groq_api_key)
        self.tavily = TavilyClient(api_key=tavily_api_key)

    def run(self, query: str, task_id: str | None = None) -> dict:
        """
        Execute research and return structured result.
        All HTTP calls (Groq API, Tavily API) are captured by the platform proxy.
        """
        task_id = task_id or f"task-{uuid.uuid4().hex[:8]}"

        search_queries = self._plan_queries(query)
        all_results: list[dict] = []
        for sq in search_queries:
            all_results.extend(self._search(sq))

        report = self._synthesize(query, all_results)

        return {
            "task_id":  task_id,
            "agent_id": AGENT_ID,
            "query":    query,
            "output":   report,
            "status":   "completed",
        }

    def _plan_queries(self, query: str) -> list[str]:
        resp = self.llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user",   "content": query},
            ],
            temperature=0.3,
            max_tokens=256,
        )
        raw = resp.choices[0].message.content.strip()
        try:
            queries = json.loads(raw)
            if isinstance(queries, list):
                return [str(q) for q in queries[:3]]
        except json.JSONDecodeError:
            pass
        return [query]

    def _search(self, query: str) -> list[dict]:
        resp = self.tavily.search(
            query=query,
            max_results=MAX_RESULTS,
            search_depth="advanced",
            include_raw_content=False,
        )
        return [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "content": r.get("content", "")[:800],
                "score":   r.get("score", 0),
            }
            for r in resp.get("results", [])
        ]

    def _synthesize(self, query: str, results: list[dict]) -> dict:
        context = "\n\n---\n\n".join(
            f"Source: {r['url']}\nTitle: {r['title']}\n{r['content']}"
            for r in results[:12]
        )
        resp = self.llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SYNTHESIZER_PROMPT},
                {"role": "user",   "content": f"Question: {query}\n\nSearch Results:\n{context}"},
            ],
            temperature=0.2,
            max_tokens=2048,
        )
        raw = resp.choices[0].message.content.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {
                "summary":      raw,
                "key_findings": [],
                "trends":       [],
                "data_points":  [],
                "conclusion":   "",
                "sources":      [r["url"] for r in results[:5]],
            }
