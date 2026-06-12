/**
 * force_expire_judges.js
 *
 * Reads _judgeActiveTask from raw blockchain storage to find the exact taskIds
 * assigned to judges alpha(2), delta(5), epsilon(6), then expires them.
 *
 * Usage:
 *   npx hardhat run scripts/force_expire_judges.js --network baseSepolia
 */
const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

const STATUS = ["PENDING","COMMITTING","REVEALING","FINALISED","EXPIRED","DISPUTED"];

// ── Storage layout for ValidationRegistry (OZ v5 Ownable + ReentrancyGuard) ──
//   slot 0  : _owner         (Ownable)
//   slot 1  : _status        (ReentrancyGuard)
//   slot 2  : identityRegistry
//   slot 3  : stakingContract
//   slot 4  : escrowManager
//   slot 5  : _agentSoloTotal
//   slot 6  : _agentSoloCount
//   slot 7  : _agentPipelineTotal
//   slot 8  : _agentPipelineCount
//   slot 9  : judgeAgreements
//   slot 10 : judgeTotalVotes
//   slot 11 : judgeAuthorized
//   slot 12 : _tasks
//   slot 13 : _taskExists
//   slot 14 : _commits
//   slot 15 : _judgeActiveTask   ← target
//   slot 16 : _validationRecords

// Probed: judgeAuthorized=slot10, so _judgeActiveTask = slot10+4 = slot14
const JUDGE_ACTIVE_TASK_SLOT = 14n;

function decodeShortString(raw32) {
  // raw32 is a 0x-prefixed 64-char hex string (32 bytes)
  const buf = Buffer.from(raw32.slice(2), "hex");
  const lastByte = buf[31];
  // Short string: lastByte = length * 2 (even), long string: lastByte & 1 == 1
  if (lastByte === 0) return null; // empty
  if ((lastByte & 1) === 0) {
    // short string
    const len = lastByte / 2;
    return buf.slice(0, len).toString("utf8");
  } else {
    // long string — length encoded differently, unlikely for taskIds
    const len = (BigInt("0x" + buf.toString("hex")) - 1n) / 2n;
    return `<long string, len=${len}>`; // handle separately if needed
  }
}

async function readJudgeActiveTask(provider, vrAddr, judgeTokenId) {
  // slot = keccak256(abi.encode(judgeTokenId, JUDGE_ACTIVE_TASK_SLOT))
  const encoded = ethers.AbiCoder.defaultAbiCoder().encode(
    ["uint256", "uint256"],
    [judgeTokenId, JUDGE_ACTIVE_TASK_SLOT]
  );
  const slot = ethers.keccak256(encoded);
  const raw  = await provider.getStorage(vrAddr, slot);
  return decodeShortString(raw);
}

