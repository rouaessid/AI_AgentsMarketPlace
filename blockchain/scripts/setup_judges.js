// scripts/setup_judges.js
// Registers judge agents via the backend API (same flow as the frontend form):
//   1. POST /api/v1/agents/register  → IPFS upload + DB entry + unsigned tx
//   2. Judge wallet signs IdentityRegistry.register()
//   3. POST /api/v1/agents/confirm   → marks agent ACTIVE
//   4. Judge wallet signs StakingContract.stake()
//
// Run after setup_complete.js:
//   npx hardhat run scripts/setup_judges.js --network localhost

const { ethers } = require("hardhat");
const http = require("http");
const fs   = require("fs");
const path = require("path");

const BACKEND = "http://localhost:8000";

// Hardhat local judge wallets — accounts #3 through #7
const JUDGES = [
  {
    private_key: "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
    agent_id:    "judge-alpha",
    name:        "Judge Alpha",
    description: "Independent AI judge. Evaluates agent execution traces using Groq (Llama-3.3-70b) with optional Tavily fact-checking. Returns a structured verdict (score 0-100, VALID/INVALID).",
    docker_image: "agentmarket/judge-alpha:v1",
    env_var_keys: ["GROQ_API_KEY", "TAVILY_API_KEY"],
    supported_tasks: ["validate", "score", "evaluate"],
    special_caps: ["trace-evaluation", "fact-checking", "commit-reveal-voting", "structured-verdict"],
    services: [{ name: "run", endpoint: "/run", version: "1.0.0",
                 skills: ["evaluation", "fact-checking", "structured-scoring"] }],
  },
  {
    private_key: "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a",
    agent_id:    "judge-beta",
    name:        "Judge Beta",
    description: "Independent AI judge using pure LLM reasoning — no external search. Evaluates correctness, completeness, coherence, and hallucinations using Groq (Llama-3.3-70b).",
    docker_image: "agentmarket/judge-beta:v1",
    env_var_keys: ["GROQ_API_KEY"],
    supported_tasks: ["validate", "score", "evaluate"],
    special_caps: ["trace-evaluation", "pure-llm-reasoning", "hallucination-detection", "commit-reveal-voting"],
    services: [{ name: "run", endpoint: "/run", version: "1.0.0",
                 skills: ["evaluation", "reasoning", "output-analysis"] }],
  },
  {
    private_key: "0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba",
    agent_id:    "judge-gamma",
    name:        "Judge Gamma",
    description: "Independent AI judge specialised in execution behaviour analysis. Evaluates tool call logic, trajectory coherence, and consistency between process and output.",
    docker_image: "agentmarket/judge-gamma:v1",
    env_var_keys: ["GROQ_API_KEY"],
    supported_tasks: ["validate", "score", "evaluate"],
    special_caps: ["trace-evaluation", "behaviour-analysis", "trajectory-coherence", "commit-reveal-voting"],
    services: [{ name: "run", endpoint: "/run", version: "1.0.0",
                 skills: ["evaluation", "trace-analysis", "behaviour-auditing"] }],
  },
  {
    private_key: "0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e",
    agent_id:    "judge-delta",
    name:        "Judge Delta",
    description: "Hallucination detection specialist. Extracts factual claims from agent output and cross-checks them against the input context and trajectory. Flags unsupported assertions.",
    docker_image: "agentmarket/judge-delta:v1",
    env_var_keys: ["GROQ_API_KEY"],
    supported_tasks: ["validate", "score", "evaluate"],
    special_caps: ["hallucination-detection", "claim-extraction", "fact-grounding", "commit-reveal-voting"],
    services: [{ name: "run", endpoint: "/run", version: "1.0.0",
                 skills: ["hallucination-detection", "claim-extraction", "fact-grounding", "source-cross-checking"] }],
  },
  {
    private_key: "0x4bbbf85ce3377467afe5d46f804f221813b2bb87f24d81f60f1fcdbf7cbf4356",
    agent_id:    "judge-epsilon",
    name:        "Judge Epsilon",
    description: "Rubric-based evaluation specialist. Scores agent output on a structured grid: relevance, completeness, accuracy, format, and prompt adherence. Each dimension 0-25, total 0-100.",
    docker_image: "agentmarket/judge-epsilon:v1",
    env_var_keys: ["GROQ_API_KEY"],
    supported_tasks: ["validate", "score", "evaluate"],
    special_caps: ["rubric-scoring", "multi-dimension-evaluation", "prompt-adherence", "commit-reveal-voting"],
    services: [{ name: "run", endpoint: "/run", version: "1.0.0",
                 skills: ["rubric-scoring", "completeness-check", "prompt-adherence", "format-validation"] }],
  },
];

const STAKE_AMOUNT    = ethers.parseEther("0.001");
const MIN_GAS_BUFFER  = ethers.parseEther("0.002");

// ── On-chain recovery helper ──────────────────────────────────────────────────
const IDENTITY_ABI_MINIMAL = [
  "function agentIdExists(string calldata agentId_) external view returns (bool)",
  "function register(string calldata agentId_, uint8 agentType_, string calldata agentURI_, string calldata version_, uint256 pricePerTask_) external returns (uint256 tokenId)",
];

