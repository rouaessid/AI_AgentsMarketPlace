/**
 * register_agents_robust.js
 * 
 * Registers analyst-01 and writer-01 using the advanced "Researcher" logic:
 *   - POST /register -> Sign -> POST /confirm -> Stake
 *   - Includes automatic RECOVERY logic for stuck/partial registrations.
 */

const { ethers } = require("ethers");
const http = require("http");
const fs   = require("fs");
const path = require("path");

// ── Config ────────────────────────────────────────────────────────────────────
const RPC     = "https://sepolia.base.org";
const BACKEND = "http://localhost:8000";

const AGENTS = [
  {
    owner_key:       "0x73046f80d52c282333a73c9ebe50d2e5dea51d05122b68b5ab9e9ce1cfccefbf", // Account #1
    stake_eth:       "0.001",
    agent_id:        "analyst-01",
    name:            "AnalystBot",
    description:     "Structured analysis and summarization agent. Takes raw text, research output, or JSON data and produces a concise, structured analysis with key insights, risks, opportunities, and a clear verdict.",
    agent_type:      "provider",
    version:         "1.0.0",
    docker_image:    "agentmarket/analyst:v1",
    llm_model:       "llama-3.3-70b-versatile",
    framework:       "groq_raw",
    language:        "python",
    supported_tasks: ["summarize", "analyze", "extract-insights", "risk-assessment", "compare", "evaluate"],
    env_var_keys:    ["GROQ_API_KEY"],
    special_caps:    ["structured-output", "chain-of-thought", "multi-format-input", "json-synthesis"],
    price_per_task:  0.00008,
    stake_amount:    0.001,
    cpu_limit:       1,
    ram_limit_mb:    256,
    timeout_sec:     60,
    services: [
      {
        name:     "run",
        endpoint: "/run",
        version:  "1.0.0",
        skills:   ["summarize", "analyze", "extract-insights", "risk-assessment", "compare"],
        domains:  ["finance", "technology", "market-research", "competitive-intelligence", "science"],
      }
    ],
  },
  {
    owner_key:       "0x73046f80d52c282333a73c9ebe50d2e5dea51d05122b68b5ab9e9ce1cfccefbf", // Account #1
    stake_eth:       "0.001",
    agent_id:        "writer-01",
    name:            "WriterBot",
    description:     "Content generation agent. Takes analysis output, bullet points, or research findings and produces polished structured written content: reports, summaries, articles, or documentation.",
    agent_type:      "provider",
    version:         "1.0.0",
    docker_image:    "agentmarket/writer:v1",
    llm_model:       "llama-3.3-70b-versatile",
    framework:       "groq_raw",
    language:        "python",
    supported_tasks: ["write", "draft", "report", "generate", "summarize", "document"],
    env_var_keys:    ["GROQ_API_KEY"],
    special_caps:    ["structured-output", "long-form-content", "multi-format-output", "chain-of-thought"],
    price_per_task:  0.00006,
    stake_amount:    0.001,
    cpu_limit:       1,
    ram_limit_mb:    256,
    timeout_sec:     60,
    services: [
      {
        name:     "run",
        endpoint: "/run",
        version:  "1.0.0",
        skills:   ["write", "draft", "report", "generate", "summarize"],
        domains:  ["finance", "technology", "market-research", "science", "business"],
      }
    ],
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

async function recoverPendingAgent(info, owner, provider, identityAddr, stakingAddr) {
  console.log(`  → Agent ${info.agent_id} already registered — checking status...`);

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
    console.log("  ✗ Agent not found on-chain.");
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

  const stakeEth = Number.parseFloat(info.stake_eth);
  console.log(`  → Staking ${stakeEth} ETH (recovery) ...`);
  const stakeTx = await owner.sendTransaction({
    to:       stakingAddr,
    value:    ethers.parseEther(String(stakeEth)),
    data:     "0x3a4b66f1",
    gasLimit: BigInt(200_000),
  });
  await waitReceipt(provider, stakeTx.hash);
  console.log(`  Staked — ${info.agent_id} recovered.`);
}

async function registerAgent(info, owner, provider, identityAddr, stakingAddr) {
  console.log(`\n── ${info.name} ${"─".repeat(40 - info.name.length)}`);
  
  const payload = { ...info, owner_address: owner.address };
  delete payload.owner_key;
  delete payload.stake_eth;

  console.log("  → POST /api/v1/agents/register ...");
  let reg;
  try {
    reg = await backendPost("/api/v1/agents/register", payload);
  } catch (e) {
    if (e.message.includes("deja utilise")) {
      await recoverPendingAgent(info, owner, provider, identityAddr, stakingAddr);
      return;
    }
    throw e;
  }

  console.log(`  registration_id : ${reg.registration_id}`);

  console.log("  → Signing IdentityRegistry.register() ...");
  const identityTx = await owner.sendTransaction({
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

  const stakeEth  = reg.stake_amount_eth ?? Number.parseFloat(info.stake_eth);
  const stakeAddr = reg.stake_contract   ?? stakingAddr;
  console.log(`  → Staking ${stakeEth} ETH ...`);
  const stakeTx = await owner.sendTransaction({
    to:       stakeAddr,
    value:    ethers.parseEther(String(stakeEth)),
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
  
  for (const info of AGENTS) {
    const owner = new ethers.Wallet(info.owner_key, provider);
    // Fund owner if needed (local dev)
    const bal = await provider.getBalance(owner.address);
    if (bal < ethers.parseEther("0.01")) {
        const [deployer] = await ethers.getSigners?.() ?? [];
        if (deployer) await deployer.sendTransaction({ to: owner.address, value: ethers.parseEther("0.1") });
    }
    await registerAgent(info, owner, provider, identityAddr, stakingAddr);
  }
}

main().catch(console.error);
