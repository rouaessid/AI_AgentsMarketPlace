// test/ValidationRegistry.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Tests complets de ValidationRegistry
// Framework : Hardhat + ethers v6 + chai
//
// Architecture refactorisée : tous les agents sont référencés par tokenId (uint256)
// commit-reveal inclut 4 sous-scores (taskCompletion, outputQuality, noFabrication, toolUsage)
// Score agrégé calculé on-chain — finaliseValidation ne prend plus de score externe
//
// Couverture :
//   ✓ Deploy & configuration
//   ✓ validationRequest (étape 1) — tokenId-based
//   ✓ assignJudges      (étape 2) — candidates sont des tokenIds uint256
//   ✓ commitVote        (étape 3) — hash inclut les 4 sous-scores
//   ✓ revealVote        (étape 4) — 4 sous-scores révélés
//   ✓ finaliseValidation (étape 5) → VALID / INVALID / DISPUTED
//   ✓ expireTask
//   ✓ Score agrégé calculé on-chain (getAgentScore)
//   ✓ Slash provider et juges déviants
//   ✓ Cas d'erreur (wrong status, wrong wallet, bad reveal, etc.)
// ─────────────────────────────────────────────────────────────────────────────

const { ethers } = require("hardhat");
const { expect } = require("chai");
const { time } = require("@nomicfoundation/hardhat-network-helpers");

// ── Constantes ────────────────────────────────────────────────────────────────

const VOTE_VALID   = 1;
const VOTE_INVALID = 2;

// Fenêtres du contrat (5 minutes chacune)
const COMMIT_WINDOW = 300;
const REVEAL_WINDOW = 300;

// TokenIds des agents du stub
const PROVIDER_TOKEN_ID = 1n;
const JUDGE_TOKEN_IDS   = [10n, 11n, 12n];

// Sous-scores par défaut (0-25 chacun, somme = 80/100)
const DEFAULT_SCORES = { tc: 20, oq: 20, nf: 20, tu: 20 };

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Calcule le commitHash d'un juge.
 * Encode : vote + 4 sous-scores + salt → keccak256
 */
function makeCommitHash(vote, tc, oq, nf, tu, salt) {
  return ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(
      ["uint8", "uint8", "uint8", "uint8", "uint8", "bytes32"],
      [vote, tc, oq, nf, tu, salt]
    )
  );
}

// ── Fixture ───────────────────────────────────────────────────────────────────

async function deployFixture() {
  const signers = await ethers.getSigners();
  const [owner, providerOwner, judge0, judge1, judge2, platformWallet, other] = signers;

  // ── Stubs ─────────────────────────────────────────────────────────────────
  const IdentityStubFactory = await ethers.getContractFactory("IdentityRegistryStub");
  const identityStub = await IdentityStubFactory.deploy();
  await identityStub.waitForDeployment();

  const StakingStubFactory = await ethers.getContractFactory("StakingContractStub");
  const stakingStub = await StakingStubFactory.deploy();
  await stakingStub.waitForDeployment();

  const EscrowStubFactory = await ethers.getContractFactory("EscrowManagerStub");
  const escrowStub = await EscrowStubFactory.deploy();
  await escrowStub.waitForDeployment();

  // ── ValidationRegistry ───────────────────────────────────────────────────
  // Constructor ne prend plus que 2 arguments (plus de reputationRegistry)
  const ValidationFactory = await ethers.getContractFactory("ValidationRegistry");
  const validation = await ValidationFactory.deploy(
    await identityStub.getAddress(),
    await stakingStub.getAddress()
  );
  await validation.waitForDeployment();

  await validation.setEscrowManager(await escrowStub.getAddress());
  await stakingStub.setValidationRegistry(await validation.getAddress());

  // ── Enregistrer agents dans le stub (tokenId-based) ──────────────────────
  // Provider : tokenId = 1, type 0 = PROVIDER
  await identityStub.registerAgent("provider-1", 0, providerOwner.address, 1);
  // Judges : type 1 = JUDGE
  await identityStub.registerAgent("judge-0", 1, judge0.address, 10);
  await identityStub.registerAgent("judge-1", 1, judge1.address, 11);
  await identityStub.registerAgent("judge-2", 1, judge2.address, 12);

  // ── Autoriser les juges via honeypot (requis par assignJudges) ───────────
  await validation.connect(owner).recordHoneypotResult(10, true, "ipfs://honeypot-0");
  await validation.connect(owner).recordHoneypotResult(11, true, "ipfs://honeypot-1");
  await validation.connect(owner).recordHoneypotResult(12, true, "ipfs://honeypot-2");

  const CANDIDATES = [10n, 11n, 12n]; // tokenIds des juges

  return {
    validation,
    identityStub,
    stakingStub,
    escrowStub,
    owner,
    providerOwner,
    judge0,
    judge1,
    judge2,
    platformWallet,
    other,
    CANDIDATES,
  };
}

