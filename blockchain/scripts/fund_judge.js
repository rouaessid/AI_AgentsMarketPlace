const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  const judgeWallet = "0xbB5385c00F70E29193AB59ca241C705dC607dD66";
  const tx = await deployer.sendTransaction({
    to: judgeWallet,
    value: ethers.parseEther("10"),
  });
  await tx.wait();
  console.log(`Funded ${judgeWallet} with 10 ETH`);
}

main().then(() => process.exit(0)).catch(e => { console.error(e); process.exit(1); });
