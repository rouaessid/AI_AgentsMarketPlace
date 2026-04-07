const { ethers, network } = require("hardhat");
const fs   = require("fs");
const path = require("path");

async function main() {
  const [deployer] = await ethers.getSigners();

  console.log(`\nDeploying StakingContract`);
  console.log(`Deployer: ${deployer.address}`);

  // Lire deployment.json pour récupérer l'adresse plateforme
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  const deployment     = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));

  const platformWallet = deployer.address; // Account #0 = plateforme

  const Factory = await ethers.getContractFactory("StakingContract");
  const staking = await Factory.deploy(platformWallet);
  await staking.waitForDeployment();

  const address = await staking.getAddress();
  console.log(`StakingContract: ${address}`);

  // Sauvegarder dans deployments/
  deployment.contracts.StakingContract = {
    address,
    platformWallet,
    deployedAt: new Date().toISOString(),
  };
  fs.writeFileSync(deploymentPath, JSON.stringify(deployment, null, 2));

  // Copier ABI
  const abiPath = path.join(
    __dirname,
    "../artifacts/contracts/StakingContract.sol/StakingContract.json"
  );
  if (fs.existsSync(abiPath)) {
    const { abi } = JSON.parse(fs.readFileSync(abiPath, "utf8"));
    fs.writeFileSync(
      path.join(__dirname, "../deployments/StakingContract.abi.json"),
      JSON.stringify(abi, null, 2)
    );
    console.log("ABI saved → deployments/StakingContract.abi.json");
  }

  console.log(`\n→ Copier dans backend/.env :`);
  console.log(`  STAKING_CONTRACT_ADDRESS=${address}`);
}

main().catch(e => { console.error(e); process.exit(1); });