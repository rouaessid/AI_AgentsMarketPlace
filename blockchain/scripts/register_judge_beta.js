/**
 * register_judge_beta.js — Register judge-beta only.
 * Honeypot onboarding runs automatically inside POST /confirm (~25s).
 * Run: node scripts/register_judge_beta.js
 */
const { runSingleJudge } = require("./_judge_helper");

const JUDGE = {
  private_key:  "0x8900abaabf0051608e714523caeed0edc096e304666123905bc96ff7df51b3c7",
  agent_id:     "judge-beta",
  name:         "Judge Beta",
  description:  "Independent AI judge using pure LLM reasoning — no external search. Evaluates agent output for correctness, completeness, coherence, and absence of hallucinations using Groq (Llama-3.3-70b).",
  docker_image: "agentmarket/judge-beta:v1",
  env_var_keys: ["GROQ_API_KEY"],
  special_caps: ["trace-evaluation", "pure-llm-reasoning", "hallucination-detection", "commit-reveal-voting"],
  supported_tasks: ["validate", "score", "evaluate"],
  evaluation_skills: ["reasoning-audit", "logical-coherence", "hallucination-detection"],
  validated_task_types: ["logic", "reasoning", "creative-writing", "coding"],
  evaluation_domains: ["general", "literature", "logic", "philosophy"],
  tools_used: ["groq/llama-3.3-70b"],
  evaluation_style: "pure-llm-reasoning",
  services: [{ name: "run", endpoint: "/run", version: "1.0.0",
               skills: ["evaluation", "reasoning", "output-analysis"] }],
};

runSingleJudge(JUDGE).catch((err) => {
  console.error("\nError:", err.message || err);
  process.exitCode = 1;
});