async function main() {
  const deployment = JSON.parse(
    fs.readFileSync(path.join(__dirname, "../deployments/deployment.json"), "utf8")
  );
  const vrAddr = deployment.contracts.ValidationRegistry.address;
  const vr     = await ethers.getContractAt("ValidationRegistry", vrAddr);
  const provider = ethers.provider;
  const now    = Math.floor(Date.now() / 1000);

  // Verify slot by reading judgeAuthorized[2] (known true → slot 10 per probe)
  const AUTH_SLOT = 10n;
  const authEncoded = ethers.AbiCoder.defaultAbiCoder().encode(
    ["uint256", "uint256"], [2n, AUTH_SLOT]
  );
  const authSlot = ethers.keccak256(authEncoded);
  const authRaw  = await provider.getStorage(vrAddr, authSlot);
  const authVal  = BigInt(authRaw) !== 0n;
  console.log(`Slot verification: judgeAuthorized[2] from storage = ${authVal} (expected true)`);
  if (!authVal) {
    console.error("⚠ Slot offset may be wrong! judgeAuthorized[2] should be true.");
    console.log("Trying offset +1...");
    // Try slot 12 for judgeAuthorized
    const AUTH_SLOT2 = 12n;
    const ae2 = ethers.AbiCoder.defaultAbiCoder().encode(["uint256","uint256"],[2n,AUTH_SLOT2]);
    const as2 = ethers.keccak256(ae2);
    const ar2 = await provider.getStorage(vrAddr, as2);
    console.log(`judgeAuthorized[2] at slot 12 = ${BigInt(ar2) !== 0n}`);
  }
  console.log();

  // Read _judgeActiveTask for stuck judges
  const stuckJudgeIds = [2n, 5n, 6n];
  const judgeNames    = { 2n: "judge-alpha", 5n: "judge-delta", 6n: "judge-epsilon" };

  const taskIds = new Set();
  console.log("=== Reading _judgeActiveTask from storage ===");
  for (const tokenId of stuckJudgeIds) {
    const taskId = await readJudgeActiveTask(provider, vrAddr, tokenId);
    console.log(`  ${judgeNames[tokenId]} (tokenId=${tokenId}): _judgeActiveTask = "${taskId}"`);
    if (taskId) taskIds.add(taskId);
  }
  console.log();

  if (taskIds.size === 0) {
    console.log("✓ No active tasks found in storage — judges should be eligible.");
    console.log("  If check_judges still shows them stuck, the storage slot may be off by 1.");
    console.log("  Re-run with --slot-probe flag or contact dev.");
    return;
  }

  // Try to expire/cancel each found task
  console.log(`=== Processing ${taskIds.size} stuck task(s) ===`);
  for (const taskId of taskIds) {
    let task;
    try { task = await vr.getTask(taskId); }
    catch (e) {
      console.log(`  task=${taskId} → getTask failed: ${e.message}`);
      continue;
    }

    const status    = Number(task.status);
    const statusName = STATUS[status] || String(status);
    const commitDl  = Number(task.commitDeadline);
    const revealDl  = Number(task.revealDeadline);

    console.log(`  task=${taskId}  status=${statusName}`);
    if (commitDl) console.log(`    commitDeadline=${new Date(commitDl*1000).toISOString()}  now=${new Date(now*1000).toISOString()}`);

    if (status === 0) {
      // PENDING — adminCancelPendingTask
      console.log(`    → adminCancelPendingTask...`);
      try {
        const tx   = await vr.adminCancelPendingTask(taskId, { gasLimit: 300_000 });
        const rcpt = await tx.wait();
        console.log(`    ✓ cancelled  tx=${rcpt.hash}`);
      } catch (e) {
        console.log(`    ✗ cancel failed: ${e.message}`);
      }
    } else if (status === 1 || status === 2) {
      const dl       = status === 1 ? commitDl : revealDl;
      const canExpire = now > dl;
      if (canExpire) {
        console.log(`    → expireTask...`);
        try {
          const tx   = await vr.expireTask(taskId, { gasLimit: 500_000 });
          const rcpt = await tx.wait();
          console.log(`    ✓ expired  tx=${rcpt.hash}`);
        } catch (e) {
          console.log(`    ✗ expireTask failed: ${e.message}`);
          // If slashing the shared wallet fails, try adminForceSetTaskExpired
          console.log(`    Hint: shared wallet may cause slash issue. Try adminCancelPendingTask if task is still PENDING.`);
        }
      } else {
        const remaining = dl - now;
        console.log(`    ⏳ deadline not yet passed — wait ${remaining}s (${(remaining/60).toFixed(1)} min)`);
        console.log(`    Commit window is 5 minutes — come back after ${new Date(dl*1000).toISOString()}`);
      }
    } else {
      console.log(`    Task is already ${statusName} — but _judgeActiveTask still set?`);
      console.log(`    This may indicate a contract state inconsistency.`);
    }
  }

  console.log("\nDone. Re-run check_judges.js to verify.");
}

main().catch(e => { console.error(e); process.exit(1); });
