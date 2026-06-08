"""
honeypot_store.py — Technical onboarding trace for judge containers.

Purpose: verify the judge container is functional and follows the protocol.
NOT a quality test — quality is guaranteed by stake/slash/consensus on-chain.

Technical checks performed on this trace:
  1. Container starts and responds to POST /run
  2. Response is valid JSON with a score field
  3. Score is between 1-99 (not hardcoded 0 or 100)
  4. challenge_token is present (proves judge fetched trace from IPFS)
  5. trajectory_check is present (proves judge parsed the trace)
"""

# One normal-quality trace — medium output, real trajectory steps.
# Any functional judge should return a score between 1-99.
TECHNICAL_TRACE: dict = {
    "task_prompt": (
        "Summarize the key trends in the AI startup ecosystem in 2024, "
        "focusing on funding patterns and major developments."
    ),
    "agent_output": (
        "The AI startup ecosystem in 2024 showed significant consolidation. "
        "Funding concentrated around foundation model companies and vertical AI. "
        "Key trends included: increased enterprise adoption, regulatory scrutiny in EU, "
        "and emergence of AI agents as a distinct product category. "
        "Notable: OpenAI valuation reached $157B, Anthropic raised $4B from Google."
    ),
    "trajectory": [
        {"seq": 0, "tool": "tavily_search", "tool_category": "search",
         "status": 200, "request_query": "AI startup funding trends 2024"},
        {"seq": 1, "tool": "groq_llm",     "tool_category": "llm",    "status": 200},
        {"seq": 2, "tool": "tavily_search", "tool_category": "search",
         "status": 200, "request_query": "OpenAI Anthropic valuation 2024"},
        {"seq": 3, "tool": "groq_llm",     "tool_category": "llm",    "status": 200},
    ],
    "tools_used":   4,
    "llm_calls":    2,
    "search_calls": 2,
    "duration_sec": 14.3,
    "total_tokens": 1200,
}
