const { ethers } = require("hardhat");

async function main() {
  const ir = await ethers.getContractAt("IdentityRegistry", "0x5FbDB2315678afecb367f032d93F642f64180aa3");
  const escrow = await ethers.getContractAt("EscrowManager", "0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0");

  const agents = ["researcher-01", "judge-alpha", "judge-beta", "judge-gamma"];
  for (const id of agents) {
    const exists = await ir.agentIdExists(id);
    const active = exists ? await ir.isActive(id) : false;
    const price  = exists ? await ir.getPricePerTask(id) : 0n;
    console.log(`${id}: exists=${exists} active=${active} price=${price.toString()}wei`);
  }

  const identityInEscrow = await escrow.identityRegistry();
  const judgeFeePct = await escrow.judgeFeePercentage();
  console.log(`EscrowManager.identityRegistry = ${identityInEscrow}`);
  console.log(`EscrowManager.judgeFeePercentage = ${judgeFeePct}%`);
}
main().catch(console.error);
