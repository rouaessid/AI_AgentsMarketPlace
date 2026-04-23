// scripts/setup_complete.js
const hre           = require("hardhat");
const { ethers }    = require("hardhat");
const fs            = require("fs");
const path          = require("path");

const NETWORK_CONFIG = {
  hardhat:       { rpcUrl: "http://127.0.0.1:8545",                chainId: 31337 },
  localhost:     { rpcUrl: "http://127.0.0.1:8545",                chainId: 31337 },
  polygonMumbai: { rpcUrl: process.env.POLYGON_MUMBAI_RPC_URL || "https://rpc-mumbai.maticvigil.com", chainId: 80001 },
  polygon:       { rpcUrl: process.env.POLYGON_RPC_URL        || "https://polygon-rpc.com",           chainId: 137   },
  sepolia:       { rpcUrl: process.env.SEPOLIA_RPC_URL        || "",                                   chainId: 11155111 },
};

async function main() {
  const [deployer] = await ethers.getSigners();
  const networkName = hre.network.name;
  const netConfig   = NETWORK_CONFIG[networkName] || { rpcUrl: "", chainId: 0 };

  console.log("\n🚀 Démarrage du déploiement complet et liaison...");
  console.log(`Réseau   : ${networkName} (chainId ${netConfig.chainId})`);
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

  // 4. Déploiement ReputationRegistry (ERC-8004 — vrai contrat)
  const Reputation = await ethers.getContractFactory("ReputationRegistry");
  const reputation = await Reputation.deploy();
  await reputation.waitForDeployment();
  const reputationAddr = await reputation.getAddress();
  console.log(`✅ ReputationRegistry (ERC-8004): ${reputationAddr}`);

  // 5. Déploiement ValidationRegistry
  const ValidationValue = await ethers.getContractFactory("ValidationRegistry");
  const validation = await ValidationValue.deploy(identityAddr, stakingAddr, reputationAddr);
  await validation.waitForDeployment();
  const validationAddr = await validation.getAddress();
  console.log(`✅ ValidationRegistry: ${validationAddr}`);

  console.log("\n🔗 Liaison des contrats...");

  // Staking → ValidationRegistry
  await (await staking.setValidationRegistry(validationAddr)).wait();
  console.log("  - StakingContract lié à ValidationRegistry");

  // ValidationRegistry → EscrowManager
  await (await validation.setEscrowManager(escrowAddr)).wait();
  console.log("  - ValidationRegistry lié à EscrowManager");

  // EscrowManager → ValidationRegistry
  await (await escrow.setValidationRegistry(validationAddr)).wait();
  console.log("  - EscrowManager lié à ValidationRegistry");

  // EscrowManager → IdentityRegistry (price verification)
  await (await escrow.setIdentityRegistry(identityAddr)).wait();
  console.log("  - EscrowManager lié à IdentityRegistry (vérification prix)");

  // ReputationRegistry → initialize(IdentityRegistry)
  await (await reputation.initialize(identityAddr)).wait();
  console.log("  - ReputationRegistry initialisé avec IdentityRegistry");

  // ReputationRegistry → autoriser ValidationRegistry à appeler recordReputation()
  await (await reputation.setAuthorizedCaller(validationAddr, true)).wait();
  console.log("  - ValidationRegistry autorisé comme caller de ReputationRegistry");

  // 5. Mise à jour de deployment.json
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  const deployment = {
    network:    networkName,
    chainId:    netConfig.chainId,
    deployedAt: new Date().toISOString(),
    deployer:   deployer.address,
    contracts: {
      IdentityRegistry:   { address: identityAddr },
      StakingContract:    { address: stakingAddr },
      EscrowManager:      { address: escrowAddr },
      ReputationRegistry: { address: reputationAddr },
      ValidationRegistry: { address: validationAddr }
    }
  };
  fs.mkdirSync(path.dirname(deploymentPath), { recursive: true });
  fs.writeFileSync(deploymentPath, JSON.stringify(deployment, null, 2));
  console.log("\n💾 deployment.json mis à jour.");

  // 6. Mise à jour AUTOMATIQUE du fichier .env
  const envPath = path.join(__dirname, "../../.env");
  if (fs.existsSync(envPath)) {
    let envContent = fs.readFileSync(envPath, "utf8");

    const replacements = {
      "IDENTITY_REGISTRY_ADDRESS":   identityAddr,
      "STAKING_CONTRACT_ADDRESS":    stakingAddr,
      "VALIDATION_REGISTRY_ADDRESS": validationAddr,
      "ESCROW_MANAGER_ADDRESS":      escrowAddr,
      "REPUTATION_REGISTRY_ADDRESS": reputationAddr,
      // Réseau — mis à jour seulement si on déploie hors localhost
      ...(networkName !== "localhost" && networkName !== "hardhat" ? {
        "RPC_URL":  netConfig.rpcUrl,
        "CHAIN_ID": String(netConfig.chainId),
      } : {}),
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
  console.log(`  ESCROW_MANAGER_ADDRESS      : ${escrowAddr}`);
  console.log(`  REPUTATION_REGISTRY_ADDRESS : ${reputationAddr}`);
  console.log(`  VALIDATION_REGISTRY_ADDRESS : ${validationAddr}`);
  console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("🚀 TOUT EST PRÊT ! Lance le backend :");
  console.log("   cd backend && uvicorn app.main:app --reload --port 8000");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
