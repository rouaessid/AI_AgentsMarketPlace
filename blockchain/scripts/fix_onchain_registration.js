/**
 * fix_onchain_registration.js
 *
 * Registers agents directly in IdentityRegistry on-chain,
 * without going through the backend API.
 *
 * Use when agents are already in the backend DB (frontend shows them)
 * but check_agents.js reports exists=false for all of them.
 *
 * Run:
 *   npx hardhat run scripts/fix_onchain_registration.js --network localhost
 */

const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

// ── Agents to register ────────────────────────────────────────────────────────
// type: 0 = PROVIDER, 1 = JUDGE
// price: in ETH (converted to wei below)
const AGENTS = [
  { id: "researcher-01", type: 0, priceEth: "0.001" },
  { id: "analyst-01",    type: 0, priceEth: "0.00008" },
  { id: "writer-01",     type: 0, priceEth: "0.00006" },
  { id: "judge-alpha",   type: 1, priceEth: "0"     },
  { id: "judge-beta",    type: 1, priceEth: "0"     },
  { id: "judge-gamma",   type: 1, priceEth: "0"     },
  { id: "judge-delta",   type: 1, priceEth: "0"     },
  { id: "judge-epsilon", type: 1, priceEth: "0"     },
];

// ── Minimal ABI ───────────────────────────────────────────────────────────────
const IDENTITY_ABI = [
  {
    inputs: [
      { name: "agentId_",      type: "string"  },
      { name: "agentType_",    type: "uint8"   },
      { name: "agentURI_",     type: "string"  },
      { name: "version_",      type: "string"  },
      { name: "pricePerTask_", type: "uint256" },
    ],
    name: "register",
    outputs: [{ name: "tokenId", type: "uint256" }],
    stateMutability: "nonpayable",
    type: "function",
  },
  {
    inputs: [{ name: "agentId_", type: "string" }],
    name: "isActive",
    outputs: [{ name: "", type: "bool" }],
    stateMutability: "view",
    type: "function",
  },
  {
    inputs: [{ name: "agentId_", type: "string" }],
    name: "agentIdExists",
    outputs: [{ name: "", type: "bool" }],
    stateMutability: "view",
    type: "function",
  },
  {
    inputs: [{ name: "agentId_", type: "string" }],
    name: "getPricePerTask",
    outputs: [{ name: "", type: "uint256" }],
    stateMutability: "view",
    type: "function",
  },
];

// ── Main ──────────────────────────────────────────────────────────────────────

async function main() {
  const [deployer] = await ethers.getSigners();

  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  if (!fs.existsSync(deploymentPath)) {
    throw new Error("deployment.json not found — run setup_complete.js first");
  }
  const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const identityAddr = deployment.contracts.IdentityRegistry.address;

  console.log(`\nDeployer        : ${deployer.address}`);
  console.log(`IdentityRegistry: ${identityAddr}`);
  console.log(`\nChecking and registering ${AGENTS.length} agents...\n`);

  const identity = new ethers.Contract(identityAddr, IDENTITY_ABI, deployer);

  let registered = 0;
  let skipped    = 0;

  for (const agent of AGENTS) {
    const exists = await identity.agentIdExists(agent.id);
    if (exists) {
      const price = await identity.getPricePerTask(agent.id);
      console.log(
        `  ✓ ${agent.id.padEnd(16)} already on-chain` +
        ` (price=${ethers.formatEther(price)} ETH)`
      );
      skipped++;
      continue;
    }

    const priceWei = ethers.parseEther(agent.priceEth);
    const typeName = agent.type === 0 ? "PROVIDER" : "JUDGE";
    const uri      = `ipfs://agentmarket/${agent.id}/v1.0.0`;

    try {
      const tx = await identity.register(
        agent.id,
        agent.type,
        uri,
        "1.0.0",
        priceWei,
      );
      const receipt = await tx.wait();
      console.log(
        `  ✓ ${agent.id.padEnd(16)} registered` +
        ` (${typeName}, price=${agent.priceEth} ETH, tx=${receipt.hash.slice(0, 14)}...)`
      );
      registered++;
    } catch (err) {
      console.error(`  ✗ ${agent.id}: ${err.message}`);
    }
  }

  console.log(`\nDone — ${registered} registered, ${skipped} already existed.`);
  console.log("Run check_agents.js to verify.\n");
}

main().catch(e => { console.error(e); process.exitCode = 1; });
