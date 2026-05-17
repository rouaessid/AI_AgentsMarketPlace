/**
 * register_judges.js
 *
 * Registers judge-alpha, judge-beta, judge-gamma by mimicking the frontend
 * RegisterAgent form flow exactly:
 *
 *   1. POST /api/v1/agents/register  → IPFS upload + DB entry + unsigned tx
 *   2. Owner wallet signs IdentityRegistry.register()
 *   3. POST /api/v1/agents/confirm   → sets agent ACTIVE in DB
 *   4. Owner wallet signs StakingContract.stake()
 *
 * If an agent is already in pending_signature (partial registration from a
 * previous failed run), the script recovers automatically:
 *   - POST /{agent_id}/retry-register  → get registration_id back
 *   - IdentityRegistry.getCurrentTokenId()  → tokenId already on-chain
 *   - Scan AgentCreated logs  → original tx_hash
 *   - POST /api/v1/agents/confirm  → mark ACTIVE
 *   - StakingContract.stake()  → stake
 *
 * One single wallet owns and signs for all 3 judges.
 *
 * Prerequisites:
 *   - Anvil running on localhost:8545 (with contracts already deployed)
 *   - Backend running on localhost:8000
 *
 * Run:
 *   node scripts/register_judges.js
 */

const { ethers } = require("ethers");
const http = require("http");
const fs   = require("fs");
const path = require("path");

// ── Config ────────────────────────────────────────────────────────────────────
const RPC     = "http://127.0.0.1:8545";
const BACKEND = "http://localhost:8000";

// Single owner wallet — signs for all 3 judges
// Address: 0x90F79bf6EB2c4f870365E785982E1f101E93b906  (Hardhat account #3)
const OWNER_KEY = "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6";

const STAKE_ETH     = "0.001";
const MIN_GAS_ETH   = "0.002";   // buffer for identity + stake txs

const JUDGES = [
  {
    agent_id:     "judge-alpha",
    name:         "Judge Alpha",
    description:  "Independent AI judge. Evaluates agent execution traces using Groq (Llama-3.3-70b) with optional Tavily fact-checking. Returns a structured verdict (score 0-100, VALID/INVALID) based on task completion quality.",
    docker_image: "agentmarket/judge-alpha:v1",
    env_var_keys: ["GROQ_API_KEY", "TAVILY_API_KEY"],
    special_caps: ["trace-evaluation", "fact-checking", "commit-reveal-voting", "structured-verdict"],
  },
  {
    agent_id:     "judge-beta",
    name:         "Judge Beta",
    description:  "Independent AI judge using pure LLM reasoning — no external search. Evaluates agent output for correctness, completeness, coherence, and absence of hallucinations using Groq (Llama-3.3-70b).",
    docker_image: "agentmarket/judge-beta:v1",
    env_var_keys: ["GROQ_API_KEY"],
    special_caps: ["trace-evaluation", "pure-llm-reasoning", "hallucination-detection", "commit-reveal-voting"],
  },
  {
    agent_id:     "judge-gamma",
    name:         "Judge Gamma",
    description:  "Independent AI judge specialised in execution behaviour analysis. Evaluates tool call logic, trajectory coherence, and consistency between process and output.",
    docker_image: "agentmarket/judge-gamma:v1",
    env_var_keys: ["GROQ_API_KEY"],
    special_caps: ["trace-evaluation", "behaviour-analysis", "trajectory-coherence", "process-verification", "commit-reveal-voting"],
  },
];

