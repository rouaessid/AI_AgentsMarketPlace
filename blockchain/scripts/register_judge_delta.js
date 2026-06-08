/**
 * register_judge_delta.js — Register judge-delta only.
 * Honeypot onboarding runs automatically inside POST /confirm (~25s).
 * Run: node scripts/register_judge_delta.js
 */
const { runSingleJudge } = require("./_judge_helper");

const JUDGE = {
  private_key:  "0x8900abaabf0051608e714523caeed0edc096e304666123905bc96ff7df51b3c7",
  agent_id:     "judge-delta",
  name:         "Judge Delta",
  description:  "Hallucination detection specialist. Extracts factual claims from agent output and cross-checks them against the input context and trajectory. Flags unsupported assertions. Uses Groq (Llama-3.3-70b).",
  docker_image: "agentmarket/judge-delta:v1",
  env_var_keys: ["GROQ_API_KEY"],
  special_caps: ["hallucination-detection", "claim-extraction", "fact-grounding", "commit-reveal-voting"],
  supported_tasks: ["validate", "score", "evaluate"],
  evaluation_skills: ["hallucination-detection", "claim-extraction", "fact-grounding", "source-cross-checking"],
  validated_task_types: ["research", "analysis", "report", "market-analysis"],
  evaluation_domains: ["finance", "technology", "market-research", "science", "startups"],
  tools_used: ["groq/llama-3.3-70b"],
  evaluation_style: "hallucination-detection",
  services: [{ name: "run", endpoint: "/run", version: "1.0.0",
               skills: ["hallucination-detection", "claim-extraction", "fact-grounding"] }],
};

runSingleJudge(JUDGE).catch((err) => {
  console.error("\nError:", err.message || err);
  process.exitCode = 1;
});
