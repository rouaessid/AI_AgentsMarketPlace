/**
 * check_judges.js — Diagnostic: eligibility + judgeAuthorized status for all judges
 *
 * Usage:
 *   npx hardhat run scripts/check_judges.js --network baseSepolia
 */
const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

async function main() {
  const deployment = JSON.parse(
    fs.readFileSync(path.join(__dirname, "../deployments/deployment.json"), "utf8")
  );

  const vrAddr      = deployment.contracts.ValidationRegistry.address;
  const stakingAddr = deployment.contracts.StakingContract.address;
  const irAddr      = deployment.contracts.IdentityRegistry.address;

  const vr      = await ethers.getContractAt("ValidationRegistry", vrAddr);
  const staking = await ethers.getContractAt("StakingContract",    stakingAddr);
  const ir      = await ethers.getContractAt("IdentityRegistry",   irAddr);

  const judgeIds = ["judge-alpha", "judge-beta", "judge-gamma", "judge-delta", "judge-epsilon"];

  console.log("=== Judge full eligibility check ===\n");
  console.log(
    "  name".padEnd(18),
    "tokenId".padEnd(10),
    "wallet".padEnd(44),
    "active".padEnd(8),
    "stakeOK".padEnd(9),
    "locked".padEnd(8),
    "authorized".padEnd(12),
    "activeTask".padEnd(12),
    "eligible"
  );
  console.log("  " + "-".repeat(130));

  let eligibleCount = 0;

  for (const jid of judgeIds) {
    let row = `  ${jid.padEnd(16)}`;
    try {
      const tokenId = await ir.getCurrentTokenId(jid);
      const wallet  = await ir.getAgentWalletByTokenId(tokenId);
      const isActive   = await ir.isActiveByTokenId(tokenId);
      const stake      = await staking.stakes(wallet);
      const isLocked   = await staking.isLocked(wallet);
      const authorized = await vr.judgeAuthorized(tokenId);
      const eligible   = await vr.isEligibleJudgeCandidate(tokenId);

      // Check active task
      let activeTask = "(none)";
      try {
        // _judgeActiveTask is internal; use the event-based approach or public getter if exists
        // Try calling isEligibleJudgeCandidate which includes the activeTask check
        activeTask = eligible ? "(none)" : "(possibly set)";
      } catch (_) {}

      const stakeAmt = ethers.formatEther(stake.amount);
      const stakeOK  = parseFloat(stakeAmt) > 0;

      if (eligible && authorized) eligibleCount++;

      row +=
        tokenId.toString().padEnd(10) +
        wallet.padEnd(44) +
        String(isActive).padEnd(8) +
        String(stakeOK).padEnd(9) +
        String(isLocked).padEnd(8) +
        String(authorized).padEnd(12) +
        activeTask.padEnd(12) +
        String(eligible && authorized);

      console.log(row);
      console.log(`    stake=${stakeAmt} ETH  lockedUntil=${new Date(Number(stake.lockedUntil)*1000).toISOString()}`);
    } catch (e) {
      console.log(row + `ERROR: ${e.message}`);
    }
  }

  console.log(`\n  Total eligible+authorized: ${eligibleCount}/5`);
  console.log(`  Required by assignJudges: 3`);

  if (eligibleCount < 3) {
    console.log("\n⚠  NOT ENOUGH eligible judges for validation!");
    console.log("   Fix: call vr.setHoneypotResult(tokenId, true, cid) for judges where authorized=false");
    console.log("   OR wait for locked judges to unlock (if authorized but locked)");
  } else {
    console.log("\n✓  Enough judges available — assignJudges should succeed.");
  }
}

main().catch(e => { console.error(e); process.exit(1); });
