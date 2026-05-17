/**
 * register_judges_robust.js
 * 
 * Registers the 5 judge agents (Alpha, Beta, Gamma, Delta, Epsilon)
 * using the advanced "Researcher" logic with automatic recovery.
 */

const { ethers } = require("ethers");
const http = require("http");
const fs   = require("fs");
const path = require("path");

// ── Config ────────────────────────────────────────────────────────────────────
const RPC     = "http://127.0.0.1:8545";
const BACKEND = "http://localhost:8000";

const JUDGES = [
  {
    private_key: "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6", // Account #3
    agent_id:    "judge-alpha",
    name:        "Judge Alpha",
    description: "Independent AI judge. Evaluates agent execution traces using Groq (Llama-3.3-70b) with optional Tavily fact-checking. Returns a structured verdict (score 0-100, VALID/INVALID).",
    docker_image: "agentmarket/judge-alpha:v1",
    env_var_keys: ["GROQ_API_KEY", "TAVILY_API_KEY"],
    supported_tasks: ["validate", "score", "evaluate"],
    special_caps: ["trace-evaluation", "fact-checking", "commit-reveal-voting", "structured-verdict"],
    evaluation_skills: ["factuality-check", "source-verification", "web-fact-checking", "coherence"],
    validated_task_types: ["research", "report", "market-analysis", "analysis", "write"],
    evaluation_domains: ["finance", "technology", "market-research", "science", "startups", "business"],
    tools_used: ["groq/llama-3.3-70b", "tavily-search"],
    evaluation_style: "fact-checking-with-search",
    services: [{ name: "run", endpoint: "/run", version: "1.0.0",
                 skills: ["evaluation", "fact-checking", "structured-scoring"] }],
  },
  {
    private_key: "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6", // Account #3
    agent_id:    "judge-beta",
    name:        "Judge Beta",
    description: "Independent AI judge using pure LLM reasoning — no external search. Evaluates correctness, completeness, coherence, and hallucinations using Groq (Llama-3.3-70b).",
    docker_image: "agentmarket/judge-beta:v1",
    env_var_keys: ["GROQ_API_KEY"],
    supported_tasks: ["validate", "score", "evaluate"],
    special_caps: ["trace-evaluation", "pure-llm-reasoning", "hallucination-detection", "commit-reveal-voting"],
    evaluation_skills: ["reasoning-audit", "logical-coherence", "hallucination-detection"],
    validated_task_types: ["logic", "reasoning", "creative-writing", "coding"],
    evaluation_domains: ["general", "literature", "logic", "philosophy"],
    tools_used: ["groq/llama-3.3-70b"],
    evaluation_style: "pure-llm-reasoning",
    services: [{ name: "run", endpoint: "/run", version: "1.0.0",
                 skills: ["evaluation", "reasoning", "output-analysis"] }],
  },
  {
    private_key: "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6", // Account #3
    agent_id:    "judge-gamma",
    name:        "Judge Gamma",
    description: "Independent AI judge specialised in execution behaviour analysis. Evaluates tool call logic, trajectory coherence, and consistency between process and output.",
    docker_image: "agentmarket/judge-gamma:v1",
    env_var_keys: ["GROQ_API_KEY"],
    supported_tasks: ["validate", "score", "evaluate"],
    special_caps: ["trace-evaluation", "behaviour-analysis", "trajectory-coherence", "commit-reveal-voting"],
    evaluation_skills: ["trajectory-analysis", "tool-use-audit", "step-by-step-verification"],
    validated_task_types: ["complex-workflow", "multi-tool-task", "coding"],
    evaluation_domains: ["software-engineering", "devops", "automation"],
    tools_used: ["groq/llama-3.3-70b"],
    evaluation_style: "behavioural-audit",
    services: [{ name: "run", endpoint: "/run", version: "1.0.0",
                 skills: ["evaluation", "trace-analysis", "behaviour-auditing"] }],
  },
  {
    private_key: "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a", // Account #4
    agent_id:    "judge-delta",
    name:        "Judge Delta",
    description: "Hallucination detection specialist. Extracts factual claims from agent output and cross-checks them against the input context and trajectory. Flags unsupported assertions. Uses Groq (Llama-3.3-70b).",
    docker_image: "agentmarket/judge-delta:v1",
    env_var_keys: ["GROQ_API_KEY"],
    supported_tasks: ["validate", "score", "evaluate"],
    special_caps: ["hallucination-detection", "claim-extraction", "fact-grounding", "commit-reveal-voting"],
    evaluation_skills: ["hallucination-detection", "claim-extraction", "fact-grounding", "source-cross-checking"],
    validated_task_types: ["research", "analysis", "report", "market-analysis"],
    evaluation_domains: ["finance", "technology", "market-research", "science", "startups"],
    tools_used: ["groq/llama-3.3-70b"],
    evaluation_style: "hallucination-detection",
    services: [{ name: "run", endpoint: "/run", version: "1.0.0",
                 skills: ["hallucination-detection", "claim-extraction", "fact-grounding", "source-cross-checking"] }],
  },
  {
    private_key: "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a", // Account #2
    agent_id:    "judge-epsilon",
    name:        "Judge Epsilon",
    description: "Rubric-based evaluation specialist. Scores agent output on a structured grid: relevance, completeness, accuracy, format, and prompt adherence. Each dimension scored 0-25 for a total of 0-100. Uses Groq (Llama-3.3-70b).",
    docker_image: "agentmarket/judge-epsilon:v1",
    env_var_keys: ["GROQ_API_KEY"],
    supported_tasks: ["validate", "score", "evaluate"],
    special_caps: ["rubric-scoring", "multi-dimension-evaluation", "prompt-adherence", "commit-reveal-voting"],
    evaluation_skills: ["rubric-scoring", "completeness-check", "prompt-adherence", "format-validation", "structured-output-review"],
    validated_task_types: ["research", "analysis", "write", "generate", "report", "summarize", "document"],
    evaluation_domains: ["finance", "technology", "market-research", "science", "business"],
    tools_used: ["groq/llama-3.3-70b"],
    evaluation_style: "rubric-based",
    services: [{ name: "run", endpoint: "/run", version: "1.0.0",
                 skills: ["rubric-scoring", "completeness-check", "prompt-adherence", "format-validation"] }],
  },
];

