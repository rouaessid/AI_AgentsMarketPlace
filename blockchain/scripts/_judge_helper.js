/**
 * _judge_helper.js — Shared logic for individual judge registration scripts.
 * Not meant to be run directly — imported by register_judge_*.js scripts.
 *
 * Usage from individual script:
 *   const { runSingleJudge } = require("./_judge_helper");
 *   runSingleJudge(JUDGE).catch(console.error);
 */

const { ethers } = require("ethers");
const http       = require("http");
const fs         = require("fs");
const path       = require("path");

const RPC     = "https://sepolia.base.org";
const BACKEND = "http://localhost:8000";

const AGENT_CREATED_TOPIC = ethers.id("AgentCreated(string,uint256,address,uint8,string,string)");

// ── HTTP helper ───────────────────────────────────────────────────────────────

function backendPost(urlPath, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const opts = {
      hostname: "localhost",
      port:     8000,
      path:     urlPath,
      method:   "POST",
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) },
    };
    const req = http.request(opts, (res) => {
      let raw = "";
      res.on("data", (c) => (raw += c));
      res.on("end",  () => {
        try {
          const parsed = JSON.parse(raw);
          if (res.statusCode >= 400)
            reject(new Error(`HTTP ${res.statusCode}: ${JSON.stringify(parsed.detail || parsed)}`));
          else
            resolve(parsed);
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

// ── Wait for tx ───────────────────────────────────────────────────────────────

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

// ── Recovery ──────────────────────────────────────────────────────────────────

async function recoverPendingAgent(info, wallet, provider, identityAddr, stakingAddr) {
  console.log(`  → ${info.agent_id} already in DB — attempting recovery...`);
  let retryResp;
  try {
    retryResp = await backendPost(`/api/v1/agents/${info.agent_id}/retry-register`, {});
  } catch (e) {
    console.log(`  ✗ retry-register failed: ${e.message}`);
    return;
  }

  const identityContract = new ethers.Contract(identityAddr, [
    "function getCurrentTokenId(string calldata agentId_) external view returns (uint256)",
    "function register(string calldata agentId_, uint8 agentType_, string calldata agentURI_, string calldata version_, uint256 pricePerTask_) external returns (uint256)",
  ], wallet);

  let tokenId;
  try {
    tokenId = Number(BigInt(await identityContract.getCurrentTokenId(info.agent_id)));
  } catch { tokenId = null; }

  if (retryResp.status === "active" && tokenId) {
    console.log(`  ✓ Already active on-chain (tokenId=${tokenId}) — skipping.`);
    return;
  }

  let registrationTxHash = null;
  if (tokenId) {
    const currentBlock = await provider.getBlockNumber();
    const step = 1000;
    let found = null;
    for (let to = currentBlock; to > 0 && !found; to -= step) {
      const from = Math.max(0, to - step + 1);
      try {
        const logs = await provider.getLogs({ address: identityAddr, topics: [AGENT_CREATED_TOPIC], fromBlock: from, toBlock: to });
        found = logs.find((l) => l.topics[1] && Number(BigInt(l.topics[1])) === tokenId);
      } catch { /* continue */ }
    }
    registrationTxHash = found?.transactionHash ?? null;
  } else {
    const regTx = await identityContract.register(
      info.agent_id, 1, retryResp.agent_uri || `ipfs://${info.agent_id}`, "1.0.0", BigInt(0), { gasLimit: BigInt(800_000) }
    );
    const regReceipt = await waitReceipt(provider, regTx.hash);
    tokenId = parseTokenId(regReceipt, identityAddr) ?? null;
    registrationTxHash = regTx.hash;
  }

  // Stake avant confirm (même ordre que l'enregistrement normal)
  const stakeTx = await wallet.sendTransaction({
    to: stakingAddr, value: ethers.parseEther("0.001"), data: "0x3a4b66f1", gasLimit: BigInt(200_000),
  });
  await waitReceipt(provider, stakeTx.hash);
  console.log("  ✓ Staked (recovery)");

  if (registrationTxHash) {
    await backendPost("/api/v1/agents/confirm", {
      registration_id: retryResp.registration_id,
      tx_hash:         registrationTxHash,
      ...(tokenId != null && { token_id: tokenId }),
    });
    console.log(`  ✓ Confirmed — ${info.agent_id} recovered.`);
  }
}

// ── Register one judge ────────────────────────────────────────────────────────

async function registerJudge(info, provider, identityAddr, stakingAddr) {
  const wallet = new ethers.Wallet(info.private_key, provider);
  console.log(`\n── ${info.name} ${"─".repeat(Math.max(0, 40 - info.name.length))}`);
  console.log(`   wallet : ${wallet.address}`);

  const balance = await provider.getBalance(wallet.address);
  console.log(`   balance: ${ethers.formatEther(balance)} ETH`);
  if (balance < ethers.parseEther("0.002"))
    throw new Error(`Insufficient ETH: ${ethers.formatEther(balance)} — need at least 0.002 ETH`);

  const payload = {
    ...info,
    agent_type:     "judge",
    owner_address:  wallet.address,
    version:        "1.0.0",
    llm_model:      "llama-3.3-70b-versatile",
    framework:      "groq_raw",
    language:       "python",
    price_per_task: 0.0,
    stake_amount:   0.001,
    cpu_limit:      1,
    ram_limit_mb:   512,
    timeout_sec:    60,
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
    to: reg.unsigned_tx.contract_address, data: reg.unsigned_tx.data,
    gasLimit: BigInt(reg.unsigned_tx.estimated_gas || 800_000),
  });
  const receipt = await waitReceipt(provider, identityTx.hash);
  const tokenId = parseTokenId(receipt, reg.unsigned_tx.contract_address);
  console.log(`  Token ID        : ${tokenId ?? "(not parsed)"}`);

  // Stake AVANT le confirm — juge financièrement engagé avant honeypot
  const stakeAddr = reg.stake_contract ?? stakingAddr;
  console.log("  → Staking 0.001 ETH (avant honeypot) ...");
  const stakeTx = await wallet.sendTransaction({
    to: stakeAddr, value: ethers.parseEther("0.001"), data: "0x3a4b66f1", gasLimit: BigInt(200_000),
  });
  await waitReceipt(provider, stakeTx.hash);
  console.log("  ✓ Staked");

  // POST /confirm — honeypot onboarding lancé en background par le backend (async)
  console.log("  → POST /api/v1/agents/confirm  [honeypot onboarding en background] ...");
  await backendPost("/api/v1/agents/confirm", {
    registration_id: reg.registration_id,
    tx_hash:         identityTx.hash,
    ...(tokenId != null && { token_id: tokenId }),
  });
  console.log(`  ✓ ${info.name} is live and authorized.`);
}

// ── Entry point ───────────────────────────────────────────────────────────────

async function runSingleJudge(judgeInfo) {
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  if (!fs.existsSync(deploymentPath))
    throw new Error("deployment.json not found — run deploy-all.js first");

  const deployment  = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const identityAddr = deployment.contracts.IdentityRegistry.address;
  const stakingAddr  = deployment.contracts.StakingContract.address;

  const provider = new ethers.JsonRpcProvider(RPC);
  const block    = await provider.getBlockNumber();
  console.log(`Base Sepolia block #${block}`);
  console.log(`IdentityRegistry : ${identityAddr}`);
  console.log(`StakingContract  : ${stakingAddr}`);
  console.log(`Backend          : ${BACKEND}\n`);

  await registerJudge(judgeInfo, provider, identityAddr, stakingAddr);
  console.log(`\nDone — ${judgeInfo.agent_id} registered.`);
}

module.exports = { runSingleJudge };
