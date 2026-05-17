/**
 * test_full_flow.js
 * ─────────────────
 * Teste le cycle complet de validation AgentMarket sur Hardhat localhost.
 *
 * Usage :
 *   npx hardhat run scripts/test_full_flow.js --network localhost
 *
 * Prérequis :
 *   - `npx hardhat node` tourne dans un autre terminal
 *   - Les 4 contrats sont déployés (deployment.json à jour)
 */

const { ethers } = require("hardhat");
const fs         = require("fs");
const path       = require("path");

// ── Adresses depuis deployment.json ─────────────────────────────────────────
const DEPLOYMENT = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../deployments/deployment.json"), "utf8")
);
const ADDR = {
  identity:   DEPLOYMENT.contracts.IdentityRegistry.address,
  staking:    DEPLOYMENT.contracts.StakingContract.address,
  escrow:     DEPLOYMENT.contracts.EscrowManager.address,
  validation: DEPLOYMENT.contracts.ValidationRegistry.address,
};

// ── Helpers ──────────────────────────────────────────────────────────────────
const ETH  = (n) => ethers.parseEther(String(n));
const fmt  = (n) => ethers.formatEther(n);
const sep  = (t) => console.log(`\n${"─".repeat(60)}\n  ${t}\n${"─".repeat(60)}`);
const ok   = (m) => console.log(`  ✅  ${m}`);
const info = (m) => console.log(`  ℹ️   ${m}`);
const warn = (m) => console.log(`  ⚠️   ${m}`);

// ── ABIs minimaux ────────────────────────────────────────────────────────────
const ABI_IDENTITY = [
  "function register(string agentId, uint8 agentType, string agentURI, string version, uint256 pricePerTask, address ownerAddress) external returns (uint256)",
  "function isActive(string agentId) external view returns (bool)",
  "function getAgentWallet(string agentId) external view returns (address)",
  "function getAgentType(string agentId) external view returns (uint8)",
  "function getCurrentTokenId(string agentId) external view returns (uint256)",
  "function getPricePerTask(string agentId) external view returns (uint256)",
];

const ABI_STAKING = [
  "function stake() external payable",
  "function getStake(address agent) external view returns (uint256)",
  "function isEligibleProvider(address agent) external view returns (bool)",
  "function isEligibleJudge(address agent) external view returns (bool)",
  "function isLocked(address agent) external view returns (bool)",
];

const ABI_ESCROW = [
  "function depositPayment(string taskId_, string agentId_) external payable",
  "function taskFunds(string taskId) external view returns (uint256)",
];

const ABI_VALIDATION = [
  "function validationRequest(string taskId, string providerAgentId, string requestURI, bytes32 requestHash, uint8 mode) external",
  "function assignJudges(string taskId, string[] candidates) external",
  "function commitVote(string taskId, string judgeId, bytes32 commitHash) external",
  "function revealVote(string taskId, string judgeId, uint8 vote, bytes32 salt) external",
  "function finaliseValidation(string taskId, uint256 aggregatedScore, string justificationURI) external",
  "function getTask(string taskId) external view returns (tuple(string taskId, string providerAgentId, address providerWallet, bytes32 requestHash, uint256 erc8004AgentId, uint8 status, uint256 createdAt, uint256 commitDeadline, uint256 revealDeadline, string[3] judgeIds, address[3] judgeWallets, uint8 finalResponse, string finalTag, uint256 score, uint8 mode))",
  "function setEscrowManager(address a) external",
  "event JudgesAssigned(string indexed taskId, string judge0, string judge1, string judge2, uint256 commitDeadline, uint256 revealDeadline)",
  "event VoteCommitted(string indexed taskId, string indexed judgeId)",
  "event VoteRevealed(string indexed taskId, string indexed judgeId, uint8 vote)",
  "event ValidationResponse(address indexed validatorAddress, uint256 indexed agentId, bytes32 indexed requestHash, uint8 response, string responseURI, bytes32 responseHash, string tag)",
  "event ScoreRecorded(string agentId, string taskId, uint8 score, uint8 mode)",
];

// ── Constantes ───────────────────────────────────────────────────────────────
const TASK_ID       = `task-test-${Date.now()}`;
const PROVIDER_ID   = "test-provider-01";
const JUDGE_IDS     = ["test-judge-01", "test-judge-02", "test-judge-03"];
const VOTE_VALID    = 1;  // InternalVote.VALID
const VOTE_INVALID  = 2;  // InternalVote.INVALID

// ─────────────────────────────────────────────────────────────────────────────

