/**
 * register_researcher.js
 *
 * Registers researcher-01 by mimicking the frontend RegisterAgent form flow:
 *
 *   1. POST /api/v1/agents/register  → IPFS upload + DB entry + unsigned tx
 *   2. Owner wallet signs IdentityRegistry.register()
 *   3. POST /api/v1/agents/confirm   → sets agent ACTIVE in DB
 *   4. Owner wallet signs StakingContract.stake()
 *
 * If the agent is already in pending_signature (partial previous run),
 * the script recovers automatically using retry-register + on-chain lookup.
 *
 * Owner: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 (Hardhat account #0 / deployer)
 *
 * Prerequisites:
 *   - Anvil running on localhost:8545 (contracts deployed)
 *   - Backend running on localhost:8000
 *
 * Run:
 *   node scripts/register_researcher.js
 */

const { ethers } = require("ethers");
const http = require("http");
const fs   = require("fs");
const path = require("path");

// ── Config ────────────────────────────────────────────────────────────────────
const RPC     = "https://sepolia.base.org";
const BACKEND = "http://localhost:8000";

// Hardhat account #0 — deployer — owner of researcher-01
// Address: 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
const OWNER_KEY = "0x7e20a7961bc4789d5b485451ff83a1201295e4951152737c0bfc8c5ba5aaceb3";

const STAKE_ETH = "0.002";

const RESEARCHER = {
  agent_id:        "researcher-01",
  name:            "ResearchBot",
  description:     "Multi-source research agent. Given a topic or question, it plans targeted search queries, aggregates information from the web using Tavily, and synthesizes a structured report with key findings, trends, data points, and sources.",
  agent_type:      "provider",
  version:         "1.0.0",
  docker_image:    "agentmarket/researcher:v1",
  llm_model:       "llama-3.3-70b-versatile",
  framework:       "groq_raw",
  language:        "python",
  supported_tasks: ["research", "report", "market-analysis", "trend-analysis", "competitive-intelligence"],
  env_var_keys:    ["GROQ_API_KEY", "TAVILY_API_KEY"],
  special_caps:    ["multi-query-planning", "web-search", "structured-output", "source-citation", "ipfs-trace-upload"],
  price_per_task:  0.0001,
  stake_amount:    Number.parseFloat(STAKE_ETH),
  cpu_limit:       1,
  ram_limit_mb:    512,
  timeout_sec:     120,
  services: [
    {
      name:     "run",
      endpoint: "/run",
      version:  "1.0.0",
      skills:   ["research", "web-search", "report-generation", "trend-analysis"],
      domains:  ["finance", "technology", "startups", "market-research", "science"],
    },
    {
      name:     "sandbox",
      endpoint: "/sandbox",
      version:  "1.0.0",
      skills:   ["research"],
    },
  ],
};

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
  return Number(BigInt(log.topics[1]));  // topics[1] = tokenId (NOT topics[2] = owner)
}

// ── Minimal ABI for recovery ──────────────────────────────────────────────────
const IDENTITY_ABI_MINIMAL = [
  "function agentIdExists(string calldata agentId_) external view returns (bool)",
  "function register(string calldata agentId_, uint8 agentType_, string calldata agentURI_, string calldata version_, uint256 pricePerTask_) external returns (uint256 tokenId)",
];

// ── Register on-chain directly (bypass backend API) ───────────────────────────
// Used when agent is already ACTIVE in DB but missing from IdentityRegistry.
async function ensureOnchain(info, signer, identityAddr, stakingAddr, provider) {
  const identity = new ethers.Contract(identityAddr, IDENTITY_ABI_MINIMAL, signer);

  const exists = await identity.agentIdExists(info.agent_id);
  if (exists) {
    console.log("  ✓ Already on-chain — nothing to do.");
    return;
  }

  console.log("  → Agent missing on-chain — registering directly in IdentityRegistry...");
  const priceWei = ethers.parseEther(String(info.price_per_task ?? 0));
  const agentType = info.agent_type === "judge" ? 1 : 0;
  const uri = `ipfs://agentmarket/${info.agent_id}/v1.0.0`;

  const tx = await identity.register(info.agent_id, agentType, uri, info.version ?? "1.0.0", priceWei);
  const receipt = await tx.wait();
  console.log(`  ✓ Registered on-chain (tx=${receipt.hash.slice(0, 18)}...)`);

  // Stake if not already staked
  if (stakingAddr && (info.stake_amount ?? 0) > 0) {
    console.log(`  → Staking ${info.stake_amount} ETH ...`);
    const stakeTx = await signer.sendTransaction({
      to:       stakingAddr,
      value:    ethers.parseEther(String(info.stake_amount)),
      data:     "0x3a4b66f1",
      gasLimit: 200_000n,
    });
    await waitReceipt(provider, stakeTx.hash);
    console.log(`  ✓ Staked — ${info.agent_id} fully recovered.`);
  }
}