// ── HTTP helper ───────────────────────────────────────────────────────────────
function backendPost(urlPath, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const opts = {
      hostname: "localhost",
      port:     8000,
      path:     urlPath,
      method:   "POST",
      headers: {
        "Content-Type":   "application/json",
        "Content-Length": Buffer.byteLength(data),
      },
    };
    const req = http.request(opts, (res) => {
      let raw = "";
      res.on("data",  (c) => (raw += c));
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

// ── Wait for tx receipt ───────────────────────────────────────────────────────
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

// Extract tokenId from AgentCreated event
// Event: AgentCreated(string agentId, uint256 indexed tokenId, address indexed owner, ...)
//   topics[0] = event sig hash
//   topics[1] = tokenId  (first indexed param)
//   topics[2] = owner address (second indexed param)
const AGENT_CREATED_TOPIC = ethers.id("AgentCreated(string,uint256,address,uint8,string,string)");

function parseTokenId(receipt, contractAddress) {
  const log = receipt.logs.find(
    (l) => l.address.toLowerCase() === contractAddress.toLowerCase()
        && l.topics[0] === AGENT_CREATED_TOPIC
  );
  if (!log || !log.topics[1]) return null;
  return Number(BigInt(log.topics[1]));  // topics[1] = tokenId (NOT topics[2] which is owner)
}

// ── Fund owner wallet if needed ───────────────────────────────────────────────
async function ensureFunded(deployer, ownerWallet, judgeCount) {
  const perJudge = ethers.parseEther(STAKE_ETH) + ethers.parseEther(MIN_GAS_ETH);
  const required = perJudge * BigInt(judgeCount);
  const balance  = await ownerWallet.provider.getBalance(ownerWallet.address);
  if (balance < required) {
    const deficit = required - balance;
    const tx = await deployer.sendTransaction({ to: ownerWallet.address, value: deficit });
    await tx.wait();
    console.log(`Funded owner    : +${ethers.formatEther(deficit)} ETH from deployer`);
  }
}

// ── Recover an agent stuck in pending_signature ───────────────────────────────
// Called when backend says "deja utilise" — agent is in DB but confirm never succeeded.
async function recoverPendingAgent(info, owner, provider, identityAddr, stakingAddr) {
  console.log("  → Agent is pending — attempting recovery...");

  // 1. Get registration_id via retry-register
  let retryResp;
  try {
    retryResp = await backendPost(`/api/v1/agents/${info.agent_id}/retry-register`, {});
  } catch (e) {
    console.log(`  ✗ retry-register failed: ${e.message}`);
    console.log("    Agent may already be ACTIVE or in an unrecoverable state — skipping.");
    return;
  }
  const registrationId = retryResp.registration_id;
  console.log(`  registration_id : ${registrationId}`);

  // 2. Get tokenId from on-chain view
  const identityContract = new ethers.Contract(identityAddr, [
    "function getCurrentTokenId(string calldata agentId_) external view returns (uint256)",
  ], provider);

  let tokenId;
  try {
    const raw = await identityContract.getCurrentTokenId(info.agent_id);
    tokenId = Number(BigInt(raw));
  } catch {
    console.log("  ✗ Agent not found on-chain — identity tx may not have been sent.");
    console.log("    Delete it from the backend DB and re-run to do a clean registration.");
    return;
  }
  console.log(`  Token ID        : ${tokenId}`);

  // 3. Find the original tx hash by scanning AgentCreated logs
  const logs = await provider.getLogs({
    address:   identityAddr,
    topics:    [AGENT_CREATED_TOPIC],
    fromBlock: 0,
    toBlock:   "latest",
  });
  const matchLog = logs.find(
    (l) => l.topics[1] && Number(BigInt(l.topics[1])) === tokenId
  );
  if (!matchLog) {
    console.log(`  ✗ No AgentCreated log for tokenId ${tokenId} — cannot find original tx.`);
    return;
  }
  const txHash = matchLog.transactionHash;
  console.log(`  Original tx     : ${txHash.slice(0, 20)}...`);

  // 4. Confirm in backend
  console.log("  → POST /api/v1/agents/confirm (recovery) ...");
  await backendPost("/api/v1/agents/confirm", {
    registration_id: registrationId,
    tx_hash:         txHash,
    token_id:        tokenId,
  });
  console.log("  Backend marked ACTIVE (recovered).");

  // 5. Stake
  const stakeEth = Number.parseFloat(STAKE_ETH);
  console.log(`  → Staking ${stakeEth} ETH via StakingContract (recovery) ...`);
  const stakeTx = await owner.sendTransaction({
    to:       stakingAddr,
    value:    ethers.parseEther(String(stakeEth)),
    data:     "0x3a4b66f1",   // keccak256("stake()")[0:4]
    gasLimit: BigInt(200_000),
  });
  console.log(`  Stake tx        : ${stakeTx.hash.slice(0, 20)}...`);
  await waitReceipt(provider, stakeTx.hash);
  console.log(`  Staked ${stakeEth} ETH — judge recovered and live.`);
}

// ── Register one judge ────────────────────────────────────────────────────────
async function registerJudge(info, owner, provider, identityAddr, stakingAddr) {
  console.log(`\n── ${info.name} ${"─".repeat(40 - info.name.length)}`);

  // ── Step 1: POST /api/v1/agents/register ──────────────────────────────────
  const payload = {
    agent_id:        info.agent_id,
    name:            info.name,
    description:     info.description,
    agent_type:      "judge",
    version:         "1.0.0",
    docker_image:    info.docker_image,
    llm_model:       "llama-3.3-70b-versatile",
    framework:       "groq_raw",
    language:        "python",
    supported_tasks: ["validate", "score", "evaluate"],
    env_var_keys:    info.env_var_keys,
    special_caps:    info.special_caps,
    owner_address:   owner.address,
    price_per_task:  0.0,
    stake_amount:    Number.parseFloat(STAKE_ETH),
    cpu_limit:       1,
    ram_limit_mb:    512,
    timeout_sec:     60,
    services: [{
      name:     "run",
      endpoint: "/run",
      version:  "1.0.0",
      skills:   ["evaluation", "trace-analysis"],
    }],
  };

  console.log("  → POST /api/v1/agents/register ...");
  let reg;
  try {
    reg = await backendPost("/api/v1/agents/register", payload);
  } catch (e) {
    if (e.message.includes("deja utilise")) {
      // Agent is in DB (probably pending_signature from a failed previous run)
      await recoverPendingAgent(info, owner, provider, identityAddr, stakingAddr);
      return;
    }
    throw e;
  }

  console.log(`  IPFS CID        : ${reg.ipfs_cid}`);
  console.log(`  registration_id : ${reg.registration_id}`);

  if (!reg.unsigned_tx?.data) {
    throw new Error("Backend did not return unsigned_tx.data");
  }

  // ── Step 2: Owner wallet signs IdentityRegistry.register() ────────────────
  console.log("  → Signing IdentityRegistry.register() ...");
  const identityTx = await owner.sendTransaction({
    to:       reg.unsigned_tx.contract_address,
    data:     reg.unsigned_tx.data,
    gasLimit: BigInt(reg.unsigned_tx.estimated_gas || 800_000),
  });
  console.log(`  Identity tx     : ${identityTx.hash.slice(0, 20)}...`);

  // ── Step 3: Wait for receipt + parse tokenId ───────────────────────────────
  const receipt = await waitReceipt(provider, identityTx.hash);
  const tokenId = parseTokenId(receipt, reg.unsigned_tx.contract_address);
  console.log(`  Token ID        : ${tokenId ?? "(not parsed)"}`);
  console.log("  Identity confirmed on-chain.");

  // ── Step 4: POST /api/v1/agents/confirm ────────────────────────────────────
  console.log("  → POST /api/v1/agents/confirm ...");
  await backendPost("/api/v1/agents/confirm", {
    registration_id: reg.registration_id,
    tx_hash:         identityTx.hash,
    ...(tokenId != null && { token_id: tokenId }),
  });
  console.log("  Backend marked ACTIVE.");

  // ── Step 5: Owner wallet stakes ─────────────────────────────────────────────
  const stakeEth  = reg.stake_amount_eth ?? Number.parseFloat(STAKE_ETH);
  const stakeAddr = reg.stake_contract ?? stakingAddr;

  if (!stakeAddr || stakeEth <= 0) {
    console.log("  ⚠ No stake contract — skipping stake.");
    return;
  }

  console.log(`  → Staking ${stakeEth} ETH via StakingContract ...`);
  const stakeTx = await owner.sendTransaction({
    to:       stakeAddr,
    value:    ethers.parseEther(String(stakeEth)),
    data:     "0x3a4b66f1",   // keccak256("stake()")[0:4]
    gasLimit: BigInt(200_000),
  });
  console.log(`  Stake tx        : ${stakeTx.hash.slice(0, 20)}...`);
  await waitReceipt(provider, stakeTx.hash);
  console.log(`  Staked ${stakeEth} ETH — judge is live.`);
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  if (!fs.existsSync(deploymentPath)) {
    throw new Error("deployment.json not found — run setup_complete.js first");
  }
  const deployment  = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const identityAddr = deployment.contracts.IdentityRegistry.address;
  const stakingAddr  = deployment.contracts.StakingContract.address;

  const provider = new ethers.JsonRpcProvider(RPC);
  try {
    const block = await provider.getBlockNumber();
    console.log(`Anvil at ${RPC} — block #${block}`);
  } catch {
    throw new Error(`Cannot reach Anvil at ${RPC} — is it running?`);
  }

  const owner = new ethers.Wallet(OWNER_KEY, provider);
  console.log(`Owner           : ${owner.address}`);
  console.log(`IdentityRegistry: ${identityAddr}`);
  console.log(`StakingContract : ${stakingAddr}`);
  console.log(`Backend         : ${BACKEND}\n`);

  const deployerKey = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80";
  const deployer    = new ethers.Wallet(deployerKey, provider);
  await ensureFunded(deployer, owner, 3);

  for (let i = 0; i < 3; i++) {
    await registerJudge(JUDGES[i], owner, provider, identityAddr, stakingAddr);
  }

  console.log("\n3 judge bots registered and staked via the form API.");
}

main().catch((err) => {
  console.error("\nError:", err.message || err);
  process.exitCode = 1;
});