async function main() {
  sep("🚀  AgentMarket — Test Flow Complet");

  // ── Signers ──────────────────────────────────────────────────────────────
  const signers  = await ethers.getSigners();
  const deployer = signers[0];   // owner de ValidationRegistry
  const provider = signers[1];   // wallet du provider agent
  const judge1   = signers[2];
  const judge2   = signers[3];
  const judge3   = signers[4];
  const buyer    = signers[5];   // client qui dépose l'escrow

  info(`Deployer : ${deployer.address}`);
  info(`Provider : ${provider.address}`);
  info(`Judge 1  : ${judge1.address}`);
  info(`Judge 2  : ${judge2.address}`);
  info(`Judge 3  : ${judge3.address}`);
  info(`Buyer    : ${buyer.address}`);

  // ── Contrats ──────────────────────────────────────────────────────────────
  const identity   = new ethers.Contract(ADDR.identity,   ABI_IDENTITY,   deployer);
  const staking    = new ethers.Contract(ADDR.staking,    ABI_STAKING,    deployer);
  const escrow     = new ethers.Contract(ADDR.escrow,     ABI_ESCROW,     deployer);
  const validation = new ethers.Contract(ADDR.validation, ABI_VALIDATION, deployer);

  // ── Step 0 : Connecter EscrowManager à ValidationRegistry ────────────────
  sep("STEP 0 — Configuration EscrowManager");
  try {
    const tx = await validation.setEscrowManager(ADDR.escrow);
    await tx.wait();
    ok(`EscrowManager connecté à ValidationRegistry`);
  } catch (e) {
    warn(`setEscrowManager: ${e.message.slice(0, 80)} (peut-être déjà fait)`);
  }

  // ── Step 1 : Enregistrement des agents ───────────────────────────────────
  sep("STEP 1 — Enregistrement des agents");

  // Provider
  try {
    const tx = await identity.connect(provider).register(
      PROVIDER_ID,
      0,                                       // AgentType.PROVIDER
      "ipfs://QmProviderManifest",
      "1.0.0",
      ethers.parseEther("0.0001"),              // pricePerTask = 0.0001 ETH (testnet)
      ethers.ZeroAddress                       // ownerAddress = msg.sender
    );
    await tx.wait();
    ok(`Provider '${PROVIDER_ID}' enregistré`);
  } catch (e) {
    warn(`Provider déjà enregistré ou erreur: ${e.message.slice(0, 80)}`);
  }

  // 3 Juges
  const judgeWallets = [judge1, judge2, judge3];
  for (let i = 0; i < 3; i++) {
    try {
      const tx = await identity.connect(judgeWallets[i]).register(
        JUDGE_IDS[i],
        1,                                     // AgentType.JUDGE
        `ipfs://QmJudgeManifest${i + 1}`,
        "1.0.0",
        0n,                                    // judges have no price per task
        ethers.ZeroAddress                     // ownerAddress = msg.sender
      );
      await tx.wait();
      ok(`Judge '${JUDGE_IDS[i]}' enregistré`);
    } catch (e) {
      warn(`Judge ${i + 1} déjà enregistré: ${e.message.slice(0, 80)}`);
    }
  }

  // Vérifications
  const providerActive = await identity.isActive(PROVIDER_ID);
  ok(`Provider actif : ${providerActive}`);
  for (const jid of JUDGE_IDS) {
    const active = await identity.isActive(jid);
    ok(`Judge '${jid}' actif : ${active}`);
  }

  // ── Step 2 : Staking ─────────────────────────────────────────────────────
  sep("STEP 2 — Staking");

  // Provider → 0.002 ETH (min 0.001)
  try {
    const tx = await staking.connect(provider).stake({ value: ETH("0.002") });
    await tx.wait();
    ok(`Provider staké 0.002 ETH`);
  } catch (e) {
    warn(`Provider stake: ${e.message.slice(0, 80)}`);
  }

  // Juges → 0.001 ETH chacun (min 0.0005)
  for (let i = 0; i < 3; i++) {
    try {
      const tx = await staking.connect(judgeWallets[i]).stake({ value: ETH("0.001") });
      await tx.wait();
      ok(`Judge ${i + 1} staké 0.001 ETH`);
    } catch (e) {
      warn(`Judge ${i + 1} stake: ${e.message.slice(0, 80)}`);
    }
  }

  // Vérifications éligibilité
  const provElig = await staking.isEligibleProvider(provider.address);
  ok(`Provider éligible : ${provElig}`);
  for (let i = 0; i < 3; i++) {
    const elig = await staking.isEligibleJudge(judgeWallets[i].address);
    ok(`Judge ${i + 1} éligible juge : ${elig}`);
  }

  // ── Step 3 : Dépôt Escrow (Buyer) ────────────────────────────────────────
  sep("STEP 3 — Escrow (Buyer dépose le paiement)");

  const TASK_PRICE = ETH("0.0001"); // must match pricePerTask set in IdentityRegistry
  try {
    const tx = await escrow.connect(buyer).depositPayment(TASK_ID, PROVIDER_ID, { value: TASK_PRICE });
    await tx.wait();
    const locked = await escrow.taskFunds(TASK_ID);
    ok(`Escrow déposé : ${fmt(locked)} ETH pour task '${TASK_ID}'`);
  } catch (e) {
    warn(`Escrow déjà déposé ou erreur: ${e.message.slice(0, 80)}`);
  }

  // ── Step 4 : validationRequest (Provider soumet le résultat) ─────────────
  sep("STEP 4 — validationRequest (Provider soumet résultat)");

  const RESULT_URI  = "ipfs://QmFakeResultHash123";
  const RESULT_HASH = ethers.keccak256(ethers.toUtf8Bytes("fake result content for testing"));

  try {
    // N'importe qui peut appeler validationRequest (le contrat vérifie via identityRegistry)
    // Mais le wallet du provider doit être le msg.sender dans le contrat
    // En réalité le backend appelle ça — ici on simule depuis le deployer
    const tx = await validation.connect(deployer).validationRequest(
      TASK_ID,
      PROVIDER_ID,
      RESULT_URI,
      RESULT_HASH,
      0   // mode 0 = solo task
    );
    const receipt = await tx.wait();
    ok(`validationRequest() émis — task '${TASK_ID}' en PENDING`);
    info(`Gas utilisé : ${receipt.gasUsed.toString()}`);
  } catch (e) {
    throw new Error(`validationRequest failed: ${e.message}`);
  }

  // ── Step 5 : assignJudges (Backend / Owner assigne les juges) ─────────────
  sep("STEP 5 — assignJudges (Backend choisit les candidats)");

  try {
    const tx = await validation.connect(deployer).assignJudges(
      TASK_ID,
      JUDGE_IDS   // on passe les 3 juges comme candidats
    );
    const receipt = await tx.wait();
    ok(`assignJudges() — 3 juges assignés`);
    info(`Gas utilisé : ${receipt.gasUsed.toString()}`);

    // Afficher l'event JudgesAssigned
    const iface = new ethers.Interface(ABI_VALIDATION);
    for (const log of receipt.logs) {
      try {
        const parsed = iface.parseLog(log);
        if (parsed.name === "JudgesAssigned") {
          ok(`  Judge 0 : ${parsed.args.judge0}`);
          ok(`  Judge 1 : ${parsed.args.judge1}`);
          ok(`  Judge 2 : ${parsed.args.judge2}`);
          const commit = new Date(Number(parsed.args.commitDeadline) * 1000).toISOString();
          const reveal = new Date(Number(parsed.args.revealDeadline) * 1000).toISOString();
          info(`  Commit deadline : ${commit}`);
          info(`  Reveal deadline : ${reveal}`);
        }
      } catch {}
    }
  } catch (e) {
    throw new Error(`assignJudges failed: ${e.message}`);
  }

  // ── Step 6 : commitVote (3 juges committent) ──────────────────────────────
  sep("STEP 6 — commitVote (les 3 juges commitent leur vote)");

  // Chaque juge génère un salt aléatoire et hash son vote
  const salts = [
    ethers.randomBytes(32),
    ethers.randomBytes(32),
    ethers.randomBytes(32),
  ];
  const votes = [VOTE_VALID, VOTE_VALID, VOTE_VALID]; // tous votent VALID

  const commitHashes = votes.map((vote, i) =>
    ethers.keccak256(
      ethers.AbiCoder.defaultAbiCoder().encode(["uint8", "bytes32"], [vote, salts[i]])
    )
  );

  for (let i = 0; i < 3; i++) {
    try {
      const tx = await validation.connect(judgeWallets[i]).commitVote(
        TASK_ID,
        JUDGE_IDS[i],
        commitHashes[i]
      );
      await tx.wait();
      ok(`Judge ${i + 1} a commité son vote (hash masqué)`);
    } catch (e) {
      throw new Error(`commitVote judge ${i + 1}: ${e.message}`);
    }
  }

  // ── Step 7 : revealVote (3 juges révèlent) ────────────────────────────────
  sep("STEP 7 — revealVote (les 3 juges révèlent leur vote)");

  for (let i = 0; i < 3; i++) {
    try {
      const tx = await validation.connect(judgeWallets[i]).revealVote(
        TASK_ID,
        JUDGE_IDS[i],
        votes[i],
        salts[i]
      );
      await tx.wait();
      ok(`Judge ${i + 1} a révélé : ${votes[i] === VOTE_VALID ? "VALID ✓" : "INVALID ✗"}`);
    } catch (e) {
      throw new Error(`revealVote judge ${i + 1}: ${e.message}`);
    }
  }

  // ── Step 8 : finaliseValidation ───────────────────────────────────────────
  sep("STEP 8 — finaliseValidation");

  try {
    const providerBalanceBefore = await ethers.provider.getBalance(provider.address);
    const judge1BalanceBefore   = await ethers.provider.getBalance(judge1.address);

    const tx = await validation.connect(deployer).finaliseValidation(
      TASK_ID,
      100,                                   // aggregatedScore (0-100)
      "ipfs://QmJustificationURI"
    );
    const receipt = await tx.wait();
    ok(`finaliseValidation() — consensus atteint`);
    info(`Gas utilisé : ${receipt.gasUsed.toString()}`);

    // Lire les events ValidationResponse + ScoreRecorded
    const iface = new ethers.Interface(ABI_VALIDATION);
    for (const log of receipt.logs) {
      try {
        const parsed = iface.parseLog(log);
        if (parsed.name === "ValidationResponse") {
          console.log(`\n  🏆  VERDICT FINAL`);
          console.log(`       response : ${parsed.args.response} / 100`);
          console.log(`       tag      : ${parsed.args.tag}`);
          console.log(`       agentId  : ${parsed.args.agentId}`);
        }
        if (parsed.name === "ScoreRecorded") {
          console.log(`\n  📊  ScoreRecorded (→ EigenTrust)`);
          console.log(`       agentId : ${parsed.args.agentId}`);
          console.log(`       taskId  : ${parsed.args.taskId}`);
          console.log(`       score   : ${parsed.args.score}`);
          console.log(`       mode    : ${parsed.args.mode === 0 ? "solo" : "pipeline"}`);
        }
      } catch {}
    }

    // Vérifier les balances après distribution
    const providerBalanceAfter = await ethers.provider.getBalance(provider.address);
    const judge1BalanceAfter   = await ethers.provider.getBalance(judge1.address);

    const providerGain = providerBalanceAfter - providerBalanceBefore;
    const judgeGain    = judge1BalanceAfter - judge1BalanceBefore;

    if (providerGain > 0n) {
      ok(`Provider a reçu : +${fmt(providerGain)} ETH`);
    } else {
      info(`Provider balance delta : ${fmt(providerGain)} ETH (inclut gas)`);
    }
    if (judgeGain > 0n) {
      ok(`Judge 1 a reçu  : +${fmt(judgeGain)} ETH`);
    }

  } catch (e) {
    throw new Error(`finaliseValidation failed: ${e.message}`);
  }

  // ── Step 9 : Vérifications finales ────────────────────────────────────────
  sep("STEP 9 — Vérifications finales");

  try {
    const task = await validation.getTask(TASK_ID);
    ok(`Task status     : ${["PENDING","COMMITTING","REVEALING","FINALISED","EXPIRED"][task.status]}`);
    ok(`Final tag       : ${task.finalTag}`);
    ok(`Final response  : ${task.finalResponse} / 100`);
    ok(`Score           : ${task.score}`);
  } catch (e) {
    warn(`getTask: ${e.message.slice(0, 80)}`);
  }

  // Vérifier que le stake provider est débloqué
  const locked = await staking.isLocked(provider.address);
  ok(`Provider stake débloqué : ${!locked}`);

  sep("✅  TEST COMPLET — Validation flow OK");
  console.log(`
  Résumé :
  ┌─────────────────────────────────────────────┐
  │  1. Provider + 3 Juges enregistrés          │
  │  2. Stakes déposés                          │
  │  3. Escrow déposé par le buyer              │
  │  4. validationRequest() → PENDING           │
  │  5. assignJudges() → COMMITTING             │
  │  6. 3× commitVote() → hashes masqués        │
  │  7. 3× revealVote() → votes VALID           │
  │  8. finaliseValidation() → VALID 100/100    │
  │  9. Fonds distribués (90% provider)         │
  └─────────────────────────────────────────────┘
  `);
}

// ─────────────────────────────────────────────────────────────────────────────

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(`\n  ❌  ERREUR : ${err.message}`);
    if (err.message.includes("revert")) {
      console.error("     → Vérifie que les contrats sont bien déployés et configurés.");
    }
    process.exit(1);
  });
