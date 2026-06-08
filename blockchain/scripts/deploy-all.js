/**
 * deploy-all.js — Full deployment script for AgentMarket on Base Sepolia.
 *
 * Usage:
 *   cd blockchain
 *   npx hardhat run scripts/deploy-all.js --network baseSepolia
 *
 * After this script completes, run manually in graph-indexer/:
 *   graph codegen && graph build
 *   graph deploy agentmarket --version-label vX.Y.Z
 */

const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

// ── Paths ──────────────────────────────────────────────────────────────────────
const ROOT            = path.resolve(__dirname, "../..");
const ENV_PATH        = path.join(ROOT, ".env");
const SUBGRAPH_PATH   = path.join(ROOT, "graph-indexer/subgraph.yaml");
const ABIS_DST_DIR    = path.join(ROOT, "graph-indexer/abis");
const ARTIFACTS_DIR   = path.join(ROOT, "blockchain/artifacts/contracts");
const DEPLOYMENTS_DIR = path.join(ROOT, "blockchain/deployments");
const DEPLOYMENT_JSON = path.join(DEPLOYMENTS_DIR, "deployment.json");

// ── Helpers ────────────────────────────────────────────────────────────────────

function updateEnv(addresses) {
    let env = fs.readFileSync(ENV_PATH, "utf8");
    const map = {
        IDENTITY_REGISTRY_ADDRESS:   addresses.identity,
        STAKING_CONTRACT_ADDRESS:    addresses.staking,
        VALIDATION_REGISTRY_ADDRESS: addresses.validation,
        ESCROW_MANAGER_ADDRESS:      addresses.escrow,
        REPUTATION_REGISTRY_ADDRESS: addresses.reputation,
    };
    for (const [key, value] of Object.entries(map)) {
        const re = new RegExp(`^${key}=.*$`, "m");
        if (re.test(env)) {
            env = env.replace(re, `${key}=${value}`);
        } else {
            env += `\n${key}=${value}`;
        }
    }
    fs.writeFileSync(ENV_PATH, env);
}

function updateSubgraph(addresses, startBlock) {
    let yaml = fs.readFileSync(SUBGRAPH_PATH, "utf8");

    // Map contract section name → new address
    const addrMap = {
        IdentityRegistry:   addresses.identity,
        EscrowManager:      addresses.escrow,
        ValidationRegistry: addresses.validation,
        StakingContract:    addresses.staking,
        ReputationRegistry: addresses.reputation,
    };

    // Replace each contract address — matches `name: ContractName` then the address line below
    for (const [name, addr] of Object.entries(addrMap)) {
        yaml = yaml.replace(
            new RegExp(
                `(name:\\s+${name}[\\s\\S]*?source:\\s*\\n\\s*address:\\s*)"[^"]*"`,
                "m"
            ),
            `$1"${addr}"`
        );
    }

    // Replace all startBlock values
    yaml = yaml.replace(/startBlock:\s*\d+/g, `startBlock: ${startBlock}`);

    fs.writeFileSync(SUBGRAPH_PATH, yaml);
}

function writeDeploymentJson(addresses, startBlock, network) {
    if (!fs.existsSync(DEPLOYMENTS_DIR)) fs.mkdirSync(DEPLOYMENTS_DIR, { recursive: true });
    const json = {
        network,
        startBlock,
        deployedAt: new Date().toISOString(),
        contracts: {
            IdentityRegistry:   { address: addresses.identity },
            StakingContract:    { address: addresses.staking },
            ReputationRegistry: { address: addresses.reputation },
            EscrowManager:      { address: addresses.escrow },
            ValidationRegistry: { address: addresses.validation },
        },
    };
    fs.writeFileSync(DEPLOYMENT_JSON, JSON.stringify(json, null, 2));
}

function copyAbis(contracts) {
    if (!fs.existsSync(ABIS_DST_DIR)) fs.mkdirSync(ABIS_DST_DIR, { recursive: true });

    for (const name of contracts) {
        const src = path.join(ARTIFACTS_DIR, `${name}.sol`, `${name}.json`);
        const dst = path.join(ABIS_DST_DIR, `${name}.json`);
        if (!fs.existsSync(src)) {
            console.warn(`   ⚠  ABI not found: ${src}`);
            continue;
        }
        const artifact = JSON.parse(fs.readFileSync(src, "utf8"));
        fs.writeFileSync(dst, JSON.stringify(artifact.abi, null, 2));
        console.log(`   ${name}.json ✓`);
    }
}

// ── Main ───────────────────────────────────────────────────────────────────────

