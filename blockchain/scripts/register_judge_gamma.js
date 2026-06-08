/**
 * register_judge_gamma.js — Register judge-gamma only.
 * Honeypot onboarding runs automatically inside POST /confirm (~25s).
 * Run: node scripts/register_judge_gamma.js
 */
const { runSingleJudge } = require("./_judge_helper");

const JUDGE = {
  private_key:  "0x8900abaabf0051608e714523caeed0edc096e304666123905bc96ff7df51b3c7",
  agent_id:     "judge-gamma",
  name:         "Judge Gamma",
  description:  "Independent AI judge specialised in execution behaviour analysis. Evaluates tool call logic, trajectory coherence, and consistency between process and output.",
  docker_image: "agentmarket/judge-gamma:v1",
  env_var_keys: ["GROQ_API_KEY"],
  special_caps: ["trace-evaluation", "behaviour-analysis", "trajectory-coherence", "commit-reveal-voting"],
  supported_tasks: ["validate", "score", "evaluate"],
  evaluation_skills: ["trajectory-analysis", "tool-use-audit", "step-by-step-verification"],
  validated_task_types: ["complex-workflow", "multi-tool-task", "coding"],
  evaluation_domains: ["software-engineering", "devops", "automation"],
  tools_used: ["groq/llama-3.3-70b"],
  evaluation_style: "behavioural-audit",
  services: [{ name: "run", endpoint: "/run", version: "1.0.0",
               skills: ["evaluation", "trace-analysis", "behaviour-auditing"] }],
};

runSingleJudge(JUDGE).catch((err) => {
  console.error("\nError:", err.message || err);
  process.exitCode = 1;
});
