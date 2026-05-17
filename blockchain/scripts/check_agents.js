const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

async function main() {
  const deployment = JSON.parse(
    fs.readFileSync(path.join(__dirname, "../deployments/deployment.json"), "utf8")
  );
  const identityAddr = deployment.contracts.IdentityRegistry.address;
  const escrowAddr   = deployment.contracts.EscrowManager.address;

  const ir    = await ethers.getContractAt("IdentityRegistry", identityAddr);
  const escrow = await ethers.getContractAt("EscrowManager",   escrowAddr);
  console.log(`IdentityRegistry : ${identityAddr}`);
  console.log(`EscrowManager    : ${escrowAddr}\n`);

  const agents = [
    "researcher-01",
    "analyst-01",
    "writer-01",
    "judge-alpha",
    "judge-beta",
    "judge-gamma",
    "judge-delta",
    "judge-epsilon",
  ];
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
