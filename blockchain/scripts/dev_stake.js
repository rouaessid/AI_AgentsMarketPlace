// scripts/dev_stake.js
// Usage: npx hardhat run scripts/dev_stake.js --network localhost
// Stake ETH for a given signer (dev only — bypasses MetaMask)
const { ethers } = require("hardhat");
const path = require("path");
const fs   = require("fs");

async function main() {
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  if (!fs.existsSync(deploymentPath)) {
    throw new Error("deployment.json introuvable. Lance d'abord setup_complete.js");
  }
  const deployment  = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const stakingAddr = deployment.contracts.StakingContract?.address;
  if (!stakingAddr) throw new Error("StakingContract introuvable dans deployment.json");

  const signers = await ethers.getSigners();

  // Passer SIGNER_INDEX=1 pour simuler un provider différent du platform wallet
  // ex: SIGNER_INDEX=1 npx hardhat run scripts/dev_stake.js --network localhost
  const idx    = Number.parseInt(process.env.SIGNER_INDEX || "0");
  const signer = signers[idx];
  console.log(`\nSigner [${idx}] : ${signer.address}`);
  console.log(`StakingContract : ${stakingAddr}\n`);

  const staking = await ethers.getContractAt("StakingContract", stakingAddr, signer);

  // Check existing stake
  const before = await staking.stakes(signer.address);
  console.log(`Stake actuel : ${ethers.formatEther(before.amount)} ETH`);

  // Stake 0.2 ETH (valeur par défaut du formulaire)
  const amount = ethers.parseEther("0.2");
  const tx = await staking.stake({ value: amount });
  await tx.wait();
  console.log(`✅ Stake confirmé : ${tx.hash}`);

  const after = await staking.stakes(signer.address);
  console.log(`Stake final     : ${ethers.formatEther(after.amount)} ETH`);
}

main().catch(e => { console.error(e); process.exitCode = 1; });
