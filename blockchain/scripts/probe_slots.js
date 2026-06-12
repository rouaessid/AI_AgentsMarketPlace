/**
 * probe_slots.js — Find the correct slot for judgeAuthorized and _judgeActiveTask
 * by probing all slots 0..25 until judgeAuthorized[2] reads as true.
 *
 * Usage:
 *   npx hardhat run scripts/probe_slots.js --network baseSepolia
 */
const { ethers } = require("hardhat");
const fs   = require("fs");
const path = require("path");

async function main() {
  const deployment = JSON.parse(
    fs.readFileSync(path.join(__dirname, "../deployments/deployment.json"), "utf8")
  );
  const vrAddr  = deployment.contracts.ValidationRegistry.address;
  const provider = ethers.provider;

  console.log(`ValidationRegistry: ${vrAddr}\n`);
  console.log("Probing slots for judgeAuthorized[2] (expected = true)...\n");

  let foundAuthSlot = null;

  for (let s = 0; s <= 25; s++) {
    const encoded = ethers.AbiCoder.defaultAbiCoder().encode(
      ["uint256", "uint256"], [2n, BigInt(s)]
    );
    const slot = ethers.keccak256(encoded);
    const raw  = await provider.getStorage(vrAddr, slot);
    const val  = BigInt(raw) !== 0n;
    if (val) {
      console.log(`  ✓ slot ${s}: judgeAuthorized[2] = TRUE`);
      foundAuthSlot = s;
    } else {
      process.stdout.write(`  slot ${s}: false\n`);
    }
  }

  if (foundAuthSlot === null) {
    console.log("\n⚠ Could not find judgeAuthorized slot. Possible issue with address.");
    return;
  }

  console.log(`\n→ judgeAuthorized is at slot ${foundAuthSlot}`);

  // _judgeActiveTask is 4 slots after judgeAuthorized based on layout:
  // judgeAuthorized, _tasks, _taskExists, _commits, _judgeActiveTask
  // So _judgeActiveTask = foundAuthSlot + 4
  console.log(`→ Probing _judgeActiveTask slots (${foundAuthSlot+1} to ${foundAuthSlot+6})...\n`);

  for (let delta = 1; delta <= 6; delta++) {
    const slot_n = foundAuthSlot + delta;
    for (const tid of [2n, 5n, 6n]) {
      const encoded = ethers.AbiCoder.defaultAbiCoder().encode(
        ["uint256", "uint256"], [tid, BigInt(slot_n)]
      );
      const slot = ethers.keccak256(encoded);
      const raw  = await provider.getStorage(vrAddr, slot);
      const lastByte = parseInt(raw.slice(-2), 16);
      if (lastByte !== 0) {
        const len = lastByte / 2;
        const str = Buffer.from(raw.slice(2, 2 + len * 2), "hex").toString("utf8");
        console.log(`  slot ${slot_n}, judge[${tid}]: "${str}"  ← FOUND`);
      } else {
        console.log(`  slot ${slot_n}, judge[${tid}]: (empty)`);
      }
    }
  }
}

main().catch(e => { console.error(e); process.exit(1); });
