/**
 * authorize_judges.js
 *
 * Appelle recordHoneypotResult(judgeId, true) sur le nouveau ValidationRegistry
 * pour chaque juge déjà enregistré dans IdentityRegistry.
 *
 * Usage:
 *   node scripts/authorize_judges.js
 */

const { ethers } = require("ethers");
const fs   = require("fs");
const path = require("path");

const RPC          = "https://sepolia.base.org";
const DEPLOYER_KEY = "0x6bc645f3983d44a688afdd157ca051b373977e2d45a9900042f226889717d2a8";

const JUDGE_IDS = [
  "judge-alpha",
  "judge-beta",
  "judge-gamma",
  "judge-delta",
  "judge-epsilon",
];

const VALIDATION_ABI = [
  {
    "inputs": [
      { "name": "judgeId_",   "type": "string" },
      { "name": "passed_",    "type": "bool"   },
      { "name": "resultCID_", "type": "string" }
    ],
    "name": "recordHoneypotResult",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "inputs": [{ "name": "judgeId", "type": "string" }],
    "name": "judgeAuthorized",
    "outputs": [{ "name": "", "type": "bool" }],
    "stateMutability": "view",
    "type": "function"
  }
];

async function main() {
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  const deployment     = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const validationAddr = deployment.contracts.ValidationRegistry.address;

  console.log("ValidationRegistry :", validationAddr);
  console.log("");

  const provider   = new ethers.JsonRpcProvider(RPC);
  const deployer   = new ethers.Wallet(DEPLOYER_KEY, provider);
  const registry   = new ethers.Contract(validationAddr, VALIDATION_ABI, deployer);

  for (const judgeId of JUDGE_IDS) {
    const already = await registry.judgeAuthorized(judgeId);
    if (already) {
      console.log(`✓ ${judgeId} already authorized — skip`);
      continue;
    }

    console.log(`→ Authorizing ${judgeId}...`);
    const tx = await registry.recordHoneypotResult(judgeId, true, "auto-authorized");
    await tx.wait();
    console.log(`✓ ${judgeId} authorized (tx: ${tx.hash.slice(0, 20)}...)`);
  }

  console.log("\n✅ All judges authorized in new ValidationRegistry.");
}

main().catch(console.error);