// ── Helpers de flow ──────────────────────────────────────────────────────────

async function doRequest(validation, providerOwner, taskId = "task-1") {
  const requestHash = ethers.keccak256(ethers.toUtf8Bytes("result-payload-" + taskId));
  const traceHash   = ethers.keccak256(ethers.toUtf8Bytes("trace-" + taskId));
  await validation.connect(providerOwner).validationRequest(
    taskId,
    PROVIDER_TOKEN_ID, // tokenId du provider (uint256)
    "ipfs://QmResult",
    requestHash,
    traceHash,
    0              // mode 0 = solo
  );
  return requestHash;
}

async function doAssign(validation, owner, taskId, candidates) {
  await validation.connect(owner).assignJudges(taskId, candidates);
}

async function doCommit(validation, judge, judgeTokenId, taskId, vote, salt, scores = DEFAULT_SCORES) {
  const commitHash = makeCommitHash(vote, scores.tc, scores.oq, scores.nf, scores.tu, salt);
  await validation.connect(judge).commitVote(taskId, judgeTokenId, commitHash);
  return commitHash;
}

async function doReveal(validation, judge, judgeTokenId, taskId, vote, salt, scores = DEFAULT_SCORES) {
  await validation.connect(judge).revealVote(
    taskId, judgeTokenId, vote, salt,
    scores.tc, scores.oq, scores.nf, scores.tu
  );
}

async function fullFlow(ctx, votes = [VOTE_VALID, VOTE_VALID, VOTE_INVALID]) {
  const { validation, owner, providerOwner, judge0, judge1, judge2, CANDIDATES } = ctx;
  const taskId = "task-full";
  const salts  = [ethers.randomBytes(32), ethers.randomBytes(32), ethers.randomBytes(32)];

  const requestHash = await doRequest(validation, providerOwner, taskId);
  await doAssign(validation, owner, taskId, CANDIDATES);

  await doCommit(validation, judge0, 10n, taskId, votes[0], salts[0]);
  await doCommit(validation, judge1, 11n, taskId, votes[1], salts[1]);
  await doCommit(validation, judge2, 12n, taskId, votes[2], salts[2]);
  // Tous committé → status = REVEALING automatiquement

  await doReveal(validation, judge0, 10n, taskId, votes[0], salts[0]);
  await doReveal(validation, judge1, 11n, taskId, votes[1], salts[1]);
  await doReveal(validation, judge2, 12n, taskId, votes[2], salts[2]);

  return { taskId, requestHash, salts };
}

// ═════════════════════════════════════════════════════════════════════════════
//  TESTS
// ═════════════════════════════════════════════════════════════════════════════

