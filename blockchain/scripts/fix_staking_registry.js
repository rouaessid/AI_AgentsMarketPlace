/**
 * fix_reputation_init.js
 * One-shot: call ReputationRegistry.initialize(IDENTITY_REGISTRY_ADDRESS)
 * Missing from deploy-all.js after the tokenId-interface redeployment.
 * Run: cd blockchain && node scripts/fix_staking_registry.js
 */

const { ethers } = require("ethers");
require("dotenv").config({ path: require("path").resolve(__dirname, "../../.env") });

const ABI = ["function initialize(address identityRegistry_) external"];

async function main() {
    const provider = new ethers.JsonRpcProvider(process.env.BASE_SEPOLIA_RPC_URL || "https://sepolia.base.org");
    const signer   = new ethers.Wallet(process.env.DEPLOYER_PRIVATE_KEY, provider);

    const reputation     = new ethers.Contract(process.env.REPUTATION_REGISTRY_ADDRESS, ABI, signer);
    const identityAddress = process.env.IDENTITY_REGISTRY_ADDRESS;

    console.log("ReputationRegistry:", process.env.REPUTATION_REGISTRY_ADDRESS);
    console.log("IdentityRegistry  :", identityAddress);
    console.log("Calling initialize...");

    const tx = await reputation.initialize(identityAddress);
    console.log("TX hash:", tx.hash);
    await tx.wait();
    console.log("✓ ReputationRegistry.initialize done — giveFeedback should work now.");
}

main().catch(e => { console.error(e); process.exit(1); });
