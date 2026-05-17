// scripts/upgrade_contracts.js
// ─────────────────────────────────────────────────────────────────────────────
// Redéploie UNIQUEMENT EscrowManager + ValidationRegistry (versions pipeline).
// IdentityRegistry, StakingContract, ReputationRegistry → intacts.
// Agents déjà enregistrés → non touchés.
//
// Usage :
//   npx hardhat run scripts/upgrade_contracts.js --network localhost
//
// Ce script :
//   1. Redéploie EscrowManager   (+ depositPaymentPipeline + releaseFundsPipeline)
//   2. Redéploie ValidationRegistry (+ recordPipelineScores + routing pipeline escrow)
//   3. Reconfigure les liens entre contrats
//   4. Met à jour deployment.json + affiche les variables .env à copier
// ─────────────────────────────────────────────────────────────────────────────

const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

const JUDGE_FEE_PERCENTAGE = 10; // 10% inchangé

async function main() {
  const [deployer] = await ethers.getSigners();

  console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("  Upgrade : EscrowManager + ValidationRegistry");
  console.log("  (IdentityRegistry, StakingContract → inchangés)");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log(`Deployer : ${deployer.address}`);

  // ── 1. Lire deployment.json existant ────────────────────────────────────────
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  if (!fs.existsSync(deploymentPath)) {
    throw new Error("deployment.json introuvable — lancez d'abord setup_complete.js");
  }
  const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));

  const identityAddress    = deployment.contracts.IdentityRegistry?.address;
  const stakingAddress     = deployment.contracts.StakingContract?.address;
  const reputationAddress  = deployment.contracts.ReputationRegistry?.address;

  if (!identityAddress) throw new Error("IdentityRegistry non trouvé dans deployment.json");
  if (!stakingAddress)  throw new Error("StakingContract non trouvé dans deployment.json");

  console.log(`\nContrats existants (conservés) :`);
  console.log(`  IdentityRegistry   : ${identityAddress}`);
  console.log(`  StakingContract    : ${stakingAddress}`);
  console.log(`  ReputationRegistry : ${reputationAddress || "(absent)"}`);

  const repAddr = reputationAddress ?? deployer.address;

  // ── 2. Redéployer EscrowManager ──────────────────────────────────────────────
  console.log("\n[1/2] Déploiement EscrowManager (pipeline)...");
  const EscrowFactory = await ethers.getContractFactory("EscrowManager");
  const escrow = await EscrowFactory.deploy(JUDGE_FEE_PERCENTAGE);
  await escrow.waitForDeployment();
  const escrowAddress = await escrow.getAddress();
  console.log(`  ✓ EscrowManager : ${escrowAddress}`);

  // ── 3. Redéployer ValidationRegistry ─────────────────────────────────────────
  console.log("\n[2/2] Déploiement ValidationRegistry (pipeline)...");
  const ValidationFactory = await ethers.getContractFactory("ValidationRegistry");
  const validation = await ValidationFactory.deploy(
    identityAddress,
    stakingAddress,
    repAddr
  );
  await validation.waitForDeployment();
  const validationAddress = await validation.getAddress();
  console.log(`  ✓ ValidationRegistry : ${validationAddress}`);

  // ── 4. Wiring ────────────────────────────────────────────────────────────────
  console.log("\nConfiguration des liens...");

  // StakingContract → nouveau ValidationRegistry
  const StakingFactory = await ethers.getContractFactory("StakingContract");
  const staking = StakingFactory.attach(stakingAddress);
  const tx1 = await staking.setValidationRegistry(validationAddress);
  await tx1.wait();
  console.log(`  ✓ StakingContract.setValidationRegistry(${validationAddress.slice(0, 10)}...)`);

  // ValidationRegistry → nouveau EscrowManager
  const tx2 = await validation.setEscrowManager(escrowAddress);
  await tx2.wait();
  console.log(`  ✓ ValidationRegistry.setEscrowManager(${escrowAddress.slice(0, 10)}...)`);

  // EscrowManager → IdentityRegistry (pour vérif prix)
  const tx3 = await escrow.setIdentityRegistry(identityAddress);
  await tx3.wait();
  console.log(`  ✓ EscrowManager.setIdentityRegistry(${identityAddress.slice(0, 10)}...)`);

  // EscrowManager → nouveau ValidationRegistry
  const tx4 = await escrow.setValidationRegistry(validationAddress);
  await tx4.wait();
  console.log(`  ✓ EscrowManager.setValidationRegistry(${validationAddress.slice(0, 10)}...)`);

  // ReputationRegistry → autoriser le nouveau ValidationRegistry (si disponible)
  if (reputationAddress) {
    try {
      const RepAbi = ["function setAuthorisedCaller(address,bool) external"];
      const rep = new ethers.Contract(reputationAddress, RepAbi, deployer);
      const tx5 = await rep.setAuthorisedCaller(validationAddress, true);
      await tx5.wait();
      console.log(`  ✓ ReputationRegistry.setAuthorisedCaller(${validationAddress.slice(0, 10)}..., true)`);
    } catch (e) {
      console.log(`  ⚠ ReputationRegistry non modifiable (${e.message.slice(0, 60)}) — ignoré`);
    }
  }

  // ── 5. Mettre à jour deployment.json ─────────────────────────────────────────
  deployment.contracts.EscrowManager = {
    address: escrowAddress,
    judgeFeePercentage: JUDGE_FEE_PERCENTAGE,
    deployedAt: new Date().toISOString(),
  };
  deployment.contracts.ValidationRegistry = {
    address: validationAddress,
    identityRegistry: identityAddress,
    stakingContract: stakingAddress,
    reputationRegistry: repAddr,
    escrowManager: escrowAddress,
    deployedAt: new Date().toISOString(),
  };
  fs.writeFileSync(deploymentPath, JSON.stringify(deployment, null, 2));
  console.log(`\n  ✓ deployment.json mis à jour`);

  // ── 6. Sauvegarder ABIs ──────────────────────────────────────────────────────
  for (const [name, addr] of [["EscrowManager", escrowAddress], ["ValidationRegistry", validationAddress]]) {
    const abiSrc = path.join(__dirname, `../artifacts/contracts/${name}.sol/${name}.json`);
    if (fs.existsSync(abiSrc)) {
      const { abi } = JSON.parse(fs.readFileSync(abiSrc, "utf8"));
      const abiDest = path.join(__dirname, `../deployments/${name}.abi.json`);
      fs.writeFileSync(abiDest, JSON.stringify(abi, null, 2));
      console.log(`  ✓ ABI saved → deployments/${name}.abi.json`);
    }
  }

  // ── 7. Résumé .env ───────────────────────────────────────────────────────────
  console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("→ Mettre à jour .env :");
  console.log(`  VALIDATION_REGISTRY_ADDRESS=${validationAddress}`);
  console.log(`  ESCROW_MANAGER_ADDRESS=${escrowAddress}`);
  console.log("\n→ Agents déjà enregistrés dans IdentityRegistry : inchangés ✓");
  console.log("→ Redémarrer le backend FastAPI après mise à jour .env");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
}

main().catch(e => { console.error(e); process.exitCode = 1; });
