// scripts/setup_judges.js
// Registers 3 judge bots in IdentityRegistry and stakes the minimum amount.
// Run after setup_complete.js:
//   npx hardhat run scripts/setup_judges.js --network localhost

const { ethers } = require("hardhat");
const fs = require("fs");
const path = require("path");

// Hardhat local judge wallets: accounts #3, #4, #5.
const JUDGE_KEYS = [
  "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
  "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a",
  "0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba",
];

const JUDGE_IDS = ["judge-alpha", "judge-beta", "judge-gamma"];
const JUDGE_NAMES = ["Judge Alpha", "Judge Beta", "Judge Gamma"];
const STAKE_AMOUNT = ethers.parseEther("0.1");
const MIN_GAS_BUFFER = ethers.parseEther("0.02");

async function main() {
  const [deployer] = await ethers.getSigners();
  const deploymentPath = path.join(__dirname, "../deployments/deployment.json");
  if (!fs.existsSync(deploymentPath)) {
    throw new Error("deployment.json not found - run setup_complete.js first");
  }

  const deployment = JSON.parse(fs.readFileSync(deploymentPath, "utf8"));
  const identityAddr = deployment.contracts.IdentityRegistry.address;
  const stakingAddr = deployment.contracts.StakingContract.address;

  console.log("\nSetting up 3 judge bots...");
  console.log(`  IdentityRegistry : ${identityAddr}`);
  console.log(`  StakingContract  : ${stakingAddr}\n`);

  const provider = ethers.provider;
  const IdentityRegistry = await ethers.getContractAt("IdentityRegistry", identityAddr);
  const StakingContract = await ethers.getContractAt("StakingContract", stakingAddr);

  const judgeAddresses = [];

  for (let i = 0; i < 3; i++) {
    const judgeWallet = new ethers.Wallet(JUDGE_KEYS[i], provider);
    const judgeId = JUDGE_IDS[i];
    const requiredBalance = STAKE_AMOUNT + MIN_GAS_BUFFER;
    const currentBalance = await provider.getBalance(judgeWallet.address);

    console.log(`${JUDGE_NAMES[i]}`);
    console.log(`  Address : ${judgeWallet.address}`);
    console.log(`  AgentId : ${judgeId}`);

    if (currentBalance < requiredBalance) {
      const deficit = requiredBalance - currentBalance;
      const fundTx = await deployer.sendTransaction({
        to: judgeWallet.address,
        value: deficit,
      });
      await fundTx.wait();
      console.log(`  Funded  : ${ethers.formatEther(deficit)} ETH`);
    }

    try {
      const exists = await IdentityRegistry.agentIdExists(judgeId);
      if (exists) {
        console.log("  Already registered in IdentityRegistry\n");
        judgeAddresses.push(judgeWallet.address);
        continue;
      }
    } catch {}

    const agentURI = `ipfs://judge-${judgeId}-v1`;
    const registerTx = await IdentityRegistry.connect(judgeWallet).register(
      judgeId,
      1,
      agentURI,
      "1.0.0",
      0
    );
    await registerTx.wait();
    console.log(`  Registered : ${registerTx.hash.slice(0, 10)}...`);

    const stakeTx = await StakingContract.connect(judgeWallet).stake({ value: STAKE_AMOUNT });
    await stakeTx.wait();
    console.log(`  Staked     : ${ethers.formatEther(STAKE_AMOUNT)} ETH\n`);

    judgeAddresses.push(judgeWallet.address);
  }

  console.log("Verifying eligibility...");
  for (let i = 0; i < 3; i++) {
    const eligible = await StakingContract.isEligibleJudge(judgeAddresses[i]);
    const locked = await StakingContract.isLocked(judgeAddresses[i]);
    console.log(`  ${JUDGE_IDS[i]}: eligible=${eligible}, locked=${locked}`);
  }

  const envPath = path.join(__dirname, "../../.env");
  if (fs.existsSync(envPath)) {
    let envContent = fs.readFileSync(envPath, "utf8");
    const additions = {
      JUDGE_1_PRIVATE_KEY: JUDGE_KEYS[0],
      JUDGE_2_PRIVATE_KEY: JUDGE_KEYS[1],
      JUDGE_3_PRIVATE_KEY: JUDGE_KEYS[2],
      JUDGE_1_ID: JUDGE_IDS[0],
      JUDGE_2_ID: JUDGE_IDS[1],
      JUDGE_3_ID: JUDGE_IDS[2],
    };

    for (const [key, value] of Object.entries(additions)) {
      const regex = new RegExp(`^${key}=.*`, "m");
      if (regex.test(envContent)) {
        envContent = envContent.replace(regex, `${key}=${value}`);
      } else {
        envContent += `\n${key}=${value}`;
      }
    }

    fs.writeFileSync(envPath, envContent);
    console.log("\n.env updated with judge private keys.");
  }

  console.log("\n3 judge bots ready.");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