const AGENT_CREATED_TOPIC = ethers.id("AgentCreated(string,uint256,address,uint8,string,string)");

// ── Helpers ───────────────────────────────────────────────────────────────────

function backendPost(urlPath, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const opts = {
      hostname: "localhost",
      port:     8000,
      path:     urlPath,
      method:   "POST",
      headers:  { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) },
    };
    const req = http.request(opts, (res) => {
      let raw = "";
      res.on("data", (c) => (raw += c));
      res.on("end",  () => {
        try {
          const parsed = JSON.parse(raw);
          if (res.statusCode >= 400) {
            reject(new Error(`HTTP ${res.statusCode}: ${JSON.stringify(parsed.detail || parsed)}`));
          } else {
            resolve(parsed);
          }
        } catch {
          reject(new Error(`Non-JSON (${res.statusCode}): ${raw.slice(0, 200)}`));
        }
      });
    });
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

async function waitReceipt(provider, txHash, maxAttempts = 40) {
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const receipt = await provider.getTransactionReceipt(txHash);
    if (receipt) {
      if (receipt.status === 0) throw new Error(`Transaction reverted: ${txHash}`);
      return receipt;
    }
  }
  throw new Error(`Not confirmed after ${maxAttempts * 2}s: ${txHash}`);
}

function parseTokenId(receipt, contractAddress) {
  const log = receipt.logs.find(
    (l) => l.address.toLowerCase() === contractAddress.toLowerCase()
        && l.topics[0] === AGENT_CREATED_TOPIC
  );
  if (!log || !log.topics[1]) return null;
  return Number(BigInt(log.topics[1]));
}

