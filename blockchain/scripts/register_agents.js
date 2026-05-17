/**
 * register_agents.js
 *
 * Registers analyst-01 and writer-01 via the backend API flow:
 *   1. POST /api/v1/agents/register  → IPFS upload + DB entry + unsigned tx
 *   2. Owner signs IdentityRegistry.register()
 *   3. POST /api/v1/agents/confirm   → marks agent ACTIVE
 *   4. Owner signs StakingContract.stake()
 *
 * Owners:
 *   analyst-01 → Hardhat account #1  0x70997970C51812dc3A010C7d01b50e0d17dc79C8
 *   writer-01  → Hardhat account #2  0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC
 *
 * Run:
 *   node scripts/register_agents.js
 */

const { ethers } = require("ethers");
const http = require("http");
const fs   = require("fs");
const path = require("path");

// ── Config ────────────────────────────────────────────────────────────────────
const RPC     = "http://127.0.0.1:8545";
const BACKEND = "http://localhost:8000";

const AGENTS = [
  {
    owner_key:       "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
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
      },
      {
        name:     "sandbox",
        endpoint: "/sandbox",
        version:  "1.0.0",
        skills:   ["summarize", "analyze"],
      },
    ],
  },
  {
    owner_key:       "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
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
      },
      {
        name:     "sandbox",
        endpoint: "/sandbox",
        version:  "1.0.0",
        skills:   ["write", "draft"],
      },
    ],
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

const AGENT_CREATED_TOPIC = ethers.id("AgentCreated(string,uint256,address,uint8,string,string)");

function parseTokenId(receipt, contractAddress) {
  const log = receipt.logs.find(
    (l) => l.address.toLowerCase() === contractAddress.toLowerCase()
        && l.topics[0] === AGENT_CREATED_TOPIC
  );
  if (!log || !log.topics[1]) return null;
  return Number(BigInt(log.topics[1]));
}

// ── Register one agent ────────────────────────────────────────────────────────
async function registerAgent(info, provider, identityAddr, stakingAddr) {
  const owner = new ethers.Wallet(info.owner_key, provider);
  console.log(`\n── ${info.name} ${"─".repeat(40 - info.name.length)}`);
  console.log(`  Owner   : ${owner.address}`);
  console.log(`  AgentId : ${info.agent_id}`);

  // Fund if needed
  const required = ethers.parseEther(info.stake_eth) + ethers.parseEther("0.002");
  const balance  = await provider.getBalance(owner.address);
  if (balance < required) {
    const [deployer] = await ethers.getSigners?.() ?? [];
    if (deployer) {
      const fundTx = await deployer.sendTransaction({ to: owner.address, value: required - balance });
      await fundTx.wait();
      console.log(`  Funded  : ${ethers.formatEther(required - balance)} ETH`);
    }
  }

  // Step 1: POST /register
  const payload = {
    agent_id: info.agent_id, name: info.name, description: info.description,
    agent_type: info.agent_type, version: info.version, docker_image: info.docker_image,
    llm_model: info.llm_model, framework: info.framework, language: info.language,
    supported_tasks: info.supported_tasks, env_var_keys: info.env_var_keys,
    special_caps: info.special_caps, owner_address: owner.address,
    price_per_task: info.price_per_task, stake_amount: info.stake_amount,
    cpu_limit: info.cpu_limit, ram_limit_mb: info.ram_limit_mb,
    timeout_sec: info.timeout_sec, services: info.services,
  };

  console.log("  → POST /api/v1/agents/register ...");
  let reg;
  try {
    reg = await backendPost("/api/v1/agents/register", payload);
  } catch (e) {
    if (e.message.includes("deja utilise") || e.message.includes("already")) {
      console.log(`  Already registered — skipping ${info.agent_id}`);
      return;
    }
    throw e;
  }

  console.log(`  IPFS CID        : ${reg.ipfs_cid}`);
  console.log(`  registration_id : ${reg.registration_id}`);

  if (!reg.unsigned_tx?.data) throw new Error("Backend did not return unsigned_tx.data");

  // Step 2: Sign IdentityRegistry.register()
  console.log("  → Signing IdentityRegistry.register() ...");
  const identityTx = await owner.sendTransaction({
    to:       reg.unsigned_tx.contract_address,
    data:     reg.unsigned_tx.data,
    gasLimit: BigInt(reg.unsigned_tx.estimated_gas || 800_000),
  });
  console.log(`  Identity tx     : ${identityTx.hash.slice(0, 20)}...`);

  const receipt = await waitReceipt(provider, identityTx.hash);
  const tokenId = parseTokenId(receipt, reg.unsigned_tx.contract_address);
  console.log(`  Token ID        : ${tokenId ?? "(not parsed)"}`);

  // Step 3: POST /confirm
  console.log("  → POST /api/v1/agents/confirm ...");
  await backendPost("/api/v1/agents/confirm", {
    registration_id: reg.registration_id,
    tx_hash:         identityTx.hash,
    ...(tokenId != null && { token_id: tokenId }),
  });
  console.log("  Backend marked ACTIVE.");

  // Step 4: Stake
  const stakeEth  = reg.stake_amount_eth ?? Number.parseFloat(info.stake_eth);
  const stakeAddr = reg.stake_contract   ?? stakingAddr;
  console.log(`  → Staking ${stakeEth} ETH ...`);
  const stakeTx = await owner.sendTransaction({
    to:       stakeAddr,
    value:    ethers.parseEther(String(stakeEth)),
    data:     "0x3a4b66f1",
    gasLimit: BigInt(200_000),
  });
  console.log(`  Stake tx        : ${stakeTx.hash.slice(0, 20)}...`);
  await waitReceipt(provider, stakeTx.hash);
  console.log(`  Staked — ${info.agent_id} is live.`);
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  if (!fs.existsSync(deploymentPath)) {
    throw new Error("deployment.json not found — run setup_complete.js first");
  }
  const deployment   = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const identityAddr = deployment.contracts.IdentityRegistry.address;
  const stakingAddr  = deployment.contracts.StakingContract.address;

  const provider = new ethers.JsonRpcProvider(RPC);
  const block = await provider.getBlockNumber();
  console.log(`Anvil at ${RPC} — block #${block}`);
  console.log(`IdentityRegistry: ${identityAddr}`);
  console.log(`StakingContract : ${stakingAddr}`);
  console.log(`Backend         : ${BACKEND}\n`);

  for (const agent of AGENTS) {
    await registerAgent(agent, provider, identityAddr, stakingAddr);
  }

  console.log("\nanalyst-01 and writer-01 registered and staked.");
}

main().catch((err) => {
  console.error("\nError:", err.message || err);
  process.exitCode = 1;
});
