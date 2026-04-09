// scripts/deploy_ValidationRegistry.js
// ─────────────────────────────────────────────────────────────────────────────
// Déploie ValidationRegistry en lisant les adresses de ses siblings depuis
// deployments/deployment.json (IdentityRegistry + StakingContract).
//
// Prérequis :
//   1. IdentityRegistry  déjà déployé  → deployment.json
//   2. StakingContract   déjà déployé  → deployment.json
//   3. ReputationRegistry non nécessaire pour l'instant → adresse zero acceptée
//      (on passera l'adresse réelle plus tard via setReputationRegistry())
//
// Usage :
//   npx hardhat run scripts/deploy_ValidationRegistry.js --network localhost
//   npx hardhat run scripts/deploy_ValidationRegistry.js --network sepolia
//
// Post-déploiement OBLIGATOIRE (fait automatiquement par ce script) :
//   stakingContract.setValidationRegistry(validationRegistryAddress)
// ─────────────────────────────────────────────────────────────────────────────

const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const [deployer] = await ethers.getSigners();

  console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("  Deploying ValidationRegistry");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log(`Deployer : ${deployer.address}`);
  console.log(`Network  : ${(await ethers.provider.getNetwork()).name}`);

  // ── 1. Lire deployment.json ───────────────────────────────────────────────
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));

  const identityAddress = deployment.contracts.IdentityRegistry?.address;
  const stakingAddress = deployment.contracts.StakingContract?.address;

  if (!identityAddress) throw new Error("IdentityRegistry address not found in deployment.json");
  if (!stakingAddress) throw new Error("StakingContract address not found in deployment.json");

  // ReputationRegistry : adresse zéro temporaire — sera setté plus tard
  // On utilise un placeholder non-zero valide pour le constructeur qui reject address(0).
  // → on déploie un stub minimal si absent, ou on accepte de passer une vraie adresse.
  // Pour l'instant : deployer.address comme placeholder (aucun appel ne sera fait dessus
  // avant qu'on appelle setReputationRegistry() avec la vraie adresse).
  const reputationAddress =
    deployment.contracts.ReputationRegistry?.address ?? deployer.address;

  console.log(`\nSiblings :`);
  console.log(`  IdentityRegistry   : ${identityAddress}`);
  console.log(`  StakingContract    : ${stakingAddress}`);
  console.log(`  ReputationRegistry : ${reputationAddress}${reputationAddress === deployer.address ? "  ⚠ placeholder — à mettre à jour" : ""
    }`);

  // ── 2. Déployer ValidationRegistry ───────────────────────────────────────
  console.log("\nDeploying...");
  const Factory = await ethers.getContractFactory("ValidationRegistry");
  const validation = await Factory.deploy(
    identityAddress,
    stakingAddress,
    reputationAddress
  );
  await validation.waitForDeployment();

  const validationAddress = await validation.getAddress();
  console.log(`✓ ValidationRegistry : ${validationAddress}`);

  // ── 3. Post-déploiement : enregistrer ValidationRegistry dans StakingContract
  // Sans ça, lockStake / unlockStake / slash revertent (onlyValidationRegistry)
  console.log("\nPost-deploy : setValidationRegistry sur StakingContract...");
  const stakingFactory = await ethers.getContractFactory("StakingContract");
  const stakingContract = stakingFactory.attach(stakingAddress);

  const tx = await stakingContract.setValidationRegistry(validationAddress);
  await tx.wait();
  console.log(`✓ StakingContract.setValidationRegistry(${validationAddress}) — tx: ${tx.hash}`);

  // ── 4. Sauvegarder dans deployment.json ──────────────────────────────────
  deployment.contracts.ValidationRegistry = {
    address: validationAddress,
    identityRegistry: identityAddress,
    stakingContract: stakingAddress,
    reputationRegistry: reputationAddress,
    deployedAt: new Date().toISOString(),
  };
  fs.writeFileSync(deploymentPath, JSON.stringify(deployment, null, 2));
  console.log(`\n✓ deployment.json mis à jour`);

  // ── 5. Sauvegarder ABI ────────────────────────────────────────────────────
  const abiSrc = path.join(
    __dirname,
    "../artifacts/contracts/ValidationRegistry.sol/ValidationRegistry.json"
  );
  if (fs.existsSync(abiSrc)) {
    const { abi } = JSON.parse(fs.readFileSync(abiSrc, "utf8"));
    const abiDest = path.join(__dirname, "../deployments/ValidationRegistry.abi.json");
    fs.writeFileSync(abiDest, JSON.stringify(abi, null, 2));
    console.log("✓ ABI saved → deployments/ValidationRegistry.abi.json");
  }

  // ── 6. Résumé ─────────────────────────────────────────────────────────────
  console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("→ Copier dans backend/.env :");
  console.log(`  VALIDATION_REGISTRY_ADDRESS=${validationAddress}`);
  console.log("\n→ Quand ReputationRegistry sera déployé :");
  console.log(`  await validationRegistry.setReputationRegistry(<REPUTATION_ADDRESS>)`);
  console.log(`  await reputationRegistry.setAuthorisedCaller("${validationAddress}", true)`);
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
}

main().catch(e => { console.error(e); process.exit(1); });
