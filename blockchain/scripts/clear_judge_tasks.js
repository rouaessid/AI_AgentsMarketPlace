/**
 * clear_judge_tasks.js
 *
 * Finds tasks assigned to judges alpha/delta/epsilon (tokenIds 2,5,6)
 * that are stuck in COMMITTING or REVEALING with expired deadlines.
 * Scans back up to 50,000 blocks in 1800-block chunks.
 *
 * Usage:
 *   npx hardhat run scripts/clear_judge_tasks.js --network baseSepolia
 */
const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

const STATUS = ["PENDING", "COMMITTING", "REVEALING", "FINALISED", "EXPIRED", "DISPUTED"];

async function main() {
  const deployment = JSON.parse(
    fs.readFileSync(path.join(__dirname, "../deployments/deployment.json"), "utf8")
  );

  const vrAddr = deployment.contracts.ValidationRegistry.address;
  const vr     = await ethers.getContractAt("ValidationRegistry", vrAddr);

  const now          = Math.floor(Date.now() / 1000);
  const latestBlock  = await ethers.provider.getBlockNumber();
  const CHUNK        = 1800;
  const MAX_LOOKBACK = 50000;
  const fromBlock    = Math.max(0, latestBlock - MAX_LOOKBACK);

  console.log(`Latest block : ${latestBlock}`);
  console.log(`Scanning from: ${fromBlock}  (${MAX_LOOKBACK} blocks back)`);
  console.log(`Chunk size   : ${CHUNK}\n`);

  // Collect all unique task IDs from JudgesAssigned + ValidationRequested
  const taskIds = new Set();
  let chunk = fromBlock;

  while (chunk <= latestBlock) {
    const to = Math.min(chunk + CHUNK - 1, latestBlock);
    try {
      const evts = await vr.queryFilter(vr.filters.JudgesAssigned(), chunk, to);
      for (const e of evts) taskIds.add(e.args.taskId);
    } catch (_) {}
    try {
      const evts2 = await vr.queryFilter(vr.filters.ValidationRequested?.() ?? [], chunk, to);
      for (const e of evts2) taskIds.add(e.args.taskId);
    } catch (_) {}
    process.stdout.write(`\r  Scanned up to block ${to} — ${taskIds.size} tasks found so far`);
    chunk += CHUNK;
  }
  console.log("\n");

  if (taskIds.size === 0) {
    console.log("No tasks found in range.");
    return;
  }

  console.log(`=== Checking ${taskIds.size} tasks ===\n`);

  // Stuck judges tokenIds
  const stuckJudges = new Set([2n, 5n, 6n]);
  let expired = 0;
  let cancelled = 0;

  for (const taskId of taskIds) {
    let task;
    try { task = await vr.getTask(taskId); } catch (_) { continue; }

    const status    = Number(task.status);
    const statusName = STATUS[status] || String(status);

    // Only care about COMMITTING(1) and REVEALING(2)
    if (status !== 1 && status !== 2) continue;

    const commitDl = Number(task.commitDeadline);
    const revealDl = Number(task.revealDeadline);

    // Check if any stuck judge is in this task
    const judges = task.judgeTokenIds || [];
    const hasStuck = judges.some(j => stuckJudges.has(BigInt(j)));

    if (!hasStuck) continue;

    const dl         = status === 1 ? commitDl : revealDl;
    const canExpire  = now > dl;
    const remaining  = canExpire ? 0 : dl - now;
    const dlStr      = new Date(dl * 1000).toISOString();

    console.log(`  task=${taskId}`);
    console.log(`    status=${statusName}  deadline=${dlStr}  canExpire=${canExpire}  remaining=${remaining}s`);
    console.log(`    judges=${judges.map(j => j.toString()).join(", ")}`);

    if (canExpire) {
      console.log(`    → expireTask ...`);
      try {
        const tx = await vr.expireTask(taskId, { gasLimit: 500_000 });
        const rcpt = await tx.wait();
        console.log(`    ✓ expireTask OK  tx=${rcpt.hash}`);
        expired++;
      } catch (e) {
        console.log(`    ✗ expireTask failed: ${e.message}`);
      }
    } else {
      console.log(`    ⏳ deadline not yet passed — wait ${remaining}s`);
    }
  }

  // Also handle PENDING tasks (assignJudges never finished)
  for (const taskId of taskIds) {
    let task;
    try { task = await vr.getTask(taskId); } catch (_) { continue; }
    if (Number(task.status) !== 0) continue;

    console.log(`  task=${taskId}  status=PENDING → adminCancelPendingTask ...`);
    try {
      const tx = await vr.adminCancelPendingTask(taskId, { gasLimit: 300_000 });
      const rcpt = await tx.wait();
      console.log(`    ✓ cancelled  tx=${rcpt.hash}`);
      cancelled++;
    } catch (e) {
      console.log(`    ✗ cancel failed: ${e.message}`);
    }
  }

  console.log(`\nDone. expired=${expired}  cancelled=${cancelled}`);
  if (expired + cancelled > 0) {
    console.log("Re-check judges:");
    console.log("  npx hardhat run scripts/check_judges.js --network baseSepolia");
  }
}

main().catch(e => { console.error(e); process.exit(1); });
