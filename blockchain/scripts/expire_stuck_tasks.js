/**
 * expire_stuck_tasks.js
 *
 * Finds validation tasks stuck in COMMITTING or REVEALING status
 * (deadline passed, judges still locked) and calls expireTask on them.
 * Also shows current lock status for all registered judge wallets.
 *
 * Usage:
 *   npx hardhat run scripts/expire_stuck_tasks.js --network baseSepolia
 */
const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

const STATUS = ["PENDING", "COMMITTING", "REVEALING", "FINALISED", "EXPIRED", "DISPUTED"];

async function main() {
  const deployment = JSON.parse(
    fs.readFileSync(path.join(__dirname, "../deployments/deployment.json"), "utf8")
  );

  const vrAddr      = deployment.contracts.ValidationRegistry.address;
  const stakingAddr = deployment.contracts.StakingContract.address;
  const irAddr      = deployment.contracts.IdentityRegistry.address;

  const [signer] = await ethers.getSigners();
  console.log(`Signer: ${signer.address}\n`);

  const vr      = await ethers.getContractAt("ValidationRegistry", vrAddr);
  const staking = await ethers.getContractAt("StakingContract",    stakingAddr);
  const ir      = await ethers.getContractAt("IdentityRegistry",   irAddr);

  const now = Math.floor(Date.now() / 1000);

  // ── 1. Show lock status for all known judge wallets ─────────────────────────
  const judgeIds = [
    "judge-alpha", "judge-beta", "judge-gamma", "judge-delta", "judge-epsilon"
  ];
  console.log("=== Judge lock status ===");
  for (const jid of judgeIds) {
    try {
      const tokenId = await ir.getCurrentTokenId(jid);
      const wallet  = await ir.getAgentWalletByTokenId(tokenId);
      const stake   = await staking.stakes(wallet);
      const locked  = await staking.isLocked(wallet);
      const lockedUntil = Number(stake.lockedUntil);
      const remaining   = lockedUntil > now ? lockedUntil - now : 0;
      console.log(
        `  ${jid.padEnd(15)} tokenId=${tokenId}  wallet=${wallet}` +
        `  locked=${locked}  unlocks_in=${remaining}s` +
        (locked ? `  (${new Date(lockedUntil * 1000).toISOString()})` : "")
      );
    } catch (e) {
      console.log(`  ${jid.padEnd(15)} — not found: ${e.message}`);
    }
  }
  console.log();

  // ── 2. Find stuck tasks via JudgesAssigned events (last 1800 blocks) ────────
  console.log("=== Scanning for stuck tasks (last 1800 blocks) ===");
  const latestBlock = await ethers.provider.getBlockNumber();
  const fromBlock   = Math.max(0, latestBlock - 1800);

  let assignedEvents = [];
  try {
    assignedEvents = await vr.queryFilter(vr.filters.JudgesAssigned(), fromBlock, latestBlock);
  } catch (e) {
    console.log(`  queryFilter failed: ${e.message}`);
  }

  if (assignedEvents.length === 0) {
    console.log("  No JudgesAssigned events found in range.");
  }

  // Also scan ValidationRequested events for PENDING orphans
  let requestedEvents = [];
  try {
    requestedEvents = await vr.queryFilter(vr.filters.ValidationRequested?.() ?? [], fromBlock, latestBlock);
  } catch (_) {}

  // Merge task IDs from both event types
  const allTaskIds = new Set([
    ...assignedEvents.map(e => e.args.taskId),
    ...requestedEvents.map(e => e.args.taskId),
  ]);

  let expired = 0;
  for (const taskId of allTaskIds) {
    let task;
    try {
      task = await vr.getTask(taskId);
    } catch (e) {
      continue; // already gone
    }

    const status     = Number(task.status);
    const statusName = STATUS[status] || String(status);
    const commitDl   = Number(task.commitDeadline);

    const canExpire =
      (status === 1 && now > commitDl) ||  // COMMITTING + deadline passed
      (status === 2 && now > Number(task.revealDeadline)); // REVEALING + deadline passed

    const canAdminCancel = (status === 0); // PENDING — assignJudges never succeeded

    console.log(
      `  task=${taskId}  status=${statusName}` +
      (commitDl ? `  commitDl=${new Date(commitDl * 1000).toISOString()}` : "") +
      `  canExpire=${canExpire}  canAdminCancel=${canAdminCancel}`
    );

    if (canExpire) {
      console.log(`  → expireTask(${taskId}) ...`);
      try {
        const tx = await vr.expireTask(taskId, { gasLimit: 500_000 });
        const receipt = await tx.wait();
        console.log(`  ✓ expireTask OK  tx=${receipt.hash}`);
        expired++;
      } catch (e) {
        console.log(`  ✗ expireTask failed: ${e.message}`);
      }
    } else if (canAdminCancel) {
      console.log(`  → adminCancelPendingTask(${taskId}) ...`);
      try {
        const tx = await vr.adminCancelPendingTask(taskId, { gasLimit: 300_000 });
        const receipt = await tx.wait();
        console.log(`  ✓ adminCancelPendingTask OK  tx=${receipt.hash}`);
        expired++;
      } catch (e) {
        console.log(`  ✗ adminCancelPendingTask failed: ${e.message}`);
      }
    }
  }

  console.log(`\nDone. ${expired} task(s) cleaned up.`);
  if (expired > 0) {
    console.log("Judges should now be unlocked — retry the validation.");
  } else {
    console.log("No stuck tasks found. If judges are still locked, wait for the 30-min window to pass.");
  }
}

main().catch(e => { console.error(e); process.exit(1); });
