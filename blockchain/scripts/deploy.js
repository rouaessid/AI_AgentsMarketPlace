// scripts/deploy.js
const { ethers, network } = require("hardhat");
const fs   = require("fs");
const path = require("path");

async function main() {
  const [deployer] = await ethers.getSigners();
  const chainId    = network.config.chainId;

  console.log(`\nDeploying IdentityRegistry`);
  console.log(`Network  : ${network.name} (chainId: ${chainId})`);
  console.log(`Deployer : ${deployer.address}`);
  console.log(`Balance  : ${ethers.formatEther(
    await ethers.provider.getBalance(deployer.address)
  )} ETH\n`);

  const Factory  = await ethers.getContractFactory("IdentityRegistry");
  const contract = await Factory.deploy();
  await contract.waitForDeployment();

  const address       = await contract.getAddress();
  const agentRegistry = await contract.agentRegistry();

  console.log(`IdentityRegistry : ${address}`);
  console.log(`agentRegistry    : ${agentRegistry}`);

  // Sauvegarder pour le backend
  const outDir  = path.join(__dirname, "../artifacts");
  fs.mkdirSync(outDir, { recursive: true });

  const deployment = {
    network, chainId, deployedAt: new Date().toISOString(),
    deployer: deployer.address,
    contracts: { IdentityRegistry: { address, agentRegistry } },
  };
  fs.writeFileSync(
    path.join(outDir, "deployment.json"),
    JSON.stringify(deployment, null, 2)
  );

  // Copier ABI
  const artifactPath = path.join(
    __dirname,
    "../artifacts/contracts/IdentityRegistry.sol/IdentityRegistry.json"
  );
  if (fs.existsSync(artifactPath)) {
    const { abi } = JSON.parse(fs.readFileSync(artifactPath, "utf8"));
    fs.writeFileSync(
      path.join(outDir, "IdentityRegistry.abi.json"),
      JSON.stringify(abi, null, 2)
    );
    console.log(`ABI saved → artifacts/IdentityRegistry.abi.json`);
  }

  console.log(`\nDeployment info → artifacts/deployment.json`);
  console.log(`\n→ Copier dans backend/.env :`);
  console.log(`  IDENTITY_REGISTRY_ADDRESS=${address}`);
  console.log(`  CHAIN_ID=${chainId}\n`);
}

main().then(() => process.exit(0)).catch(e => { console.error(e); process.exit(1); });
