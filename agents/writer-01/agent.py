"""
agent.py — WriterBot core logic.

2-step process:
  Pre-process (Python) — extraire le JSON du researcher du contexte pipeline
  Step 1 (LLM)        — extraire les faits clés en texte brut
  Step 2 (LLM)        — rédiger le rapport final en prose propre
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

from groq import Groq

LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
AGENT_ID  = "writer-01"

_EXTRACT_PROMPT = """\
You are a research analyst. Extract ONLY the facts explicitly stated in the text below.

List in plain text (no JSON, no markdown):
- Main topic
- Key findings (copy exact numbers/stats from source only)
- Trends mentioned
- Conclusion
- Sources cited

If a specific number is absent from the text, write "not available" — never estimate.
"""

_WRITE_PROMPT = """\
You are a professional writer. Write a concise, polished report using ONLY the facts listed below.

RULES:
- Write 180-250 words of natural prose paragraphs
- Include ONLY numbers/percentages explicitly stated in the facts — never invent statistics
- If future trends or forecasts are mentioned in the facts, include a short outlook paragraph
- Match the language of the task (write in French if the task is in French)

FORBIDDEN in the "content" field: { } [ ] JSON keys, escaped quotes, bullet points, markdown.
The content must be plain readable prose sentences and paragraphs ONLY.