async function ensureJudgeOnchain(info, wallet, identityAddr, stakingAddr, provider) {
  const identity = new ethers.Contract(identityAddr, IDENTITY_ABI_MINIMAL, wallet);
  const exists   = await identity.agentIdExists(info.agent_id);
  if (exists) {
    console.log(`  ✓ ${info.agent_id} already on-chain — nothing to do.`);
    return;
  }

  console.log(`  → ${info.agent_id} missing on-chain — registering directly...`);
  const tx = await identity.register(
    info.agent_id, 1, `ipfs://agentmarket/${info.agent_id}/v1.0.0`, "1.0.0", 0n
  );
  await tx.wait();
  console.log(`  ✓ Registered on-chain.`);

  // Stake
  console.log(`  → Staking ${ethers.formatEther(STAKE_AMOUNT)} ETH ...`);
  const stakeTx = await wallet.sendTransaction({
    to: stakingAddr, value: STAKE_AMOUNT, data: "0x3a4b66f1", gasLimit: 200_000n,
  });
  await stakeTx.wait();
  console.log(`  ✓ Staked — ${info.agent_id} fully recovered.`);
}

// ── HTTP helper ───────────────────────────────────────────────────────────────

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
      res.on("end", () => {
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

// ── Register one judge ────────────────────────────────────────────────────────

async function registerJudge(info, deployer, provider, stakingAddr, identityAddr) {
  const wallet = new ethers.Wallet(info.private_key, provider);

  console.log(`\n── ${info.name} ${"─".repeat(40 - info.name.length)}`);
  console.log(`  Address : ${wallet.address}`);
  console.log(`  AgentId : ${info.agent_id}`);

  // Fund wallet if needed
  const required = STAKE_AMOUNT + MIN_GAS_BUFFER;
  const balance  = await provider.getBalance(wallet.address);
  if (balance < required) {
    const deficit = required - balance;
    const fundTx = await deployer.sendTransaction({ to: wallet.address, value: deficit });
    await fundTx.wait();
    console.log(`  Funded  : ${ethers.formatEther(deficit)} ETH`);
  }

  // Step 1: POST /api/v1/agents/register
  const payload = {
    agent_id:        info.agent_id,
    name:            info.name,
    description:     info.description,
    version:         "1.0.0",
    agent_type:      "judge",
    owner_address:   wallet.address,
    docker_image:    info.docker_image,
    env_var_keys:    info.env_var_keys,
    supported_tasks: info.supported_tasks,
    special_caps:    info.special_caps,
    services:        info.services,
    llm_model:       "llama-3.3-70b-versatile",
    framework:       "groq_raw",
    language:        "python",
    price_per_task:  0.0,
    stake_amount:    0.001,
    cpu_limit:       1,
    ram_limit_mb:    512,
    timeout_sec:     60,
  };

  console.log("  → POST /api/v1/agents/register ...");
  let reg;
  try {
    reg = await backendPost("/api/v1/agents/register", payload);
  } catch (e) {
    if (e.message.includes("deja utilise") || e.message.includes("already") || e.message.includes("existe")) {
      console.log(`  Already in DB — checking on-chain state...`);
      await ensureJudgeOnchain(info, wallet, identityAddr, stakingAddr, provider);
      return;
    }
    throw e;
  }

  console.log(`  IPFS CID        : ${reg.ipfs_cid}`);
  console.log(`  registration_id : ${reg.registration_id}`);

  if (!reg.unsigned_tx?.data) throw new Error("Backend did not return unsigned_tx.data");

  // Step 2: Judge wallet signs IdentityRegistry.register()
  console.log("  → Signing IdentityRegistry.register() ...");
  const identityTx = await wallet.sendTransaction({
    to:       reg.unsigned_tx.contract_address,
    data:     reg.unsigned_tx.data,
    gasLimit: BigInt(reg.unsigned_tx.estimated_gas || 800_000),
  });
  console.log(`  Identity tx     : ${identityTx.hash.slice(0, 20)}...`);
  await waitReceipt(provider, identityTx.hash);

  // Step 3: POST /api/v1/agents/confirm
  console.log("  → POST /api/v1/agents/confirm ...");
  await backendPost("/api/v1/agents/confirm", {
    registration_id: reg.registration_id,
    tx_hash:         identityTx.hash,
  });
  console.log("  Backend marked ACTIVE.");

  // Step 4: Judge wallet stakes
  console.log(`  → Staking ${ethers.formatEther(STAKE_AMOUNT)} ETH ...`);
  const stakeTx = await wallet.sendTransaction({
    to:       stakingAddr,
    value:    STAKE_AMOUNT,
    data:     "0x3a4b66f1",  // stake() selector
    gasLimit: BigInt(200_000),
  });
  console.log(`  Stake tx        : ${stakeTx.hash.slice(0, 20)}...`);
  await waitReceipt(provider, stakeTx.hash);
  console.log(`  Staked — ${info.agent_id} ready.\n`);
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const [deployer] = await ethers.getSigners();
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");

  if (!fs.existsSync(deploymentPath)) {
    throw new Error("deployment.json not found — run setup_complete.js first");
  }

  const deployment   = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const stakingAddr  = deployment.contracts.StakingContract.address;
  const identityAddr = deployment.contracts.IdentityRegistry.address;

  const provider = ethers.provider;
  console.log(`\nDeployer        : ${deployer.address}`);
  console.log(`IdentityRegistry: ${identityAddr}`);
  console.log(`StakingContract : ${stakingAddr}`);
  console.log(`Backend         : ${BACKEND}\n`);
  console.log(`Setting up ${JUDGES.length} judge agents...`);

  for (const judge of JUDGES) {
    await registerJudge(judge, deployer, provider, stakingAddr, identityAddr);
  }

  console.log(`${JUDGES.length} judge agents registered and staked.`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
