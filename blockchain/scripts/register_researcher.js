// scripts/register_researcher.js
//
// Registers ResearchBot (provider) and 3 judge wallets on-chain:
//   - IdentityRegistry.registerAgent()
//   - StakingContract.stake()
//
// Run AFTER setup_complete.js:
//   npx hardhat run scripts/register_researcher.js --network localhost
//
const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

// ── Load deployment addresses ─────────────────────────────────────────────
const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
if (!fs.existsSync(deploymentPath)) {
  console.error("❌  deployment.json not found. Run setup_complete.js first.");
  process.exit(1);
}
const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
const { IdentityRegistry, StakingContract } = deployment.contracts;

// ── Minimal ABIs ─────────────────────────────────────────────────────────
const IDENTITY_ABI = [
  "function registerAgent(string calldata agentId, uint8 agentType, address wallet) external",
  "function isActive(string calldata agentId) external view returns (bool)",
  "function agentIdExists(string calldata agentId) external view returns (bool)",
];

const STAKING_ABI = [
  "function stake() external payable",
  "function isEligibleProvider(address agent) external view returns (bool)",
  "function isEligibleJudge(address agent) external view returns (bool)",
  "function getStake(address agent) external view returns (uint256)",
];

// ── Agent config ──────────────────────────────────────────────────────────
const AGENTS = [
  {
    agentId:   "researcher-01",
    type:      0,           // 0 = PROVIDER
    label:     "ResearchBot (Provider)",
    stakeEth:  "0.2",
    signerIdx: 1,           // Hardhat account #1 = 0x70997970...
  },
  {
    agentId:   "judge-llama-01",
    type:      1,           // 1 = JUDGE
    label:     "Judge Llama (judge-llama-01)",
    stakeEth:  "0.1",
    signerIdx: 2,           // Hardhat account #2 = 0x3C44Cdd...
  },
  {
    agentId:   "judge-claude-02",
    type:      1,
    label:     "Judge Claude (judge-claude-02)",
    stakeEth:  "0.1",
    signerIdx: 3,           // Hardhat account #3
  },
  {
    agentId:   "judge-gpt-03",
    type:      1,
    label:     "Judge GPT (judge-gpt-03)",
    stakeEth:  "0.1",
    signerIdx: 4,           // Hardhat account #4
  },
];

// ─────────────────────────────────────────────────────────────────────────────
async function main() {
  const signers = await ethers.getSigners();
  const deployer = signers[0];

  console.log("\n🚀  Register ResearchBot + Judges on-chain");
  console.log(`    IdentityRegistry : ${IdentityRegistry.address}`);
  console.log(`    StakingContract  : ${StakingContract.address}\n`);

  const identity = new ethers.Contract(IdentityRegistry.address, IDENTITY_ABI, deployer);

  for (const agent of AGENTS) {
    const signer  = signers[agent.signerIdx];
    const staking = new ethers.Contract(StakingContract.address, STAKING_ABI, signer);

    console.log(`────────────────────────────────────────────`);
    console.log(`  ${agent.label}`);
    console.log(`  Wallet  : ${signer.address}`);
    console.log(`  agentId : ${agent.agentId}`);

    // 1. Register in IdentityRegistry (deployer signs — owner-only)
    const alreadyExists = await identity.agentIdExists(agent.agentId);
    if (alreadyExists) {
      console.log(`  ⚠️   Already registered — skipping registerAgent()`);
    } else {
      const identityWithDeployer = identity.connect(deployer);
      const tx = await identityWithDeployer.registerAgent(
        agent.agentId,
        agent.type,
        signer.address,
      );
      await tx.wait();
      console.log(`  ✅  Registered in IdentityRegistry`);
    }

    // 2. Stake
    const currentStake = await staking.getStake(signer.address).catch(() => 0n);
    if (currentStake > 0n) {
      console.log(`  ⚠️   Already staked (${ethers.formatEther(currentStake)} ETH) — skipping`);
    } else {
      const stakeTx = await staking.stake({ value: ethers.parseEther(agent.stakeEth) });
      await stakeTx.wait();
      console.log(`  ✅  Staked ${agent.stakeEth} ETH`);
    }

    // 3. Verify
    const active = await identity.isActive(agent.agentId);
    const eligible = agent.type === 0
      ? await staking.isEligibleProvider(signer.address).catch(() => false)
      : await staking.isEligibleJudge(signer.address).catch(() => false);

    console.log(`  ✅  Active     : ${active}`);
    console.log(`  ✅  Eligible   : ${eligible}`);
  }

  // ── Write wallet mapping to a file for judge bots ─────────────────────
  const walletMap = {};
  for (const agent of AGENTS) {
    const signer = signers[agent.signerIdx];
    walletMap[agent.agentId] = {
      address:    signer.address,
      signerIdx:  agent.signerIdx,
      type:       agent.type === 0 ? "provider" : "judge",
    };
  }

  const outPath = path.join(__dirname, "../deployments/agent_wallets.json");
  fs.writeFileSync(outPath, JSON.stringify(walletMap, null, 2));
  console.log(`\n💾  agent_wallets.json saved → ${outPath}`);

  console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("✅  All agents registered and staked.");
  console.log("    Next: start the researcher server + judge bots.");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
