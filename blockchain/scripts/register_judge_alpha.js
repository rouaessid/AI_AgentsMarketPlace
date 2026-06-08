/**
 * register_judge_alpha.js — Register judge-alpha only.
 * Honeypot onboarding runs automatically inside POST /confirm (~25s).
 * Run: node scripts/register_judge_alpha.js
 */
const { runSingleJudge } = require("./_judge_helper");

const JUDGE = {
  private_key:  "0x8900abaabf0051608e714523caeed0edc096e304666123905bc96ff7df51b3c7",
  agent_id:     "judge-alpha",
  name:         "Judge Alpha",
  description:  "Independent AI judge. Evaluates agent execution traces using Groq (Llama-3.3-70b) with optional Tavily fact-checking. Returns a structured verdict (score 0-100, VALID/INVALID) based on task completion quality.",
  docker_image: "agentmarket/judge-alpha:v1",
  env_var_keys: ["GROQ_API_KEY", "TAVILY_API_KEY"],
  special_caps: ["trace-evaluation", "fact-checking", "commit-reveal-voting", "structured-verdict"],
  supported_tasks: ["validate", "score", "evaluate"],
  evaluation_skills: ["factuality-check", "source-verification", "web-fact-checking", "coherence"],
  validated_task_types: ["research", "report", "market-analysis", "analysis", "write"],
  evaluation_domains: ["finance", "technology", "market-research", "science", "startups", "business"],
  tools_used: ["groq/llama-3.3-70b", "tavily-search"],
  evaluation_style: "fact-checking-with-search",
  services: [{ name: "run", endpoint: "/run", version: "1.0.0",
               skills: ["evaluation", "fact-checking", "structured-scoring"] }],
};

runSingleJudge(JUDGE).catch((err) => {
  console.error("\nError:", err.message || err);
  process.exitCode = 1;
});
