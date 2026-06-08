/**
 * register_judge_epsilon.js — Register judge-epsilon only.
 * Honeypot onboarding runs automatically inside POST /confirm (~25s).
 * Run: node scripts/register_judge_epsilon.js
 */
const { runSingleJudge } = require("./_judge_helper");

const JUDGE = {
  private_key:  "0x8900abaabf0051608e714523caeed0edc096e304666123905bc96ff7df51b3c7",
  agent_id:     "judge-epsilon",
  name:         "Judge Epsilon",
  description:  "Rubric-based evaluation specialist. Scores agent output on a structured grid: relevance, completeness, accuracy, format, and prompt adherence. Each dimension scored 0-25 for a total of 0-100.",
  docker_image: "agentmarket/judge-epsilon:v1",
  env_var_keys: ["GROQ_API_KEY"],
  special_caps: ["rubric-scoring", "multi-dimension-evaluation", "prompt-adherence", "commit-reveal-voting"],
  supported_tasks: ["validate", "score", "evaluate"],
  evaluation_skills: ["rubric-scoring", "completeness-check", "prompt-adherence", "format-validation"],
  validated_task_types: ["research", "analysis", "write", "generate", "report", "summarize"],
  evaluation_domains: ["finance", "technology", "market-research", "science", "business"],
  tools_used: ["groq/llama-3.3-70b"],
  evaluation_style: "rubric-based",
  services: [{ name: "run", endpoint: "/run", version: "1.0.0",
               skills: ["rubric-scoring", "completeness-check", "prompt-adherence", "format-validation"] }],
};

runSingleJudge(JUDGE).catch((err) => {
  console.error("\nError:", err.message || err);
  process.exitCode = 1;
});