async function main() {
    const [deployer] = await ethers.getSigners();
    const balance    = await ethers.provider.getBalance(deployer.address);
    console.log("Deployer :", deployer.address);
    console.log("Balance  :", ethers.formatEther(balance), "ETH\n");

    if (balance < ethers.parseEther("0.01")) {
        throw new Error("Insufficient balance — need at least 0.01 ETH");
    }

    // Fetch nonce once and increment manually to avoid Base Sepolia nonce race
    let nonce = await deployer.getNonce("pending");
    console.log("Starting nonce:", nonce, "\n");

    // ── 1. IdentityRegistry ────────────────────────────────────────────────────
    console.log("1/5  IdentityRegistry...");
    const IdentityRegistry = await ethers.getContractFactory("IdentityRegistry");
    const identity = await IdentityRegistry.deploy({ nonce: nonce++ });
    await identity.waitForDeployment();
    const identityAddress = await identity.getAddress();
    console.log("     →", identityAddress);

    // ── 2. StakingContract ─────────────────────────────────────────────────────
    console.log("2/5  StakingContract...");
    const StakingContract = await ethers.getContractFactory("StakingContract");
    const staking = await StakingContract.deploy(deployer.address, { nonce: nonce++ });
    await staking.waitForDeployment();
    const stakingAddress = await staking.getAddress();
    console.log("     →", stakingAddress);

    // ── 3. ReputationRegistry ──────────────────────────────────────────────────
    console.log("3/5  ReputationRegistry...");
    const ReputationRegistry = await ethers.getContractFactory("ReputationRegistry");
    const reputation = await ReputationRegistry.deploy({ nonce: nonce++ });
    await reputation.waitForDeployment();
    const reputationAddress = await reputation.getAddress();
    console.log("     →", reputationAddress);

    // ── 4. EscrowManager ───────────────────────────────────────────────────────
    console.log("4/5  EscrowManager (judgeFee=10%)...");
    const EscrowManager = await ethers.getContractFactory("EscrowManager");
    const escrow = await EscrowManager.deploy(10, { nonce: nonce++ });
    await escrow.waitForDeployment();
    const escrowAddress = await escrow.getAddress();
    console.log("     →", escrowAddress);

    // ── 5. ValidationRegistry ─────────────────────────────────────────────────
    console.log("5/5  ValidationRegistry...");
    const ValidationRegistry = await ethers.getContractFactory("ValidationRegistry");
    const validation = await ValidationRegistry.deploy(
        identityAddress, stakingAddress, { nonce: nonce++ }
    );
    await validation.waitForDeployment();
    const validationAddress = await validation.getAddress();
    console.log("     →", validationAddress);

    // ── Deployment block ───────────────────────────────────────────────────────
    const deployBlock = await ethers.provider.getBlockNumber();
    console.log("\nDeployment block:", deployBlock);

    // ── Post-deploy setters ────────────────────────────────────────────────────
    console.log("\nPost-deploy setters...");

    let tx;
    tx = await validation.setEscrowManager(escrowAddress);
    await tx.wait();
    console.log("   ValidationRegistry.setEscrowManager ✓");

    tx = await escrow.setValidationRegistry(validationAddress);
    await tx.wait();
    console.log("   EscrowManager.setValidationRegistry ✓");

    tx = await escrow.setIdentityRegistry(identityAddress);
    await tx.wait();
    console.log("   EscrowManager.setIdentityRegistry   ✓");

    const addresses = {
        identity:   identityAddress,
        staking:    stakingAddress,
        reputation: reputationAddress,
        escrow:     escrowAddress,
        validation: validationAddress,
    };

    // ── Write deployments/deployment.json ─────────────────────────────────────
    console.log("\nWriting deployments/deployment.json...");
    const network = (await ethers.provider.getNetwork()).name;
    writeDeploymentJson(addresses, deployBlock, network);
    console.log("   deployments/deployment.json ✓");

    // ── Update .env ────────────────────────────────────────────────────────────
    console.log("Updating .env...");
    updateEnv(addresses);
    console.log("   .env ✓");

    // ── Update subgraph.yaml ───────────────────────────────────────────────────
    console.log("Updating subgraph.yaml...");
    updateSubgraph(addresses, deployBlock);
    console.log("   subgraph.yaml ✓");

    // ── Copy ABIs ──────────────────────────────────────────────────────────────
    console.log("Copying ABIs → graph-indexer/abis/...");
    copyAbis([
        "IdentityRegistry",
        "StakingContract",
        "ReputationRegistry",
        "EscrowManager",
        "ValidationRegistry",
    ]);

    // ── Summary ────────────────────────────────────────────────────────────────
    console.log("\n✅  Deployment complete!\n");
    console.log("  IdentityRegistry   :", identityAddress);
    console.log("  StakingContract    :", stakingAddress);
    console.log("  ReputationRegistry :", reputationAddress);
    console.log("  EscrowManager      :", escrowAddress);
    console.log("  ValidationRegistry :", validationAddress);
    console.log("  Start block        :", deployBlock);

    console.log("\n── Next steps ────────────────────────────────────────────");
    console.log("  cd graph-indexer");
    console.log("  graph codegen && graph build");
    console.log("  graph deploy agentmarket --version-label vX.Y.Z");
    console.log("  → Mets à jour GRAPH_URL dans .env avec la nouvelle version");
    console.log("──────────────────────────────────────────────────────────\n");
}

main().catch((err) => {
    console.error("\n❌  Deployment failed:", err.message);
    process.exit(1);
});
