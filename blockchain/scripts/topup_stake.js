/**
 * topup_stake.js — Ajoute du stake pour le wallet des juges
 * Usage: npx hardhat run scripts/topup_stake.js --network baseSepolia
 */
const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");
require("dotenv").config({ path: path.resolve(__dirname, "../../.env") });

const TOPUP_AMOUNT = "0.005"; // ETH à ajouter

async function main() {
  const deployment = JSON.parse(
    fs.readFileSync(path.join(__dirname, "../deployments/deployment.json"), "utf8")
  );
  const stakingAddr = deployment.contracts.StakingContract.address;

  // Utiliser la clé privée du wallet juge (pas le deployer)
  const judgeKey    = "0x8900abaabf0051608e714523caeed0edc096e304666123905bc96ff7df51b3c7";
  const judgeSigner = new ethers.Wallet(judgeKey, ethers.provider);
  const judgeAddr   = await judgeSigner.getAddress();

  const staking = await ethers.getContractAt("StakingContract", stakingAddr, judgeSigner);

  const before = await staking.stakes(judgeAddr);
  console.log(`Wallet      : ${judgeAddr}`);
  console.log(`Stake avant : ${ethers.formatEther(before.amount)} ETH`);
  console.log(`Top-up de   : ${TOPUP_AMOUNT} ETH`);

  const tx = await staking.stake({ value: ethers.parseEther(TOPUP_AMOUNT) });
  await tx.wait();
  console.log(`TX : ${tx.hash}`);

  const after = await staking.stakes(judgeAddr);
  console.log(`Stake après : ${ethers.formatEther(after.amount)} ETH`);
  console.log("✓ Done");
}

main().catch(e => { console.error(e); process.exit(1); });
