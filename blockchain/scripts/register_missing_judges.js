/**
 * register_missing_judges.js
 *
 * Registers judge-delta and judge-epsilon on-chain with correct agentType=1 (JUDGE).
 * Uses registration_ids already in the backend DB.
 */

const { ethers } = require("ethers");
const http = require("http");
const fs   = require("fs");
const path = require("path");

const RPC     = "https://sepolia.base.org";
const BACKEND = "http://localhost:8000";

// Correct key for 0xbB5385c00F70E29193AB59ca241C705dC607dD66
const JUDGE_PRIVATE_KEY = "0x8900abaabf0051608e714523caeed0edc096e304666123905bc96ff7df51b3c7";

const MISSING_JUDGES = [
  {
    agent_id:        "judge-delta",
    registration_id: "15828ae2-744d-44ec-afcf-db5aa8e2c0b3",
    agent_uri:       "ipfs://QmLOCALfdfae6868d15fc8d1dc5fc596f25d63306169110",
    version:         "1.0.0",
  },
  {
    agent_id:        "judge-epsilon",
    registration_id: "190f4ef0-244d-4214-944e-1fb1d0b5dd10",
    agent_uri:       "ipfs://QmLOCAL7cdea26f9d73a1b669a08d1a5a5d896725aaff5b",
    version:         "1.0.0",
  },
];

const AGENT_CREATED_TOPIC = ethers.id("AgentCreated(string,uint256,address,uint8,string,string)");

// ── ABI for IdentityRegistry.register ────────────────────────────────────────
const IDENTITY_ABI = [
  "function register(string calldata agentId_, uint8 agentType_, string calldata agentURI_, string calldata version_, uint256 pricePerTask_) external returns (uint256)",
];

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
    await new Promise((r) => setTimeout(r, 3000));
    const receipt = await provider.getTransactionReceipt(txHash);
    if (receipt) {
      if (receipt.status === 0) throw new Error(`Transaction reverted: ${txHash}`);
      return receipt;
    }
  }
  throw new Error(`Not confirmed after ${maxAttempts * 3}s: ${txHash}`);
}

function parseTokenId(receipt, contractAddress) {
  const log = receipt.logs.find(
    (l) => l.address.toLowerCase() === contractAddress.toLowerCase()
        && l.topics[0] === AGENT_CREATED_TOPIC
  );
  if (!log || !log.topics[1]) return null;
  return Number(BigInt(log.topics[1]));
}

async function main() {
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const identityAddr = deployment.contracts.IdentityRegistry.address;
  const stakingAddr  = deployment.contracts.StakingContract.address;

  const provider = new ethers.JsonRpcProvider(RPC);
  const wallet   = new ethers.Wallet(JUDGE_PRIVATE_KEY, provider);

  console.log(`Judge wallet: ${wallet.address}`);
  const bal = await provider.getBalance(wallet.address);
  console.log(`Balance: ${ethers.formatEther(bal)} ETH`);

  const identityContract = new ethers.Contract(identityAddr, IDENTITY_ABI, wallet);

  for (const judge of MISSING_JUDGES) {
    console.log(`\n── ${judge.agent_id} ${"─".repeat(40 - judge.agent_id.length)}`);

    // 1. Verify not already on-chain
    const checkAbi = ["function getCurrentTokenId(string calldata agentId_) external view returns (uint256)"];
    const checker  = new ethers.Contract(identityAddr, checkAbi, provider);
    let alreadyOnChain = false;
    try {
      const tid = await checker.getCurrentTokenId(judge.agent_id);
      if (Number(tid) > 0) {
        console.log(`  ✓ Already on-chain (tokenId=${tid}) — skipping registration.`);
        alreadyOnChain = true;
      }
    } catch {
      // not on-chain
    }

    if (!alreadyOnChain) {
      // 2. Call IdentityRegistry.register() with agentType=1 (JUDGE)
      console.log("  → Calling IdentityRegistry.register(agentType=1) ...");
      const tx = await identityContract.register(
        judge.agent_id,
        1,                 // agentType = JUDGE
        judge.agent_uri,
        judge.version,
        BigInt(0),         // pricePerTask = 0
        { gasLimit: BigInt(800_000) }
      );
      console.log(`  tx: ${tx.hash}`);
      const receipt = await waitReceipt(provider, tx.hash);
      const tokenId = parseTokenId(receipt, identityAddr);
      console.log(`  Token ID: ${tokenId ?? "(not parsed)"}`);

      // 3. Confirm with backend
      console.log("  → POST /api/v1/agents/confirm ...");
      await backendPost("/api/v1/agents/confirm", {
        registration_id: judge.registration_id,
        tx_hash:         tx.hash,
        ...(tokenId != null && { token_id: tokenId }),
      });
      console.log("  ✓ Confirmed");
    }

    // 4. Stake 0.001 ETH
    console.log("  → Staking 0.001 ETH ...");
    const stakeTx = await wallet.sendTransaction({
      to:       stakingAddr,
      value:    ethers.parseEther("0.001"),
      data:     "0x3a4b66f1",
      gasLimit: BigInt(200_000),
    });
    await waitReceipt(provider, stakeTx.hash);
    console.log(`  ✓ Staked — ${judge.agent_id} is live.`);
  }

  console.log("\n── Done ──");
}

main().catch(console.error);