async function recoverPendingAgent(info, wallet, provider, identityAddr, stakingAddr) {
  console.log(`  → Judge ${info.agent_id} already registered — checking status...`);

  let retryResp;
  try {
    retryResp = await backendPost(`/api/v1/agents/${info.agent_id}/retry-register`, {});
  } catch (e) {
    console.log(`  ✗ retry-register failed: ${e.message}`);
    return;
  }

  if (retryResp.status === "active") {
    console.log(`  ✓ ${info.agent_id} is already active — skipping.`);
    return;
  }

  const registrationId = retryResp.registration_id;

  const identityContract = new ethers.Contract(identityAddr, [
    "function getCurrentTokenId(string calldata agentId_) external view returns (uint256)",
  ], provider);

  let tokenId;
  try {
    const raw = await identityContract.getCurrentTokenId(info.agent_id);
    tokenId = Number(BigInt(raw));
  } catch {
    console.log("  ✗ Judge not found on-chain.");
    return;
  }

  const logs = await provider.getLogs({
    address:   identityAddr,
    topics:    [AGENT_CREATED_TOPIC],
    fromBlock: 0,
    toBlock:   "latest",
  });
  const matchLog = logs.find(
    (l) => l.topics[1] && Number(BigInt(l.topics[1])) === tokenId
  );
  if (!matchLog) return;
  const txHash = matchLog.transactionHash;

  console.log("  → POST /api/v1/agents/confirm (recovery) ...");
  await backendPost("/api/v1/agents/confirm", {
    registration_id: registrationId,
    tx_hash:         txHash,
    token_id:        tokenId,
  });

  console.log(`  → Staking 0.001 ETH (recovery) ...`);
  const stakeTx = await wallet.sendTransaction({
    to:       stakingAddr,
    value:    ethers.parseEther("0.001"),
    data:     "0x3a4b66f1",
    gasLimit: BigInt(200_000),
  });
  await waitReceipt(provider, stakeTx.hash);
  console.log(`  Staked — ${info.agent_id} recovered.`);
}

async function registerJudge(info, deployer, provider, identityAddr, stakingAddr) {
  const wallet = new ethers.Wallet(info.private_key, provider);
  console.log(`\n── ${info.name} ${"─".repeat(40 - info.name.length)}`);
  
  // Fund wallet if needed
  const bal = await provider.getBalance(wallet.address);
  if (bal < ethers.parseEther("0.003")) {
      await deployer.sendTransaction({ to: wallet.address, value: ethers.parseEther("0.05") });
  }

  const payload = { 
    ...info, 
    agent_type: "judge", 
    owner_address: wallet.address,
    version: "1.0.0",
    llm_model: "llama-3.3-70b-versatile",
    framework: "groq_raw",
    language: "python",
    price_per_task: 0.0,
    stake_amount: 0.001,
    cpu_limit: 1,
    ram_limit_mb: 512,
    timeout_sec: 60,
  };
  delete payload.private_key;

  console.log("  → POST /api/v1/agents/register ...");
  let reg;
  try {
    reg = await backendPost("/api/v1/agents/register", payload);
  } catch (e) {
    if (e.message.includes("deja utilise")) {
      await recoverPendingAgent(info, wallet, provider, identityAddr, stakingAddr);
      return;
    }
    throw e;
  }

  console.log(`  registration_id : ${reg.registration_id}`);

  console.log("  → Signing IdentityRegistry.register() ...");
  const identityTx = await wallet.sendTransaction({
    to:       reg.unsigned_tx.contract_address,
    data:     reg.unsigned_tx.data,
    gasLimit: BigInt(reg.unsigned_tx.estimated_gas || 800_000),
  });
  
  const receipt = await waitReceipt(provider, identityTx.hash);
  const tokenId = parseTokenId(receipt, reg.unsigned_tx.contract_address);
  console.log(`  Token ID        : ${tokenId ?? "(not parsed)"}`);

  console.log("  → POST /api/v1/agents/confirm ...");
  await backendPost("/api/v1/agents/confirm", {
    registration_id: reg.registration_id,
    tx_hash:         identityTx.hash,
    ...(tokenId != null && { token_id: tokenId }),
  });

  console.log(`  → Staking 0.001 ETH ...`);
  const stakeTx = await wallet.sendTransaction({
    to:       stakingAddr,
    value:    ethers.parseEther("0.001"),
    data:     "0x3a4b66f1",
    gasLimit: BigInt(200_000),
  });
  await waitReceipt(provider, stakeTx.hash);
  console.log(`  Done — ${info.agent_id} is live.`);
}

async function main() {
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const identityAddr = deployment.contracts.IdentityRegistry.address;
  const stakingAddr  = deployment.contracts.StakingContract.address;

  const provider = new ethers.JsonRpcProvider(RPC);
  const deployer = new ethers.Wallet("0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80", provider);

  for (const info of JUDGES) {
    await registerJudge(info, deployer, provider, identityAddr, stakingAddr);
  }
}

main().catch(console.error);