Respond ONLY with this JSON object (no markdown fences):
{
  "title": "<concise title>",
  "content": "<180-250 words of clean prose — sentences and paragraphs only, absolutely no JSON>",
  "sections": ["Introduction", "Tendances clés", "Perspectives"],
  "word_count": <integer>,
  "format": "report"
}
"""


class WriterAgent:
    def __init__(self, groq_api_key: str):
        self.llm = Groq(api_key=groq_api_key)

    def run(self, prompt: str, task_id: str | None = None) -> dict:
        task_id = task_id or f"task-{uuid.uuid4().hex[:8]}"
        content = self._write(prompt)
        return {
            "task_id":  task_id,
            "agent_id": AGENT_ID,
            "output":   content,
            "status":   "completed",
        }

    def _write(self, content: str) -> dict:
        # Pre-process (Python, no LLM): extract researcher output from pipeline JSON wrapper
        research_text = _extract_research_from_context(content)

        # Step 1: LLM — extract key facts as plain text bullets
        extracted = self._extract_facts(research_text[:8000])

        # Step 2: LLM — write polished 150-250 word prose report
        return self._write_polished(extracted)

    def _extract_facts(self, text: str) -> str:
        resp = self.llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _EXTRACT_PROMPT},
                {"role": "user",   "content": text},
            ],
            temperature=0.0,
            max_tokens=600,
        )
        return resp.choices[0].message.content.strip()

    def _write_polished(self, extracted: str) -> dict:
        resp = self.llm.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _WRITE_PROMPT},
                {"role": "user",   "content": f"Facts to use:\n\n{extracted}"},
            ],
            temperature=0.0,
            max_tokens=1200,
        )
        raw = resp.choices[0].message.content.strip()
        return _parse_and_normalize(raw)


# ── Pre-processing: extract clean research text from pipeline context ─────────

def _extract_research_from_context(content: str) -> str:
    """
    The pipeline passes the writer something like:
      Tâche : ...
      Contexte :
      [Étape 1]
      {"task_id": "...", "output": {researcher JSON}, "status": "completed"}

    Extract just the researcher's output dict and convert it to readable plain text.
    """
    # Find JSON block after [Étape N]
    m = re.search(r'\[Étape \d+\]\s*(\{)', content)
    if not m:
        return content  # no pipeline context found, use as-is

    json_start = m.start(1)
    try:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(content[json_start:])
    except json.JSONDecodeError:
        # Try brute-force: find the last } in the string
        end = content.rfind("}")
        if end == -1:
            return content
        try:
            obj = json.loads(content[json_start:end + 1])
        except json.JSONDecodeError:
            return content

    # The researcher output is nested under "output"
    output = obj.get("output", obj)
    if isinstance(output, dict):
        return _dict_to_readable(output)
    if isinstance(output, str):
        return output
    return content


def _dict_to_readable(d: dict) -> str:
    """Convert researcher output dict to clean readable plain text."""
    lines: list[str] = []

    if d.get("title"):
        lines.append(f"Title: {d['title']}")

    if d.get("query"):
        lines.append(f"Topic: {d['query']}")

    if d.get("summary"):
        lines.append(f"\nSummary:\n{d['summary']}")

    if isinstance(d.get("key_findings"), list):
        lines.append("\nKey Findings:")
        for item in d["key_findings"]:
            if isinstance(item, dict):
                point  = item.get("point") or item.get("finding") or item.get("title") or str(item)
                source = item.get("source") or item.get("url", "")
                line   = f"  - {point}"
                if source:
                    line += f" (source: {source})"
                lines.append(line)
            else:
                lines.append(f"  - {item}")

    if isinstance(d.get("trends"), list):
        lines.append("\nTrends:")
        for t in d["trends"]:
            if isinstance(t, dict):
                desc = t.get("trend") or t.get("description") or t.get("title") or str(t)
                lines.append(f"  - {desc}")
            else:
                lines.append(f"  - {t}")

    if isinstance(d.get("data_points"), list):
        lines.append("\nData Points:")
        for dp in d["data_points"]:
            if isinstance(dp, dict):
                metric = dp.get("metric") or dp.get("indicator") or ""
                value  = dp.get("value") or dp.get("stat") or ""
                src    = dp.get("source") or ""
                lines.append(f"  - {metric} {value} {src}".strip())
            else:
                lines.append(f"  - {dp}")

    if d.get("conclusion"):
        lines.append(f"\nConclusion:\n{d['conclusion']}")

    if isinstance(d.get("sources"), list):
        lines.append("\nSources:")
        for s in d["sources"]:
            lines.append(f"  - {s}")

    return "\n".join(lines) if lines else json.dumps(d, ensure_ascii=False)


# ── Output parsing and normalization ─────────────────────────────────────────

def _parse_and_normalize(raw: str) -> dict:
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    if not raw.startswith("{"):
        m = re.search(r'\{[\s\S]*\}', raw)
        if m:
            raw = m.group(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"title": "Report", "content": raw, "sections": [], "word_count": len(raw.split()), "format": "report"}
    return _normalize_output(data)


def _normalize_output(data: Any) -> dict:
    if not isinstance(data, dict):
        data = {"title": "Report", "content": str(data), "sections": [], "format": "report"}

    title    = str(data.get("title") or "Report").strip()
    content  = data.get("content", "")
    sections = data.get("sections") if isinstance(data.get("sections"), list) else []
    fmt      = "report"

    # If content is a dict/list (nested JSON slipped through), flatten it
    if isinstance(content, (dict, list)):
        content = _flatten_to_prose(content)
    else:
        content = str(content).strip()
        # If content is an escaped JSON string, parse and flatten
        decoded = _try_json(content)
        if decoded is not None:
            content = _flatten_to_prose(decoded)

    # Strip any remaining JSON artifacts from content
    content = re.sub(r'"[a-z_]{2,30}"\s*:', ' ', content)    # "key": patterns
    content = re.sub(r'[{}\[\]]', ' ', content)               # braces/brackets
    content = re.sub(r'\\[nrt"]', ' ', content)               # escape sequences
    content = re.sub(r'\s{2,}', ' ', content).strip()         # normalize whitespace

    if not sections:
        sections = ["Introduction", "Tendances", "Conclusion"]

    return {
        "title":      title,
        "content":    content,
        "sections":   [str(s) for s in sections[:8]],
        "word_count": len(content.split()),
        "format":     fmt,
    }


def _try_json(value: str) -> Any | None:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _flatten_to_prose(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    if isinstance(value, dict):
        parts = []
        for v in value.values():
            if isinstance(v, str) and len(v) > 20:
                parts.append(v)
            elif isinstance(v, list):
                parts.extend(str(i) for i in v if isinstance(i, str))
        return " ".join(parts) if parts else json.dumps(value, ensure_ascii=False)
    return str(value)
