// scripts/setup_complete.js
const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("\n🚀 Démarrage du déploiement complet et liaison...");
  console.log(`Deployer : ${deployer.address}\n`);

  // 1. Déploiement IdentityRegistry
  const Identity = await ethers.getContractFactory("IdentityRegistry");
  const identity = await Identity.deploy();
  await identity.waitForDeployment();
  const identityAddr = await identity.getAddress();
  console.log(`✅ IdentityRegistry : ${identityAddr}`);

  // 2. Déploiement StakingContract
  const Staking = await ethers.getContractFactory("StakingContract");
  const staking = await Staking.deploy(deployer.address); // arg: platformWallet
  await staking.waitForDeployment();
  const stakingAddr = await staking.getAddress();
  console.log(`✅ StakingContract  : ${stakingAddr}`);

  // 3. Déploiement EscrowManager (10% fee)
  const Escrow = await ethers.getContractFactory("EscrowManager");
  const escrow = await Escrow.deploy(10);
  await escrow.waitForDeployment();
  const escrowAddr = await escrow.getAddress();
  console.log(`✅ EscrowManager    : ${escrowAddr}`);

  // 4. Déploiement ValidationRegistry (placeholder pour Reputation)
  const ValidationValue = await ethers.getContractFactory("ValidationRegistry");
  const validation = await ValidationValue.deploy(identityAddr, stakingAddr, deployer.address);
  await validation.waitForDeployment();
  const validationAddr = await validation.getAddress();
  console.log(`✅ ValidationRegistry: ${validationAddr}`);

  console.log("\n🔗 Liaison des contrats...");

  // Liaison Staking -> Validation
  await (await staking.setValidationRegistry(validationAddr)).wait();
  console.log("  - StakingContract lié à ValidationRegistry");

  // Liaison Validation -> Escrow
  await (await validation.setEscrowManager(escrowAddr)).wait();
  console.log("  - ValidationRegistry lié à EscrowManager");

  // Liaison Escrow -> Validation
  await (await escrow.setValidationRegistry(validationAddr)).wait();
  console.log("  - EscrowManager lié à ValidationRegistry");

  // 5. Mise à jour de deployment.json
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  const deployment = {
    network: "localhost",
    chainId: 31337,
    deployedAt: new Date().toISOString(),
    deployer: deployer.address,
    contracts: {
      IdentityRegistry: { address: identityAddr },
      StakingContract: { address: stakingAddr },
      EscrowManager: { address: escrowAddr },
      ValidationRegistry: { address: validationAddr }
    }
  };
  fs.writeFileSync(deploymentPath, JSON.stringify(deployment, null, 2));
  console.log("\n💾 deployment.json mis à jour.");

  // 6. Mise à jour AUTOMATIQUE du fichier .env
  const envPath = path.join(__dirname, "../../.env");
  if (fs.existsSync(envPath)) {
    let envContent = fs.readFileSync(envPath, "utf8");
    
    const replacements = {
      "IDENTITY_REGISTRY_ADDRESS": identityAddr,
      "STAKING_CONTRACT_ADDRESS": stakingAddr,
      "VALIDATION_REGISTRY_ADDRESS": validationAddr,
      "ESCROW_MANAGER_ADDRESS": escrowAddr
    };

    for (const [key, value] of Object.entries(replacements)) {
      const regex = new RegExp(`^${key}=.*`, "m");
      if (regex.test(envContent)) {
        envContent = envContent.replace(regex, `${key}=${value}`);
      } else {
        envContent += `\n${key}=${value}`;
      }
    }

    fs.writeFileSync(envPath, envContent);
    console.log("✅ Fichier .env mis à jour automatiquement.");
  }

  // 7. Affichage final
  console.log("\n📋 Récapitulatif des adresses :");
  console.log(`  IDENTITY_REGISTRY_ADDRESS   : ${identityAddr}`);
  console.log(`  STAKING_CONTRACT_ADDRESS    : ${stakingAddr}`);
  console.log(`  VALIDATION_REGISTRY_ADDRESS : ${validationAddr}`);
  console.log(`  ESCROW_MANAGER_ADDRESS      : ${escrowAddr}`);
  console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("🚀 TOUT EST PRÊT ! Vous pouvez lancer le frontend.");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
