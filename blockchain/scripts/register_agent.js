const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

async function main() {
  // ── Signer (Account #0 Hardhat) ──────────────────────────────────────────
  const [signer] = await ethers.getSigners();
  console.log("Signer:", signer.address);

  // ── Adresse du contrat ────────────────────────────────────────────────────
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  if (!fs.existsSync(deploymentPath)) {
    console.error("deployments/deployment.json introuvable — lancer d'abord deploy.js");
    process.exit(1);
  }
  const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const address    = deployment.contracts.IdentityRegistry.address;
  console.log("Contract :", address);

  // ── ABI depuis deployments/ ───────────────────────────────────────────────
  const abiPath = path.join(__dirname, "../deployments/IdentityRegistry.abi.json");
  let abi;
  if (fs.existsSync(abiPath)) {
    abi = JSON.parse(fs.readFileSync(abiPath, "utf8"));
    console.log("ABI      : deployments/IdentityRegistry.abi.json");
  } else {
    // ABI minimal fallback
    abi = [
      "function register(string agentId_, uint8 agentType_, string agentURI_, string version_) returns (uint256)",
      "event AgentCreated(string indexed agentId, uint256 indexed tokenId, address indexed owner, uint8 agentType, string agentURI, string version)"
    ];
    console.log("ABI      : minimal (fallback)");
  }

  const contract = new ethers.Contract(address, abi, signer);

  // ── Paramètres ────────────────────────────────────────────────────────────
  // Modifier AGENT_URI avec l'agent_uri reçu du /register
  const AGENT_ID   = "strategy-1";
  const AGENT_TYPE = 0;                        // 0=PROVIDER 1=JUDGE
  const AGENT_URI  = "ipfs://QmLOCAL04498837f9906e61a1f55869524fe9847392a317";     // ← remplacer par l'agent_uri du /register
  const VERSION    = "1.0.0";

  console.log("\nRegistering agent...");
  console.log("  agentId  :", AGENT_ID);
  console.log("  agentType:", AGENT_TYPE);
  console.log("  agentURI :", AGENT_URI);
  console.log("  version  :", VERSION);

  // ── Envoyer la tx ─────────────────────────────────────────────────────────
  const tx      = await contract.register(AGENT_ID, AGENT_TYPE, AGENT_URI, VERSION);
  console.log("\nTx hash  :", tx.hash);

  const receipt = await tx.wait();
  console.log("Block    :", receipt.blockNumber);

  // ── Récupérer le tokenId depuis l'event ───────────────────────────────────
  let tokenId = 1;
  for (const log of receipt.logs) {
    try {
      const parsed = contract.interface.parseLog(log);
      if (parsed && parsed.name === "AgentCreated") {
        tokenId = parsed.args.tokenId.toString();
        console.log("\nEvent AgentCreated:");
        console.log("  agentId :", parsed.args.agentId);
        console.log("  tokenId :", tokenId);
        console.log("  owner   :", parsed.args.owner);
      }
    } catch {}
  }

  // ── Résumé pour /confirm ──────────────────────────────────────────────────
  console.log("\n══════════════════════════════════════════════════");
  console.log("Copier dans POST /api/v1/agents/confirm :");
  console.log("══════════════════════════════════════════════════");
  console.log(JSON.stringify({
    registration_id: "← coller le registration_id reçu du /register",
    tx_hash:         tx.hash,
    token_id:        parseInt(tokenId),
  }, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});