describe("ValidationRegistry", function () {

  // ── Deploy ─────────────────────────────────────────────────────────────────
  describe("Deployment", function () {
    it("stores sibling addresses", async function () {
      const ctx = await deployFixture();
      expect(await ctx.validation.identityRegistry())
        .to.equal(await ctx.identityStub.getAddress());
      expect(await ctx.validation.stakingContract())
        .to.equal(await ctx.stakingStub.getAddress());
    });

    it("reverts if any sibling is address(0)", async function () {
      const F    = await ethers.getContractFactory("ValidationRegistry");
      const rand = ethers.Wallet.createRandom().address;
      const dummy = await F.deploy(rand, rand);
      await expect(F.deploy(ethers.ZeroAddress, rand))
        .to.be.revertedWithCustomError(dummy, "ZeroAddress");
      await expect(F.deploy(rand, ethers.ZeroAddress))
        .to.be.revertedWithCustomError(dummy, "ZeroAddress");
    });

    it("owner is deployer", async function () {
      const ctx = await deployFixture();
      expect(await ctx.validation.owner()).to.equal(ctx.owner.address);
    });
  });

  // ── Step 1 : validationRequest ────────────────────────────────────────────
  describe("validationRequest", function () {
    it("creates task and emits ValidationRequest (ERC-8004)", async function () {
      const ctx = await deployFixture();
      const requestHash = ethers.keccak256(ethers.toUtf8Bytes("payload"));
      const traceHash   = ethers.keccak256(ethers.toUtf8Bytes("trace"));

      await expect(
        ctx.validation.connect(ctx.providerOwner).validationRequest(
          "task-1", PROVIDER_TOKEN_ID, "ipfs://QmResult", requestHash, traceHash, 0
        )
      )
        .to.emit(ctx.validation, "ValidationRequest")
        .withArgs(await ctx.validation.getAddress(), PROVIDER_TOKEN_ID, "ipfs://QmResult", requestHash);
    });

    it("task status is PENDING after request", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      const task = await ctx.validation.getTask("task-1");
      expect(task.status).to.equal(0); // PENDING = 0
    });

    it("requestHash et providerTokenId stockés dans la tâche", async function () {
      const ctx = await deployFixture();
      const requestHash = await doRequest(ctx.validation, ctx.providerOwner);
      const task = await ctx.validation.getTask("task-1");
      expect(task.requestHash).to.equal(requestHash);
      expect(task.providerTokenId).to.equal(PROVIDER_TOKEN_ID);
    });

    it("reverts on duplicate taskId", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await expect(doRequest(ctx.validation, ctx.providerOwner))
        .to.be.revertedWithCustomError(ctx.validation, "TaskAlreadyExists");
    });

    it("reverts if provider not active", async function () {
      const ctx = await deployFixture();
      await ctx.identityStub.setActive("provider-1", false);
      const rh = ethers.keccak256(ethers.toUtf8Bytes("x"));
      const th = ethers.keccak256(ethers.toUtf8Bytes("t"));
      await expect(
        ctx.validation.connect(ctx.providerOwner).validationRequest(
          "task-x", PROVIDER_TOKEN_ID, "ipfs://x", rh, th, 0
        )
      ).to.be.revertedWithCustomError(ctx.validation, "ProviderIneligible");
    });

    it("reverts if provider type is JUDGE", async function () {
      const ctx = await deployFixture();
      const rh = ethers.keccak256(ethers.toUtf8Bytes("x"));
      const th = ethers.keccak256(ethers.toUtf8Bytes("t"));
      // judge-0 a tokenId=10, type=JUDGE → ne peut pas être provider
      await expect(
        ctx.validation.connect(ctx.judge0).validationRequest(
          "task-x", 10n, "ipfs://x", rh, th, 0
        )
      ).to.be.revertedWithCustomError(ctx.validation, "ProviderIneligible");
    });

    it("reverts if provider stake insufficient", async function () {
      const ctx = await deployFixture();
      await ctx.stakingStub.setEligibleProvider(ctx.providerOwner.address, false);
      const rh = ethers.keccak256(ethers.toUtf8Bytes("x"));
      const th = ethers.keccak256(ethers.toUtf8Bytes("t"));
      await expect(
        ctx.validation.connect(ctx.providerOwner).validationRequest(
          "task-x", PROVIDER_TOKEN_ID, "ipfs://x", rh, th, 0
        )
      ).to.be.revertedWithCustomError(ctx.validation, "ProviderIneligible");
    });

    it("locks provider stake", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      expect(await ctx.stakingStub.lockCount(ctx.providerOwner.address)).to.equal(1n);
    });
  });

  // ── Step 2 : assignJudges ─────────────────────────────────────────────────
  describe("assignJudges", function () {
    it("assigns 3 judges and emits JudgesAssigned", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);

      await expect(ctx.validation.connect(ctx.owner).assignJudges("task-1", ctx.CANDIDATES))
        .to.emit(ctx.validation, "JudgesAssigned");
    });

    it("task status is COMMITTING after assign", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      const task = await ctx.validation.getTask("task-1");
      expect(task.status).to.equal(1); // COMMITTING = 1
    });

    it("judges are marked busy (tokenId-based)", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      expect(await ctx.validation.isJudgeBusy(10n)).to.equal(true);
      expect(await ctx.validation.isJudgeBusy(11n)).to.equal(true);
      expect(await ctx.validation.isJudgeBusy(12n)).to.equal(true);
    });

    it("reverts if not owner", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await expect(
        ctx.validation.connect(ctx.other).assignJudges("task-1", ctx.CANDIDATES)
      ).to.be.revertedWithCustomError(ctx.validation, "OwnableUnauthorizedAccount");
    });

    it("reverts if not enough eligible judges", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await ctx.stakingStub.setEligibleJudge(ctx.judge0.address, false);
      await ctx.stakingStub.setEligibleJudge(ctx.judge1.address, false);
      await expect(
        ctx.validation.connect(ctx.owner).assignJudges("task-1", ctx.CANDIDATES)
      ).to.be.revertedWithCustomError(ctx.validation, "NotEnoughEligibleJudges");
    });

    it("reverts if wrong status", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await expect(
        ctx.validation.connect(ctx.owner).assignJudges("task-1", ctx.CANDIDATES)
      ).to.be.revertedWithCustomError(ctx.validation, "WrongStatus");
    });

    it("reverts if too many candidates", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      const tooMany = Array(21).fill(10n);
      await expect(
        ctx.validation.connect(ctx.owner).assignJudges("task-1", tooMany)
      ).to.be.revertedWithCustomError(ctx.validation, "TooManyCandidates");
    });
  });

  // ── Step 3 : commitVote ───────────────────────────────────────────────────
  describe("commitVote", function () {
    it("accepts commit and emits VoteCommitted", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);

      const salt = ethers.randomBytes(32);
      const commitHash = makeCommitHash(VOTE_VALID, 20, 20, 20, 20, salt);

      await expect(
        ctx.validation.connect(ctx.judge0).commitVote("task-1", 10n, commitHash)
      )
        .to.emit(ctx.validation, "VoteCommitted")
        .withArgs("task-1", 10n);
    });

    it("transitions to REVEALING when all 3 committed", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);

      const s0 = ethers.randomBytes(32);
      const s1 = ethers.randomBytes(32);
      const s2 = ethers.randomBytes(32);
      await doCommit(ctx.validation, ctx.judge0, 10n, "task-1", VOTE_VALID, s0);
      await doCommit(ctx.validation, ctx.judge1, 11n, "task-1", VOTE_VALID, s1);
      await doCommit(ctx.validation, ctx.judge2, 12n, "task-1", VOTE_VALID, s2);

      const task = await ctx.validation.getTask("task-1");
      expect(task.status).to.equal(2); // REVEALING = 2
    });

    it("reverts if commit window closed", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await time.increase(COMMIT_WINDOW + 1);

      const salt = ethers.randomBytes(32);
      const commitHash = makeCommitHash(VOTE_VALID, 20, 20, 20, 20, salt);
      await expect(
        ctx.validation.connect(ctx.judge0).commitVote("task-1", 10n, commitHash)
      ).to.be.revertedWithCustomError(ctx.validation, "CommitWindowClosed");
    });

    it("reverts if wrong wallet", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);

      const commitHash = makeCommitHash(VOTE_VALID, 20, 20, 20, 20, ethers.randomBytes(32));
      await expect(
        ctx.validation.connect(ctx.other).commitVote("task-1", 10n, commitHash)
      ).to.be.revertedWithCustomError(ctx.validation, "CallerNotJudgeWallet");
    });

    it("reverts on double commit", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);

      const salt = ethers.randomBytes(32);
      const commitHash = makeCommitHash(VOTE_VALID, 20, 20, 20, 20, salt);
      await ctx.validation.connect(ctx.judge0).commitVote("task-1", 10n, commitHash);
      await expect(
        ctx.validation.connect(ctx.judge0).commitVote("task-1", 10n, commitHash)
      ).to.be.revertedWithCustomError(ctx.validation, "AlreadyCommitted");
    });
  });

  // ── Step 4 : revealVote ───────────────────────────────────────────────────
  describe("revealVote", function () {
    it("accepts reveal and emits VoteRevealed", async function () {
      const ctx = await deployFixture();
      const salt = ethers.randomBytes(32);
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await doCommit(ctx.validation, ctx.judge0, 10n, "task-1", VOTE_VALID, salt);
      await doCommit(ctx.validation, ctx.judge1, 11n, "task-1", VOTE_VALID, ethers.randomBytes(32));
      await doCommit(ctx.validation, ctx.judge2, 12n, "task-1", VOTE_VALID, ethers.randomBytes(32));

      await expect(
        ctx.validation.connect(ctx.judge0).revealVote("task-1", 10n, VOTE_VALID, salt, 20, 20, 20, 20)
      )
        .to.emit(ctx.validation, "VoteRevealed")
        .withArgs("task-1", 10n, VOTE_VALID, 20, 20, 20, 20);
    });

    it("reverts on wrong salt (CommitMismatch)", async function () {
      const ctx = await deployFixture();
      const salt = ethers.randomBytes(32);
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await doCommit(ctx.validation, ctx.judge0, 10n, "task-1", VOTE_VALID, salt);
      await doCommit(ctx.validation, ctx.judge1, 11n, "task-1", VOTE_VALID, ethers.randomBytes(32));
      await doCommit(ctx.validation, ctx.judge2, 12n, "task-1", VOTE_VALID, ethers.randomBytes(32));

      await expect(
        ctx.validation.connect(ctx.judge0).revealVote(
          "task-1", 10n, VOTE_VALID, ethers.randomBytes(32), 20, 20, 20, 20 // mauvais salt
        )
      ).to.be.revertedWithCustomError(ctx.validation, "CommitMismatch");
    });

    it("reverts if reveal window closed", async function () {
      const ctx = await deployFixture();
      const salt = ethers.randomBytes(32);
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await doCommit(ctx.validation, ctx.judge0, 10n, "task-1", VOTE_VALID, salt);
      await doCommit(ctx.validation, ctx.judge1, 11n, "task-1", VOTE_VALID, ethers.randomBytes(32));
      await doCommit(ctx.validation, ctx.judge2, 12n, "task-1", VOTE_VALID, ethers.randomBytes(32));

      await time.increase(COMMIT_WINDOW + REVEAL_WINDOW + 1);

      await expect(
        ctx.validation.connect(ctx.judge0).revealVote("task-1", 10n, VOTE_VALID, salt, 20, 20, 20, 20)
      ).to.be.revertedWithCustomError(ctx.validation, "RevealWindowClosed");
    });

    it("transitions COMMITTING → REVEALING after commit deadline si pas tous committé", async function () {
      const ctx = await deployFixture();
      const salt = ethers.randomBytes(32);
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);

      // Seul judge-0 commit
      await doCommit(ctx.validation, ctx.judge0, 10n, "task-1", VOTE_VALID, salt);

      await time.increase(COMMIT_WINDOW + 1);

      // revealVote force la transition COMMITTING → REVEALING
      await expect(
        ctx.validation.connect(ctx.judge0).revealVote("task-1", 10n, VOTE_VALID, salt, 20, 20, 20, 20)
      ).to.emit(ctx.validation, "VoteRevealed");

      const task = await ctx.validation.getTask("task-1");
      expect(task.status).to.equal(2); // REVEALING
    });
  });

  // ── Step 5 : finaliseValidation — VALID ───────────────────────────────────
  describe("finaliseValidation — verdict VALID (2 VALID, 1 INVALID)", function () {
    it("emits ValidationResponse with response=100 tag=VALID", async function () {
      const ctx = await deployFixture();
      const { taskId, requestHash } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);

      await expect(
        ctx.validation.connect(ctx.owner).finaliseValidation(taskId, "ipfs://QmJustif")
      )
        .to.emit(ctx.validation, "ValidationResponse")
        .withArgs(
          await ctx.validation.getAddress(),
          PROVIDER_TOKEN_ID,
          requestHash,
          100,
          "ipfs://QmJustif",
          (v) => typeof v === "string" || typeof v === "bigint",
          "VALID"
        );
    });

    it("task status is FINALISED", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif");
      const task = await ctx.validation.getTask(taskId);
      expect(task.status).to.equal(3); // FINALISED = 3
    });

    it("task stores aggregated score computed on-chain from judge sub-scores", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif");
      const task = await ctx.validation.getTask(taskId);
      // Chaque juge : 20+20+20+20 = 80 → (80+80+80)/3 = 80
      expect(task.score).to.equal(80n);
    });

    it("getAgentScore reflète la tâche finalisée", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif");
      const { averageScore, totalTasks } = await ctx.validation.getAgentScore(PROVIDER_TOKEN_ID);
      expect(totalTasks).to.equal(1n);
      expect(averageScore).to.equal(80n);
    });

    it("emits ScoreRecorded event", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await expect(ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif"))
        .to.emit(ctx.validation, "ScoreRecorded")
        .withArgs(PROVIDER_TOKEN_ID, taskId, 80n, 0); // mode 0 = solo
    });

    it("deviant judge (voted INVALID) slashed — JudgeSlashed event", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await expect(
        ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif")
      ).to.emit(ctx.validation, "JudgeSlashed")
        .withArgs(12n, ctx.judge2.address, (v) => v >= 0n, "DEVIATED");
    });

    it("provider stake unlocked after finalise", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif");
      expect(await ctx.stakingStub.unlockCount(ctx.providerOwner.address)).to.equal(1n);
    });

    it("judges freed after finalise", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif");
      expect(await ctx.validation.isJudgeBusy(10n)).to.equal(false);
      expect(await ctx.validation.isJudgeBusy(11n)).to.equal(false);
      expect(await ctx.validation.isJudgeBusy(12n)).to.equal(false);
    });

    it("calls escrow releaseFunds on VALID", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif");
      expect(await ctx.escrowStub.releaseCount()).to.equal(1n);
      expect(await ctx.escrowStub.lastTaskId()).to.equal(taskId);
    });
  });

  // ── Step 5 : finaliseValidation — INVALID ────────────────────────────────
  describe("finaliseValidation — verdict INVALID (2 INVALID, 1 VALID)", function () {
    it("emits ValidationResponse with response=0 tag=INVALID", async function () {
      const ctx = await deployFixture();
      const { taskId, requestHash } = await fullFlow(ctx, [VOTE_INVALID, VOTE_INVALID, VOTE_VALID]);

      await expect(
        ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif")
      )
        .to.emit(ctx.validation, "ValidationResponse")
        .withArgs(
          await ctx.validation.getAddress(), PROVIDER_TOKEN_ID, requestHash,
          0, "ipfs://QmJustif", (v) => true, "INVALID"
        );
    });

    it("provider slashed and emits ProviderSlashed", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_INVALID, VOTE_INVALID, VOTE_VALID]);
      await expect(ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif"))
        .to.emit(ctx.validation, "ProviderSlashed");
    });

    it("deviant judge (voted VALID) slashed with reason DEVIATED", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_INVALID, VOTE_INVALID, VOTE_VALID]);
      await expect(ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif"))
        .to.emit(ctx.validation, "JudgeSlashed")
        .withArgs(12n, ctx.judge2.address, (v) => v >= 0n, "DEVIATED");
    });

    it("calls escrow releaseFunds on INVALID (provider slashé séparément)", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_INVALID, VOTE_INVALID, VOTE_VALID]);
      await ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif");
      // INVALID → releaseFunds (vers les juges consensuels), refundClient est réservé à DISPUTED
      expect(await ctx.escrowStub.releaseCount()).to.equal(1n);
      expect(await ctx.escrowStub.lastTaskId()).to.equal(taskId);
    });
  });

  // ── Step 5 : finaliseValidation — DISPUTED ───────────────────────────────
  describe("finaliseValidation — verdict DISPUTED (1V / 1I / absent)", function () {
    it("tag=DISPUTED, response=50, no provider slash", async function () {
      const ctx = await deployFixture();
      const taskId = "task-disp";
      const salts  = [ethers.randomBytes(32), ethers.randomBytes(32)];

      await doRequest(ctx.validation, ctx.providerOwner, taskId);
      await doAssign(ctx.validation, ctx.owner, taskId, ctx.CANDIDATES);

      // judge-0 VALID, judge-1 INVALID, judge-2 ne commit pas
      await doCommit(ctx.validation, ctx.judge0, 10n, taskId, VOTE_VALID,   salts[0]);
      await doCommit(ctx.validation, ctx.judge1, 11n, taskId, VOTE_INVALID, salts[1]);

      await time.increase(COMMIT_WINDOW + 1);

      await doReveal(ctx.validation, ctx.judge0, 10n, taskId, VOTE_VALID,   salts[0]);
      await doReveal(ctx.validation, ctx.judge1, 11n, taskId, VOTE_INVALID, salts[1]);

      await time.increase(REVEAL_WINDOW + 1);

      const requestHash = (await ctx.validation.getTask(taskId)).requestHash;

      await expect(ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif"))
        .to.emit(ctx.validation, "ValidationResponse")
        .withArgs(
          await ctx.validation.getAddress(), PROVIDER_TOKEN_ID, requestHash,
          50, "ipfs://QmJustif", (v) => true, "DISPUTED"
        );

      // Pas de ProviderSlashed
      const filter = ctx.validation.filters.ProviderSlashed();
      const events = await ctx.validation.queryFilter(filter);
      expect(events.length).to.equal(0);
    });
  });

  // ── Score agrégé ──────────────────────────────────────────────────────────
  describe("finaliseValidation — score on-chain", function () {
    it("stores aggregated score in task (auto-calculated)", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif");
      const task = await ctx.validation.getTask(taskId);
      expect(task.score).to.be.gte(0n);
      expect(task.score).to.be.lte(100n);
    });

    it("reverts if reveal window still open", async function () {
      const ctx = await deployFixture();
      const taskId = "task-open";
      const salts  = [ethers.randomBytes(32), ethers.randomBytes(32), ethers.randomBytes(32)];
      await doRequest(ctx.validation, ctx.providerOwner, taskId);
      await doAssign(ctx.validation, ctx.owner, taskId, ctx.CANDIDATES);
      await doCommit(ctx.validation, ctx.judge0, 10n, taskId, VOTE_VALID, salts[0]);
      await doCommit(ctx.validation, ctx.judge1, 11n, taskId, VOTE_VALID, salts[1]);
      await doCommit(ctx.validation, ctx.judge2, 12n, taskId, VOTE_VALID, salts[2]);
      await doReveal(ctx.validation, ctx.judge0, 10n, taskId, VOTE_VALID, salts[0]);
      // judge1 et judge2 n'ont pas encore révélé → fenêtre ouverte
      await expect(
        ctx.validation.finaliseValidation(taskId, "ipfs://")
      ).to.be.revertedWithCustomError(ctx.validation, "RevealWindowStillOpen");
    });
  });

  // ── expireTask ────────────────────────────────────────────────────────────
  describe("expireTask", function () {
    it("expires COMMITTING task after commit deadline", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await time.increase(COMMIT_WINDOW + 1);

      await expect(ctx.validation.expireTask("task-1"))
        .to.emit(ctx.validation, "TaskExpired").withArgs("task-1");

      const task = await ctx.validation.getTask("task-1");
      expect(task.status).to.equal(4); // EXPIRED = 4
    });

    it("slashes absent judges on expire", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await time.increase(COMMIT_WINDOW + 1);
      await ctx.validation.expireTask("task-1");
      // Tous les juges absents (aucun commit) → slashés
      expect(await ctx.stakingStub.slashCount(ctx.judge0.address)).to.equal(1n);
      expect(await ctx.stakingStub.slashCount(ctx.judge1.address)).to.equal(1n);
      expect(await ctx.stakingStub.slashCount(ctx.judge2.address)).to.equal(1n);
    });

    it("reverts if not yet expirable", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await expect(ctx.validation.expireTask("task-1"))
        .to.be.revertedWithCustomError(ctx.validation, "NotExpirable");
    });

    it("emits ValidationResponse with tag EXPIRED", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      await time.increase(COMMIT_WINDOW + 1);

      await expect(ctx.validation.expireTask("task-1"))
        .to.emit(ctx.validation, "ValidationResponse");
    });
  });

  // ── Score d'agent (getAgentScore) ────────────────────────────────────────
  describe("getAgentScore", function () {
    it("returns correct averageScore and totalTasks after VALID", async function () {
      const ctx = await deployFixture();
      const { taskId } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(taskId, "ipfs://QmJustif");

      const { averageScore, totalTasks } = await ctx.validation.getAgentScore(PROVIDER_TOKEN_ID);
      expect(totalTasks).to.equal(1n);
      expect(averageScore).to.equal(80n); // (80+80+80)/3 = 80
    });

    it("totalTasks accumule sur plusieurs tâches", async function () {
      const ctx = await deployFixture();
      // Tâche 1
      const { taskId: t1 } = await fullFlow(ctx, [VOTE_VALID, VOTE_VALID, VOTE_INVALID]);
      await ctx.validation.finaliseValidation(t1, "ipfs://QmJ1");

      // Tâche 2 (même provider, nouveau taskId)
      const taskId2 = "task-full-2";
      const salts   = [ethers.randomBytes(32), ethers.randomBytes(32), ethers.randomBytes(32)];
      await doRequest(ctx.validation, ctx.providerOwner, taskId2);
      await doAssign(ctx.validation, ctx.owner, taskId2, ctx.CANDIDATES);
      await doCommit(ctx.validation, ctx.judge0, 10n, taskId2, VOTE_VALID, salts[0]);
      await doCommit(ctx.validation, ctx.judge1, 11n, taskId2, VOTE_VALID, salts[1]);
      await doCommit(ctx.validation, ctx.judge2, 12n, taskId2, VOTE_VALID, salts[2]);
      await doReveal(ctx.validation, ctx.judge0, 10n, taskId2, VOTE_VALID, salts[0]);
      await doReveal(ctx.validation, ctx.judge1, 11n, taskId2, VOTE_VALID, salts[1]);
      await doReveal(ctx.validation, ctx.judge2, 12n, taskId2, VOTE_VALID, salts[2]);
      await ctx.validation.finaliseValidation(taskId2, "ipfs://QmJ2");

      const { totalTasks } = await ctx.validation.getAgentScore(PROVIDER_TOKEN_ID);
      expect(totalTasks).to.equal(2n);
    });
  });

  // ── isEligibleJudgeCandidate view ────────────────────────────────────────
  describe("isEligibleJudgeCandidate", function () {
    it("returns true for valid judge (tokenId)", async function () {
      const ctx = await deployFixture();
      expect(await ctx.validation.isEligibleJudgeCandidate(10n)).to.equal(true);
    });

    it("returns false for provider tokenId", async function () {
      const ctx = await deployFixture();
      // provider a type=PROVIDER → inéligible comme juge
      expect(await ctx.validation.isEligibleJudgeCandidate(PROVIDER_TOKEN_ID)).to.equal(false);
    });

    it("returns false for inactive judge", async function () {
      const ctx = await deployFixture();
      await ctx.identityStub.setActive("judge-0", false);
      expect(await ctx.validation.isEligibleJudgeCandidate(10n)).to.equal(false);
    });

    it("returns false for judge already busy", async function () {
      const ctx = await deployFixture();
      await doRequest(ctx.validation, ctx.providerOwner);
      await doAssign(ctx.validation, ctx.owner, "task-1", ctx.CANDIDATES);
      expect(await ctx.validation.isEligibleJudgeCandidate(10n)).to.equal(false);
    });
  });

  // ── Honeypot ──────────────────────────────────────────────────────────────
  describe("Honeypot (recordHoneypotResult)", function () {
    it("judge non autorisé via honeypot est exclu de l'assignation", async function () {
      const ctx = await deployFixture();
      // Révoquer l'autorisation de judge-2
      await ctx.validation.connect(ctx.owner).recordHoneypotResult(12, false, "ipfs://fail");
      await doRequest(ctx.validation, ctx.providerOwner);
      // Seulement judge-0 (10) et judge-1 (11) sont autorisés → < 3 → revert
      await expect(
        ctx.validation.connect(ctx.owner).assignJudges("task-1", ctx.CANDIDATES)
      ).to.be.revertedWithCustomError(ctx.validation, "NotEnoughEligibleJudges");
    });

    it("isJudgeAuthorized retourne l'état correct", async function () {
      const ctx = await deployFixture();
      expect(await ctx.validation.isJudgeAuthorized(10n)).to.equal(true);
      expect(await ctx.validation.isJudgeAuthorized(99n)).to.equal(false); // inconnu
    });
  });

  // ── Admin setters ─────────────────────────────────────────────────────────
  describe("Admin setters", function () {
    it("owner can update staking contract address", async function () {
      const ctx  = await deployFixture();
      const addr = ethers.Wallet.createRandom().address;
      await ctx.validation.connect(ctx.owner).setStakingContract(addr);
      expect(await ctx.validation.stakingContract()).to.equal(addr);
    });

    it("owner can update identity registry address", async function () {
      const ctx  = await deployFixture();
      const addr = ethers.Wallet.createRandom().address;
      await ctx.validation.connect(ctx.owner).setIdentityRegistry(addr);
      expect(await ctx.validation.identityRegistry()).to.equal(addr);
    });

    it("non-owner cannot update siblings", async function () {
      const ctx  = await deployFixture();
      const addr = ethers.Wallet.createRandom().address;
      await expect(
        ctx.validation.connect(ctx.other).setStakingContract(addr)
      ).to.be.revertedWithCustomError(ctx.validation, "OwnableUnauthorizedAccount");
    });

    it("reverts setIdentityRegistry with address(0)", async function () {
      const ctx = await deployFixture();
      await expect(
        ctx.validation.connect(ctx.owner).setIdentityRegistry(ethers.ZeroAddress)
      ).to.be.revertedWithCustomError(ctx.validation, "ZeroAddress");
    });
  });
});