// ── Register the researcher ───────────────────────────────────────────────────
async function registerResearcher(info, owner, provider, identityAddr, stakingAddr) {
  console.log(`\n── ${info.name} ${"─".repeat(40 - info.name.length)}`);

  // ── Step 1: POST /api/v1/agents/register ──────────────────────────────────
  const payload = {
    agent_id:        info.agent_id,
    name:            info.name,
    description:     info.description,
    agent_type:      info.agent_type,
    version:         info.version,
    docker_image:    info.docker_image,
    llm_model:       info.llm_model,
    framework:       info.framework,
    language:        info.language,
    supported_tasks: info.supported_tasks,
    env_var_keys:    info.env_var_keys,
    special_caps:    info.special_caps,
    owner_address:   owner.address,
    price_per_task:  info.price_per_task,
    stake_amount:    info.stake_amount,
    cpu_limit:       info.cpu_limit,
    ram_limit_mb:    info.ram_limit_mb,
    timeout_sec:     info.timeout_sec,
    services:        info.services,
  };

  console.log("  → POST /api/v1/agents/register ...");
  let reg;
  try {
    reg = await backendPost("/api/v1/agents/register", payload);
  } catch (e) {
    if (e.message.includes("deja utilise") || e.message.includes("already") || e.message.includes("existe")) {
      console.log("  Agent already in DB — checking on-chain state...");
      await ensureOnchain(info, owner, identityAddr, stakingAddr, provider);
      return;
    }
    throw e;
  }

  console.log(`  IPFS CID        : ${reg.ipfs_cid}`);
  console.log(`  registration_id : ${reg.registration_id}`);

  if (!reg.unsigned_tx?.data) {
    throw new Error("Backend did not return unsigned_tx.data");
  }

  // ── Step 2: Owner signs IdentityRegistry.register() ────────────────────
  console.log("  → Signing IdentityRegistry.register() ...");
  const identityTx = await owner.sendTransaction({
    to:       reg.unsigned_tx.contract_address,
    data:     reg.unsigned_tx.data,
    gasLimit: BigInt(reg.unsigned_tx.estimated_gas || 800_000),
  });
  console.log(`  Identity tx     : ${identityTx.hash.slice(0, 20)}...`);

  // ── Step 3: Wait for receipt + parse tokenId ───────────────────────────
  const receipt = await waitReceipt(provider, identityTx.hash);
  const tokenId = parseTokenId(receipt, reg.unsigned_tx.contract_address);
  console.log(`  Token ID        : ${tokenId ?? "(not parsed)"}`);
  console.log("  Identity confirmed on-chain.");

  // ── Step 4: POST /api/v1/agents/confirm ─────────────────────────────────
  console.log("  → POST /api/v1/agents/confirm ...");
  await backendPost("/api/v1/agents/confirm", {
    registration_id: reg.registration_id,
    tx_hash:         identityTx.hash,
    ...(tokenId != null && { token_id: tokenId }),
  });
  console.log("  Backend marked ACTIVE.");

  // ── Step 5: Stake ────────────────────────────────────────────────────────
  const stakeEth  = reg.stake_amount_eth ?? Number.parseFloat(STAKE_ETH);
  const stakeAddr = reg.stake_contract   ?? stakingAddr;

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
  console.log(`  Staked ${stakeEth} ETH — researcher is live.`);
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
  console.log(`Backend         : ${BACKEND}`);

  // Verify balance covers stake + gas
  const balance  = await owner.provider.getBalance(owner.address);
  const required = ethers.parseEther(STAKE_ETH) + ethers.parseEther("0.002");
  if (balance < required) {
    throw new Error(
      `Insufficient balance: have ${ethers.formatEther(balance)} ETH, need at least ${ethers.formatEther(required)} ETH`
    );
  }

  await registerResearcher(RESEARCHER, owner, provider, identityAddr, stakingAddr);

  console.log("\nresearcher-01 registered and staked.");
}

main().catch((err) => {
  console.error("\nError:", err.message || err);
  process.exitCode = 1;
});
