// scripts/deploy_EscrowManager.js
const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const [deployer] = await ethers.getSigners();

  console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("  Deploying EscrowManager");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log(`Deployer : ${deployer.address}`);

  const JUDGE_FEE_PERCENTAGE = 10; // 10%

  const Factory = await ethers.getContractFactory("EscrowManager");
  const escrow = await Factory.deploy(JUDGE_FEE_PERCENTAGE);
  await escrow.waitForDeployment();

  const escrowAddress = await escrow.getAddress();
  console.log(`✓ EscrowManager : ${escrowAddress}`);

  // Sauvegarder dans deployment.json
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  let deployment = {};
  if (fs.existsSync(deploymentPath)) {
    deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  }

  deployment.contracts.EscrowManager = {
    address: escrowAddress,
    judgeFeePercentage: JUDGE_FEE_PERCENTAGE,
    deployedAt: new Date().toISOString(),
  };

  fs.writeFileSync(deploymentPath, JSON.stringify(deployment, null, 2));
  console.log(`✓ deployment.json mis à jour`);

  // Sauvegarder ABI
  const abiSrc = path.join(
    __dirname,
    "../artifacts/contracts/EscrowManager.sol/EscrowManager.json"
  );
  if (fs.existsSync(abiSrc)) {
    const { abi } = JSON.parse(fs.readFileSync(abiSrc, "utf8"));
    const abiDest = path.join(__dirname, "../deployments/EscrowManager.abi.json");
    fs.writeFileSync(abiDest, JSON.stringify(abi, null, 2));
    console.log("✓ ABI saved → deployments/EscrowManager.abi.json");
  }

  console.log("\nProchaines étapes :");
  console.log(`1. Mettre à jour ValidationRegistry : await validationRegistry.setEscrowManager("${escrowAddress}")`);
  console.log(`2. Mettre à jour EscrowManager : await escrowManager.setValidationRegistry(<VALIDATION_REGISTRY_ADDRESS>)`);
}

main().catch(e => { console.error(e); process.exit(1); });
