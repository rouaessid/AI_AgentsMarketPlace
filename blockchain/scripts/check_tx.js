const { ethers } = require("hardhat");
async function main() {
  const txHash = "0x9d4567260c908bcf95c677d6f19d0fa0287036f4f9a5fe03c824b8e119185499";
  try {
    const receipt = await ethers.provider.getTransactionReceipt(txHash);
    if (!receipt) { console.log("TX NOT FOUND on chain"); return; }
    console.log("status:", receipt.status === 1 ? "SUCCESS" : "REVERTED");
    console.log("to:", receipt.to);
    console.log("gasUsed:", receipt.gasUsed.toString());
    console.log("logs:", receipt.logs.length, "events emitted");
  } catch(e) { console.log("Error:", e.message); }
}
main().catch(console.error);
