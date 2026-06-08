/**
 * redeploy-validation.js — Redeploy only ValidationRegistry.
 *
 * Usage:
 *   cd blockchain
 *   npx hardhat run scripts/redeploy-validation.js --network baseSepolia
 */

const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

const ROOT          = path.resolve(__dirname, "../..");
const ENV_PATH      = path.join(ROOT, ".env");
const SUBGRAPH_PATH = path.join(ROOT, "graph-indexer/subgraph.yaml");
const ABIS_DST_DIR  = path.join(ROOT, "graph-indexer/abis");
const ARTIFACTS_DIR = path.join(ROOT, "blockchain/artifacts/contracts");

function readEnv(key) {
    const env = fs.readFileSync(ENV_PATH, "utf8");
    const match = env.match(new RegExp(`^${key}=(.*)$`, "m"));
    return match ? match[1].trim() : null;
}

function updateEnv(key, value) {
    let env = fs.readFileSync(ENV_PATH, "utf8");
    const re = new RegExp(`^${key}=.*$`, "m");
    env = re.test(env) ? env.replace(re, `${key}=${value}`) : env + `\n${key}=${value}`;
    fs.writeFileSync(ENV_PATH, env);
}

function updateSubgraph(address, startBlock) {
    let yaml = fs.readFileSync(SUBGRAPH_PATH, "utf8");
    // Mettre à jour uniquement l'adresse et le startBlock de ValidationRegistry
    yaml = yaml.replace(
        /(name:\s+ValidationRegistry[\s\S]*?source:\s*\n\s*address:\s*)"[^"]*"/m,
        `$1"${address}"`
    );
    yaml = yaml.replace(
        /(name:\s+ValidationRegistry[\s\S]*?startBlock:\s*)\d+/m,
        `$1${startBlock}`
    );
    fs.writeFileSync(SUBGRAPH_PATH, yaml);
}

function copyAbi() {
    const src = path.join(ARTIFACTS_DIR, "ValidationRegistry.sol", "ValidationRegistry.json");
    const dst = path.join(ABIS_DST_DIR, "ValidationRegistry.json");
    const artifact = JSON.parse(fs.readFileSync(src, "utf8"));
    fs.writeFileSync(dst, JSON.stringify(artifact.abi, null, 2));
    console.log("   ValidationRegistry.json ✓");
}

async function main() {
    const [deployer] = await ethers.getSigners();
    console.log("Deployer :", deployer.address);

    const identityAddress   = readEnv("IDENTITY_REGISTRY_ADDRESS");
    const stakingAddress    = readEnv("STAKING_CONTRACT_ADDRESS");
    const escrowAddress = readEnv("ESCROW_MANAGER_ADDRESS");

    console.log("\nUsing existing contracts:");
    console.log("  IdentityRegistry  :", identityAddress);
    console.log("  StakingContract   :", stakingAddress);
    console.log("  EscrowManager     :", escrowAddress);

    console.log("\nDeploying ValidationRegistry...");
    const ValidationRegistry = await ethers.getContractFactory("ValidationRegistry");
    const validation = await ValidationRegistry.deploy(
        identityAddress, stakingAddress
    );
    await validation.waitForDeployment();
    const validationAddress = await validation.getAddress();
    console.log("  →", validationAddress);

    // Set EscrowManager on new ValidationRegistry
    let tx = await validation.setEscrowManager(escrowAddress);
    await tx.wait();
    console.log("  setEscrowManager ✓");

    const setVrAbi = [
        { "inputs": [{ "type": "address", "name": "_registry" }],
          "name": "setValidationRegistry", "outputs": [],
          "stateMutability": "nonpayable", "type": "function" }
    ];

    // Set new ValidationRegistry on EscrowManager
    const escrow = new ethers.Contract(escrowAddress, setVrAbi, deployer);
    tx = await escrow.setValidationRegistry(validationAddress);
    await tx.wait();
    console.log("  EscrowManager.setValidationRegistry ✓");

    // Set new ValidationRegistry on StakingContract
    const staking = new ethers.Contract(stakingAddress, setVrAbi, deployer);
    tx = await staking.setValidationRegistry(validationAddress);
    await tx.wait();
    console.log("  StakingContract.setValidationRegistry ✓");

    const deployBlock = await ethers.provider.getBlockNumber();

    console.log("\nUpdating .env...");
    updateEnv("VALIDATION_REGISTRY_ADDRESS", validationAddress);
    console.log("  .env ✓");

    console.log("Updating subgraph.yaml...");
    updateSubgraph(validationAddress, deployBlock);
    console.log("  subgraph.yaml ✓");

    console.log("Copying ABI...");
    copyAbi();

    console.log("\n✅  ValidationRegistry redeployed!");
    console.log("  Address    :", validationAddress);
    console.log("  Start block:", deployBlock);
    console.log("\n── Next steps ────────────────────────────────────────────");
    console.log("  cd graph-indexer");
    console.log("  graph codegen && graph build");
    console.log("  graph deploy agentmarket --version-label v4.1.0");
    console.log("  → Restart backend");
    console.log("──────────────────────────────────────────────────────────\n");
}

main().catch((err) => {
    console.error("\n❌  Deploy failed:", err.message);
    process.exit(1);
});
