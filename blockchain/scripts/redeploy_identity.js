// redeploy_identity.js
// Redéploie uniquement IdentityRegistry, migre les agents existants,
// relinke ValidationRegistry + EscrowManager.
// Staking, Escrow, Validation restent aux mêmes adresses.

const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

// Adresses actuelles (lues depuis .env ou deployment.json)
function loadEnv() {
  const envPath = path.join(__dirname, "../../.env");
  const content = fs.readFileSync(envPath, "utf8");
  const get = (key) => {
    const m = content.match(new RegExp(`^${key}=(.+)$`, "m"));
    return m ? m[1].trim() : null;
  };
  return {
    identityOld:  get("IDENTITY_REGISTRY_ADDRESS"),
    validation:   get("VALIDATION_REGISTRY_ADDRESS"),
    escrow:       get("ESCROW_MANAGER_ADDRESS"),
  };
}

const OLD_IDENTITY_ABI = [
  "function totalTokensMinted() view returns (uint256)",
  "function getAgentIdByToken(uint256) view returns (string)",
  "function getAgent(string) view returns (tuple(string agentId, uint8 agentType, uint8 status, address owner, address agentWallet, uint256 createdAt, uint256 currentTokenId, uint256[] tokenHistory, uint256 pricePerTask))",
  "function agentURI(string) view returns (string)",
  "function getVersion(uint256) view returns (tuple(uint256 tokenId, string agentURI, string version, uint256 mintedAt, bool isCurrent))",
];

async function main() {
  const [deployer] = await ethers.getSigners();
  const env = loadEnv();

  console.log("\n📖 Lecture des agents sur l'ancienne IdentityRegistry...");
  const oldIdentity = new ethers.Contract(env.identityOld, OLD_IDENTITY_ABI, deployer);

  const total = await oldIdentity.totalTokensMinted();
  console.log(`   ${total} token(s) frappés`);

  // Collecter tous les agents PROVIDER (type=0) à migrer
  const toMigrate = [];
  for (let tokenId = 1; tokenId <= Number(total); tokenId++) {
    try {
      const agentId = await oldIdentity.getAgentIdByToken(tokenId);
      const agent   = await oldIdentity.getAgent(agentId);
      const version = await oldIdentity.getVersion(tokenId);
      if (agent.agentType === 0n) {   // PROVIDER uniquement
        toMigrate.push({ agentId, agentType: 0, agentURI: version.agentURI,
                         version: version.version, pricePerTask: agent.pricePerTask });
        console.log(`   → migrer PROVIDER : ${agentId} (${version.version})`);
      } else {
        console.log(`   → ignorer JUDGE   : ${agentId} (type incorrect, sera re-enregistré)`);
      }
    } catch (_) { /* token brûlé ou inexistant */ }
  }

  // 1. Déploiement nouvelle IdentityRegistry
  console.log("\n🚀 Déploiement nouvelle IdentityRegistry...");
  const Identity = await ethers.getContractFactory("IdentityRegistry");
  const identity = await Identity.deploy();
  await identity.waitForDeployment();
  const newIdentityAddr = await identity.getAddress();
  console.log(`✅ Nouvelle IdentityRegistry : ${newIdentityAddr}`);

  // 2. Migration des agents PROVIDER
  console.log("\n📋 Migration des agents...");
  for (const a of toMigrate) {
    const tx = await identity.register(
      a.agentId, a.agentType, a.agentURI, a.version, a.pricePerTask
    );
    await tx.wait();
    console.log(`✅ Migré : ${a.agentId}`);
  }

  // 3. Relinkage ValidationRegistry
  console.log("\n🔗 Relinkage des contrats...");
  const valAbi  = ["function setIdentityRegistry(address) external"];
  const escAbi  = ["function setIdentityRegistry(address) external"];
  const validation = new ethers.Contract(env.validation, valAbi, deployer);
  const escrow     = new ethers.Contract(env.escrow,     escAbi, deployer);

  await (await validation.setIdentityRegistry(newIdentityAddr)).wait();
  console.log("   ValidationRegistry → nouvelle IdentityRegistry ✅");

  await (await escrow.setIdentityRegistry(newIdentityAddr)).wait();
  console.log("   EscrowManager      → nouvelle IdentityRegistry ✅");

  // 4. Mise à jour .env
  const envPath = path.join(__dirname, "../../.env");
  let envContent = fs.readFileSync(envPath, "utf8");
  envContent = envContent.replace(
    /^IDENTITY_REGISTRY_ADDRESS=.*/m,
    `IDENTITY_REGISTRY_ADDRESS=${newIdentityAddr}`
  );
  fs.writeFileSync(envPath, envContent);
  console.log(`\n✅ .env mis à jour : IDENTITY_REGISTRY_ADDRESS=${newIdentityAddr}`);

  console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("DONE. Étapes suivantes :");
  console.log("  1. Vide la DB : supprime agents researcher-01 et judge-alpha");
  console.log("  2. Redémarre le backend — le indexer re-détecte researcher-01");
  console.log("  3. Enregistre les 3 juges via le formulaire (type=Judge)");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
}

main().catch((e) => { console.error(e); process.exitCode = 1; });
