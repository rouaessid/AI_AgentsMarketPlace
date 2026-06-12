/**
 * check_balances.js — Vérifie les balances ETH et stakes
 * Usage: npx hardhat run scripts/check_balances.js --network baseSepolia
 */
const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

async function main() {
  const deployment = JSON.parse(
    fs.readFileSync(path.join(__dirname, "../deployments/deployment.json"), "utf8")
  );
  const stakingAddr = deployment.contracts.StakingContract.address;
  const staking = await ethers.getContractAt("StakingContract", stakingAddr);

  const wallets = {
    "Judge wallet  ": "0xbB5385c00F70E29193AB59ca241C705dC607dD66",
    "Deployer wallet": (await ethers.getSigners())[0].address,
  };

  console.log("=== ETH Balances & Stakes ===\n");
  for (const [label, addr] of Object.entries(wallets)) {
    const balance = await ethers.provider.getBalance(addr);
    const stake   = await staking.stakes(addr);
    console.log(`${label} : ${addr}`);
    console.log(`  ETH balance : ${ethers.formatEther(balance)} ETH`);
    console.log(`  Stake       : ${ethers.formatEther(stake.amount)} ETH`);
    console.log();
  }
}

main().catch(e => { console.error(e); process.exit(1); });
